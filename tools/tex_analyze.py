import os, re, zlib

OUT = 'extracted/assets'


def read_varint(d, p):
    val = 0
    shift = 0
    while True:
        b = d[p]
        p += 1
        val |= (b & 0x7f) << shift
        if not (b & 0x80):
            return val, p
        shift += 7


rows = []
for root, dirs, files in os.walk(OUT):
    for f in files:
        if not f.endswith('.meta'):
            continue
        txt = open(os.path.join(root, f)).read()
        mh = re.search(r'meta_hex: ([0-9a-f ]+)', txt).group(1)
        zl = int(re.search(r'zlib_len: (\d+)', txt).group(1))
        tl = int(re.search(r'texels_len: (\d+)', txt).group(1))
        b = bytes.fromhex(mh.replace(' ', ''))
        rows.append((f, b, zl, tl))

print('total tex:', len(rows))
for f, b, zl, tl in rows[:60]:
    # b = const5 + middle + zlen_varint
    # find zlen varint: decode from the end backwards is hard; decode forward after const5
    p = 5
    vals = []
    try:
        while p < len(b):
            v, p = read_varint(b, p)
            vals.append(v)
    except Exception:
        vals.append('ERR')
    print('%-24s len=%-9d vals=%s' % (f, tl, vals))
