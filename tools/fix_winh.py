import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if '#include <windows.h>' not in s:
    s = s.replace('''#include <atomic>
#include <cctype>''', '''#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif
#include <atomic>
#include <cctype>''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('windows.h added')
