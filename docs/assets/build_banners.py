"""Build the README banners (docs/assets/banner-*.svg): Commonworld brand lockup, light and dark.

Text is converted to outlines (DejaVu Sans, the font of the site's OG images), so the SVGs look the same in
every viewer and never depend on installed fonts. Needs fontTools and DejaVu Sans:
    python3 docs/assets/build_banners.py
Colours are the site's design tokens (atlas/site/components/cw-components.css). The mark is atlas/site/static/cw-mark-*.svg.
"""
import os
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = '/usr/share/fonts/truetype/dejavu'
W, H = 1280, 400
THEMES = {
    'light': {'card': '#fbfaf7', 'line': '#dfded6', 'ink': '#202522', 'muted': '#646a64', 'accent': '#b34128',
              'tile': '#f4f0e7', 'mark_ink': '#202522', 'olive': '#63705b'},
    'dark': {'card': '#151816', 'line': '#30372f', 'ink': '#eef0e9', 'muted': '#a3aba0', 'accent': '#ff8063',
             'tile': '#20251f', 'mark_ink': '#eef0e9', 'olive': '#a9b89e'},
}
MARK_C = 'M330 213 L378 285 L262 285 A102 92.5 0 0 0 262 470 L318 470 L350 540 L255 540 A167 163.5 0 0 1 255 213 Z'
MARK_W = 'M283 325 L345 325 L403 412 L470 318 L494 318 L550 410 L626 297 L690 297 L556 535 L541 535 L482 436 L412 530 L396 530 Z'
_fonts = {}


def font(bold):
    k = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    if k not in _fonts:
        _fonts[k] = TTFont(os.path.join(FONTS, k))
    return _fonts[k]


def text_path(s, x, y, size, bold=False, spacing=0.0):
    """(svg path d, advance width in px) for s with its baseline at y."""
    f = font(bold)
    gs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f['hmtx']
    scale = size / f['head'].unitsPerEm
    pen = SVGPathPen(gs, ntos=lambda v: ('%.1f' % v).rstrip('0').rstrip('.'))
    cx = 0.0
    for ch in s:
        g = cmap[ord(ch)]
        gs[g].draw(TransformPen(pen, (scale, 0, 0, -scale, x + cx, y)))
        cx += hmtx[g][0] * scale + spacing
    return pen.getCommands(), cx - spacing


def banner(theme, lines, label, out):
    t = THEMES[theme]
    tx, maxw = 404, W - 404 - 72
    parts = []
    for s, y, size, bold, colour, spacing in lines:
        d, w = text_path(s, tx, y, size, bold, spacing)
        assert w <= maxw, f'{out}: "{s}" is {w:.0f}px, more than {maxw}px'
        parts.append(f'<path fill="{t[colour]}" d="{d}"/>')
    tile = 232
    ty = (H - tile) / 2
    k = tile / 768
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{label}">'
           f'<title>{label}</title>'
           f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="28" fill="{t["card"]}" stroke="{t["line"]}" stroke-width="2"/>'
           f'<g transform="translate(96 {ty}) scale({k:.6f})"><rect width="768" height="768" rx="150" fill="{t["tile"]}"/>'
           f'<path fill="{t["mark_ink"]}" d="{MARK_C}"/><path fill="#cb7756" d="{MARK_W}"/></g>'
           + ''.join(parts) + '</svg>\n')
    with open(os.path.join(HERE, out), 'w', encoding='utf-8') as fh:
        fh.write(svg)


MOTTO = 'A shared world for humans and agents'
SUB = 'Where humans and agents meet, experiment, build, play, and create together.'
for th in THEMES:
    banner(th, [('Commonworld', 172, 84, True, 'ink', 0),
                (MOTTO, 232, 34, False, 'ink', 0),
                ('Where humans and agents meet, experiment, build,', 284, 24, False, 'muted', 0),
                ('play, and create together.', 318, 24, False, 'muted', 0)],
           f'Commonworld. {MOTTO}. {SUB}', f'banner-commonworld-{th}.svg')
    banner(th, [('COMMONWORLD', 140, 26, True, 'accent', 1.5),
                ('Atlas', 230, 92, True, 'ink', 0),
                ('Verified catalog of AI-agent platforms', 286, 34, False, 'ink', 0),
                (MOTTO, 330, 26, False, 'muted', 0)],
           f'Commonworld Atlas. Verified catalog of AI-agent platforms. {MOTTO}.', f'banner-atlas-{th}.svg')
print('ok')
