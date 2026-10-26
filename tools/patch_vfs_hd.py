import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''    // game/... paths resolve relative to the executable directory
    if (guest_path.rfind("game/", 0) == 0) {
        std::string cand = exe_dir() + "/../" + guest_path;
        if (GetFileAttributesA(cand.c_str()) != INVALID_FILE_ATTRIBUTES)
            return cand;
    }
    return guest_path;
}'''
new = '''    // game/... paths resolve relative to the executable directory
    if (guest_path.rfind("game/", 0) == 0) {
        std::string cand = exe_dir() + "/../" + guest_path;
        if (GetFileAttributesA(cand.c_str()) != INVALID_FILE_ATTRIBUTES)
            return cand;
    }
    // Bare resource names ("fonts-efigsb.sla", "splash.sla", ...): the engine
    // checks the download cache first, then the plain name. Our APK stores
    // them with the "hd-" prefix — try both.
    if (guest_path.find('/') == std::string::npos && guest_path.find('.') != std::string::npos) {
        std::string cand = "game/assets/" + guest_path;
        if (GetFileAttributesA(cand.c_str()) != INVALID_FILE_ATTRIBUTES)
            return cand;
        std::string cand2 = "game/assets/hd-" + guest_path;
        if (GetFileAttributesA(cand2.c_str()) != INVALID_FILE_ATTRIBUTES)
            return cand2;
    }
    return guest_path;
}'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('hd- fallback added')
else:
    print('pattern miss')
