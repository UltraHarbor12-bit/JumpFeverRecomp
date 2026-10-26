import io

# 1) glGetString: override identity strings for GLES expectations
p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''    register_host_fn("glGetString", [](GuestCall& c) {
        using PFN = const GLubyte* (*)(GLenum);
        static PFN fn = (PFN)glproc("glGetString");
        static std::map<u32, u64> cache;
        u32 name = (u32)c.x[0];
        auto it = cache.find(name);
        if (it != cache.end()) { c.ret = it->second; return; }
        const GLubyte* s = fn ? fn((GLenum)name) : nullptr;
        if (!s) { c.ret = 0; return; }
        std::string str((const char*)s);
        u64 g = alloc_native_data(str.size() + 1, 8);
        if (g) gwrite(g, str.c_str(), str.size() + 1);
        cache[name] = g;
        c.ret = g;
    });'''
new = '''    register_host_fn("glGetString", [](GuestCall& c) {
        using PFN = const GLubyte* (*)(GLenum);
        static PFN fn = (PFN)glproc("glGetString");
        static std::map<u32, u64> cache;
        u32 name = (u32)c.x[0];
        auto it = cache.find(name);
        if (it != cache.end()) { c.ret = it->second; return; }
        std::string str;
        // The engine validates the GL identity; report GLES2 equivalents.
        if (name == 0x1F02)                      // GL_VERSION
            str = "OpenGL ES 2.0 (sjfport)";
        else if (name == 0x1F01)                 // GL_RENDERER
            str = "sjfport Renderer";
        else if (name == 0x8B8C)                 // GL_SHADING_LANGUAGE_VERSION
            str = "OpenGL ES GLSL ES 1.00";
        else {
            const GLubyte* s = fn ? fn((GLenum)name) : nullptr;
            if (!s) { c.ret = 0; return; }
            str = (const char*)s;
        }
        u64 g = alloc_native_data(str.size() + 1, 8);
        if (g) gwrite(g, str.c_str(), str.size() + 1);
        cache[name] = g;
        c.ret = g;
    });'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('glGetString identity override added')
else:
    print('pattern miss')

# 2) name the abort caller
import bisect
rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    q = line.rstrip().split('\t')
    if len(q) < 3:
        continue
    try:
        rows.append((int(q[0], 16), int(q[1], 16), q[2]))
    except ValueError:
        pass
rows.sort()
addrs = [r[0] for r in rows]
for t in (0x2fa62c,):
    i = bisect.bisect_right(addrs, t) - 1
    a, sz, n = rows[i]
    print('0x%06x -> %s (0x%x)%s' % (t, n, a, ' INSIDE' if t < a + max(sz, 4) else ''))
