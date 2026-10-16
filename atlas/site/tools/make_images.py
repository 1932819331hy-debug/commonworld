#!/usr/bin/env python3
"""One-off asset generator (needs Pillow). NOT part of the zero-dependency build.

Takes the Commonworld marks from the prototype UI
(branch prototype/local-runtime-only-2026-10-09, design-preview/assets/commonworld-mark-{light,dark}.png),
cuts the rounded-square corners to transparency, and writes small web assets into ../static/:
cw-mark-{light,dark}.png (96px, shown at 46px), cw-mark-{light,dark}-192.png (landing logo, shown at 96px), favicon.ico, apple-touch-icon.png, icon-192.png,
og-atlas.png (1200x630 Open Graph image).

Usage:  python3 tools/make_images.py /path/to/commonworld-mark-light.png /path/to/commonworld-mark-dark.png
Get the marks with e.g.:
  git show prototype/local-runtime-only-2026-10-09:design-preview/assets/commonworld-mark-light.png > /tmp/mark-light.png
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'static')


def rounded(im, inset=5, radius_frac=0.205):
    im = im.convert('RGBA')
    w, h = im.size
    mask = Image.new('L', (w * 4, h * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((inset * 4, inset * 4, (w - inset) * 4, (h - inset) * 4), radius=int(w * 4 * radius_frac), fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    im.putalpha(mask)
    return im.crop((inset, inset, w - inset, h - inset))


def font(names, size):
    for n in names:
        for d in ('/usr/share/fonts/truetype/dejavu', '/System/Library/Fonts/Supplemental', '/Library/Fonts'):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main(light_path, dark_path):
    L, D = rounded(Image.open(light_path)), rounded(Image.open(dark_path))
    sz = lambda im, s: im.resize((s, s), Image.LANCZOS)
    sz(L, 96).save(f'{OUT}/cw-mark-light.png', optimize=True)
    sz(D, 96).save(f'{OUT}/cw-mark-dark.png', optimize=True)
    # 2x marks for the landing logo (shown at 96 CSS px): palette PNG, visually identical, ~7 KB each
    for name, im in (('light', L), ('dark', D)):
        sz(im, 192).quantize(colors=256, method=Image.FASTOCTREE, dither=Image.FLOYDSTEINBERG).save(f'{OUT}/cw-mark-{name}-192.png', optimize=True)
    flat = Image.new('RGBA', L.size, (244, 241, 234, 255)); flat.alpha_composite(L)
    sz(flat, 180).convert('RGB').save(f'{OUT}/apple-touch-icon.png', optimize=True)
    sz(L, 192).save(f'{OUT}/icon-192.png', optimize=True)
    sz(L, 48).save(f'{OUT}/favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])

    W, H = 1200, 630
    og = Image.new('RGB', (W, H), '#f4f1ea')
    d = ImageDraw.Draw(og)
    d.rounded_rectangle((40, 40, W - 40, H - 40), radius=36, fill='#fbfaf7', outline='#dfded6', width=2)
    m = sz(L, 260); og.paste(m, (100, 185), m)
    fb = font(['DejaVuSans-Bold.ttf', 'Arial Bold.ttf'], 26)
    d.text((410, 175), 'COMMONWORLD', font=fb, fill='#b8432a')
    d.text((405, 215), 'Atlas', font=font(['DejaVuSans-Bold.ttf', 'Arial Bold.ttf'], 96), fill='#202522')
    d.text((410, 345), 'Verified catalog of AI-agent platforms', font=font(['DejaVuSans.ttf', 'Arial.ttf'], 34), fill='#202522')
    d.text((410, 400), 'A shared world for humans and agents', font=font(['DejaVuSans.ttf', 'Arial.ttf'], 28), fill='#5f655f')
    d.text((410, 480), 'commonworld.one/atlas', font=font(['DejaVuSans-Bold.ttf', 'Arial Bold.ttf'], 24), fill='#63705b')
    og.save(f'{OUT}/og-atlas.png', optimize=True)
    print('images written to', os.path.normpath(OUT))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
