import io

p = 'port/src/dex/jni_env.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
changed = False
if '#include "sjfport/elf_loader.h"' not in s:
    s = s.replace('#include "sjfport/host_calls.h"',
                  '#include "sjfport/host_calls.h"\n#include "sjfport/elf_loader.h"\n#include "sjfport/runtime.h"')
    changed = True
if changed:
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('includes added')
else:
    print('includes already present')
