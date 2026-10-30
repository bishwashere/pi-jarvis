import json
import socket
import threading
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import hassmic_jarvis as bridge
from device_context import bind_device, conversation_id, device_id
from echo_devices import EchoDevice, DeviceSession, WakeCoordinator, AnnouncementRouter, load_devices


def device(number, group=None):
    return EchoDevice(f'echo-{number}',f'Echo {number}',f'SERIAL{number}',f'echo{number}.local',16700,
                      f'conversation-{number}',group or f'room-{number}')


def registry(tmp_path, rows):
    path=tmp_path/'devices.json'
    path.write_text(json.dumps({'schema_version':1,'default_device_id':'echo-1','devices':rows}))
    return path


def row(number):
    return dict(device_id=f'echo-{number}',display_name=f'Echo {number}',hardware_serial=f'S{number}',
                wyoming_host=f'echo{number}.local',wyoming_port=16700)


def test_registry_two_devices_default_conversations_and_disable(tmp_path):
    a,b=row(1),row(2)
    devices,default=load_devices(registry(tmp_path,[a,b]))
    assert default=='echo-1' and len(devices)==2
    assert devices[0].conversation_id!=devices[1].conversation_id
    assert all(d.wake_group=='shared' for d in devices)
    b['enabled']=False
    assert len(load_devices(registry(tmp_path,[a,b]))[0])==1


@pytest.mark.parametrize('field,value', [('device_id','echo-1'),('hardware_serial','S1'),
    ('wyoming_host','echo1.local'),('conversation_id','shared-conversation'),
    ('device_id','../../x'),('wyoming_port',True),('enabled','yes')])
def test_registry_rejects_ambiguous_or_invalid_devices(tmp_path,field,value):
    a,b=row(1),row(2)
    if field=='conversation_id':a[field]=value
    b[field]=value
    with pytest.raises(ValueError):load_devices(registry(tmp_path,[a,b]))


def test_group_ownership_and_stand_down_are_device_scoped():
    coordinator=WakeCoordinator()
    a=DeviceSession(device(1,'shared'),coordinator)
    b=DeviceSession(device(2,'shared'),coordinator)
    c=DeviceSession(device(3,'other-room'),coordinator)
    assert a.acquire() and not b.acquire() and c.acquire()
    b.release()  # a rejected wake cannot release another Echo's ownership
    assert not b.acquire()
    a.start_stand_down(3600)
    assert a.stand_down_remaining()>3500 and b.stand_down_remaining()==0
    a.detach()
    assert b.acquire()
    b.stop();assert a.acquire()


def test_router_target_broadcast_validation_and_atomic_queueing():
    devices=[device(1),device(2)]
    queues={d.device_id:bridge.Announcements() for d in devices}
    coordinator=WakeCoordinator()
    states={d.device_id:DeviceSession(d,coordinator) for d in devices}
    router=AnnouncementRouter(devices,'echo-1',queues,states)
    assert router.handle({'text':'default'})['device_ids']==['echo-1']
    assert router.handle({'text':'second','device_id':'echo-2'})['device_ids']==['echo-2']
    assert router.handle({'text':'both','broadcast':True})['device_ids']==['echo-1','echo-2']
    assert [queues['echo-1'].pending.get(),queues['echo-1'].pending.get()]==['default','both']
    assert [queues['echo-2'].pending.get(),queues['echo-2'].pending.get()]==['second','both']
    assert router.handle({'text':'quiet welcome','device_id':'echo-2','followup':False})['ok']
    assert queues['echo-2'].pending.get() == {'text':'quiet welcome','followup':False}
    assert not router.handle({'text':'invalid','broadcast':True,'followup':'false'})['ok']
    assert all(queue.pending.empty() for queue in queues.values())
    for target in [{'device_id':'unknown'},{'device_ids':['echo-1','echo-1']},
                   {'broadcast':False},{'broadcast':True,'device_id':'echo-1'}]:
        assert not router.handle({'text':'reject',**target})['ok']
    for _ in range(64):queues['echo-2'].pending.put('full')
    assert not router.handle({'text':'overflow','broadcast':True})['ok']
    assert queues['echo-1'].pending.empty()
    queues['echo-1'].connected=True
    status=router.handle({'command':'status'})
    assert status['devices']['echo-1']['echo_connected'] is True
    assert status['devices']['echo-2']['echo_connected'] is False


def test_api_context_isolation_in_parallel(monkeypatch):
    import call_agent_api
    import streaming_reply
    from streaming_input import StreamingInput
    calls=[]
    lock=threading.Lock()
    barrier=threading.Barrier(2)
    class Response:
        headers={'Content-Type':'application/json'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def close(self):pass
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'ok'}}]}
    def post(url,**kwargs):
        if 'data' in kwargs:kwargs['events']=[json.loads(c) for c in kwargs.pop('data')]
        with lock:calls.append(kwargs)
        return Response()
    monkeypatch.setattr(call_agent_api.requests,'post',post)
    failures=[]
    def worker(d):
        try:
            with bind_device(d):
                barrier.wait(3)
                assert device_id()==d.device_id
                call_agent_api.ask_pasture('hello')
                call_agent_api.start_new_pasture_session()
                list(streaming_reply.api_events('hello'))
                # Capture identity at construction, then upload on its own thread.
                with StreamingInput() as upload:
                    upload.partial('hello')
                    list(upload.events('hello'))
        except BaseException as exc:failures.append(exc)
    threads=[threading.Thread(target=worker,args=(device(i),)) for i in (1,2)]
    for t in threads:t.start()
    for t in threads:t.join(5);assert not t.is_alive()
    assert not failures
    assert len(calls)==8
    for call in calls:
        identifier=call['headers']['X-Pasture-Device-Id']
        expected='conversation-'+identifier[-1]
        assert call['headers']['X-Pasture-Conversation-Id']==expected
        if 'json' in call:assert call['json']['conversation_id']==expected
        else:assert call['events'][0]['conversation_id']==expected
    assert device_id() is None


def test_two_simultaneous_echo_conversations_reply_on_correct_socket(tmp_path):
    coordinator=WakeCoordinator()
    barrier=threading.Barrier(2)
    failures=[]
    received={1:[],2:[]}
    calls=[]
    threads=[]
    wires=[]
    def echo(peer,number):
        try:
            assert peer.next_event()[0]=='describe'
            peer.send('info',{'satellite':{'supports_jarvis_followup':True}})
            assert peer.next_event()[0]=='run-satellite'
            for _ in range(2):
                peer.send('run-pipeline',{'start_stage':'asr'})
                peer.send('audio-chunk',{'rate':16000,'width':2,'channels':1},b'\xd0\x07'*3200)
                for _ in range(25):peer.send('audio-chunk',{'rate':16000,'width':2,'channels':1},bytes(3200))
                while True:
                    kind,_,pcm=peer.next_event()
                    if kind=='audio-chunk':received[number].append(pcm)
                    if kind=='audio-stop':peer.send('played');break
        except BaseException as exc:failures.append(exc)
    def controller(wire,number):
        d=device(number);state=DeviceSession(d,coordinator)
        path=tmp_path/d.device_id;path.mkdir()
        def ask(text):
            calls.append((device_id(),conversation_id(),text))
            barrier.wait(5)  # both requests must be active at the same time
            return {'reply':str(number)}
        def synth(text,filename):
            assert Path(filename).parent==path
            with wave.open(filename,'wb') as out:
                out.setparams((1,2,22050,0,'NONE','not compressed'))
                out.writeframes(int(text).to_bytes(2,'little')*100)
            return filename
        try:
            with bind_device(d):
                bridge.serve(wire,lambda _:f'question {number}',ask,synth,path,
                             max_turns=2,session=state)
        except BaseException as exc:failures.append(exc)
        finally:state.release()
    try:
        for number in (1,2):
            a,b=socket.socketpair();a.settimeout(5);b.settimeout(5)
            wire,peer=bridge.Wire(a),bridge.Wire(b);wires.extend([wire,peer])
            threads.extend([threading.Thread(target=echo,args=(peer,number),daemon=True),
                            threading.Thread(target=controller,args=(wire,number),daemon=True)])
        for t in threads:t.start()
        for t in threads:t.join(8);assert not t.is_alive()
        assert not failures
        assert len(calls)==4
        for number in (1,2):
            assert b''.join(received[number])==number.to_bytes(2,'little')*200
        assert not coordinator.owners
    finally:
        for wire in wires:wire.close()


def test_same_group_rejects_second_wake_before_capture(tmp_path,monkeypatch):
    coordinator=WakeCoordinator()
    first=DeviceSession(device(1,'shared'),coordinator)
    second=DeviceSession(device(2,'shared'),coordinator)
    assert first.acquire()
    incoming=iter([('info',{'satellite':{'supports_jarvis_followup':True}},b''),
                   ('run-pipeline',{'start_stage':'asr'},b'')])
    sent=[]
    wire=SimpleNamespace(send=lambda *a:sent.append(a),next_event=lambda:next(incoming),
                         sock=SimpleNamespace(settimeout=lambda _:None))
    monkeypatch.setattr(bridge,'capture',lambda *a,**k:pytest.fail('duplicate wake captured'))
    with pytest.raises(StopIteration):bridge.serve(wire,None,None,None,tmp_path,session=second)
    assert ('error',{'code':'stt-no-text-recognized'}) in sent
    assert coordinator.owners['shared']=='echo-1'


def test_whisper_shared_model_is_serialized():
    from multi_echo import SerializedWhisper
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def transcribe(pcm):
        calls.append(pcm)
        if pcm==b'first':entered.set();assert release.wait(3)
        return pcm
    shared=SerializedWhisper(SimpleNamespace(transcribe=transcribe))
    a=threading.Thread(target=shared.transcribe,args=(b'first',))
    b=threading.Thread(target=shared.transcribe,args=(b'second',))
    a.start();assert entered.wait(2);b.start()
    assert calls==[b'first'];release.set();a.join(2);b.join(2)
    assert calls==[b'first',b'second']


def test_disconnected_echo_does_not_block_another(tmp_path,monkeypatch):
    stop=threading.Event();offline=threading.Event();healthy=threading.Event()
    coordinator=WakeCoordinator()
    class FakeWire:
        def __init__(self,sock):self.sock=sock
        def close(self):pass
    monkeypatch.setattr(bridge,'Wire',FakeWire)
    def serve(*args,**kwargs):
        assert kwargs['session'].device.device_id=='echo-2'
        kwargs['announcements'].connected=True
        healthy.set();assert offline.wait(2);stop.set()
    monkeypatch.setattr(bridge,'serve',serve)
    def connect(address,timeout):
        if address[0]=='echo1.local':offline.set();raise ConnectionRefusedError('fixture')
        return SimpleNamespace(close=lambda:None)
    threads=[]
    for number in (1,2):
        d=device(number)
        threads.append(threading.Thread(target=bridge.run_connected,
            args=(d.host,d.port,None,None,None,tmp_path,bridge.Announcements()),
            kwargs=dict(connect=connect,stop_event=stop,session=DeviceSession(d,coordinator))))
    for t in threads:t.start()
    for t in threads:t.join(3);assert not t.is_alive()
    assert offline.is_set() and healthy.is_set()


def test_supervisor_runs_two_virtual_echos_and_shuts_down_cleanly(tmp_path,monkeypatch):
    import multi_echo
    import speech_to_text
    import call_agent_api
    import text_to_speech
    import jarvis_command_server
    rows=[{**row(i),'wake_group':f'room-{i}'} for i in (1,2)]
    path=registry(tmp_path,rows)
    monkeypatch.setattr(multi_echo,'LOG_DIR',str(tmp_path))
    monkeypatch.setattr(multi_echo,'STREAMING_ENABLED',False)
    monkeypatch.setattr(multi_echo,'COMMAND_SERVER_ENABLED',True)
    handlers={}
    monkeypatch.setattr(multi_echo.signal,'signal',lambda signum,handler:handlers.setdefault(signum,handler))
    stopped=[]
    def server(handler):
        assert handler({'command':'status'})['default_device_id']=='echo-1'
        return SimpleNamespace(shutdown=lambda:stopped.append('shutdown'),server_close=lambda:stopped.append('close'))
    monkeypatch.setattr(jarvis_command_server,'start_command_server',server)
    monkeypatch.setattr(speech_to_text,'transcribe_with_whisper',lambda filename:'hello')
    barrier=threading.Barrier(2)
    def ask(text):
        barrier.wait(3)
        return {'reply':device_id()[-1]}
    monkeypatch.setattr(call_agent_api,'ask_pasture',ask)
    def synth(text,filename):
        with wave.open(filename,'wb') as out:
            out.setparams((1,2,22050,0,'NONE','not compressed'));out.writeframes(int(text).to_bytes(2,'little')*50)
        return filename
    monkeypatch.setattr(text_to_speech,'synthesize_to_wav',synth)
    peers=[];connections={};failures=[];finished=[];finish_lock=threading.Lock()
    for i in (1,2):
        a,b=socket.socketpair();a.settimeout(3);b.settimeout(3)
        connections[f'echo{i}.local']=a;peers.append(bridge.Wire(b))
    original=bridge.run_connected
    def run_connected(*args,**kwargs):
        return original(*args,**kwargs,connect=lambda address,timeout:connections.pop(address[0]))
    monkeypatch.setattr(bridge,'run_connected',run_connected)
    def echo(peer,i):
        try:
            assert peer.next_event()[0]=='describe'
            peer.send('info',{'satellite':{'supports_jarvis_followup':True}})
            assert peer.next_event()[0]=='run-satellite'
            peer.send('run-pipeline',{'start_stage':'asr'})
            peer.send('audio-chunk',{'rate':16000,'width':2,'channels':1},b'\xd0\x07'*3200)
            for _ in range(25):peer.send('audio-chunk',{'rate':16000,'width':2,'channels':1},bytes(3200))
            audio=b''
            while True:
                kind,_,pcm=peer.next_event()
                if kind=='audio-chunk':audio+=pcm
                if kind=='audio-stop':peer.send('played');break
            assert audio==i.to_bytes(2,'little')*50
            with finish_lock:
                finished.append(i)
                if len(finished)==2:handlers[multi_echo.signal.SIGTERM]()
        except BaseException as exc:
            failures.append(exc)
            if multi_echo.signal.SIGTERM in handlers:handlers[multi_echo.signal.SIGTERM]()
    threads=[threading.Thread(target=echo,args=(peer,i),daemon=True) for i,peer in enumerate(peers,1)]
    for t in threads:t.start()
    try:
        multi_echo.run(path)
        for t in threads:t.join(4);assert not t.is_alive()
        assert not failures
        assert sorted(finished)==[1,2]
        assert stopped==['shutdown','close']
        assert not list(tmp_path.glob('multi-echo-*'))
        for number in (1,2):
            log=(tmp_path/'devices'/f'echo-{number}.log').read_text()
            assert 'echo_worker_started' in log and 'hassmic_command' in log
            assert f"device_id='echo-{number}'" in log
            assert f"device_id='echo-{3-number}'" not in log
    finally:
        for peer in peers:peer.close()


def test_legacy_single_echo_entrypoint_still_works(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr(sys,'argv',['hassmic_jarvis.py','--host','echo.local'])
    monkeypatch.setattr(bridge,'ECHO_DEVICES_PATH','')
    monkeypatch.setattr(bridge,'LOG_DIR',str(tmp_path))
    monkeypatch.setattr(bridge,'STREAMING_ENABLED',False)
    monkeypatch.setattr(bridge,'COMMAND_SERVER_ENABLED',False)
    calls=[]
    monkeypatch.setattr(bridge,'run_connected',lambda *args,**kwargs:calls.append((args,kwargs)))
    bridge.main()
    assert len(calls)==1 and calls[0][0][0]=='echo.local'
    assert calls[0][1]=={}
