"""Find refs to a global with a tight adrp window (<=2 instructions)."""
import sys
from collections import deque
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, CS_OP_MEM, CS_OP_REG
from elftools.elf.elffile import ELFFile

TARGET = int(sys.argv[1], 16)
SO = 'port/game/libsonicjumpfever.so'

e = ELFFile(open(SO, 'rb'))
text = e.get_section_by_name('.text')
data = open(SO, 'rb').read()
base = text['sh_addr']
code = data[text['sh_offset']:text['sh_offset'] + text['sh_size']]

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True
md.skipdata = True

page = TARGET & ~0xFFF
off = TARGET & 0xFFF

recent = deque(maxlen=3)
hits = []
count = 0
for ins in md.disasm(code, base):
    count += 1
    if ins.id == 0 or ins.mnemonic == '.byte':
        recent.clear()
        continue
    if ins.mnemonic == 'adrp':
        try:
            ops2 = ins.operands
        except Exception:
            recent.clear()
            continue
        if len(ops2) == 2:
            recent.append((ins.address, ops2[0].reg, ops2[1].imm))
            continue
    try:
        ops = ins.operands
    except Exception:
        recent.clear()
        continue
    if ins.mnemonic in ('ret',) or ins.mnemonic.startswith('b'):
        recent.clear()
        continue
    mem = None
    for op in ops:
        if op.type == CS_OP_MEM:
            mem = op
    if mem is not None and mem.mem.disp == off:
        for (aaddr, reg, apage) in reversed(recent):
            if apage == page and reg == mem.mem.base:
                kind = 'WRITE' if ins.mnemonic.startswith('st') else 'read'
                hits.append((ins.address, kind, ins.mnemonic, ins.op_str, aaddr))
                break
    recent.clear() if ins.mnemonic in ('bl', 'blr') else None

print('scanned:', count, 'refs to 0x%x:' % TARGET, len(hits))
for a, kind, mn, ops, aaddr in hits:
    print('  0x%05x %-5s %-6s %-30s (adrp @0x%05x)' % (a, kind, mn, ops, aaddr))
