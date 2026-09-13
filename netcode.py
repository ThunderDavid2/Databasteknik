"""Length-prefixed pickled message objects over TCP, shared by the server and the game.

Wire format: 4 bytes big-endian unsigned length, then that many bytes of pickle.

The message classes live here rather than in the notebook because pickle records
the module path of every class it serializes: a State pickles as "netcode.State",
and the unpickler's allowlist is keyed on that exact pair. Both processes must
import this module under the name "netcode" or unpickling fails.
"""

import io
import math
import pickle
import select
import socket
import struct
import time

PORT = 50007
HEADER = struct.Struct("!I")
MAX_MSG = 64 * 1024              # refuse absurd length prefixes
PROTOCOL = pickle.HIGHEST_PROTOCOL


def _finite(*values):
    """True if every value is a real, finite number."""
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


class Hello:
    """First message a client sends. The name is the save-file key."""

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def valid(self):
        # __init__ is bypassed when unpickling, so this is the only validation
        # that ever runs on received data, and slots may be unset entirely.
        try:
            return isinstance(self.name, str) and 1 <= len(self.name) <= 16
        except AttributeError:
            return False


class Welcome:
    """Server's reply. resume is a saved (x, y) world position, or None if new."""

    __slots__ = ("pid", "tint", "resume")

    def __init__(self, pid, tint, resume=None):
        self.pid, self.tint, self.resume = pid, tint, resume

    def valid(self):
        try:
            if not isinstance(self.pid, int):
                return False
            if len(self.tint) != 3 or not _finite(*self.tint):
                return False
            if self.resume is None:
                return True
            return len(self.resume) == 2 and _finite(*self.resume)
        except (AttributeError, TypeError):
            return False


class State:
    """A client's own frog, in WORLD coordinates."""

    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x, self.y = x, y

    def valid(self):
        try:
            return _finite(self.x, self.y)
        except AttributeError:
            return False


class PlayerView:
    """One entry in a snapshot: somebody else's frog as the server last heard it."""

    __slots__ = ("pid", "name", "tint", "x", "y")

    def __init__(self, pid, name, tint, x, y):
        self.pid, self.name, self.tint, self.x, self.y = pid, name, tint, x, y

    def valid(self):
        try:
            return (isinstance(self.pid, int) and isinstance(self.name, str)
                    and len(self.tint) == 3 and _finite(*self.tint)
                    and _finite(self.x, self.y))
        except (AttributeError, TypeError):
            return False


class Snapshot:
    """The complete roster, sent to everyone at 20 Hz."""

    __slots__ = ("players",)

    def __init__(self, players):
        self.players = players

    def valid_players(self):
        """The entries that are safe to draw. Anything malformed is dropped."""
        try:
            return [p for p in self.players
                    if isinstance(p, PlayerView) and p.valid()]
        except (AttributeError, TypeError):
            return []


ALLOWED = {
    ("netcode", "Hello"),
    ("netcode", "Welcome"),
    ("netcode", "State"),
    ("netcode", "PlayerView"),
    ("netcode", "Snapshot"),
}


class ProtocolError(Exception):
    """An undecodable or disallowed message. Never fatal to the server."""


class SafeUnpickler(pickle.Unpickler):
    """Only our five message classes may be constructed from the wire.

    pickle's default loads() runs whatever the sender encodes -- an object whose
    __reduce__ returns (os.system, ("rm -rf ~",)) executes on receipt, so anyone
    who can reach the port would own the host machine. find_class is the only
    hook pickle uses to look up a global, so refusing everything outside the
    allowlist closes that hole while still permitting our own messages.
    """

    def find_class(self, module, name):
        if (module, name) not in ALLOWED:
            raise pickle.UnpicklingError(f"refusing to load {module}.{name}")
        return super().find_class(module, name)


def recv_exact(sock, n):
    """recv() is allowed to return fewer bytes than asked, so loop until n or EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None                      # peer closed the connection
        buf += chunk
    return bytes(buf)


def send_msg(sock, obj):
    payload = pickle.dumps(obj, protocol=PROTOCOL)
    if len(payload) > MAX_MSG:
        raise ValueError(f"message too large to send: {len(payload)} bytes")
    sock.sendall(HEADER.pack(len(payload)) + payload)   # one sendall: never split


def recv_msg(sock):
    """Return the next message object, or None if the peer closed the connection.

    Raises ProtocolError for anything undecodable, so callers need to catch only
    (OSError, ProtocolError) rather than pickle's long tail of failure modes.
    """
    header = recv_exact(sock, HEADER.size)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length > MAX_MSG:
        # Never allocate on a stranger's word: a bogus prefix of \xff\xff\xff\xff
        # would otherwise ask for a 4 GiB read.
        raise ProtocolError(f"refusing {length}-byte message")
    payload = recv_exact(sock, length)
    if payload is None:
        return None
    try:
        return SafeUnpickler(io.BytesIO(payload)).load()
    except Exception as e:                   # UnpicklingError, EOFError, and a long tail
        raise ProtocolError(f"undecodable message: {e!r}") from e


class NetClient:
    """Client socket, drained once per frame from the game loop. No threads.

    All isinstance dispatch stays inside this module so that reloading netcode in
    a notebook cannot leave the caller comparing against stale class objects. The
    notebook only calls update() and reads attributes off the returned PlayerViews.
    """

    SEND_HZ = 20

    def __init__(self, host, name, port=PORT):
        # The 5 second timeout is still active here, so a server that accepts but
        # never replies raises instead of hanging the notebook kernel forever.
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        send_msg(self.sock, Hello(name))
        welcome = recv_msg(self.sock)
        if not isinstance(welcome, Welcome) or not welcome.valid():
            self.sock.close()
            raise ConnectionError(f"expected a valid Welcome, got {welcome!r}")

        self.my_id = welcome.pid
        self.tint = tuple(welcome.tint)
        self.resume = welcome.resume          # (x, y) to restore, or None
        self.sock.settimeout(None)
        self.connected = True
        self.remotes = []
        self._last_send = 0.0

    def update(self, x, y):
        """Call once per frame. Returns the other players' latest world positions
        as PlayerView objects -- read p.x, p.y, p.tint, p.name."""
        self._send(x, y)
        self._drain()
        return self.remotes

    def _send(self, x, y):
        now = time.monotonic()
        if not self.connected or now - self._last_send < 1.0 / self.SEND_HZ:
            return                                   # not time to send yet
        self._last_send = now
        try:
            send_msg(self.sock, State(x, y))
        except (OSError, ValueError):
            self._die()

    def _drain(self):
        """Read every snapshot that has already arrived, then return immediately."""
        while self.connected:
            # 0 = do not wait. This says "at least one byte is ready", not "a whole
            # message is ready", so recv_msg could in principle block partway
            # through one; at under 300 bytes on a LAN that does not happen.
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
            if isinstance(msg, Snapshot):
                self.remotes = [p for p in msg.valid_players()
                                if p.pid != self.my_id]

    def _die(self):
        self.connected = False
        self.remotes = []        # stop drawing frozen frogs at their last positions

    def close(self):
        self._die()
        try:
            self.sock.close()
        except OSError:
            pass
