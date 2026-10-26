import io, os, sys

def patch(path, pairs):
    s = open(path, encoding='utf-8').read()
    for old, new in pairs:
        if old not in s:
            print('MISS in %s: %r' % (path, old[:60]))
            continue
        s = s.replace(old, new, 1)
    open(path, 'w', encoding='utf-8').write(s)
    print('patched', path)

patch('port/src/dependencies/libc.cpp', [
    ('#include <atomic>\n#include <chrono>', '#include <atomic>\n#include <cctype>\n#include <chrono>'),
    ('#include <map>\n#include <mutex>', '#include <map>\n#include <mutex>\n#include <thread>'),
])

patch('port/src/dependencies/libm.cpp', [
    ('#include <cmath>', '#include <cmath>\n#include <cstring>'),
])

patch('port/src/dependencies/libgl.cpp', [
    ('#include "sjfport/host_calls.h"', '#include "sjfport/host_calls.h"\n\n#include <map>'),
])

patch('port/src/runtime/guest_memory.cpp', [
    ('''void log_msg(LogLevel level, const char* tag, const std::string& msg) {
    static std::mutex m;
    static bool verbose = true;
    std::lock_guard<std::mutex> lk(m);''',
     '''namespace {
bool g_verbose = true;
std::mutex g_log_mutex;
}

void log_msg(LogLevel level, const char* tag, const std::string& msg) {
    std::lock_guard<std::mutex> lk(g_log_mutex);'''),
    ('case LogLevel::Debug: lv = "D"; if (!verbose) return; break;',
     'case LogLevel::Debug: lv = "D"; if (!g_verbose) return; break;'),
    ('''void set_log_verbose(bool v) {
    static bool verbose = true;
    verbose = v;
}''',
     '''void set_log_verbose(bool v) {
    g_verbose = v;
}'''),
])

patch('port/src/runtime/guest_abi.cpp', [
    ('''    // clamp to 4 KiB
    return std::string(p, strnlen(p, 4096));''',
     '''    // clamp to 4 KiB (strnlen is POSIX; do it manually for portability)
    size_t n = 0;
    while (n < 4096 && p[n])
        ++n;
    return std::string(p, n);'''),
])
print('done')
