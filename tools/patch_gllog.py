import io

p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# add first-call logging to the GLFN macro
old = '''#define GLFN(TYPE, name)                                                       \\
    register_host_fn(name, [](GuestCall& c) {                                  \\
        using FnT = TYPE;                                                      \\
        static FnT fn = (FnT)glproc(name);                                     \\
        (void)fn;                                                              \\
        c.ret = 0;'''
new = '''#define GLFN(TYPE, name)                                                       \\
    register_host_fn(name, [](GuestCall& c) {                                  \\
        using FnT = TYPE;                                                      \\
        static FnT fn = (FnT)glproc(name);                                     \\
        static bool logged = false;                                            \\
        if (!logged) {                                                         \\
            logged = true;                                                     \\
            LOGI("GL first call: %s (fn=%p)", name, (void*)fn);                 \\
        }                                                                      \\
        (void)fn;                                                              \\
        c.ret = 0;'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('GL first-call logging added')
else:
    print('macro pattern miss')
