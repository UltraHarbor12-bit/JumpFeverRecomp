import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''        std::time_t t = (std::time_t)c.x[0];
        std::tm* tm = std::gmtime(&t);'''
new = '''        // POSIX: gmtime(const time_t *tp) — the guest passes a POINTER
        std::time_t t = 0;
        if (c.x[0])
            gread(&t, c.x[0], 8);
        else
            t = std::time(nullptr);
        std::tm* tm = std::gmtime(&t);'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('gmtime pointer deref fixed')
else:
    print('pattern miss')
