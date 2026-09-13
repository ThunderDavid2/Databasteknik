"""Relay server for the SpelLokalt multiplayer prototype.

One process, one thread, one select() loop. Clients simulate their own frog and
send its world position ~20 times a second; this server keeps the last position
it heard from each of them and mails the whole roster back to everybody at the
same rate. It runs no physics.

A player who disconnects is simply absent from the next snapshot, so leave,
crash, timeout and network drop all collapse into one code path and there is no
ghost-player handling to get wrong.

Run it in a terminal, not a notebook cell: a Jupyter kernel holding a listening
socket cannot release it when you re-run the cell.
"""

import select
import shelve
import socket
import time

from netcode import (PORT, Hello, PlayerView, ProtocolError, Snapshot, State,
                     Welcome, recv_msg, send_msg)

TINTS = [(255, 255, 255), (255, 120, 120), (120, 200, 255),
         (160, 255, 140), (255, 220, 120), (220, 150, 255)]
TICK = 1 / 20
SAVE_PATH = "players"        # shelve creates ./players (dbm.sqlite3 on Python 3.14)
AUTOSAVE = 5.0

# A sanity bound on what is worth writing to disk -- not level knowledge, which
# the server deliberately does not have. The game has no respawn, so a player who
# walks off the edge of the tiles falls forever; persisting that position would
# make them resume mid-fall on every future reconnect, and the save file would
# turn a recoverable annoyance into a permanent one. Keeping their last sane
# position instead means a fall costs them nothing.
SANE_BOX = (-10_000, -10_000, 10_000, 10_000)     # min_x, min_y, max_x, max_y


def sane(x, y):
    min_x, min_y, max_x, max_y = SANE_BOX
    return min_x <= x <= max_x and min_y <= y <= max_y


def remember(save, info):
    """Persist a player's last playable position and colour, keyed by name.

    Saves info["sane"], not info["state"]: the newest position is what everyone
    else should *see* (including a frog mid-fall), but what belongs on disk is
    the last position they can actually resume from.

    Plain dicts go on disk, not message objects: the save file outlives code
    changes, so coupling it to a class definition would mean that renaming a
    field breaks every existing save.
    """
    if info["sane"] is None:
        return
    # shelve with writeback=False (the default) does not persist in-place
    # mutation of a retrieved value -- you have to assign back to the key.
    save[info["name"]] = {"x": info["sane"].x,
                          "y": info["sane"].y,
                          "tint": list(info["tint"])}


def pick_tint(save, clients, name):
    """A returning player keeps their colour and position; a new one gets the
    lowest colour nobody online is currently using."""
    saved = save.get(name)
    if saved is not None:
        return tuple(saved["tint"]), (saved["x"], saved["y"])
    taken = {info["tint"] for info in clients.values()}
    for tint in TINTS:
        if tint not in taken:
            return tint, None
    return TINTS[len(clients) % len(TINTS)], None      # more players than colours


def drop(save, clients, sock):
    info = clients.pop(sock, None)
    if info is not None:
        remember(save, info)                           # save on the way out
        print("- %s (player %d) left (%d online)"
              % (info["name"], info["id"], len(clients)), flush=True)
    try:
        sock.close()
    except OSError:
        pass


def broadcast(save, clients):
    players = [PlayerView(info["id"], info["name"], info["tint"],
                          info["state"].x, info["state"].y)
               for info in clients.values() if info["state"] is not None]
    payload = Snapshot(players)
    for sock in list(clients):        # list() so drop() can mutate the dict
        try:
            send_msg(sock, payload)
        except (OSError, ValueError):
            drop(save, clients, sock)


def accept(save, listener, clients, next_id):
    """Take one pending connection. Returns the next free player id."""
    conn, addr = listener.accept()
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(5)                             # do not hang on a silent peer
        hello = recv_msg(conn)
        if not isinstance(hello, Hello) or not hello.valid():
            raise ProtocolError(f"bad hello: {hello!r}")
        conn.settimeout(None)

        name = hello.name
        if any(info["name"] == name for info in clients.values()):
            name = f"{name}~{next_id}"                 # two people, one name
        tint, resume = pick_tint(save, clients, name)

        send_msg(conn, Welcome(next_id, tint, resume))
        clients[conn] = {"id": next_id, "name": name, "tint": tint,
                         "state": None, "sane": None}
        print("+ %s joined as player %d from %s (%d online)%s"
              % (name, next_id, addr[0], len(clients),
                 "" if resume is None else " [resumed]"), flush=True)
        return next_id + 1
    except (OSError, ProtocolError, ValueError) as e:
        print("  rejected %s: %s" % (addr[0], e), flush=True)
        clients.pop(conn, None)
        conn.close()
        return next_id


def main():
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", PORT))                   # 0.0.0.0, or the LAN cannot see us
    listener.listen(8)
    print("listening on port %d, Ctrl-C to stop" % PORT, flush=True)

    save = shelve.open(SAVE_PATH)     # one handle for the server's lifetime
    clients = {}                      # socket -> {"id", "name", "tint", "state"}
    next_id = 1
    next_tick = time.monotonic() + TICK
    next_save = time.monotonic() + AUTOSAVE

    try:
        while True:
            timeout = max(0.0, next_tick - time.monotonic())
            readable, _, _ = select.select([listener] + list(clients), [], [], timeout)

            for sock in readable:
                if sock is listener:
                    next_id = accept(save, listener, clients, next_id)
                    continue
                info = clients.get(sock)
                if info is None:
                    continue                           # dropped earlier this pass
                try:
                    msg = recv_msg(sock)
                except (OSError, ProtocolError):
                    msg = None
                if msg is None:
                    drop(save, clients, sock)
                elif isinstance(msg, State) and msg.valid():
                    info["state"] = msg                    # newest, for broadcast
                    if sane(msg.x, msg.y):
                        info["sane"] = msg                 # last playable, for the shelf
                # anything else is ignored on purpose -> forward compatibility

            now = time.monotonic()
            if now >= next_tick:
                # Reset from "now" rather than += TICK: if the loop ever stalls
                # past a tick, += would leave us behind schedule and fire a burst
                # of catch-up broadcasts. Only the newest position matters.
                next_tick = now + TICK
                broadcast(save, clients)
            if now >= next_save:
                next_save = now + AUTOSAVE
                for info in clients.values():          # survive an abrupt kill
                    remember(save, info)
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        for info in clients.values():
            remember(save, info)
        save.close()
        listener.close()


if __name__ == "__main__":
    main()
