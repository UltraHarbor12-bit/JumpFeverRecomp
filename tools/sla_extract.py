import os, re, zlib, struct, json, sys

ASSETS = 'extracted/apk/assets'
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
        if shift > 70:
            raise ValueError('varint overflow')


def parse_sla(path):
    d = open(path, 'rb').read()
    if d[:4] != b'=O&D':
        return None
    p = 4
    ver = d[p]; p += 1
    count, p = read_varint(d, p)
    entries = []
    for i in range(count):
        nlen, p = read_varint(d, p)
        name = d[p:p + nlen].decode('utf-8', 'replace'); p += nlen
        plen, p = read_varint(d, p)
        payload = d[p:p + plen]
        if len(payload) != plen:
            raise ValueError('truncated payload in %s entry %s' % (path, name))
        p += plen
        entries.append((name, payload))
    return ver, entries, len(d) - p


def find_zlib(payload, start, end):
    end = min(end, len(payload) - 1)
    for z in range(start, end):
        if payload[z] == 0x78 and payload[z + 1] in (0x01, 0x5e, 0x9c, 0xda):
            dec = zlib.decompressobj()
            try:
                out = dec.decompress(payload[z:])
                if dec.eof:
                    used = len(payload) - z - len(dec.unused_data)
                    return z, used, out
            except Exception:
                pass
    return None


def wav_header(nbytes, rate=22050, bits=16, ch=1):
    byterate = rate * ch * bits // 8
    block = ch * bits // 8
    return (b'RIFF' + struct.pack('<I', 36 + nbytes) + b'WAVEfmt '
            + struct.pack('<IHHIIHH', 16, 1, ch, rate, byterate, block, bits)
            + b'data' + struct.pack('<I', nbytes))


def extract_snd(path, outdir):
    """Parse a .snd container: records of PCM sounds with zlib payloads."""
    base = os.path.basename(path)
    d = open(path, 'rb').read()
    if d[:4] != bytes.fromhex('e206b15b'):
        print('%s: not SND' % base)
        return
    os.makedirs(outdir, exist_ok=True)
    p = 4
    ver = d[p]; p += 1
    rec = 0
    report = []
    while p < len(d) - 4:
        # scan forward for 0x81 0x22 marker (sound record tag)
        q = d.find(b'\x81\x22', p)
        if q < 0:
            report.append('tail %d bytes unparsed from %d: %s' % (len(d) - p, p, d[p:p+32].hex(' ')))
            break
        pre = d[p:q]
        try:
            rate, r1 = read_varint(d, q + 2)
            dsizeflag, r2 = read_varint(d, r1)
            zlen, r3 = read_varint(d, r2)
            zstart = r3
            dsize = dsizeflag & 0x7FFFFFFF
            sflags = dsizeflag >> 31
        except Exception as ex:
            report.append('rec %d varint fail: %s' % (rec, ex))
            break
        dec = zlib.decompressobj()
        try:
            pcm = dec.decompress(d[zstart:])
        except Exception as ex:
            report.append('rec %d zlib fail: %s' % (rec, ex))
            break
        consumed = len(d) - zstart - len(dec.unused_data)
        if not dec.eof or consumed != zlen:
            report.append('rec %d: WARN zlen field=%d actual=%d eof=%s' % (rec, zlen, consumed, dec.eof))
        if len(pcm) != dsize:
            report.append('rec %d: WARN dsize field=%d produced=%d' % (rec, dsize, len(pcm)))
        fn = os.path.join(outdir, '%s_%03d_%dHz.wav' % (base.replace('.snd', ''), rec, rate))
        open(fn, 'wb').write(wav_header(len(pcm), rate=rate) + pcm)
        report.append('rec %d: pre=%s rate=%d dsize=%d sflags=%#x zlen=%d -> %s' % (rec, pre.hex(' '), rate, dsize, sflags, zlen, os.path.basename(fn)))
        rec += 1
        p = zstart + consumed
    print('== %s: %d sounds ==' % (base, rec))
    for r in report:
        print('  ', r)


def extract_loc(path, outdir):
    base = os.path.basename(path)
    d = open(path, 'rb').read()
    os.makedirs(outdir, exist_ok=True)
    if d[:4] != bytes.fromhex('d96db1fb'):
        print('%s: not LOC (%s)' % (base, d[:4].hex()))
        return
    count = struct.unpack('<I', d[4:8])[0]
    table_end = 8 + count * 8
    pairs = [struct.unpack('<II', d[8 + i * 8:16 + i * 8]) for i in range(count)]
    blob = d[table_end:]
    lines = []
    for h, off in pairs:
        start = 4 + off
        end = blob.find(b'\x00', start)
        s = blob[start:end].decode('utf-8', 'replace')
        lines.append('%08x\t%d\t%s' % (h, off, s))
    open(os.path.join(outdir, base + '.txt'), 'w', encoding='utf-8').write('\n'.join(lines))
    print('== %s: %d strings, blob=%d bytes, first offsets: %s' % (base, count, len(blob), [p[1] for p in pairs[:5]]))
    print('   blob head hex:', blob[:24].hex(' '))
    print('   sample:', lines[1] if len(lines) > 1 else lines[0])


def main():
    os.makedirs(OUT, exist_ok=True)
    index = {}
    for f in sorted(os.listdir(ASSETS)):
        path = os.path.join(ASSETS, f)
        if f.endswith('.sla'):
            try:
                res = parse_sla(path)
            except Exception as ex:
                print('FAIL %s: %s' % (f, ex))
                continue
            ver, entries, trailing = res
            outdir = os.path.join(OUT, f[:-4])
            os.makedirs(outdir, exist_ok=True)
            print('%s: ver=%d entries=%d trailing=%d' % (f, ver, len(entries), trailing))
            listing = []
            for name, payload in entries:
                safe = name.replace('/', '__')
                listing.append(name)
                if payload[:1] in (b'{', b'[', b'<'):
                    open(os.path.join(outdir, safe), 'wb').write(payload)
                    continue
                hit = find_zlib(payload, 5, 64) if len(payload) > 64 else find_zlib(payload, 5, len(payload))
                if payload[:5] == bytes.fromhex('a2fce69001') and hit:
                    z, used, texels = hit
                    meta = payload[:z]
                    open(os.path.join(outdir, safe + '.texels'), 'wb').write(texels)
                    open(os.path.join(outdir, safe + '.meta'), 'w').write(
                        'meta_hex: %s\nzlib_len: %d\ntexels_len: %d\n' % (meta.hex(' '), used, len(texels)))
                    continue
                if payload[:4] == bytes.fromhex('e206b15b'):
                    extract_snd_inner(path, payload, os.path.join(outdir, safe))
                    continue
                open(os.path.join(outdir, safe + '.bin'), 'wb').write(payload)
                if hit:
                    z, used, out = hit
                    open(os.path.join(outdir, safe + '.zdata'), 'wb').write(out)
            index[f] = listing
        elif f.endswith('.snd'):
            extract_snd(path, os.path.join(OUT, 'snd'))
        elif f.endswith('.loc'):
            extract_loc(path, os.path.join(OUT, 'loc'))
    json.dump(index, open(os.path.join(OUT, '_index.json'), 'w'), indent=1)
    print('index -> %s' % os.path.join(OUT, '_index.json'))


def extract_snd_inner(path, payload, outdir):
    """For player.snd payloads embedded in .sla: write the raw snd then parse records."""
    tmp = os.path.join('extracted', 'analysis', '_tmp_embedded.snd')
    open(tmp, 'wb').write(payload)
    extract_snd(tmp, outdir)
    os.remove(tmp)


if __name__ == '__main__':
    main()
