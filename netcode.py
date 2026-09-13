import io
import math
import pickle
import select
import socket
import struct
import time

PORT = 50007
HEADER = struct.Struct("!I")
MAX_MSG = 64 * 1024
PROTOCOL = pickle.HIGHEST_PROTOCOL


class JoinRequest:

    def __init__(self, name):
        self.name = name




class JoinResponse:
    def __init__(self, pid, tint, resume=None):
        self.pid, self.tint, self.resume = pid, tint, resume



class PlayerState:

    def __init__(self, x, y):
        self.x, self.y = x, y




class RemotePlayerState:

    def __init__(self, pid, name, tint, x, y):
        self.pid, self.name, self.tint, self.x, self.y = pid, name, tint, x, y


class RosterSnapshot:

    def __init__(self, players):
        self.players = players




ALLOWED = {
    ("netcode", "JoinRequest"),
    ("netcode", "JoinResponse"),
    ("netcode", "PlayerState"),
    ("netcode", "RemotePlayerState"),
    ("netcode", "RosterSnapshot"),
}


class ProtocolError(Exception):
    pass


class SafeUnpickler(pickle.Unpickler):

    def find_class(self, module, name):
        if (module, name) not in ALLOWED:
            raise pickle.UnpicklingError(f"refusing to load {module}.{name}")
        return super().find_class(module, name)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def send_msg(sock, obj):
    payload = pickle.dumps(obj, protocol=PROTOCOL)
    if len(payload) > MAX_MSG:
        raise ValueError(f"message too large to send: {len(payload)} bytes")
    sock.sendall(HEADER.pack(len(payload)) + payload)


def recv_msg(sock):
    header = recv_exact(sock, HEADER.size)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length > MAX_MSG:
        raise ProtocolError(f"refusing {length}-byte message")
    payload = recv_exact(sock, length)
    if payload is None:
        return None
    try:
        return SafeUnpickler(io.BytesIO(payload)).load()
    except Exception as e:
        raise ProtocolError(f"undecodable message: {e!r}") from e


class NetClient:

    SEND_HZ = 20

    def __init__(self, host, name, port=PORT):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        send_msg(self.sock, JoinRequest(name))
        join_response = recv_msg(self.sock)
        if not isinstance(join_response, JoinResponse):
            self.sock.close()
            raise ConnectionError(f"expected a valid JoinResponse, got {join_response!r}")

        self.my_id = join_response.pid
        self.tint = tuple(join_response.tint)
        self.resume = join_response.resume
        self.sock.settimeout(None)
        self.connected = True
        self.remotes = []
        self._last_send = 0.0

    def update(self, x, y):
        self._send(x, y)
        self._drain()
        return self.remotes

    def _send(self, x, y):
        now = time.monotonic()
        if not self.connected or now - self._last_send < 1.0 / self.SEND_HZ:
            return
        self._last_send = now
        try:
            send_msg(self.sock, PlayerState(x, y))
        except (OSError, ValueError):
            self._die()

    def _drain(self):
        while self.connected:
            readable, _, _ = select.select([self.sock], [], [], 0)
            if not readable:
                return
            try:
                msg = recv_msg(self.sock)
            except (OSError, ProtocolError):
                msg = None
            if msg is None:
                self._die()
                return
            if isinstance(msg, RosterSnapshot):
                self.remotes = [p for p in msg.players
                                if p.pid != self.my_id]

    def _die(self):
        self.connected = False
        self.remotes = []

    def close(self):
        self._die()
        try:
            self.sock.close()
        except OSError:
            pass
