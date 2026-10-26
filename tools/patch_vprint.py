import io

p = 'port/src/dependencies/liblog.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''    register_host_fn("__android_log_vprint", [](GuestCall& c) {
        LOGW("__android_log_vprint called (va_list form) — not expanded");
        c.ret = 0;
    });''',
'''    register_host_fn("__android_log_vprint", [](GuestCall& c) {
        int prio = (int)(i32)c.x[0];
        std::string tag = gstr(c.x[1]);
        c.use_valist = true;
        c.va_ptr = c.x[3];
        std::string msg = guest_format(c, c.x[2]);
        const char* pl = (prio >= 6) ? "E" : (prio >= 5 ? "W" : "I");
        LOGW("logcat[%s][%s] %s", tag.c_str(), pl, msg.c_str());
        c.ret = (u64)msg.size();
    });''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('vprint implemented')
