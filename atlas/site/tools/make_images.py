#!/usr/bin/env python3
"""One-off asset generator (needs Pillow). NOT part of the zero-dependency build.

Source: the vector Commonworld mark (redrawn 2026-10-18): cw-mark-{light,dark}.svg plus their transparent 1024 px PNG exports
(cw-mark-{light,dark}-1024.png, rounded tile with transparent corners). The SVGs are copied as-is into ../static/
(cw-mark-light.svg, cw-mark-dark.svg, favicon.svg); the PNG fallbacks are downsampled from the 1024 px exports:
cw-mark-{light,dark}.png (96px), cw-mark-{light,dark}-192.png (192px), favicon.ico (16/32/48), apple-touch-icon.png (180px,
opaque, full-bleed tile colour), icon-192.png, og-atlas.png (1200x630 Open Graph fallback).
File names stay the same as before, so already indexed URLs keep working (overwritten in place).

Usage:  python3 tools/make_images.py /path/to/brand/assets   (dir with cw-mark-*.svg and png-exports/cw-mark-*-1024.png)
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'static')


def font(names, size):
    for n in names:
        for d in ('/usr/share/fonts/truetype/dejavu', '/System/Library/Fonts/Supplemental', '/Library/Fonts'):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main(src):
    import shutil
    png = lambda n: os.path.join(src, 'png-exports', f'cw-mark-{n}-1024.png')
    L, D = Image.open(png('light')).convert('RGBA'), Image.open(png('dark')).convert('RGBA')
    sz = lambda im, s: im.resize((s, s), Image.LANCZOS)
    for name in ('light', 'dark'):
        shutil.copy(os.path.join(src, f'cw-mark-{name}.svg'), f'{OUT}/cw-mark-{name}.svg')
    shutil.copy(os.path.join(src, 'cw-mark-light.svg'), f'{OUT}/favicon.svg')
    sz(L, 96).save(f'{OUT}/cw-mark-light.png', optimize=True)
    sz(D, 96).save(f'{OUT}/cw-mark-dark.png', optimize=True)
    # 2x marks for the landing logo (shown at 96 CSS px): palette PNG, visually identical, ~7 KB each
    for name, im in (('light', L), ('dark', D)):
        sz(im, 192).quantize(colors=256, method=Image.FASTOCTREE, dither=Image.FLOYDSTEINBERG).save(f'{OUT}/cw-mark-{name}-192.png', optimize=True)
    flat = Image.new('RGBA', L.size, (244, 240, 231, 255)); flat.alpha_composite(L)  # iOS masks the corners itself
    sz(flat, 180).convert('RGB').save(f'{OUT}/apple-touch-icon.png', optimize=True)
    sz(L, 192).save(f'{OUT}/icon-192.png', optimize=True)
    sz(L, 256).save(f'{OUT}/favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])

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
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
