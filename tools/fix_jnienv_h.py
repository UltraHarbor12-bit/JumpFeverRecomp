import io

p = 'port/src/dex/jni_env.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if '#include "sjfport/jni_env.h"' not in s:
    s = s.replace('#include "sjfport/elf_loader.h"',
                  '#include "sjfport/elf_loader.h"\n#include "sjfport/jni_env.h"')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('jni_env.h included')
