import io

# 1) elf_loader: bind SL_IID_* blobs by name
p = 'port/src/runtime/elf_loader.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'sl_bind_iid' not in s:
    s = s.replace('''                        S = alloc_native_data(st_size, 8);
                        out.bound_imports[nm] = S;
                        out.unresolved.push_back(nm);''',
'''                        S = alloc_native_data(st_size, 8);
                        out.bound_imports[nm] = S;
                        out.unresolved.push_back(nm);
                        if (nm.rfind("SL_IID_", 0) == 0)
                            sl_bind_iid(nm.c_str(), S);''')
    s = s.replace('#include "sjfport/host_calls.h"',
                  '#include "sjfport/host_calls.h"\n#include "sjfport/libopensl.h"')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('elf_loader iid binding ok')

# 2) libopensl.h
open('port/include/sjfport/libopensl.h', 'w').write(
'''// sjfport — OpenSL ES object model
#pragma once
#include "common.h"

namespace sjf {
void register_libOpenSLES_module();
void sl_bind_iid(const char* name, u64 blob_addr);
} // namespace sjf
''')
print('libopensl.h ok')

# 3) libgl.cpp: drop the old OpenSL stub
p = 'port/src/dependencies/libgl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
start = s.find('// ---------------------------------------------------------------------------\n// OpenSL ES (Hito 3: audio)')
if start != -1:
    end = s.find('} // namespace sjf', start)
    if end != -1:
        s = s[:start] + s[end:]
        io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
        print('old opensl stub removed')
    else:
        print('end not found')
else:
    print('stub not found')

# 4) CMakeLists: add libopensl.cpp
p = 'port/CMakeLists.txt'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'libopensl.cpp' not in s:
    s = s.replace('    src/dependencies/libgl.cpp',
                  '    src/dependencies/libgl.cpp\n    src/dependencies/libopensl.cpp')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('cmake updated')
