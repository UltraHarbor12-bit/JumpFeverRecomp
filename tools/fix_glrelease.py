import io

p = 'port/src/platform/window.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''    SDL_GL_MakeCurrent(g_window, g_ctx);
    SDL_GL_SetSwapInterval(1);''',
'''    SDL_GL_MakeCurrent(g_window, g_ctx);
    SDL_GL_SetSwapInterval(1);
    // Release the context: the engine's RENDER thread will claim it via
    // eglMakeCurrent. A WGL context refuses to be made current on a second
    // thread while still current here ("resource already in use").
    SDL_GL_MakeCurrent(g_window, nullptr);''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('context released after creation')
