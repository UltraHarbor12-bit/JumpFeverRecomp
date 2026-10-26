"""Find adrp+add computed references to an address."""
import sys
from collections import deque
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, CS_OP_IMM, CS_OP_REG
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
low = TARGET & 0xFFF

recent = deque(maxlen=6)
count = 0
hits = []
for ins in md.disasm(code, base):
    count += 1
    if ins.id == 0 or ins.mnemonic == '.byte':
        continue
    if ins.mnemonic == 'adrp':
        try:
            ops = ins.operands
        except Exception:
            continue
        if len(ops) == 2 and ops[1].imm == page:
            recent.append((ins.address, ops[0].reg))
        continue
    if ins.mnemonic == 'add' and len(ins.operands) == 3:
        try:
            d, s1, s2 = ins.operands
        except Exception:
            continue
        if d.type == CS_OP_REG and s1.type == CS_OP_REG and s2.type == CS_OP_IMM:
            if s2.imm == low:
                for (aaddr, reg) in reversed(recent):
                    if reg == s1.reg:
                        hits.append((ins.address, aaddr))
                        break
    try:
        _, written = ins.regs_access()
        for r in written:
            pass
    except Exception:
        pass
    # simple: clear recent on branches
    if ins.mnemonic == 'ret' or (ins.mnemonic.startswith('b') and not ins.mnemonic.startswith('bl')):
        recent.clear()

print('scanned:', count, 'adrp+add refs to 0x%x:' % TARGET, len(hits))
for a, aa in hits[:20]:
    print('  0x%05x (adrp @0x%05x)' % (a, aa))
