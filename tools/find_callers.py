"""Find direct BL/B/BL callers of a target address."""
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile

targets = [int(x, 16) for x in sys.argv[1:]] or [0x330798]
SO = 'port/game/libsonicjumpfever.so'

e = ELFFile(open(SO, 'rb'))
text = e.get_section_by_name('.text')
data = open(SO, 'rb').read()
base = text['sh_addr']
code = data[text['sh_offset']:text['sh_offset'] + text['sh_size']]

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.skipdata = True

hits = {t: [] for t in targets}
for ins in md.disasm(code, base):
    if ins.id == 0 or ins.mnemonic == '.byte':
        continue
    if ins.mnemonic not in ('bl', 'b'):
        continue
    try:
        if not ins.operands:
            continue
        op = ins.operands[0]
        if op.type != 2:  # CS_OP_IMM
            continue
    except Exception:
        continue
    for t in targets:
        if op.imm == t:
            hits[t].append((ins.address, ins.mnemonic))

for t in targets:
    print('callers of 0x%x: %d' % (t, len(hits[t])))
    for a, mn in hits[t][:20]:
        print('   0x%05x %s' % (a, mn))
