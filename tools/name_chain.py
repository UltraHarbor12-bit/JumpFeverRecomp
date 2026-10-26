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

def nearest(addr):
    best = None
    for a, sz, n in rows:
        if a <= addr < a + max(sz, 4):
            return a, sz, n, 'inside'
        if a <= addr:
            best = (a, sz, n)
        else:
            break
    return best[0], best[1], best[2], 'before'

for target in (0x4fefb0, 0x28563c, 0x4ff5c0, 0x28524c, 0x32c7a8, 0x4bbb40, 0x4bbad8):
    a, sz, n, kind = nearest(target)
    print('0x%06x -> 0x%06x +0x%x (%s) %s' % (target, a, sz, kind, n))
