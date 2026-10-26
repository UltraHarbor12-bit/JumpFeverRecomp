import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");
    auto t0 = std::chrono::steady_clock::now();
    for (;;) {
        if (!platform_pump())
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(8));''',
'''    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");
    auto t0 = std::chrono::steady_clock::now();
    auto last_sample = t0;
    for (;;) {
        if (!platform_pump())
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_sample).count()
            >= 2000) {
            last_sample = now;
            LOGI("--- pc sample ---");
            jit_dump_threads();
        }''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('pc sampling added')
