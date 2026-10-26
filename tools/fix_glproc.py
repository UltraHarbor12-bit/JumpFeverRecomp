import io

# 1) glproc: don't cache NULL results
p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''void* glproc(const char* name) {
    static std::map<std::string, void*> cache;
    auto it = cache.find(name);
    if (it != cache.end())
        return it->second;
    PROC p = wglGetProcAddress(name);
    if (!p || p == (PROC)1 || p == (PROC)2 || p == (PROC)3 || p == (PROC)-1) {
        if (!g_opengl32)
            g_opengl32 = LoadLibraryA("opengl32.dll");
        p = g_opengl32 ? GetProcAddress(g_opengl32, name) : nullptr;
    }
    cache[name] = (void*)p;
    return (void*)p;
}''',
'''void* glproc(const char* name) {
    static std::map<std::string, void*> cache;
    auto it = cache.find(name);
    if (it != cache.end())
        return it->second;
    PROC p = wglGetProcAddress(name);
    if (!p || p == (PROC)1 || p == (PROC)2 || p == (PROC)3 || p == (PROC)-1) {
        if (!g_opengl32)
            g_opengl32 = LoadLibraryA("opengl32.dll");
        p = g_opengl32 ? GetProcAddress(g_opengl32, name) : nullptr;
    }
    if (p)
        cache[name] = (void*)p; // NULL results are NOT cached: a context may
                                // not have been current on the first attempt
    else
        LOGW("glproc: %s unresolved (no current context?)", name);
    return (void*)p;
}''')

# 2) platform_make_current: report failures
p = 'port/src/platform/window.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''void platform_make_current() {
    if (g_window && g_ctx)
        SDL_GL_MakeCurrent(g_window, g_ctx);
}''',
'''void platform_make_current() {
    if (g_window && g_ctx) {
        if (SDL_GL_MakeCurrent(g_window, g_ctx) != 0)
            LOGE("SDL_GL_MakeCurrent failed: %s", SDL_GetError());
    }
}''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('glproc + make_current fixed')
