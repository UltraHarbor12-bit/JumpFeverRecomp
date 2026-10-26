# JumpFeverRecomp

**A PC port of *Sonic Jump Fever* (Android, ARM64) — bring your own APK.**

🇪🇸 [Leer en español](README.es.md)

> [!IMPORTANT]
> **This repository contains no game data.** No APK, no `libsonicjumpfever.so`, no textures, music or sprites.
> The launcher extracts everything it needs from **your own legally obtained APK** on your machine.
> Don't open issues or PRs containing game files.

## How it works

JumpFeverRecomp does not translate the game ahead of time. It loads the original Android ARM64 native library and runs it through a JIT, while re-implementing the Android environment around it (a Wine-style compatibility layer):

- **ELF loader + [dynarmic](https://github.com/merryhime/dynarmic)** — runs the game's ARM64 code on x86-64.
- **Android shims** — JNI, bionic `libc`/`libm`/`libdl`/`pthread`, `liblog`, `libandroid`, OpenGL ES (on top of desktop GL) and OpenSL ES (on top of SDL2 audio).
- **SDL2** for window, input (keyboard, mouse-as-touch, gamepad) and audio.
- **Python launcher** (stdlib + tkinter only) that installs your APK's data, downloads missing toolchains, builds and starts the game.

## Features

- All 4 zones playable end to end (Green Hill, Blue Sky, Jungle, Mechanical), menus, saving, audio
- Widescreen: 9:16 original, 3:4, 4:3, 16:10, 16:9, 21:9 or auto
- Keyboard, mouse and gamepad, with remappable keys
- Save editor (rings, red rings, energy, characters, boosters)
- Optional: Cream, Rouge and Vector are selectable. Their code, stats and portraits exist in the original game, but their sprites never shipped, so the launcher builds stand-in sprites **locally from your own APK** (recolored Knuckles / Silver / Amy)
- Fixed or weekly-rotating zone selector

## Requirements

- **Sonic Jump Fever 1.6.1, arm64-v8a** APK that you own. The `.so` inside must have SHA-256 `4bbe841e2068c389324414750ccd37ca8153a693643d1cd62e4377c5cb07bd3f` (addresses are hard-coded for this exact build).
- Python 3.8+ with `tkinter`
- A GPU/driver with OpenGL support
- Windows 10/11 x64 or Linux x64

## Quick start

```text
Windows:  double-click Lanzador.bat
Linux:    ./lanzador.sh
```

1. **INSTALAR** → pick your APK → *Instalar datos del juego*
2. **COMPILAR** → Windows or Linux → *Descargar lo que falta* → *Compilar*
3. **JUGAR** → choose zone and aspect ratio → *JUGAR!*

Controls: mouse = touch · arrows / A-D = tilt · Esc = back · F11 or Alt+Enter = fullscreen · gamepad: stick/d-pad, A, B/Start.

## Command line

```text
sjfport game/libsonicjumpfever.so [options]        (run from port/)
  --window WxH          window size            --fullscreen      fullscreen
  --aspect W:H|auto     widescreen             --zone Z          green_hill_zone | blue_sky_zone | jungle_zone | mechanical_zone
  --controls FILE       key mapping            --profile-edit F  edit the save from the game
  --no-extra-chars      hide Cream/Rouge/Vector
  --timeout S           0 = no limit           --debug --verbose diagnostics
```

## Build from source

Needs CMake ≥ 3.20, Ninja, a C++20 compiler, SDL2 and Boost headers. The launcher can fetch all of this for you; manually:

```bash
# Linux
sudo apt install cmake ninja-build g++ libsdl2-dev libgl-dev libboost-dev
cmake -S port -B port/build-linux -G Ninja
cmake --build port/build-linux
# Windows from Linux (zig cross-build)
cmake -S port -B port/build-win -G Ninja -DCMAKE_TOOLCHAIN_FILE=port/cmake/zig-windows.cmake
```

## Status

| Platform | State |
|---|---|
| Linux | Tested: all zones, menus, saving, audio, gamepad, widescreen, save editor, remapping, extra characters |
| Windows | Compiles and links (MinGW and zig cross-build). Tested under Wine; **not yet validated on real Windows** — reports welcome |

## Repository layout

```text
port/src, port/include   C++ source (runtime/JIT, Android shims, platform, engine hooks)
port/third_party/        dynarmic (patched), stb_vorbis, jni.h
port/game/               EMPTY — the launcher installs your data here
tools/launcher/          Python launcher, save reader, controls, music, extra characters
tools/                   analysis/patching helper scripts
docs/                    technical write-up, milestone by milestone (Spanish)
```

## Legal

This is an unofficial fan project for interoperability and preservation. It is not affiliated with or endorsed by SEGA.
*Sonic*, *Sonic Jump Fever* and *SEGA* are trademarks of SEGA Corporation. You must own a legal copy of the game.
Do not distribute the portable folder the launcher can create (`dist/`): it contains data from your APK.
Original code is MIT licensed; third-party code keeps its own license — see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
