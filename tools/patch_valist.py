import io

# 1) host_calls.h: valist fields in GuestCall
p = 'port/include/sjfport/host_calls.h'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''    // vararg cursor state (see guest_abi.h)
    u64 vargp = 0;   // next GP register index
    u64 vargf = 0;   // next FP register index
    u64 vargs = 0;   // stack cursor (byte offset from sp)''',
'''    // vararg cursor state (see guest_abi.h)
    u64 vargp = 0;   // next GP register index
    u64 vargf = 0;   // next FP register index
    u64 vargs = 0;   // stack cursor (byte offset from sp)
    // va_list mode (for vsnprintf/vprintf handlers)
    bool use_valist = false;
    u64 va_ptr = 0;
    u64 va_stack = 0, va_gr_top = 0, va_vr_top = 0;
    i32 va_gr_offs = 0, va_vr_offs = 0;
    bool va_inited = false;''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('host_calls.h ok')

# 2) guest_abi.cpp: valist-aware pullers
p = 'port/src/runtime/guest_abi.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''u64 GuestCall_vararg_gp(GuestCall& c) {
    if (c.vargp < 8)
        return c.x[c.vargp++];''',
'''u64 GuestCall_vararg_gp(GuestCall& c) {
    if (c.use_valist) {
        if (!c.va_inited) {
            struct VL { u64 stack, gr_top, vr_top; i32 gr_offs, vr_offs; } vl{};
            gread(&vl, c.va_ptr, sizeof(vl));
            c.va_stack = vl.stack;
            c.va_gr_top = vl.gr_top;
            c.va_vr_top = vl.vr_top;
            c.va_gr_offs = vl.gr_offs;
            c.va_vr_offs = vl.vr_offs;
            c.va_inited = true;
        }
        if (c.va_gr_offs > -64) {
            c.va_gr_offs -= 8;
            u64 v = 0;
            gread(&v, c.va_gr_top + c.va_gr_offs, 8);
            return v;
        }
        u64 v = 0;
        gread(&v, c.va_stack, 8);
        c.va_stack += 8;
        return v;
    }
    if (c.vargp < 8)
        return c.x[c.vargp++];''')

s = s.replace('''double GuestCall_vararg_fp(GuestCall& c) {
    if (c.vargf < 8) {''',
'''double GuestCall_vararg_fp(GuestCall& c) {
    if (c.use_valist) {
        if (!c.va_inited) {
            struct VL { u64 stack, gr_top, vr_top; i32 gr_offs, vr_offs; } vl{};
            gread(&vl, c.va_ptr, sizeof(vl));
            c.va_stack = vl.stack;
            c.va_gr_top = vl.gr_top;
            c.va_vr_top = vl.vr_top;
            c.va_gr_offs = vl.gr_offs;
            c.va_vr_offs = vl.vr_offs;
            c.va_inited = true;
        }
        if (c.va_vr_offs > -128) {
            c.va_vr_offs -= 16;
            u64 bits = 0;
            gread(&bits, c.va_vr_top + c.va_vr_offs, 8);
            double d;
            std::memcpy(&d, &bits, 8);
            return d;
        }
        u64 bits = 0;
        gread(&bits, c.va_stack, 8);
        c.va_stack += 8;
        double d;
        std::memcpy(&d, &bits, 8);
        return d;
    }
    if (c.vargf < 8) {''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('guest_abi.cpp ok')

# 3) libc.cpp: real vsnprintf / vprintf / vfprintf
p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''    H("vprintf", [](GuestCall& c) {
        // va_list on AArch64: {stack, gr_top, vr_top, gr_offs, vr_offs}
        // For boot we support the common case: args still in registers is
        // impossible at vprintf time; parse the va_list struct directly.
        struct GuestVaList { u64 stack, gr_top, vr_top; i32 gr_offs, vr_offs; };
        GuestVaList vl;
        gread(&vl, c.x[1], sizeof(vl));
        GuestCall tmp = c;
        tmp.vargp = 8; // force stack pulls... emulate via va_list below
        std::string fmt = gstr(c.x[0]);
        std::string out;
        size_t i = 0;
        auto pull_gp = [&]() -> u64 {
            if (vl.gr_offs > -64) {
                vl.gr_offs -= 8;
                u64 v = 0;
                gread(&v, vl.gr_top + vl.gr_offs + 8, 8);
                return v;
            }
            u64 v = 0;
            gread(&v, vl.stack, 8);
            vl.stack += 8;
            return v;
        };
        auto pull_fp = [&]() -> double {
            if (vl.vr_offs > -128) {
                vl.vr_offs -= 16;
                u64 bits = 0;
                gread(&bits, vl.vr_top + vl.vr_offs + 16, 8);
                double d; std::memcpy(&d, &bits, 8);
                return d;
            }
            u64 bits = 0;
            gread(&bits, vl.stack, 8);
            vl.stack += 8;
            double d; std::memcpy(&d, &bits, 8);
            return d;
        };
        (void)pull_gp; (void)pull_fp; (void)i; (void)fmt;
        // (full vprintf formatting is implemented in guest_format only for
        // register varargs; va_list variant is rare during boot — log raw)
        LOGW("vprintf called (format: %s) — raw passthrough", gstr(c.x[0]).c_str());
        c.ret = 0;
    });''',
'''    H("vprintf", [](GuestCall& c) {
        c.use_valist = true;
        c.va_ptr = c.x[1];
        std::string s = guest_format(c, c.x[0]);
        std::fputs(s.c_str(), stdout);
        c.ret = s.size();
    });''')

s = s.replace('''    H("fprintf", [](GuestCall& c) {
        c.vargp = 2; c.vargf = 0;
        std::string s = guest_format(c, c.x[1]);
        FILE* f = file_from_slot(c.x[0]);
        std::fputs(s.c_str(), f ? f : stdout);
        c.ret = s.size();
    });''',
'''    H("fprintf", [](GuestCall& c) {
        c.vargp = 2; c.vargf = 0;
        std::string s = guest_format(c, c.x[1]);
        FILE* f = file_from_slot(c.x[0]);
        std::fputs(s.c_str(), f ? f : stdout);
        c.ret = s.size();
    });
    H("vfprintf", [](GuestCall& c) {
        c.use_valist = true;
        c.va_ptr = c.x[2];
        std::string s = guest_format(c, c.x[1]);
        FILE* f = file_from_slot(c.x[0]);
        std::fputs(s.c_str(), f ? f : stdout);
        c.ret = s.size();
    });''')

s = s.replace('''    H("vsnprintf", [](GuestCall& c) {
        LOGW("vsnprintf called — returning empty string");
        if (c.x[1]) ((char*)guest_to_host(c.x[0]))[0] = 0;
        c.ret = 0;
    });''',
'''    H("vsnprintf", [](GuestCall& c) {
        c.use_valist = true;
        c.va_ptr = c.x[3];
        std::string s = guest_format(c, c.x[2]);
        size_t n = (size_t)c.x[1];
        if (n) {
            size_t copy = s.size() < n - 1 ? s.size() : n - 1;
            std::memcpy(guest_to_host(c.x[0]), s.c_str(), copy);
            ((char*)guest_to_host(c.x[0]))[copy] = 0;
        }
        c.ret = s.size();
    });''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('libc.cpp valist ok')
