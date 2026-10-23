#!/usr/bin/env python3
"""Generates src/pages/og-assets.gen.ts: the data the Worker needs to draw per-post Open Graph images (src/pages/og.ts).

The Worker has no font engine and no image library, and adding one (resvg/satori WASM) would add megabytes and blow the
100 ms CPU cap. So everything that needs a font or a rasterizer is done here, once, with Pillow (the same library and the
same fonts as the Atlas OG images, atlas/site/og_images.py):

  * the static background (1200x630): page color, the paper card, the CW mark, "Commonworld" and the brand subtitle,
    the colored bar under the header; quantized to a small palette and stored as zlib-compressed palette indices.
    The bar is stored as levels of a "bar ramp" palette slot, so the Worker paints it in the post's section color by
    filling those palette entries (no pixel work).
  * anti-aliased glyph masks (16 levels) for the text the Worker draws: the post title (three sizes), the byline,
    the section kicker, the footer URL and the date.

Same fonts + same Pillow -> byte-identical output. Fonts: Liberation Sans Bold/Regular 2.x (SIL OFL 1.1), the fonts the
Atlas OG images use in CI. The script refuses to run with any other font, so the post images match the Atlas images.
Fonts are looked up in the same folders as atlas/site/og_images.py, plus $CW_OG_FONT_DIR.

Run from platform/ after changing a layout constant, the palette, the mark or the character set:
    npm run gen:og        (= python3 scripts/gen_og_assets.py)
"""
import base64, hashlib, json, os, sys, zlib

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # platform/
OUT = os.path.join(ROOT, 'src', 'pages', 'og-assets.gen.ts')
MARK = os.path.join(ROOT, 'src', 'pages', 'static', 'brand', 'cw-mark-light-256.png')

W, H = 1200, 630
# Commonworld light tokens (same as atlas/site/og_images.py)
BG, PAPER, INK, MUTED, LINE = '#f4f1ea', '#fbfaf7', '#202522', '#686e68', '#dfded6'
ACCENT_TEXT, OLIVE = '#bf472c', '#63705b'
SUBTITLE = 'A shared world for humans and agents'  # brand subtitle, verbatim (AGENTS.md rule 7)

# palette layout: background colors first, then one 16-entry ramp per drawn color (level 0 = paper, 15 = full color)
BG_COLORS = 96
RAMPS = ['bar', 'ink', 'muted', 'olive']
RAMP_BASE = {name: BG_COLORS + 16 * i for i, name in enumerate(RAMPS)}

L, R = 90, W - 90
BAR_Y, BAR_H = 170, 10

FONT_DIRS = [os.environ.get('CW_OG_FONT_DIR', ''), '/usr/share/fonts/truetype/liberation2', '/usr/share/fonts/truetype/liberation',
             '/Library/Fonts', os.path.expanduser('~/Library/Fonts'), 'C:/Windows/Fonts']


def find(name):
    for d in FONT_DIRS:
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    sys.exit(f'gen_og_assets: {name} not found (install fonts-liberation2 or set CW_OG_FONT_DIR)')


BOLD, REG = find('LiberationSans-Bold.ttf'), find('LiberationSans-Regular.ttf')


def rgb(hexs):
    return tuple(int(hexs[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------- character sets
def cps(*ranges):
    out = []
    for a, b in ranges:
        out += list(range(a, b + 1))
    return out


ASCII = cps((0x20, 0x7E))
LATIN = ASCII + cps((0xA0, 0x17F), (0x2010, 0x2027))  # incl. dashes, quotes, the ellipsis
# titles: Latin (incl. Latin-1 and Extended-A), Greek, Cyrillic, common punctuation and symbols. Anything else (emoji,
# CJK, ...) is left out of the image by the Worker; the page title itself is unchanged.
TITLE = LATIN + cps((0x370, 0x3FF), (0x400, 0x45F), (0x490, 0x491), (0x2030, 0x2030), (0x2039, 0x203A),
                    (0x20AC, 0x20AC), (0x2122, 0x2122), (0x2190, 0x2193))

# name -> (font file, size, character set)
FONTS = {
    'title72': (BOLD, 72, TITLE),
    'title60': (BOLD, 60, TITLE),
    'title50': (BOLD, 50, TITLE),
    'byline': (REG, 28, LATIN),
    'kicker': (BOLD, 19, LATIN),
    'foot': (BOLD, 23, ASCII + [0x2026]),
    'date': (REG, 21, ASCII),
}


def has_glyph(font, ch, notdef):
    if ch == ' ' or ch == '\u00a0':
        return True
    m = font.getmask(ch)
    return not (m.size == notdef[0] and bytes(m) == notdef[1])


def glyph_set(path, size, charset):
    font = ImageFont.truetype(path, size)
    nd = font.getmask('\U0010fffd')
    notdef = (nd.size, bytes(nd))
    ascent, descent = font.getmetrics()
    rows, data = [], bytearray()
    for cp in charset:
        ch = chr(cp)
        if not has_glyph(font, ch, notdef):
            continue
        adv = round(font.getlength(ch) * 64)
        x0, y0, x1, y1 = font.getbbox(ch, anchor='ls')
        w, h = max(0, x1 - x0), max(0, y1 - y0)
        if w and h:
            im = Image.new('L', (w, h), 0)
            ImageDraw.Draw(im).text((-x0, -y0), ch, font=font, fill=255, anchor='ls')
            lv = bytes((v * 15 + 127) // 255 for v in im.tobytes())
        else:
            lv = b''
            x0 = y0 = w = h = 0
        rows.append([cp, adv, x0, y0, w, h, len(data)])
        data += lv
    return {'size': size, 'ascent': ascent, 'descent': descent, 'glyphs': rows,
            'data': base64.b64encode(zlib.compress(bytes(data), 9)).decode()}


# ---------------------------------------------------------------- background
def rounded_mask(size, box, radius, scale=4):
    """Anti-aliased (supersampled) rounded-rectangle coverage mask, 0..255."""
    big = Image.new('L', (size[0] * scale, size[1] * scale), 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(big).rounded_rectangle((x0 * scale, y0 * scale, x1 * scale - 1, y1 * scale - 1), radius=radius * scale, fill=255)
    return big.resize(size, Image.BOX)


def background():
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 40, W - 40, H - 40), radius=36, fill=PAPER, outline=LINE, width=2)
    m = Image.open(MARK).convert('RGBA').resize((64, 64), Image.LANCZOS)
    im.paste(m, (L, 80), m)
    d.text((L + 80, 82), 'Commonworld', font=ImageFont.truetype(BOLD, 34), fill=INK, anchor='la')
    d.text((L + 81, 124), SUBTITLE, font=ImageFont.truetype(REG, 20), fill=MUTED, anchor='la')
    pal = im.quantize(colors=BG_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    idx = bytearray(pal.tobytes())
    colors = pal.getpalette()[:BG_COLORS * 3]
    colors += [0] * (BG_COLORS * 3 - len(colors))
    # bar under the header, as bar-ramp levels (painted in the section color at request time)
    bar = rounded_mask((R - L, BAR_H), (0, 0, R - L, BAR_H), BAR_H // 2)
    for y in range(BAR_H):
        for x in range(R - L):
            lv = (bar.getpixel((x, y)) * 15 + 127) // 255
            if lv:
                idx[(BAR_Y + y) * W + L + x] = RAMP_BASE['bar'] + lv
    return bytes(colors), bytes(idx)


def main():
    colors, idx = background()
    fonts = {name: glyph_set(*spec) for name, spec in FONTS.items()}
    layout = {'W': W, 'H': H, 'L': L, 'R': R, 'BAR_Y': BAR_Y, 'BAR_H': BAR_H, 'BG_COLORS': BG_COLORS, 'RAMP_BASE': RAMP_BASE,
              'colors': {'paper': PAPER, 'ink': INK, 'muted': MUTED, 'olive': OLIVE, 'bar': OLIVE}}
    body = json.dumps([layout, base64.b64encode(colors).decode(), base64.b64encode(idx).decode(), fonts], sort_keys=True)
    digest = hashlib.sha1(body.encode()).hexdigest()[:12]
    src = f"""// GENERATED by scripts/gen_og_assets.py — do not edit. Run `npm run gen:og` after changing the script.
// Per-post Open Graph image data for src/pages/og.ts: the static background (palette indices, zlib) and glyph masks
// (16 levels, zlib) of Liberation Sans Bold/Regular 2.x (SIL Open Font License 1.1).
export interface OgFont {{ size: number; ascent: number; descent: number; glyphs: number[][]; data: string }}
/** Fingerprint of everything below; part of every image URL's ?v= (src/pages/og.ts ogVersion). */
export const OG_ASSETS_HASH = {json.dumps(digest)};
export const OG_LAYOUT = {json.dumps(layout)} as const;
/** RGB triples of the background palette (OG_LAYOUT.BG_COLORS entries), base64. */
export const OG_BG_PALETTE = {json.dumps(base64.b64encode(colors).decode())};
/** W*H palette indices of the background, zlib, base64. */
export const OG_BG_INDICES = {json.dumps(base64.b64encode(zlib.compress(idx, 9)).decode())};
/** Glyph rows: [codepoint, advance*64, x0, y0 (from the baseline), w, h, offset into the unpacked levels]. */
export const OG_FONTS: Record<string, OgFont> = {json.dumps(fonts, separators=(',', ':'))};
"""
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f'wrote {os.path.relpath(OUT, ROOT)} ({len(src) // 1024} KiB)')


if __name__ == '__main__':
    main()
