"""Validated Echo inventory, independent sessions, and local announcement routing."""
import json
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from config import API_CONVERSATION_ID


@dataclass(frozen=True)
class EchoDevice:
    device_id: str
    display_name: str
    hardware_serial: str
    host: str
    port: int
    conversation_id: str
    wake_group: str
    room: str | None = None


def load_devices(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Echo registry requires schema_version 1')
    rows = data.get('devices')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('Echo registry must contain 1 through 8 devices')
    devices = []
    ids, serials, endpoints, conversations = set(), set(), set(), set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('enabled', True)) is not bool:
            raise ValueError('Invalid Echo device entry')
        identifier = row.get('device_id', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', identifier):
            raise ValueError('Echo device_id must be a short lowercase ID')
        serial = row.get('hardware_serial', '')
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError(f'{identifier}: hardware_serial is required')
        serial = serial.strip()
        host, port = row.get('wyoming_host'), row.get('wyoming_port', 16700)
        if not isinstance(host, str) or not host.strip() or any(c.isspace() for c in host):
            raise ValueError(f'{identifier}: invalid wyoming_host')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f'{identifier}: invalid wyoming_port')
        conversation = row.get('conversation_id', f'{API_CONVERSATION_ID}-{identifier}')
        group = row.get('wake_group', 'shared')
        name = row.get('display_name', identifier)
        room = row.get('room')
        for label, value in [('conversation_id', conversation), ('wake_group', group), ('display_name', name)]:
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError(f'{identifier}: invalid {label}')
        if room is not None and (not isinstance(room, str) or len(room) > 256):
            raise ValueError(f'{identifier}: invalid room')
        for seen, value, label in [(ids, identifier, 'device_id'), (serials, serial, 'serial'),
                                    (endpoints, (host, port), 'endpoint'),
                                    (conversations, conversation, 'conversation_id')]:
            if value in seen:
                raise ValueError(f'Duplicate Echo {label}')
            seen.add(value)
        if row.get('enabled', True):
            devices.append(EchoDevice(identifier, name, serial, host, port, conversation, group, room))
    if not devices:
        raise ValueError('At least one Echo must be enabled')
    default = data.get('default_device_id', devices[0].device_id)
    if default not in {device.device_id for device in devices}:
        raise ValueError('default_device_id must name an enabled Echo')
    return devices, default


class WakeCoordinator:
    """First waking device owns its group's conversation until it returns idle."""
    def __init__(self):
        self.lock = threading.Lock()
        self.owners = {}

    def acquire(self, device):
        with self.lock:
            owner = self.owners.get(device.wake_group)
            if owner is not None and owner != device.device_id:
                return False
            self.owners[device.wake_group] = device.device_id
            return True

    def release(self, device):
        with self.lock:
            if self.owners.get(device.wake_group) == device.device_id:
                del self.owners[device.wake_group]


class DeviceSession:
    def __init__(self, device, coordinator):
        self.device = device
        self.coordinator = coordinator
        self.paused_until = 0
        self.socket_lock = threading.Lock()
        self.sock = None
        self.stopped = False

    def acquire(self):
        return self.coordinator.acquire(self.device)

    def release(self):
        self.coordinator.release(self.device)

    def stand_down_remaining(self):
        return max(0, self.paused_until - time.monotonic())

    def start_stand_down(self, seconds):
        self.paused_until = time.monotonic() + seconds

    def attach(self, sock):
        with self.socket_lock:
            if self.stopped:
                sock.close()
                raise EOFError('Device runtime stopping')
            self.sock = sock

    def detach(self):
        with self.socket_lock:
            self.sock = None
        self.release()

    def stop(self):
        with self.socket_lock:
            self.stopped = True
            if self.sock is not None:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.release()


class AnnouncementRouter:
    def __init__(self, devices, default_id, queues, sessions):
        self.devices = {device.device_id: device for device in devices}
        self.default_id = default_id
        self.queues = queues
        self.sessions = sessions
        self.lock = threading.Lock()

    def handle(self, payload):
        command = str(payload.get('command') or payload.get('action') or '').replace('_', ' ').strip().lower()
        if command == 'status':
            devices = {identifier: {**queue.handle({'command':'status'}),
                'display_name': self.devices[identifier].display_name,
                'room': self.devices[identifier].room,
                'wake_group': self.devices[identifier].wake_group,
                'stand_down_seconds': round(self.sessions[identifier].stand_down_remaining(), 1)}
                for identifier, queue in self.queues.items()}
            return {'ok': True, 'status': 'running', 'default_device_id': self.default_id,
                    'echo_connected': any(d['echo_connected'] for d in devices.values()),
                    'pending_announcements': sum(d['pending_announcements'] for d in devices.values()),
                    'devices': devices}
        if command not in {'', 'speak', 'say'}:
            return {'ok':False,'error':f'unknown command: {command}'}
        text = str(payload.get('text') or payload.get('instruction') or payload.get('message') or '').strip()
        if not text:
            return {'ok':False,'error':'text, instruction, or message is required'}
        selectors = sum(key in payload for key in ('device_id','device_ids','broadcast'))
        if selectors > 1:
            return {'ok':False,'error':'Use only one of device_id, device_ids, or broadcast'}
        if 'broadcast' in payload:
            if payload['broadcast'] is not True:
                return {'ok':False,'error':'broadcast must be true'}
            targets = list(self.devices)
        elif 'device_ids' in payload:
            targets = payload['device_ids']
        else:
            targets = [payload.get('device_id', self.default_id)]
        if (not isinstance(targets,list) or not targets or
                any(not isinstance(i,str) or i not in self.devices for i in targets) or
                len(set(targets)) != len(targets)):
            return {'ok':False,'error':'Targets must be unique enabled Echo device IDs'}
        with self.lock:
            # All producers pass through this lock; consumers only free space.
            if any(self.queues[i].pending.full() for i in targets):
                return {'ok':False,'error':'An Echo announcement queue is full; nothing queued'}
            for identifier in targets:
                self.queues[identifier].handle({'text':text})
        return {'ok':True,'queued':True,'device_ids':targets,'text':text}
