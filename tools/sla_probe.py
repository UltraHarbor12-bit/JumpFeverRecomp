import os, re, zlib, sys

ASSETS = 'extracted/apk/assets'


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
        if shift > 63:
            raise ValueError('varint too long at %d' % p)


NAME_RE = re.compile(rb'[a-zA-Z0-9_][a-zA-Z0-9_.]{2,40}')
ENTRY_RE = re.compile(rb'^[a-z0-9_.-]+\.(tex|mtp|spr|anm|phy|json|snd|txt|loc|fnt|mat|mesh|cam|par|lvl|nav|ani|skl|sfx|bin)$')


def probe(path):
    d = open(path, 'rb').read()
    base = os.path.basename(path)
    if d[:4] != b'=O&D':
        print('%s: not SLA (magic %s)' % (base, d[:4].hex()))
        return
    p = 4
    ver = d[p]; p += 1
    count, p = read_varint(d, p)
    names = [(m.start(), m.group().decode()) for m in NAME_RE.finditer(d) if ENTRY_RE.match(m.group())]
    print('%s: ver=%d count=%d size=%d names_found=%d' % (base, ver, count, len(d), len(names)))
    for off, n in names[:60]:
        print('   @%07d %s' % (off, n))
    if len(names) > 60:
        print('   ... %d more' % (len(names) - 60))
    print()


def deep(path):
    d = open(path, 'rb').read()
    base = os.path.basename(path)
    print('=== DEEP %s (%d bytes) ===' % (base, len(d)))
    p = 4
    ver = d[p]; p += 1
    count, p = read_varint(d, p)
    print('ver=%d count=%d toc_end=%d' % (ver, count, p))
    for i in range(min(count, 12)):
        start = p
        try:
            nlen, p = read_varint(d, p)
            name = d[p:p + nlen].decode('utf-8', 'replace'); p += nlen
        except Exception as ex:
            print('  entry %d: name parse failed at %d: %s' % (i, p, ex))
            break
        # varint after name
        try:
            A, pA = read_varint(d, p)
        except Exception:
            A, pA = None, p
        print('entry %d @%d name=%r nlen=%d next_varint=%r (ends %d)' % (i, start, name, nlen, A, pA))
        # raw hex of the 40 bytes following the name
        print('   after name: %s' % d[p:p + 40].hex(' '))
        # try: assume A = payload length, payload starts at pA
        if A is not None and pA + A <= len(d):
            payload = d[pA:pA + A]
            print('   payload[0:24]: %s' % payload[:24].hex(' '))
            z = payload.find(b'\x78\xda')
            if z >= 0 and z < 64:
                dec = zlib.decompressobj()
                try:
                    out = dec.decompress(payload[z:])
                    used = len(payload) - z - len(dec.unused_data)
                    print('   zlib at payload+%d: consumed=%d produced=%d eof=%s' % (z, used, len(out), dec.eof))
                    print('   payload tail after zlib: %s' % payload[z + used:z + used + 32].hex(' '))
                except Exception as ex:
                    print('   zlib fail: %s' % ex)
            elif payload[:1] in (b'{', b'[', b'<'):
                txt = payload[:200].decode('utf-8', 'replace')
                print('   text payload: %r' % txt)
            p = pA + A
        else:
            print('   (A invalid or out of range)')
            break
    print('   file tail: %s' % d[-48:].hex(' '))
    print()


def snd(path):
    d = open(path, 'rb').read()
    base = os.path.basename(path)
    print('=== SND %s (%d bytes) ===' % (base, len(d)))
    print('head: %s' % d[:64].hex(' '))
    z = d.find(b'\x78\xda')
    if z >= 0:
        dec = zlib.decompressobj()
        try:
            out = dec.decompress(d[z:])
            used = len(d) - z - len(dec.unused_data)
            print('zlib@%d consumed=%d produced=%d eof=%s' % (z, used, len(out), dec.eof))
            print('produced head: %s' % out[:48].hex(' '))
            print('after stream: %s' % d[z + used:z + used + 48].hex(' '))
        except Exception as ex:
            print('zlib fail: %s' % ex)
    print('tail: %s' % d[-48:].hex(' '))
    print()


def loc(path):
    d = open(path, 'rb').read()
    base = os.path.basename(path)
    print('=== LOC %s (%d bytes) ===' % (base, len(d)))
    print('head: %s' % d[:64].hex(' '))
    print('tail: %s' % d[-48:].hex(' '))
    print()


if __name__ == '__main__':
    print('########## SLA PROBE ##########')
    for f in sorted(os.listdir(ASSETS)):
        if f.endswith('.sla'):
            probe(os.path.join(ASSETS, f))
    deep(os.path.join(ASSETS, 'hd-splash.sla'))
    deep(os.path.join(ASSETS, 'settings.sla'))
    deep(os.path.join(ASSETS, 'hd-player_sonic.sla'))
    snd(os.path.join(ASSETS, 'sfx.snd'))
    loc(os.path.join(ASSETS, 'strings_es.loc'))
