from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile

SO = 'port/game/libsonicjumpfever.so'
data = open(SO, 'rb').read()

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
print('== PlayerProfile::PlayerProfile() @0x330798 ==')
for ins in md.disasm(data[0x330798:0x330798 + 0x2c], 0x330798):
    print('  0x%05x: %-8s %s' % (ins.address, ins.mnemonic, ins.op_str))

# is the ctor in .init_array?
e = ELFFile(open(SO, 'rb'))
dyn = e.get_section_by_name('.dynamic')
init_arr = init_sz = 0
for tag in dyn.iter_tags():
    if tag.entry.d_tag == 'DT_INIT_ARRAY':
        init_arr = tag.entry.d_val
    elif tag.entry.d_tag == 'DT_INIT_ARRAYSZ':
        init_sz = tag.entry.d_val

# read relocations for init array entries (values are RELATIVE relocs)
relocs = {}
rel = e.get_section_by_name('.rela.dyn')
for r in rel.iter_relocations():
    relocs[r['r_offset']] = r['r_addend']

print('\ninit_array @0x%x size %d -> %d entries' % (init_arr, init_sz, init_sz // 8))
hits = []
for i in range(init_sz // 8):
    off = init_arr + i * 8
    val = relocs.get(off)
    if val is not None and (0x330798 <= val < 0x330798 + 0x2c):
        hits.append((i, val))
print('ctor in init_array:', hits if hits else 'NO')

# also show what writes near the ctor (who calls it)
print('\ninit_array entries whose target is in [0x330700, 0x330800]:')
for i in range(init_sz // 8):
    off = init_arr + i * 8
    val = relocs.get(off)
    if val is not None and 0x330700 <= val < 0x330800:
        print('  entry %d -> 0x%x' % (i, val))
