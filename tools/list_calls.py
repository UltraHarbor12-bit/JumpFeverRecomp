import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile

SO = 'port/game/libsonicjumpfever.so'
data = open(SO, 'rb').read()

rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    p = line.rstrip().split('\t')
    if len(p) < 3:
        continue
    try:
        rows.append((int(p[0], 16), int(p[1], 16), p[2]))
    except ValueError:
        pass
rows.sort()

import bisect
addrs = [r[0] for r in rows]

def nearest(addr):
    i = bisect.bisect_right(addrs, addr) - 1
    if i < 0:
        return '?'
    a, sz, n = rows[i]
    inside = addr < a + max(sz, 4)
    return '%s%s' % (n, '' if inside else ' [+0x%x]' % (addr - a))

e = ELFFile(open(SO, 'rb'))
text = e.get_section_by_name('.text')

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
start = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x2852b8
count = int(sys.argv[2]) if len(sys.argv) > 2 else 200
calls = []
for ins in md.disasm(data[text['sh_offset'] + (start - text['sh_addr']):
                           text['sh_offset'] + (start - text['sh_addr']) + count * 4], start):
    if ins.mnemonic in ('bl', 'b') and ins.op_str.startswith('#'):
        try:
            tgt = int(ins.op_str[1:], 16)
        except ValueError:
            continue
        calls.append((ins.address, tgt, nearest(tgt)))
for a, t, n in calls:
    print('  0x%05x -> 0x%05x  %s' % (a, t, n[:100]))
