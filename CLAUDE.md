# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small 2D platformer game prototype built with pygame-ce, plus a separate, unfinished experiment for
LAN multiplayer using raw TCP sockets. There is no README, no git repo, no test suite, and no linter
configured — this is early-stage coursework/prototype code (DD1334).

## Commands

There is no build, lint, or test tooling in this repo. The only "run" targets are:

- **Run the game**: open `SpelLokalt.ipynb` in Jupyter/VS Code and run all cells in order (the game
  loop lives in a notebook, not a standalone script). Use the project venv's kernel:
  `.venv/bin/python` (Python 3.14.7, pygame-ce 2.5.8 already installed).
- **Activate the venv directly**: `source .venv/bin/activate`
- **Run the networking experiment** (two separate processes, same LAN):
  1. `python srv.py` — starts a blocking TCP server on port 50007, waits for one connection, prints
     the received pickled payload.
  2. `python client.py` — connects to the server and sends a test payload. `client.py` hardcodes the
     server's LAN IP (`HOST`) — update it to match whatever machine `srv.py` is running on.

There is no `requirements.txt`; dependencies only exist as what's already installed in `.venv`
(pygame-ce, ipykernel/jupyter stack). If new packages are needed, install into `.venv` with
`.venv/bin/pip install <pkg>`.

## Architecture

### The game (`SpelLokalt.ipynb`)

The entire game is written as sequential notebook cells that must run in order (there's no `.py`
entry point) — pygame is initialized in one cell, then later cells depend on state (the `screen`
surface, loaded images) created by earlier ones:

1. **Init & asset loading** — creates the `screen` (1920x1080), loads `blueSky.jpg` as background,
   `terrainSheet.png` as a spritesheet (a single `platform` tile is cut out via `subsurface` and
   scaled 3x), and `frog.png` as the player sprite (also scaled 3x).
2. **`render_platforms()`** — blits the background then the `platform` tile at a fixed, hardcoded
   list of `(x, y)` coordinates forming a level layout (stairs, a path across the top, etc.). To
   change the level, edit these coordinates directly — there's no level-data format or tilemap
   loader.
3. **`render_player(player)`** — blits the player's image at its current position.
4. **`Player`** class — holds position, horizontal `speed`, and simple gravity/jump physics
   (`vel_y`, `gravity`, `jump_power`). `apply_gravity()` hardcodes the ground collision at `y >= 500`
   (there's no real collision detection against the platforms rendered by `render_platforms()` — the
   player doesn't actually land on them).
5. **`handle_input()`** — reads `A`/`D`/`SPACE` from `pygame.key.get_pressed()`.
6. **`is_Grounded()`** — stub, currently unused/incomplete; ground detection actually happens inline
   in `Player.apply_gravity()`.
7. **Main loop cell** — instantiates `Player`, then each frame: renders platforms and player,
   processes `QUIT`, reads input, and updates the player's position/physics. No `clock.tick()`/FPS
   cap is set.

Assets referenced by the notebook (`blueSky.jpg`, `terrainSheet.png`, `frog.png`) live at the repo
root, not under `assets/`. The `assets/` directory (`2.jpg`-`5.jpg`, an empty `assets/Terrain/`) is
not currently referenced by any code.

### Networking experiment (`client.py`, `srv.py`)

A standalone proof-of-concept for sending Python objects over a socket, unrelated to and not wired
into the game loop above. Wire format: a 4-byte big-endian length prefix (`struct.pack("!I", len)`)
followed by a `pickle`-serialized payload. `srv.py` handles exactly one connection and one message
before exiting. If multiplayer is built out from this, the pickle-over-raw-socket approach and the
hardcoded IP/single-connection server are the parts most likely to need replacing.
