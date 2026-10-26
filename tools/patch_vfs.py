import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# VFS resolver helper (inserted after the FILE slot helpers)
s = s.replace('''void set_std_streams(u64 sf_blob) {''',
'''// Resolve Android-ish asset paths to the port's local asset directory.
std::string vfs_resolve(const std::string& guest_path) {
    size_t p = guest_path.find("assets/");
    if (p != std::string::npos) {
        std::string rest = guest_path.substr(p + 7);
        if (!rest.empty())
            return "game/assets/" + rest;
    }
    return guest_path;
}

void set_std_streams(u64 sf_blob) {''')

# use it in fopen
s = s.replace('''        std::string path = gstr(c.x[0]), mode = gstr(c.x[1]);
        LOGD("fopen(\\"%s\\", \\"%s\\")", path.c_str(), mode.c_str());
        FILE* f = std::fopen(path.c_str(), mode.c_str());''',
'''        std::string path = gstr(c.x[0]), mode = gstr(c.x[1]);
        std::string resolved = vfs_resolve(path);
        if (resolved != path)
            LOGD("fopen(\\"%s\\") -> \\"%s\\"", path.c_str(), resolved.c_str());
        else
            LOGD("fopen(\\"%s\\", \\"%s\\")", path.c_str(), mode.c_str());
        FILE* f = std::fopen(resolved.c_str(), mode.c_str());''')

# use it in open
s = s.replace('''        std::string path = gstr(c.x[0]);
        int flags = (int)(i32)c.x[1];
        const char* hmode = (flags & 1) ? ((flags & 2) ? "wb+" : "rb") : "rb";
        FILE* f = std::fopen(path.c_str(), hmode);''',
'''        std::string path = gstr(c.x[0]);
        int flags = (int)(i32)c.x[1];
        const char* hmode = (flags & 1) ? ((flags & 2) ? "wb+" : "rb") : "rb";
        std::string resolved = vfs_resolve(path);
        FILE* f = std::fopen(resolved.c_str(), hmode);''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('vfs added')
