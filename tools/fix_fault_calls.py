import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# fix remaining 2-arg fault calls (reads)
for name in ('Read8', 'Read16', 'Read32', 'Read64', 'Read128'):
    s = s.replace('fault("%s", vaddr);' % name, 'fault("%s", vaddr, false);' % name)

# check the broken region around line 258
lines = s.split('\n')
print('--- lines 250-262 ---')
for i in range(249, 262):
    if i < len(lines):
        print(i + 1, '|', lines[i])

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
