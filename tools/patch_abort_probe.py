import io

# 1) abort: log guest backtrace
p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''    H("abort", [](GuestCall& c) {
        LOGE("guest called abort()");''',
'''    H("abort", [](GuestCall& c) {
        LOGE("guest called abort()");
        jit_backtrace_here("abort");''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('abort backtrace added')

# 2) remove the obsolete PlayerProfile::load probe block
p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
start = s.find('    // Probe: initialise PlayerProfile')
end = s.find('    // Deliver the native window immediately after onCreate.')
if start != -1 and end != -1 and start < end:
    s = s[:start] + s[end:]
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('probe block removed')
else:
    print('probe anchors off', start, end)
