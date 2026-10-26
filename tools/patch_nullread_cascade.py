import io, re

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# 1) fault() takes is_write; null-page writes are silent, reads cascade
s = s.replace('''    void fault(const char* what, u64 vaddr) {''',
              '''    void fault(const char* what, u64 vaddr, bool is_write) {''')
s = s.replace('''        if (vaddr < 0x10000)
            return; // null-page shadow: expected''',
'''        if (vaddr < 0x10000) {
            if (is_write)
                return; // writes into the null-page shadow are absorbed
            // reads mean the engine expected real data here: cascade
        }''')

# 2) call sites
for op, size in (('Read8', '1'), ('Read16', '2'), ('Read32', '4'), ('Read64', '8')):
    s = re.sub(r'fault\("(Read%s)", vaddr\)' % size,
               r'fault("\1", vaddr, false)' if False else 'fault("%s", vaddr, false)' % op,
               s)
s = s.replace('fault("Read128", vaddr);', 'fault("Read128", vaddr, false);')
s = s.replace('fault("Write8", vaddr);', 'fault("Write8", vaddr, true);')
s = s.replace('fault("Write16", vaddr);', 'fault("Write16", vaddr, true);')
s = s.replace('fault("Write32", vaddr);', 'fault("Write32", vaddr, true);')
s = s.replace('fault("Write64", vaddr);', 'fault("Write64", vaddr, true);')
s = s.replace('fault("Write128", vaddr);', 'fault("Write128", vaddr, true);')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('read faults now cascade')
