# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A 2D platformer game prototype built with pygame-ce, now with working LAN multiplayer: a
notebook-driven client with real tile collision and a scrolling camera, talking to a standalone
relay server over TCP. There is no git repo, no README, no test suite, and no linter configured —
this is early-stage coursework/prototype code (DD1334).

## Commands

There is no build, lint, or test tooling in this repo. The run targets are:

- **Run the game client**: open `SpelLokalt.ipynb` in Jupyter/VS Code and run all cells in order
  (the game loop lives in a notebook, not a standalone script). Use the project venv's kernel:
  `.venv/bin/python` (Python 3.14.7, pygame-ce 2.5.8 already installed).
- **Activate the venv directly**: `source .venv/bin/activate`
- **Run the multiplayer server** (once, in a real terminal — see below):
  `python server.py` — binds `0.0.0.0:50007` and relays player positions to everyone connected.
- **Test multiplayer without a second real client**: `python dummy_player.py [host] [name]` —
  connects as an ordinary client and walks a fake frog back and forth, so the pipeline is testable
  from one machine.
- Before connecting from the notebook, edit `SERVER_HOST` and `PLAYER_NAME` in the client-connect
  cell of `SpelLokalt.ipynb` to point at whatever machine `server.py` is running on, and to a name
  unique to the person running it (it doubles as the save-file key).

There is no `requirements.txt`; dependencies only exist as what's already installed in `.venv`
(pygame-ce, ipykernel/jupyter stack). If new packages are needed, install into `.venv` with
`.venv/bin/pip install <pkg>`.

**Important**: run `server.py` in a terminal, never execute it from a notebook cell — a Jupyter
kernel holding a listening socket cannot release it when the cell is re-run, so the port stays
bound after a restart attempt.

## Architecture

### Wire protocol (`netcode.py`)

Shared by the server and the notebook client — both must import it under the module name
`netcode`, because pickle records the defining module of every class it serializes (a
`PlayerState` pickles as `"netcode.PlayerState"`) and the unpickler's allowlist is keyed on that
exact pair.

- Wire format: a 4-byte big-endian length prefix (`struct.Struct("!I")`) followed by a pickled
  payload, capped at `MAX_MSG` (64 KiB) in both directions to reject a hostile or corrupt length
  prefix before allocating.
- `SafeUnpickler` overrides `find_class` to allow-list exactly five classes (`JoinRequest`,
  `JoinResponse`, `PlayerState`, `RemotePlayerState`, `RosterSnapshot`); anything else raises
  rather than executing arbitrary code via `__reduce__`. Adding a new message type means adding it
  to `ALLOWED` here.
- `NetClient` is the client-side connection object used from the notebook: `JoinRequest`/
  `JoinResponse` handshake on connect, then `update(x, y)` once per frame sends the local player's
  `PlayerState` (throttled to `SEND_HZ = 20`) and drains any buffered `RosterSnapshot`s
  non-blockingly, returning the other players' latest `RemotePlayerState`s. A dead/rejected
  connection sets `connected = False` and clears `remotes` rather than raising, so the render loop
  doesn't need special-case error handling per frame.

### Relay server (`server.py`)

Single process, single thread, one `select()` loop — no per-client threads. It runs no physics and
holds no level knowledge: it just remembers the last `PlayerState` heard from each socket and
broadcasts a `RosterSnapshot` of everyone to everyone at `TICK = 1/20`.

- Persistence is a `shelve` file (`SAVE_PATH = "players"`, backed by `dbm.sqlite3` on Python 3.14 —
  hence the `players`/`players-shm`/`players-wal` files at the repo root) keyed by player name,
  storing last position and tint. Saved on disconnect, every `AUTOSAVE` (5s) seconds, and on
  shutdown.
- Deliberately saves the last *sane* position (`sane()` bounds-checks against `SANE_BOX`), not the
  newest one: the game has no respawn, so persisting a mid-fall position would strand a returning
  player permanently instead of just costing them one fall.
- A returning player (same name) gets their saved tint and position back via `JoinResponse.resume`;
  a new name gets the lowest unused tint from `TINTS`. Two connections with the same name get
  disambiguated as `name~id`.
- A disconnect (leave, crash, timeout, or network drop) is handled by one code path — the player is
  just absent from the next snapshot — so there's no separate ghost-player cleanup to maintain.

### Game client (`SpelLokalt.ipynb`)

Sequential notebook cells that must run in order — there's no `.py` entry point — because later
cells depend on state (`screen`, loaded/scaled images, tile lists) created by earlier ones:

1. **Init & asset loading** — creates the `screen` (1920x1080), loads `blueSky.jpg` as background,
   cuts a `platform` tile out of `terrainSheet.png`, a `frog.png` player sprite, and `ground`/`below`
   tiles out of `world_tileset.png` (all scaled 3x). Imports `NetClient` from `netcode`.
2. **Level layout** — `PLATFORMS`, `GROUND` (a strip across the bottom of a 1920-wide world), and
   `BELOW` (filler rows under the ground strip) are hardcoded tile-coordinate lists — there's no
   tilemap/level-data format, edit these lists directly to change the layout.
3. **`make_island()` + `ISLANDS`** — a small prefab helper that generates floating-island tile
   coordinates (ground row + below-tile fill) merged into `GROUND`/`BELOW`, rather than hand-listing
   every tile.
4. **`tinted_frog()`** — recolors the frog sprite per remote player via `BLEND_RGBA_MULT` so players
   are visually distinguishable; memoized in `_tint_cache` since it would otherwise re-run per
   remote player per frame.
5. **`Camera`** — tracks the local player vertically only (`follow()`; horizontal offset is
   commented out) and does all world rendering: background, platforms, ground/below tiles, remote
   players (from `NetClient.update()`), then the local player, each offset by the camera.
6. **`Player`** — position, gravity (`vel_y`, `gravity`, `jump_power`), and an `on_ground` flag set
   by real collision resolution (see below), not a hardcoded ground `y`.
7. **`handle_input()`** — reads `A`/`D`/`SPACE` from `pygame.key.get_pressed()`.
8. **`SOLID_RECTS` + `handle_platform_collision()`** — the actual collision system: builds
   `pygame.Rect`s for every platform/ground/below tile once, then each frame resolves overlap by
   comparing top/bottom/left/right penetration depth and pushing the player out along the shallowest
   axis, setting `on_ground` when landing from above. This replaced the old hardcoded `y >= 500`
   ground check.
9. **`is_Grounded()`** — a separate, simpler ground check against `PLATFORMS`/`GROUND` tile lists
   directly (not `SOLID_RECTS`); currently unused by the main loop, which relies on
   `handle_platform_collision`'s `on_ground` return value instead.
10. **Client connect cell** — sets `PLAYER_NAME`/`SERVER_HOST`, closes any existing `net` (so
    re-running the cell doesn't leak a socket), and opens a new `NetClient`.
11. **Main loop cell** — instantiates `Camera`/`Player`, restores `net.resume` position if present,
    then each frame: input → move/gravity/collision → `net.update()` for remote positions →
    `camera.render_world()` → caption shows FPS/name/id/connection status/remote count →
    `clock.tick(60)`.

Assets: `blueSky.jpg`, `terrainSheet.png`, `frog.png`, and `world_tileset.png` live at the repo
root. `assets/` (`2.jpg`-`5.jpg`, empty `assets/Terrain/`) and `brackeys_platformer_assets/`
(sprites/sounds/music/fonts) are not currently referenced by any code.
