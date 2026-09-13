"""A headless fake player, for testing multiplayer with only one notebook open.

One notebook file gives you one Jupyter kernel, so opening two real game windows
on one machine is awkward. This connects as an ordinary client and paces back and
forth along the ground, which makes the whole pipeline testable on your own.

    python dummy_player.py [host] [name]
"""

import math
import sys
import time

from netcode import NetClient

GROUND_Y = 1032          # the GROUND row: 1080 - GROUND_HEIGHT, with GROUND_HEIGHT = 48
FROG_H = 96              # frog.png is 32x32, scaled 3x

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
name = sys.argv[2] if len(sys.argv) > 2 else "bot"

net = NetClient(host, name)
print("bot connected as player", net.my_id, "tint", net.tint)

start = time.monotonic()
try:
    while net.connected:
        t = time.monotonic() - start
        net.update(700 + 400 * math.sin(t * 0.5), GROUND_Y - FROG_H)
        time.sleep(1 / 60)
except KeyboardInterrupt:
    pass
finally:
    net.close()
    print("bot disconnected")
