import zlib

d = open('extracted/apk/assets/sfx.snd', 'rb').read()
print('len', len(d))
print('head', d[:32].hex(' '))
q = d.find(b'\x81\x22', 5)
print('q =', q, 'bytes at q:', d[q:q + 12].hex(' ') if q >= 0 else None)


def rv(d, p):
    val = 0
    shift = 0
    while True:
        b = d[p]
        p += 1
        val |= (b & 0x7f) << shift
        if not (b & 0x80):
            return val, p
        shift += 7


p = q + 2
rate, p = rv(d, p); print('rate', rate, '-> next', p, d[p:p+4].hex(' '))
ds, p = rv(d, p); print('dsize', ds, '-> next', p, d[p:p+4].hex(' '))
fl, p = rv(d, p); print('flags', fl, '-> next', p, d[p:p+4].hex(' '))
zl, p = rv(d, p); print('zlen', zl, '-> next', p, 'bytes at zstart:', d[p:p+4].hex(' '))
dec = zlib.decompressobj()
try:
    out = dec.decompress(d[p:])
    print('OK produced', len(out), 'eof', dec.eof)
except Exception as ex:
    print('FAIL', ex)
    print('context 16..40:', d[16:40].hex(' '))
