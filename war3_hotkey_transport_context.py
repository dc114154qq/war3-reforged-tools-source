"""Typed identity and wire contract for the shared loader transport."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import struct

_identity = ContextVar('hotkey_transport_identity', default=None)


@contextmanager
def transport_scope(identity):
    if identity.profile is None:
        raise ValueError('Shared transport requires an identified adapter')
    token = _identity.set(identity)
    try:
        yield
    finally:
        _identity.reset(token)


class TransportProfile:
    def __init__(self, identity):
        self.id = identity.version
        self.digest = hashlib.sha256(json.dumps(identity.profile, sort_keys=True).encode()).hexdigest()

    def bridge_bytes(self):
        # The generic loader's configuration has no hotkey object-layout fields.
        return struct.pack('<13I', 1, 52, *([0] * 11))


def current_profile():
    identity = _identity.get()
    if identity is None:
        raise RuntimeError('No verified hotkey session is active')
    return TransportProfile(identity)


def prepare_operation(kind, payload):
    if kind != 'hotkey' or len(payload) != 800:
        raise ValueError('Invalid hotkey transport operation')
    magic, version, status, count = struct.unpack_from('<4I', payload)
    if (magic, version, status) != (0x4b485257, 4, 1) or not 1 <= count <= 16:
        raise ValueError('Invalid hotkey wire header')
    index = 0
    while index < count:
        operation = struct.unpack_from('<I', payload, 32 + index * 48)[0]
        if not 1 <= operation <= 13:
            raise ValueError('Unknown hotkey operation')
        if operation == 3:
            if index + 3 > count:
                raise ValueError('Incomplete selection query')
            index += 3
        else:
            index += 1
    return struct.pack('<3I', 0x4b485257, 216, 800), b'hotkey_bridge_abi', b'HotkeyBridgeQuery'


def verify_opened_process(memory):
    from war3_hotkey_adapters import identify_process
    from war3_hotkey_transport import bytes_at
    expected = _identity.get()
    if expected is None:
        raise RuntimeError('Missing expected process identity')
    memory.read = lambda address, size: bytes_at(memory.handle, address, size)
    actual = identify_process(memory, memory.pid)
    if actual.key != expected.key:
        raise RuntimeError('Game process incarnation changed before dispatch')
    return actual
