// sjfport — entry point
#include "sjfport/common.h"
#include "sjfport/platform.h"
#include "sjfport/runtime.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#endif

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>

namespace sjf {
bool boot(const std::string& so_path);
void jit_dump_threads();
}

#ifdef _WIN32
static LONG WINAPI crash_filter(EXCEPTION_POINTERS* ep) {
    auto* r = ep->ExceptionRecord;
    if (r->ExceptionCode != EXCEPTION_ACCESS_VIOLATION &&
        r->ExceptionCode != EXCEPTION_ILLEGAL_INSTRUCTION &&
        r->ExceptionCode != EXCEPTION_STACK_OVERFLOW &&
        r->ExceptionCode != EXCEPTION_INT_DIVIDE_BY_ZERO)
        return EXCEPTION_CONTINUE_SEARCH;
    auto* c = ep->ContextRecord;
    HMODULE mod = nullptr;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCSTR)r->ExceptionAddress, &mod);
    char mname[MAX_PATH] = {0};
    if (mod)
        GetModuleFileNameA(mod, mname, MAX_PATH);
    LOGE("CRASH: code=0x%08lx addr=%p mod=%s+0x%llx rip=0x%llx rsp=0x%llx rax=0x%llx rcx=0x%llx rdx=0x%llx",
         (unsigned long)r->ExceptionCode, r->ExceptionAddress, mname,
         (unsigned long long)((uintptr_t)r->ExceptionAddress - (uintptr_t)mod),
         (unsigned long long)c->Rip, (unsigned long long)c->Rsp,
         (unsigned long long)c->Rax, (unsigned long long)c->Rcx, (unsigned long long)c->Rdx);
    if (r->NumberParameters >= 2)
        LOGE("CRASH access: type=%llu target=0x%llx",
             (unsigned long long)r->ExceptionInformation[0],
             (unsigned long long)r->ExceptionInformation[1]);
    sjf::jit_dump_threads();
    std::fflush(stderr);
    std::_Exit(1);
    return EXCEPTION_EXECUTE_HANDLER;
}
#endif

static void start_watchdog(int seconds) {
    std::thread([seconds]() {
        std::this_thread::sleep_for(std::chrono::seconds(seconds));
        LOGE("watchdog: %d s elapsed, terminating process", seconds);
        if (sjf::debug_mode())
            sjf::jit_dump_threads();
        sjf::request_quit(); // graceful: lifecycle + save
        std::this_thread::sleep_for(std::chrono::seconds(10));
        LOGE("watchdog: graceful shutdown stalled, hard exit");
        std::fflush(stderr);
        std::_Exit(0);
    }).detach();
}

int main(int argc, char** argv) {
#ifdef _WIN32
    AddVectoredExceptionHandler(1, crash_filter);
    timeBeginPeriod(1); // Sleep()/sleep_for granularity 15.6 ms -> 1 ms
#endif
    std::string so = "game/libsonicjumpfever.so";
    std::string shot = "first_frame.bmp";
    int shot_swap = 180;
    int timeout = 20;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--quiet")
            sjf::set_log_verbose(false);
        else if (a == "--verbose")
            sjf::set_log_verbose(true);
        else if (a == "--debug")
            sjf::set_debug_mode(true);
        else if (a == "--window" && i + 1 < argc) {
            int w = 0, h = 0;
            if (std::sscanf(argv[++i], "%dx%d", &w, &h) == 2)
                sjf::platform_set_window_options(w, h, false);
        } else if (a == "--zone" && i + 1 < argc)
            sjf::set_default_zone(argv[++i]);
        else if (a == "--profile-edit" && i + 1 < argc)
            sjf::profile_edit_load(argv[++i]);
        else if (a == "--controls" && i + 1 < argc)
            sjf::platform_set_controls_file(argv[++i]);
        else if (a == "--hidden")
            sjf::platform_set_hidden(true);
        else if (a == "--aspect" && i + 1 < argc)
            sjf::platform_set_aspect(argv[++i]);
        else if (a == "--surface" && i + 1 < argc) {
            int w = 0, h = 0;
            if (std::sscanf(argv[++i], "%dx%d", &w, &h) == 2)
                sjf::platform_set_surface_size(w, h);
        } else if (a == "--anim-fallback")
            sjf::set_anim_fallback(true);
        else if (a == "--no-extra-chars")
            sjf::set_extra_chars(false);
        else if (a == "--fullscreen")
            sjf::platform_set_window_options(0, 0, true);
        else if (a == "--timeout" && i + 1 < argc)
            timeout = std::atoi(argv[++i]);
        else if (a == "--shot" && i + 1 < argc)
            shot = argv[++i];
        else if (a == "--shot-swap" && i + 1 < argc)
            shot_swap = std::atoi(argv[++i]);
        else
            so = a;
    }
    sjf::platform_set_screenshot(shot.c_str(), shot_swap);
    if (timeout > 0)
        start_watchdog(timeout);
    LOGI("sjfport starting (so=%s, timeout=%ds)", so.c_str(), timeout);
    bool ok = sjf::boot(so);
    LOGI("sjfport finished: %s", ok ? "OK" : "FAILED");
    std::fflush(stdout);
    std::fflush(stderr);
    // Guest threads are still alive inside the JIT: skip static destructors.
    std::_Exit(ok ? 0 : 1);
}
