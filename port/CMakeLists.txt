cmake_minimum_required(VERSION 3.20)
project(sjfport LANGUAGES C CXX ASM)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# --- dynarmic (A64 only, bundled externals) ---
set(DYNARMIC_TESTS OFF CACHE BOOL "" FORCE)
set(DYNARMIC_FRONTENDS "A64" CACHE STRING "" FORCE)
set(DYNARMIC_WARNINGS_AS_ERRORS OFF CACHE BOOL "" FORCE)
set(DYNARMIC_USE_BUNDLED_EXTERNALS ON CACHE BOOL "" FORCE)
set(DYNARMIC_USE_PRECOMPILED_HEADERS OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/dynarmic EXCLUDE_FROM_ALL)

add_executable(sjfport
    src/main.cpp
    src/engine/boot.cpp
    src/engine/profile_edit.cpp
    src/platform/window.cpp
    src/platform/audio.cpp
    third_party/stb/stb_vorbis.c
    src/runtime/guest_memory.cpp
    src/runtime/guest_abi.cpp
    src/runtime/host_calls.cpp
    src/runtime/elf_loader.cpp
    src/runtime/jit.cpp
    src/dex/jni_env.cpp
    src/dependencies/libc.cpp
    src/dependencies/libm.cpp
    src/dependencies/liblog.cpp
    src/dependencies/libdl.cpp
    src/dependencies/libandroid.cpp
    src/dependencies/libgl.cpp
    src/dependencies/libopensl.cpp
    src/dependencies/pthread.cpp
)

if(WIN32)
    set(SDL2_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../tools/sdl2/SDL2-2.32.10/x86_64-w64-mingw32")

    target_include_directories(sjfport PRIVATE
        include
        third_party/dynarmic/src
        third_party/ndk
        ${SDL2_DIR}/include/SDL2
    )

    target_link_directories(sjfport PRIVATE ${SDL2_DIR}/lib)

    target_link_libraries(sjfport PRIVATE dynarmic SDL2 opengl32
        mingw32 user32 gdi32 winmm imm32 ole32 oleaut32 shell32 oleacc uuid version hid setupapi dxguid dinput8)

    add_custom_command(TARGET sjfport POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${SDL2_DIR}/bin/SDL2.dll" "$<TARGET_FILE_DIR:sjfport>")
else()
    # Linux / POSIX build (development + headless testing under Xvfb)
    find_package(SDL2 REQUIRED)
    find_package(OpenGL REQUIRED)
    find_package(Threads REQUIRED)
    target_include_directories(sjfport PRIVATE
        include
        third_party/dynarmic/src
        third_party/ndk
        ${SDL2_INCLUDE_DIRS}
    )
    target_link_libraries(sjfport PRIVATE dynarmic ${SDL2_LIBRARIES} OpenGL::GL Threads::Threads ${CMAKE_DL_LIBS})
endif()

if(MINGW)
    target_link_options(sjfport PRIVATE -static -static-libgcc -static-libstdc++)
endif()
