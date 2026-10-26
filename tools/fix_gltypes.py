import io

p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, encoding='utf-8', newline=None).read()
anchor = '''#include <cctype>
#include <cstring>'''
add = '''// GL 1.5/2.0 scalar types missing from MinGW's GL/gl.h
#include <cstddef>
typedef std::ptrdiff_t GLsizeiptr;
typedef std::ptrdiff_t GLintptr;
typedef char GLchar;

#include <cctype>
#include <cstring>'''
if anchor in s:
    s = s.replace(anchor, add, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched libgl.cpp')
else:
    print('anchor not found')
