"""Regenerates tools/launcher/assets/bg.png (launcher background, original art).

Style of the game's menus: sky-blue gradient, cyan glow, light rays, sparkles
and rings. Needs Pillow only to REGENERATE; the launcher just loads the PNG.
    python tools/launcher/make_assets.py
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 980, 720
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main():
    os.makedirs(OUT, exist_ok=True)
    random.seed(7)
    img = Image.new('RGB', (W, H))
    d = ImageDraw.Draw(img)
    top, mid, bot = (22, 120, 230), (64, 170, 245), (150, 225, 255)
    for y in range(H):
        t = y / (H - 1)
        c = lerp(top, mid, t / 0.55) if t < 0.55 else lerp(mid, bot, (t - 0.55) / 0.45)
        d.line([(0, y), (W, y)], fill=c)
    cx, cy = W * 0.56, H * 0.46

    # light rays
    rays = Image.new('L', (W, H), 0)
    rd = ImageDraw.Draw(rays)
    for i in range(14):
        a0 = i * (2 * math.pi / 14) + 0.12
        a1 = a0 + 0.10
        r = 1400
        rd.polygon([(cx, cy), (cx + r * math.cos(a0), cy + r * math.sin(a0)),
                    (cx + r * math.cos(a1), cy + r * math.sin(a1))], fill=38)
    rays = rays.filter(ImageFilter.GaussianBlur(6))
    img = Image.composite(Image.new('RGB', (W, H), (190, 245, 255)), img, rays)

    # glow
    glow = Image.new('L', (W, H), 0)
    gd = ImageDraw.Draw(glow)
    for r in range(260, 0, -4):
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=int(200 * (1 - r / 260) ** 1.6))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img = Image.composite(Image.new('RGB', (W, H), (120, 245, 255)), img, glow)

    # sparkles, stars and ring outlines
    fx = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fx)
    for _ in range(90):
        x, y, s = random.uniform(0, W), random.uniform(0, H), random.choice([1, 1, 2, 2, 3])
        fd.ellipse([x - s, y - s, x + s, y + s], fill=(255, 255, 255, random.randint(120, 230)))
    for _ in range(14):
        x, y, s = random.uniform(0, W), random.uniform(0, H), random.uniform(5, 11)
        pts = []
        for k in range(10):
            rr = s if k % 2 == 0 else s * 0.45
            a = -math.pi / 2 + k * math.pi / 5
            pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
        fd.polygon(pts, fill=(140, 235, 255, 150))
    for _ in range(10):
        x, y, s = random.uniform(0, W), random.uniform(0, H), random.uniform(5, 10)
        fd.ellipse([x - s, y - s, x + s, y + s], outline=(170, 240, 255, 140), width=2)
    img = Image.alpha_composite(img.convert('RGBA'), fx).convert('RGB')
    img.save(os.path.join(OUT, 'bg.png'), optimize=True)
    print('ok', os.path.join(OUT, 'bg.png'))


if __name__ == '__main__':
    main()
