import select
import shelve
import socket
import time

from netcode import (
    PORT,
    JoinRequest,
    JoinResponse,
    PlayerState,
    RemotePlayerState,
    RosterSnapshot,
    recv_msg,
    send_msg,
)

TICK = 1 / 20
SAVE_PATH = "players"
AUTOSAVE = 5.0


def remember(save, info):
    if info["state"] is None:
        return
    save[info["name"]] = {
        "x": info["state"].x,
        "y": info["state"].y,
        "char": info["char"],
    }


def resume_position(save, name):
    saved = save.get(name)
    if saved is None:
        return None
    else:
        return (saved["x"], saved["y"])


def drop(save, clients, sock):
    info = clients.pop(sock, None)
    if info is not None:
        remember(save, info)
        print(
            "- %s (player %d) left (%d online)"
            % (info["name"], info["id"], len(clients)),
            flush=True,
        )
    sock.close()


def broadcast(save, clients):
    players = [
        RemotePlayerState(
            info["id"], info["name"], info["char"], info["state"].x, info["state"].y
        )
        for info in clients.values()
        if info["state"] is not None
    ]
    payload = RosterSnapshot(players)
    for sock in list(clients):
        send_msg(sock, payload)


def accept(save, listener, clients, next_id):
    conn, addr = listener.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(5)
    join_request = recv_msg(conn)
    conn.settimeout(None)

    name = join_request.name
    resume = resume_position(save, name)

    send_msg(conn, JoinResponse(next_id, join_request.char, resume))
    clients[conn] = {
        "id": next_id,
        "name": name,
        "char": join_request.char,
        "state": None,
    }
    if resume is None:
        resumed_note = ""
    else:
        resumed_note = " [resumed]"
    print(
        "+ %s joined as player %d from %s (%d online)%s"
        % (
            name,
            next_id,
            addr[0],
            len(clients),
            resumed_note,
        ),
        flush=True,
    )
    return next_id + 1


def main():
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", PORT))
    listener.listen(8)
    print("listening on port %d, Ctrl-C to stop" % PORT, flush=True)

    save = shelve.open(SAVE_PATH)
    clients = {}
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
                    continue
                try:
                    msg = recv_msg(sock)
                except (OSError, ValueError):
                    msg = None
                if msg is None:
                    drop(save, clients, sock)
                elif isinstance(msg, PlayerState):
                    info["state"] = msg

            now = time.monotonic()
            if now >= next_tick:
                next_tick = now + TICK
                broadcast(save, clients)
            if now >= next_save:
                next_save = now + AUTOSAVE
                for info in clients.values():
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
