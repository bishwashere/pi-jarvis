"""HTTP boundary checks without opening sockets, speaking, or calling an agent."""
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
import threading
from unittest.mock import Mock

import pytest
import jarvis_command_server as server


@pytest.fixture
def handler_factory(monkeypatch):
    captured = {}
    class FakeServer:
        def __init__(self, address, handler):
            captured['handler'] = handler
        def serve_forever(self):
            pass
    monkeypatch.setattr(server, '_CommandHTTPServer', FakeServer)
    monkeypatch.setattr(server.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(server, 'COMMAND_SERVER_HOST', '127.0.0.1')
    monkeypatch.setattr(server, 'COMMAND_SERVER_TOKEN', 'test-token')
    monkeypatch.setattr(server, 'voice_event', lambda *a, **kw: None)
    command = Mock(return_value={'ok': True})
    server.start_command_server(command)
    def create(headers=(), body=b'{}', authorized=True):
        handler = object.__new__(captured['handler'])
        handler.path = '/command'
        handler.headers = Message()
        if authorized:
            handler.headers['Authorization'] = 'Bearer test-token'
        for key, value in headers:
            handler.headers[key] = value
        handler.rfile = BytesIO(body)
        handler.send_json = Mock()
        return handler, command
    return create


@pytest.mark.parametrize('headers,status', [
    ([],400),([('Content-Length','-1')],400),([('Content-Length','junk')],400),
    ([('Content-Length','2'),('Content-Length','2')],400),
    ([('Content-Length','65537')],413),([('Content-Length','9'*5000)],413),
    ([('Content-Length','2'),('Transfer-Encoding','chunked')],400),
])
def test_bad_framing_rejected_before_read(handler_factory, headers, status):
    handler, command = handler_factory(headers)
    handler.rfile = Mock(read=Mock(side_effect=AssertionError('Must not read rejected body')))
    handler.do_POST()
    assert handler.send_json.call_args.args[0] == status
    command.assert_not_called()


def test_unauthorized_never_reads_body(handler_factory):
    handler, command = handler_factory([('Content-Length','2')],authorized=False)
    handler.rfile = Mock(read=Mock(side_effect=AssertionError('Must not read unauthenticated body')))
    handler.do_POST()
    assert handler.send_json.call_args.args[0] == 401
    command.assert_not_called()


@pytest.mark.parametrize('body,length', [(b'{}',3),(b'[]',2),(b'{x',2),(b'\xff',1)])
def test_bad_json_and_incomplete_body_rejected(handler_factory, body, length):
    handler, command = handler_factory([('Content-Length',str(length))],body)
    handler.do_POST()
    assert handler.send_json.call_args.args[0] == 400
    command.assert_not_called()


def test_slow_body_times_out(handler_factory):
    handler, command = handler_factory([('Content-Length','2')])
    handler.rfile = Mock(read=Mock(side_effect=TimeoutError))
    handler.do_POST()
    assert handler.send_json.call_args.args[0] == 408
    command.assert_not_called()


def test_valid_request_and_exception_redaction(handler_factory):
    handler, command = handler_factory([('Content-Length','2')])
    handler.do_POST()
    command.assert_called_once_with({})
    assert handler.send_json.call_args.args[0] == 200
    command.side_effect = RuntimeError('private detail')
    handler.rfile = BytesIO(b'{}')
    handler.do_POST()
    assert handler.send_json.call_args.args == (500, {'ok':False,'error':'Command failed'})


def test_both_token_headers_and_duplicate_rejection(monkeypatch):
    monkeypatch.setattr(server,'COMMAND_SERVER_TOKEN','test-token')
    for key,value in [('Authorization','Bearer test-token'),('X-Jarvis-Token','test-token')]:
        headers=Message();headers[key]=value
        assert server._authorized(headers)
        headers[key]=value
        assert not server._authorized(headers)
    headers=Message();headers['Authorization']='Bearer wrong'
    assert not server._authorized(headers)


def test_connection_worker_limit_and_release(monkeypatch):
    limited=object.__new__(server._CommandHTTPServer)
    limited.slots=threading.BoundedSemaphore(1)
    limited.shutdown_request=Mock()
    start=Mock()
    monkeypatch.setattr(server.ThreadingHTTPServer,'process_request',start)
    monkeypatch.setattr(server.ThreadingHTTPServer,'process_request_thread',lambda *a:None)
    limited.process_request('one',('host',1))
    limited.process_request('two',('host',2))
    assert start.call_count==1
    limited.shutdown_request.assert_called_once_with('two')
    limited.process_request_thread('one',('host',1))
    limited.process_request('three',('host',3))
    assert start.call_count==2


def test_socket_timeout_set_before_http_reads(handler_factory,monkeypatch):
    handler,_=handler_factory()
    handler.request=Mock()
    monkeypatch.setattr(server.BaseHTTPRequestHandler,'setup',lambda self:None)
    handler.setup()
    handler.request.settimeout.assert_called_once_with(server.COMMAND_SERVER_READ_TIMEOUT)


def test_external_bind_still_requires_token(monkeypatch):
    monkeypatch.setattr(server,'COMMAND_SERVER_HOST','0.0.0.0')
    monkeypatch.setattr(server,'COMMAND_SERVER_TOKEN','')
    with pytest.raises(RuntimeError,match='TOKEN is required'):
        server.start_command_server(Mock())


@pytest.mark.parametrize('key,value', [
    ('JARVIS_COMMAND_SERVER_MAX_BODY_BYTES','0'),
    ('JARVIS_COMMAND_SERVER_MAX_BODY_BYTES','1048577'),
    ('JARVIS_COMMAND_SERVER_READ_TIMEOUT','0'),
    ('JARVIS_COMMAND_SERVER_READ_TIMEOUT','nan'),
    ('JARVIS_COMMAND_SERVER_MAX_CONNECTIONS','0'),
    ('JARVIS_COMMAND_SERVER_MAX_CONNECTIONS','129'),
])
def test_invalid_limits_rejected_in_fresh_process(key,value):
    import os
    import subprocess
    import sys
    from pathlib import Path
    env={k:v for k,v in os.environ.items() if not k.startswith('JARVIS_')}
    env[key]=value
    result=subprocess.run([sys.executable,'-c','import config'],
        cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True)
    assert result.returncode!=0
    assert key in result.stderr
