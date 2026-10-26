import sys, os
from elftools.elf.elffile import ELFFile

path = sys.argv[1] if len(sys.argv) > 1 else 'extracted/apk/lib/arm64-v8a/libsonicjumpfever.so'
e = ELFFile(open(path, 'rb'))
h = e.header
print('class:', h['e_ident']['EI_CLASS'], '| machine:', h['e_machine'], '| type:', h['e_type'])
print()
print('== SECTIONS ==')
for s in e.iter_sections():
    print('  %-26s %-14s size=%d' % (s.name, s['sh_type'], s['sh_size']))
print()
print('== DT_NEEDED ==')
dyn = e.get_section_by_name('.dynamic')
if dyn:
    for tag in dyn.iter_tags():
        if tag.entry.d_tag == 'DT_NEEDED':
            print('  ', tag.needed)
print()
os.makedirs('extracted/analysis', exist_ok=True)
for secname in ['.dynsym', '.symtab']:
    sec = e.get_section_by_name(secname)
    if sec is None or sec['sh_type'] == 'SHT_NO_BITS':
        print('%s: ABSENT' % secname)
        continue
    imports = []
    exports = []
    for sym in sec.iter_symbols():
        if not sym.name:
            continue
        if sym['st_shndx'] == 'SHN_UNDEF':
            imports.append(sym.name)
        else:
            exports.append((sym.name, sym['st_value'], sym['st_size']))
    print('%s: total=%d imports=%d defined=%d' % (secname, sec.num_symbols(), len(imports), len(exports)))
    with open('extracted/analysis/%s_imports.txt' % secname, 'w') as f:
        f.write('\n'.join(sorted(imports)))
    with open('extracted/analysis/%s_exports.txt' % secname, 'w') as f:
        for n, v, sz in sorted(exports, key=lambda x: x[1]):
            f.write('%s\t%s\t%s\n' % (hex(v), hex(sz), n))
    print('  -- sample defined (by addr) --')
    for n, v, sz in sorted(exports, key=lambda x: x[1])[:25]:
        print('   ', hex(v), hex(sz), n[:120])
    print('  -- sample imports --')
    for n in sorted(imports)[:35]:
        print('   ', n)
    print()
