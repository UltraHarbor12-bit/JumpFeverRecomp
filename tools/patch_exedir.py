import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''// Resolve Android-ish asset paths to the port's local asset directory.
std::string vfs_resolve(const std::string& guest_path) {
    size_t p = guest_path.find("assets/");
    if (p != std::string::npos) {
        std::string rest = guest_path.substr(p + 7);
        if (!rest.empty())
            return "game/assets/" + rest;
    }
    return guest_path;
}''',
'''// Resolve Android-ish asset paths to the port's local asset directory.
std::string vfs_resolve(const std::string& guest_path) {
    size_t p = guest_path.find("assets/");
    if (p != std::string::npos) {
        std::string rest = guest_path.substr(p + 7);
        if (!rest.empty()) {
            std::string cand = "game/assets/" + rest;
            if (GetFileAttributesA(cand.c_str()) != INVALID_FILE_ATTRIBUTES)
                return cand;
            return exe_dir() + "/../" + cand;
        }
    }
    // game/... paths resolve relative to the executable directory
    if (guest_path.rfind("game/", 0) == 0) {
        std::string cand = exe_dir() + "/../" + guest_path;
        if (GetFileAttributesA(cand.c_str()) != INVALID_FILE_ATTRIBUTES)
            return cand;
    }
    return guest_path;
}''')

s = s.replace('''constexpr u64 kWatched = 0x1005cbed0ull; // PlayerProfile singleton (.bss)''',
'''std::string exe_dir() {
    static std::string dir;
    if (dir.empty()) {
        char buf[MAX_PATH] = {0};
        GetModuleFileNameA(nullptr, buf, MAX_PATH);
        std::string exe = buf;
        size_t slash = exe.find_last_of("/\\\\");
        dir = (slash == std::string::npos) ? "." : exe.substr(0, slash);
    }
    return dir;
}

constexpr u64 kWatched = 0x1005cbed0ull; // PlayerProfile singleton (.bss)''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('exe-relative path resolution added')
