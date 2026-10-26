# sjf_save.py — read/write Sonic Jump Fever save files (localsettings.dat, profile0.dat).
#
# Format (engine serializer, reverse-engineered from the files themselves):
#   value := type:u8 payload
#     0x00 null    (no payload)
#     0x01 bool    u8
#     0x02 int32   4 bytes LE
#     0x03 int64   8 bytes LE
#     0x06 string  varint len + bytes
#     0x07 map     varint count, count x (varint keylen, key, value)
#     0x08 array   varint count, count x value
#     0x09 int64   8 bytes LE (timestamps in ms)
#
# WARNING (hito 8): do NOT write profile0.dat. Re-encoding it byte-exactly
# with one int changed (energyCount) made the game discard the whole profile
# and start a fresh one (ftueState=1, age gate) -> it has an integrity check.
# Reading is safe; for tests use SJF_TIME_OFFSET (guest clock) instead.
#   varint = unsigned LEB128. No checksum.
import struct

ZONES = ['green_hill_zone', 'blue_sky_zone', 'jungle_zone', 'mechanical_zone']


class SaveFormatError(Exception):
    pass


def _varint(b, i):
    v = s = 0
    while True:
        if i >= len(b):
            raise SaveFormatError('truncated varint')
        c = b[i]; i += 1
        v |= (c & 0x7f) << s
        s += 7
        if not c & 0x80:
            return v, i


def _enc_varint(v):
    out = bytearray()
    while True:
        c = v & 0x7f
        v >>= 7
        out.append(c | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _read(b, i):
    if i >= len(b):
        raise SaveFormatError('truncated value')
    t = b[i]; i += 1
    if t == 0x00:
        return (t, None), i
    if t == 0x01:
        return (t, b[i]), i + 1
    if t == 0x02:
        return (t, struct.unpack_from('<i', b, i)[0]), i + 4
    if t in (0x03, 0x09):
        return (t, struct.unpack_from('<q', b, i)[0]), i + 8
    if t == 0x06:
        n, i = _varint(b, i)
        return (t, b[i:i + n].decode('utf-8', 'surrogateescape')), i + n
    if t == 0x07:
        n, i = _varint(b, i)
        items = []
        for _ in range(n):
            kl, i = _varint(b, i)
            k = b[i:i + kl].decode('utf-8', 'surrogateescape'); i += kl
            v, i = _read(b, i)
            items.append([k, v])
        return (t, items), i
    if t == 0x08:
        n, i = _varint(b, i)
        arr = []
        for _ in range(n):
            v, i = _read(b, i)
            arr.append(v)
        return (t, arr), i
    raise SaveFormatError('unknown value type 0x%02x at %d' % (t, i - 1))


def _write(v):
    t, x = v
    if t == 0x00:
        return b'\x00'
    if t == 0x01:
        return bytes([t, x & 0xff])
    if t == 0x02:
        return bytes([t]) + struct.pack('<i', x)
    if t in (0x03, 0x09):
        return bytes([t]) + struct.pack('<q', x)
    if t == 0x06:
        raw = x.encode('utf-8', 'surrogateescape')
        return bytes([t]) + _enc_varint(len(raw)) + raw
    if t == 0x07:
        out = bytearray([t]) + _enc_varint(len(x))
        for k, val in x:
            kb = k.encode('utf-8', 'surrogateescape')
            out += _enc_varint(len(kb)) + kb + _write(val)
        return bytes(out)
    if t == 0x08:
        out = bytearray([t]) + _enc_varint(len(x))
        for val in x:
            out += _write(val)
        return bytes(out)
    raise SaveFormatError('cannot encode type 0x%02x' % t)


def load(path):
    b = open(path, 'rb').read()
    v, i = _read(b, 0)
    if i != len(b) or v[0] != 0x07:
        raise SaveFormatError('unexpected layout (%d of %d bytes parsed)' % (i, len(b)))
    if _write(v) != b:
        raise SaveFormatError('round-trip mismatch: refusing to edit')
    return v


def save(path, v):
    data = _write(v)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    import os
    os.replace(tmp, path)


def get_key(v, key, default=None):
    for k, val in v[1]:
        if k == key:
            return val[1]
    return default


def set_string(v, key, s):
    for item in v[1]:
        if item[0] == key:
            item[1] = (0x06, s)
            return
    v[1].append([key, (0x06, s)])


def find_all(v, key, path=''):
    """Yield (path, item) for every map entry named key (recursive)."""
    t, x = v
    if t == 0x07:
        for item in x:
            if item[0] == key:
                yield path + '/' + key, item
            for r in find_all(item[1], key, path + '/' + item[0]):
                yield r
    elif t == 0x08:
        for n, val in enumerate(x):
            for r in find_all(val, key, '%s[%d]' % (path, n)):
                yield r


def set_zone(localsettings_path, zone, next_zone=None):
    """Set currentZone (and nextZone). Returns the previous currentZone."""
    v = load(localsettings_path)
    prev = get_key(v, 'currentZone', '')
    set_string(v, 'currentZone', zone)
    if next_zone is not None:
        set_string(v, 'nextZone', next_zone)
    save(localsettings_path, v)
    return prev


def weekly_zone(date=None):
    """Weekly rotation through the four zones (ISO week number)."""
    import datetime
    d = date or datetime.date.today()
    w = d.isocalendar()[1]
    return ZONES[w % len(ZONES)], ZONES[(w + 1) % len(ZONES)]


if __name__ == '__main__':
    import sys
    v = load(sys.argv[1])            # sjf_save.py FILE  -> dump top level (read-only)
    for k, val in v[1]:
        print('%-26s type=0x%02x %r' % (k, val[0], str(val[1])[:60]))
