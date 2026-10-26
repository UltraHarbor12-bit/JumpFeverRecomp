# Third-party notices

This repository vendors the following third-party code. Each keeps its own license;
check the license files inside each folder before redistributing.

| Component | Location | License |
|---|---|---|
| [dynarmic](https://github.com/merryhime/dynarmic) (ARM64 JIT), with local clang-compatibility patches | `port/third_party/dynarmic/` | 0BSD (its bundled externals — fmt, mcl, xbyak, zydis, robin-map, biscuit, oaknut, Catch2 — have their own licenses in `externals/`) |
| [stb_vorbis](https://github.com/nothings/stb) | `port/third_party/stb/` | Public domain / MIT |
| Android NDK `jni.h` | `port/third_party/ndk/` | Apache License 2.0 |

Downloaded on demand by the launcher (not stored in the repo): SDL2 (zlib), Boost (BSL-1.0),
CMake (BSD-3), Ninja (Apache-2.0), WinLibs MinGW-w64 (GPL/LGPL runtime exceptions), zig (MIT), ffmpeg (LGPL/GPL, optional).

## Trademarks

"Sonic", "Sonic the Hedgehog", "Sonic Jump Fever" and "SEGA" are trademarks of SEGA Corporation.
This project is not affiliated with, endorsed by, or sponsored by SEGA.
