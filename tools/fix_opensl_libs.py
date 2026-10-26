import io

# 1) libgl.cpp: restore the OpenSL ES module (stub)
p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, encoding='utf-8', newline=None).read()
if 'register_libOpenSLES_module' not in s:
    s += '''
// ---------------------------------------------------------------------------
// OpenSL ES (Hito 3: audio)
// ---------------------------------------------------------------------------
void register_libOpenSLES_module() {
    register_host_fn("slCreateEngine", [](GuestCall& c) {
        LOGW("slCreateEngine() — audio not implemented yet");
        if (c.x[0]) { u64 v = 0; gwrite(c.x[0], &v, 8); }
        c.ret = 9; // SL_RESULT_FEATURE_UNSUPPORTED
    });
}

} // namespace sjf
'''
    # the file already ends with "} // namespace sjf" — remove the duplicate tail
    s = s.replace('''} // namespace sjf

// ---------------------------------------------------------------------------
// OpenSL ES (Hito 3: audio)''', '''// ---------------------------------------------------------------------------
// OpenSL ES (Hito 3: audio)''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('ok opensl restored')
else:
    print('opensl already present')

# 2) CMakeLists: SDL2 system libs
p = 'port/CMakeLists.txt'
s = io.open(p, encoding='utf-8', newline=None).read()
s = s.replace('target_link_libraries(sjfport PRIVATE dynarmic SDL2 opengl32)',
'''target_link_libraries(sjfport PRIVATE dynarmic SDL2 opengl32
    mingw32 user32 gdi32 winmm imm32 ole32 oleaut32 shell32 oleacc uuid version hid setupapi dxguid dinput8)''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok cmake libs')
