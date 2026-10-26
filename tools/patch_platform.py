import io

def rd(p):
    with io.open(p, 'r', encoding='utf-8', newline=None) as f:
        return f.read()

def wr(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)

# ---------- boot.cpp: window + onNativeWindowCreated + frame loop ----------
p = 'port/src/engine/boot.cpp'
s = rd(p)
s = s.replace('''#include "sjfport/jni_env.h"
#include "sjfport/runtime.h"

#include <cstring>
#include <string>''', '''#include "sjfport/jni_env.h"
#include "sjfport/platform.h"
#include "sjfport/runtime.h"

#include <chrono>
#include <cstring>
#include <string>
#include <thread>''')

s = s.replace('''    LOGI("=== boot reached the end of Hito 1 (no window/EGL yet) ===");
    return true;
}''', '''    // ---------- Hito 2: window, surface, frame loop ----------
    if (!platform_create_window(540, 960)) {
        LOGW("boot: window creation failed — stopping before onNativeWindowCreated");
        return true;
    }
    u64 native_window = alloc_native_data(32, 8);
    if (cb && cb->onNativeWindowCreated) {
        LOGI("boot: -> callbacks->onNativeWindowCreated");
        guest_call((u64)cb->onNativeWindowCreated, activity, native_window, 0, 0, 0, 0, 0, 0,
                   "onNativeWindowCreated");
        LOGI("boot: onNativeWindowCreated returned");
    }

    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");
    auto t0 = std::chrono::steady_clock::now();
    for (;;) {
        if (!platform_pump())
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                      std::chrono::steady_clock::now() - t0)
                      .count();
        if (ms > 60000) {
            LOGI("boot: 60 s of frame loop reached, stopping");
            break;
        }
    }
    LOGI("boot: frame loop ended");
    return true;
}''')
wr(p, s)
print('ok boot.cpp')

# ---------- CMakeLists: platform + SDL2 ----------
p = 'port/CMakeLists.txt'
s = rd(p)
s = s.replace('''    src/main.cpp
    src/engine/boot.cpp''', '''    src/main.cpp
    src/engine/boot.cpp
    src/platform/window.cpp''')

s = s.replace('''target_include_directories(sjfport PRIVATE
    include
    third_party/dynarmic/src
    third_party/ndk
)

target_link_libraries(sjfport PRIVATE dynarmic)''', '''set(SDL2_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../tools/sdl2/SDL2-2.32.10/x86_64-w64-mingw32")

target_include_directories(sjfport PRIVATE
    include
    third_party/dynarmic/src
    third_party/ndk
    ${SDL2_DIR}/include
)

target_link_directories(sjfport PRIVATE ${SDL2_DIR}/lib)

target_link_libraries(sjfport PRIVATE dynarmic SDL2 opengl32)

add_custom_command(TARGET sjfport POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${SDL2_DIR}/bin/SDL2.dll" "$<TARGET_FILE_DIR:sjfport>")''')
wr(p, s)
print('ok CMakeLists')

# ---------- main.cpp: --shot ----------
p = 'port/src/main.cpp'
s = rd(p)
s = s.replace('''#include "sjfport/common.h"''', '''#include "sjfport/common.h"
#include "sjfport/platform.h"''')
s = s.replace('''        else if (a == "--timeout" && i + 1 < argc)
            timeout = std::atoi(argv[++i]);''', '''        else if (a == "--timeout" && i + 1 < argc)
            timeout = std::atoi(argv[++i]);
        else if (a == "--shot" && i + 1 < argc)
            shot = argv[++i];
        else if (a == "--shot-swap" && i + 1 < argc)
            shot_swap = std::atoi(argv[++i]);''')
s = s.replace('''    std::string so = "game/libsonicjumpfever.so";
    int timeout = 20;''', '''    std::string so = "game/libsonicjumpfever.so";
    std::string shot = "first_frame.bmp";
    int shot_swap = 180;
    int timeout = 20;''')
s = s.replace('''    if (timeout > 0)
        start_watchdog(timeout);''', '''    sjf::platform_set_screenshot(shot.c_str(), shot_swap);
    if (timeout > 0)
        start_watchdog(timeout);''')
wr(p, s)
print('ok main.cpp')
print('done')
