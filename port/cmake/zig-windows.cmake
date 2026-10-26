# Cross-compile sjfport.exe for Windows (x86_64, MinGW ABI) from Linux using zig.
# Usage: cmake -S port -B port/build-win -G Ninja -DCMAKE_TOOLCHAIN_FILE=port/cmake/zig-windows.cmake
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(_z "${CMAKE_CURRENT_LIST_DIR}/zig")
set(CMAKE_C_COMPILER   "${_z}/zig-cc")
set(CMAKE_CXX_COMPILER "${_z}/zig-c++")
set(CMAKE_ASM_COMPILER "${_z}/zig-cc")
set(CMAKE_AR           "${_z}/zig-ar")
set(CMAKE_RANLIB       "${_z}/zig-ranlib")
set(CMAKE_RC_COMPILER  "${_z}/zig-rc")
set(MINGW TRUE)
# fmt 10.1 (dynarmic external) trips clang>=17 consteval checks; GCC is unaffected.
set(CMAKE_CXX_FLAGS_INIT "-DFMT_CONSTEVAL=")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
