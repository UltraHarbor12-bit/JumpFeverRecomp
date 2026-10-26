# port_linux.py - make the sjfport sources build on both MinGW (unchanged
# behaviour) and Linux. Idempotent; reads/writes with LF newlines.
import io, re, sys
ROOT = sys.argv[1] if len(sys.argv) > 1 else '/home/user/jfp/port'

def patch(rel, pairs):
    p = ROOT + '/' + rel
    s = io.open(p, encoding='utf-8', newline=None).read()
    for old, new in pairs:
        if new in s and old not in s:
            continue
        if old not in s:
            raise SystemExit('pattern not found in %s:\n%s' % (rel, old))
        s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', rel)

# ---------------- libc.cpp ----------------
patch('src/dependencies/libc.cpp', [
 ('#ifdef _WIN32\n#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#endif\n#include <atomic>',
  '#include "sjfport/host_compat.h"\n#include <atomic>'),
 ('#ifdef _WIN32\n#include <io.h>\n#include <fcntl.h>\n#endif\n', ''),
 ('''        char buf[MAX_PATH] = {0};
        GetModuleFileNameA(nullptr, buf, MAX_PATH);
        std::string exe = buf;''', '''        std::string exe = host_exe_path();'''),
])
p = ROOT + '/src/dependencies/libc.cpp'
s = io.open(p, encoding='utf-8', newline=None).read()
s = re.sub(r'GetFileAttributesA\(([^)]*?)\.c_str\(\)\) != INVALID_FILE_ATTRIBUTES', r'host_path_exists(\1)', s)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

# ---------------- libandroid.cpp ----------------
patch('src/dependencies/libandroid.cpp', [
 ('#ifdef _WIN32\n#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <io.h>\n#endif\n',
  '#include "sjfport/host_compat.h"\n'),
 ('''#ifdef _WIN32
    if (g_sensor_ident >= 0 && g_sensor_enabled && GetTickCount64() - g_sensor_last_ms >= 16) {
        ident = g_sensor_ident;
        data = g_sensor_data;
        return true;
    }
#endif''', '''    if (g_sensor_ident >= 0 && g_sensor_enabled && host_ticks_ms() - g_sensor_last_ms >= 16) {
        ident = g_sensor_ident;
        data = g_sensor_data;
        return true;
    }'''),
 ('''#ifdef _WIN32
        DWORD t0 = GetTickCount();''', '''        u64 t0 = host_ticks_ms();'''),
 ('''                    HANDLE h = (HANDLE)_get_osfhandle(hostfd);
                    if (h == INVALID_HANDLE_VALUE)
                        continue;
                    DWORD avail = 0;
                    if (PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr) && avail > 0) {''',
  '''                    if (host_pipe_available(hostfd) > 0) {'''),
 ('''            if (timeout > 0 && (GetTickCount() - t0) >= (DWORD)timeout)
                break;
            Sleep(1);''', '''            if (timeout > 0 && (host_ticks_ms() - t0) >= (u64)timeout)
                break;
            host_sleep_ms(1);'''),
 ('''        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
#else
        (void)outFd; (void)outEvents; (void)outData; (void)timeout;
        c.ret = (u64)(i64)-3;
#endif''', '''        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT'''),
 ('u64 now = (u64)GetTickCount64();', 'u64 now = host_ticks_ms();'),
])

# ---------------- libgl.cpp ----------------
patch('src/dependencies/libgl.cpp', [
 ('''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>''', '''#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>
#else
#define GL_GLEXT_LEGACY 1 // we declare the GL 1.5/2.0 types ourselves
#include <GL/gl.h>
#include <SDL.h>
#endif'''),
 ('''HMODULE g_opengl32 = nullptr;

void* glproc(const char* name) {
    static std::map<std::string, void*> cache;
    auto it = cache.find(name);
    if (it != cache.end())
        return it->second;
    PROC p = wglGetProcAddress(name);''', '''#ifdef _WIN32
HMODULE g_opengl32 = nullptr;
#endif

void* glproc(const char* name) {
    static std::map<std::string, void*> cache;
    auto it = cache.find(name);
    if (it != cache.end())
        return it->second;
#ifndef _WIN32
    void* sp = SDL_GL_GetProcAddress(name);
    if (sp)
        cache[name] = sp;
    return sp;
#else
    PROC p = wglGetProcAddress(name);'''),
 ('''    cache[name] = (void*)p;
    return (void*)p;
}''', '''    if (p) // never cache NULL (the context may not be current yet)
        cache[name] = (void*)p;
    return (void*)p;
#endif
}'''),
])

# ---------------- window.cpp ----------------
patch('src/platform/window.cpp', [
 ('''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <SDL.h>''', '''#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif
#include <SDL.h>'''),
])
print('done')
