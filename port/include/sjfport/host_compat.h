// sjfport — thin host-OS compatibility layer (Windows/MinGW and POSIX/Linux).
// Windows builds keep using the exact Win32/MSVCRT calls they always used;
// POSIX builds get equivalents so the port can be built and debugged on Linux.
#pragma once
#include <chrono>
#include <cstdint>
#include <string>
#include <thread>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#else
#include <fcntl.h>
#include <limits.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#ifndef MAX_PATH
#define MAX_PATH 4096
#endif
#define _read ::read
#define _write ::write
#define _close ::close
#endif

namespace sjf {

// Monotonic milliseconds (GetTickCount64 equivalent).
inline std::uint64_t host_ticks_ms() {
    return (std::uint64_t)std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

inline void host_sleep_ms(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }

// Directory containing the running executable.
inline std::string host_exe_path() {
#ifdef _WIN32
    char buf[MAX_PATH] = {0};
    GetModuleFileNameA(nullptr, buf, MAX_PATH);
    return buf;
#else
    char buf[MAX_PATH] = {0};
    ssize_t n = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    return n > 0 ? std::string(buf, (size_t)n) : std::string(".");
#endif
}

inline bool host_path_exists(const std::string& p) {
#ifdef _WIN32
    return GetFileAttributesA(p.c_str()) != INVALID_FILE_ATTRIBUTES;
#else
    struct stat st;
    return ::stat(p.c_str(), &st) == 0;
#endif
}

// Bytes waiting in a host pipe fd (non-blocking). -1 on error.
inline long host_pipe_available(int hostfd) {
#ifdef _WIN32
    HANDLE h = (HANDLE)_get_osfhandle(hostfd);
    if (h == INVALID_HANDLE_VALUE)
        return -1;
    DWORD avail = 0;
    if (!PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr))
        return -1;
    return (long)avail;
#else
    int avail = 0;
    if (ioctl(hostfd, FIONREAD, &avail) != 0)
        return -1;
    return avail;
#endif
}

} // namespace sjf
