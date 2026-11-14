"""Authenticated builder's client for the local, narrowly scoped admin service."""
import json
import socket


SOCKET_PATH = '/run/rat-race-control/control.sock'


class ControlUnavailable(Exception):
    pass


class ControlError(Exception):
    pass


def request_control(action):
    if action not in ('status', 'update', 'rollback'):
        raise ValueError('Unknown server action')
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(15)
            connection.connect(SOCKET_PATH)
            connection.sendall(json.dumps({'action': action}).encode()+b'\n')
            with connection.makefile('rb') as stream:
                payload = stream.readline(131073)
            if len(payload) > 131072:
                raise ControlUnavailable()
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise ControlUnavailable()
    except (OSError, AttributeError, ValueError) as error:
        raise ControlUnavailable() from error
    if result.get('error'):
        raise ControlError(result['error'])
    return result
