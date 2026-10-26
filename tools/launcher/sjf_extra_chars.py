"""Packages for the unreleased characters (hito 10): Vector, Rouge, Cream.

The game's code, stats, names and select-screen portraits for them shipped,
but their in-game sprite packages (player_X.sla, playerextra_X.sla, sfx_X.sla)
never did. This builds them from a donor character with a hue remap so they
read as the right character in game:

    Vector <- Knuckles  (has Player_Attack, which PlayerVector asks for)   red  -> green
    Rouge  <- Silver    (has Player_Hover/HovertoFall, used by PlayerRouge) cyan -> pink
    Cream  <- Amy       (Player_Fly is aliased to Player_Jump by sjfport)  pink -> cream, red -> orange

Pure Python (zlib + a 64K lookup table): no Pillow needed on the user's PC.
Files go to port/game/assets/hd-player_<c>.sla etc. (derived from YOUR APK,
same as the rest of port/game). sjfport falls back to the plain donor if they
are missing.
"""
import colorsys
import os
import struct
import zlib
from array import array

DONORS = {'vector': 'knuckles', 'rouge': 'silver', 'cream': 'amy'}
TEX_MAGICS = (0x1219be22, 0x123ba722)  # seen in player sheets / docs 04


# ---------------------------------------------------------------- .sla / .tex
def _varint(d, p):
    v = s = 0
    while True:
        b = d[p]; p += 1
        v |= (b & 0x7f) << s
        if not b & 0x80:
            return v, p
        s += 7


def _enc_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7f
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def read_sla(path):
    d = open(path, 'rb').read()
    if d[:4] != b'=O&D':
        raise ValueError('%s: not an .sla' % path)
    ver = d[4]
    n, p = _varint(d, 5)
    ents = []
    for _ in range(n):
        ln, p = _varint(d, p); name = d[p:p + ln].decode(); p += ln
        ln, p = _varint(d, p); ents.append((name, d[p:p + ln])); p += ln
    return ver, ents


def write_sla(path, ver, ents):
    out = bytearray(b'=O&D' + bytes([ver]) + _enc_varint(len(ents)))
    for name, payload in ents:
        nb = name.encode()
        out += _enc_varint(len(nb)) + nb + _enc_varint(len(payload)) + payload
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(out)
    os.replace(tmp, path)


def recolor_tex(payload, lut):
    """RGBA4444 .tex (magic, fmt, flags, w, h, raw|0x80000000, zlib_len, zlib)."""
    p = 0
    magic, p = _varint(payload, p)
    if magic not in TEX_MAGICS:
        return payload
    fmt, flags = payload[p], payload[p + 1]
    w, h = struct.unpack_from('<HH', payload, p + 2)
    p += 6
    rawf, p = _varint(payload, p)
    zl, p = _varint(payload, p)
    if fmt != 0x0b or not rawf & 0x80000000:  # only RGBA4444 + zlib (all player sheets)
        return payload
    hdr = payload[:p - len(_enc_varint(zl)) - len(_enc_varint(rawf))]
    px = array('H')
    px.frombytes(zlib.decompress(payload[p:p + zl]))
    px = array('H', [lut[v] for v in px])
    raw = px.tobytes()
    z = zlib.compress(raw, 9)
    return hdr + _enc_varint(0x80000000 | len(raw)) + _enc_varint(len(z)) + z + payload[p + zl:]


# ------------------------------------------------------------------- colours
def _rule(src_ranges, hue_to, sat_mul=1.0, val_mul=1.0, min_sat=0.30):
    return (src_ranges, hue_to / 360.0, sat_mul, val_mul, min_sat)


RULES = {
    # Knuckles red -> Vector green (keeps white gloves, tan muzzle, shoes)
    'vector': [_rule([(338, 360), (0, 18)], 112, 0.85, 0.95)],
    # Silver cyan accents -> Rouge pink/magenta
    'rouge': [_rule([(160, 220)], 322, 1.0, 1.0, 0.20)],
    # Amy pink fur -> Cream's cream/beige, red dress & boots -> orange
    'cream': [_rule([(295, 338)], 36, 0.42, 1.08, 0.18), _rule([(338, 360), (0, 16)], 24, 1.0, 1.05)],
}


def build_lut(rules):
    """64K table: RGBA4444 (R in the top nibble) -> recoloured RGBA4444."""
    rgb = [0] * 4096
    for v in range(4096):
        r, g, b = (v >> 8) & 15, (v >> 4) & 15, v & 15
        hh, ss, vv = colorsys.rgb_to_hsv(r / 15.0, g / 15.0, b / 15.0)
        deg = hh * 360.0
        for ranges, hue_to, smul, vmul, min_sat in rules:
            if ss >= min_sat and vv > 0.12 and any(a <= deg < b for a, b in ranges):
                nr, ng, nb = colorsys.hsv_to_rgb(hue_to, min(1.0, ss * smul), min(1.0, vv * vmul))
                r, g, b = (int(round(c * 15)) for c in (nr, ng, nb))
                break
        rgb[v] = (r << 8) | (g << 4) | b
    lut = [0] * 65536
    for v in range(65536):
        lut[v] = (rgb[v >> 4] << 4) | (v & 15)
    return lut


# ------------------------------------------------------------------- build
def build_character(assets, char, log=print, force=False):
    donor = DONORS[char]
    lut = None
    made = []
    for kind in ('player', 'playerextra'):
        src = os.path.join(assets, 'hd-%s_%s.sla' % (kind, donor))
        dst = os.path.join(assets, 'hd-%s_%s.sla' % (kind, char))
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        if os.path.isfile(dst) and not force and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        if lut is None:
            lut = build_lut(RULES[char])
        ver, ents = read_sla(src)
        out = []
        for name, payload in ents:
            out.append((name, recolor_tex(payload, lut) if name.endswith('.tex') else payload))
        write_sla(dst, ver, out)
        made.append(os.path.basename(dst))
    # voices/SFX: plain copy of the donor's bank
    s_src = os.path.join(assets, 'sfx_%s.sla' % donor)
    s_dst = os.path.join(assets, 'sfx_%s.sla' % char)
    if os.path.isfile(s_src) and (force or not os.path.isfile(s_dst)):
        with open(s_src, 'rb') as a, open(s_dst + '.tmp', 'wb') as b:
            b.write(a.read())
        os.replace(s_dst + '.tmp', s_dst)
        made.append(os.path.basename(s_dst))
    if made:
        log('personaje %s: %s (sprites de %s recoloreados)' % (char, ', '.join(made), donor))
    return made


def build_all(assets, log=print, force=False):
    out = []
    for c in ('vector', 'rouge', 'cream'):
        out += build_character(assets, c, log, force)
    return out


if __name__ == '__main__':
    import sys
    import time
    t = time.time()
    a = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', '..', 'port', 'game',
                                                           'assets')
    build_all(a, force='--force' in sys.argv)
    print('%.1f s' % (time.time() - t))
