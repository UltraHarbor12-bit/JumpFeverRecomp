import io

p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''    register_host_fn("eglMakeCurrent", [](GuestCall& c) {
        platform_make_current();
        c.ret = 1;
    });''', '''    register_host_fn("eglMakeCurrent", [](GuestCall& c) {
        static int n = 0;
        if (n++ < 5) LOGI("eglMakeCurrent #%d", n);
        platform_make_current();
        c.ret = 1;
    });''')

s = s.replace('''    register_host_fn("eglSwapBuffers", [](GuestCall& c) {
        platform_swap();
        c.ret = 1;
    });''', '''    register_host_fn("eglSwapBuffers", [](GuestCall& c) {
        static int n = 0;
        ++n;
        if (n == 1 || n % 60 == 0) LOGI("eglSwapBuffers #%d", n);
        platform_swap();
        c.ret = 1;
    });''')

s = s.replace('''    GLFN(void (*)(GLuint), "glLinkProgram") if (fn) fn((GLuint)c.x[0]);
    GLFN_END''', '''    GLFN(void (*)(GLuint), "glLinkProgram")
        if (fn) {
            fn((GLuint)c.x[0]);
            static int n = 0;
            if (n++ < 5) LOGI("glLinkProgram #%d", n);
        }
    GLFN_END''')

s = s.replace('''    GLFN(void (*)(GLuint), "glUseProgram") if (fn) fn((GLuint)c.x[0]);
    GLFN_END''', '''    GLFN(void (*)(GLuint), "glUseProgram")
        if (fn) {
            fn((GLuint)c.x[0]);
            static int n = 0;
            if (n == 1) LOGI("glUseProgram first call");
        }
    GLFN_END''')

s = s.replace('''    GLFN(void (*)(GLenum, GLint, GLsizei), "glDrawArrays")
        if (fn) fn((GLenum)c.x[0], (GLint)(i32)c.x[1], (GLsizei)(i32)c.x[2]);
    GLFN_END''', '''    GLFN(void (*)(GLenum, GLint, GLsizei), "glDrawArrays")
        if (fn) {
            fn((GLenum)c.x[0], (GLint)(i32)c.x[1], (GLsizei)(i32)c.x[2]);
            static int n = 0;
            if (n++ < 3) LOGI("glDrawArrays #%d mode=%u count=%d", n, (unsigned)c.x[0],
                              (int)(i32)c.x[2]);
        }
    GLFN_END''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('instrumented gl')
