# sla_hash_find.py <hash_hex> — search FNV-1 hash among .sla entry names and strings inside them
import sys, glob, re, os
def fnv(b):
    h = 0x811c9dc5
    for c in b: h = ((h * 0x01000193) & 0xffffffff) ^ c
    return h
def varint(b, i):
    v = s = 0
    while True:
        c = b[i]; i += 1; v |= (c & 0x7f) << s; s += 7
        if not c & 0x80: return v, i
target = int(sys.argv[1], 16)
for path in sorted(glob.glob('/home/user/jfp/port/game/assets/*.sla')):
    d = open(path, 'rb').read()
    if d[:4] != b'\x3d\x4f\x26\x44': continue
    i = 5; n, i = varint(d, i)
    for _ in range(n):
        l, i = varint(d, i); name = d[i:i+l]; i += l
        pl, i = varint(d, i); payload = d[i:i+pl]; i += pl
        cands = {name, os.path.splitext(name)[0], name.lower()}
        for s in re.findall(rb'[A-Za-z0-9_./-]{3,64}', payload): cands.add(s)
        for c in cands:
            for v in (c, c.lower()):
                if fnv(v) == target:
                    print(os.path.basename(path), name.decode(errors='replace'), '->', v.decode(errors='replace'))
