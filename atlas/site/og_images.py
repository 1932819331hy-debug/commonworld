"""Per-page Open Graph images for the Atlas (1200x630 PNG). Needs Pillow; optional for the build.

build.py describes every indexable page as a small JSON-able spec (kind, title, category color, status, chips, description)
and calls render_all(). Each spec is hashed together with RENDER_VERSION, the resolved fonts and the logo bytes; the PNG is
cached under atlas/site/.og-cache/<hash>.png (gitignored) and copied into dist, so a rebuild only renders what changed.
Same spec + same fonts -> byte-identical PNG (palette PNG, no timestamps, no dithering).

If Pillow is not installed, build.py falls back to the single static og-atlas.png and prints a warning
(check.py then fails on "unique og:image", on purpose). Install with: pip install Pillow
"""
import hashlib, json, os, shutil

RENDER_VERSION = 'og-v3'
W, H = 1200, 630
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.og-cache')
MARK = os.path.join(HERE, 'static', 'cw-mark-light-192.png')  # vector mark's 192 px export, downsampled to 64 px

# palette = Commonworld light tokens (components/cw-components.css)
BG, PAPER, INK, MUTED, LINE = '#f4f1ea', '#fbfaf7', '#202522', '#686e68', '#dfded6'
ACCENT_TEXT, OLIVE, LIVE, DEAD = '#bf472c', '#63705b', '#2f7d4f', '#a24e3d'

FONT_DIRS = ['/usr/share/fonts/truetype/inter', '/usr/share/fonts/opentype/inter', '/usr/share/fonts/truetype/liberation',
             '/usr/share/fonts/truetype/liberation2', '/usr/share/fonts/truetype/dejavu', '/Library/Fonts',
             '/System/Library/Fonts/Supplemental', os.path.expanduser('~/Library/Fonts'), 'C:/Windows/Fonts']
BOLD = ['Inter-Bold.ttf', 'Inter-SemiBold.ttf', 'LiberationSans-Bold.ttf', 'Arial Bold.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf']
REG = ['Inter-Regular.ttf', 'LiberationSans-Regular.ttf', 'Arial.ttf', 'arial.ttf', 'DejaVuSans.ttf']


def _find(names):
    for n in names:
        for d in FONT_DIRS:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None


def available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


_FONTS = None


def fonts():
    global _FONTS
    if _FONTS is None:
        _FONTS = (_find(BOLD), _find(REG))
    return _FONTS


def _mark_hash():
    return hashlib.sha1(open(MARK, 'rb').read()).hexdigest()[:12] if os.path.exists(MARK) else 'nomark'


def spec_key(spec):
    b, r = fonts()
    raw = json.dumps({'v': RENDER_VERSION, 'spec': spec, 'fonts': [os.path.basename(b or ''), os.path.basename(r or '')],
                      'mark': _mark_hash()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()


# ---------------------------------------------------------------- drawing
def _font(path, size):
    from PIL import ImageFont
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _w(f, s):
    return f.getlength(s)


def _break_word(word, f, max_w):
    out, cur = [], ''
    for ch in word:
        if cur and _w(f, cur + ch) > max_w:
            out.append(cur); cur = ch
        else:
            cur += ch
    return out + ([cur] if cur else [])


def wrap(text, f, max_w, max_lines):
    """Greedy word wrap; over-long words are broken; the last line gets an ellipsis if text remains.
    Returns (lines, truncated)."""
    words = []
    for wd in text.split():
        words += _break_word(wd, f, max_w) if _w(f, wd) > max_w else [wd]
    lines, cur, i = [], '', 0
    while i < len(words):
        cand = (cur + ' ' + words[i]).strip()
        if _w(f, cand) <= max_w:
            cur = cand; i += 1
        else:
            lines.append(cur); cur = ''
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    truncated = i < len(words)
    if truncated and lines:
        last = lines[-1].rstrip(' ,;:.—-')
        while last and _w(f, last + '…') > max_w:
            last = last[:-1].rstrip(' ,;:.—-')
        lines[-1] = last + '…'
    return lines, truncated


def _pill(d, x, y, text, f, fg, dot=None, h=40):
    pad = 16
    tw = _w(f, text)
    dw = 18 if dot else 0
    wd = int(pad * 2 + dw + tw)
    d.rounded_rectangle((x, y, x + wd, y + h), radius=h // 2, fill=PAPER, outline=LINE, width=2)
    if dot:
        cy = y + h // 2
        d.ellipse((x + pad, cy - 5, x + pad + 10, cy + 5), fill=dot)
    d.text((x + pad + dw, y + h // 2), text, font=f, fill=fg, anchor='lm')
    return x + wd


def render(spec, path):
    from PIL import Image, ImageDraw
    fb, fr = fonts()
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 40, W - 40, H - 40), radius=36, fill=PAPER, outline=LINE, width=2)
    L, R = 90, W - 90

    # header: logo + COMMONWORLD / Atlas, kicker chip on the right
    if os.path.exists(MARK):
        m = Image.open(MARK).convert('RGBA').resize((64, 64), Image.LANCZOS)
        im.paste(m, (L, 80), m)
    d.text((L + 82, 84), 'COMMONWORLD', font=_font(fb, 19), fill=ACCENT_TEXT)
    d.text((L + 80, 106), spec.get('brand') or 'Atlas', font=_font(fb, 34), fill=INK)
    kick = spec.get('kicker') or ''
    if kick:
        fk = _font(fb, 19)
        kw = _w(fk, kick)
        x0 = R - kw - (24 if spec.get('kicker_color') else 0)
        if spec.get('kicker_color'):
            d.rounded_rectangle((x0, 104, x0 + 14, 118), radius=3, fill=spec['kicker_color'])
            x0 += 24
        d.text((x0, 111), kick, font=fk, fill=INK, anchor='lm')

    # category bar: one color, or proportional segments [(count, color)]
    by, bh = 170, 10
    segs = spec.get('bar') or [[1, OLIVE]]
    tot = sum(n for n, _ in segs) or 1
    x = L
    bar = Image.new('RGB', (R - L, bh), PAPER)
    bd = ImageDraw.Draw(bar)
    for i, (n, col) in enumerate(segs):
        x1 = R if i == len(segs) - 1 else x + round((R - L) * n / tot)
        bd.rectangle((x - L, 0, x1 - L, bh), fill=col)
        x = x1
    mask = Image.new('L', (R - L, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, R - L - 1, bh - 1), radius=bh // 2, fill=255)
    im.paste(bar, (L, by), mask)

    # title: largest size that fits in 2 lines
    title = spec['title']
    for size in (84, 76, 68, 60, 54, 48, 44):
        ft = _font(fb, size)
        lines, trunc = wrap(title, ft, R - L, 2)
        if not trunc:
            break
    lh = int(size * 1.08)
    y = 214
    for ln in lines:
        d.text((L, y), ln, font=ft, fill=INK, anchor='la')
        y += lh
    y += 18

    # chips: status, type, claims, …
    fc = _font(fb, 20)
    x = L
    for c in spec.get('chips', []):
        fg = {'live': LIVE, 'closed': DEAD}.get(c.get('tone'), OLIVE if c.get('tone') == 'olive' else MUTED)
        dot = {'live': '#48a671', 'closed': DEAD}.get(c.get('tone'))
        if x + _w(fc, c['text']) + 60 > R:
            break
        x = _pill(d, x, y, c['text'], fc, fg, dot) + 12
    y += 40 + 26

    # description: as many lines as fit above the footer (max 2)
    desc = spec.get('desc') or ''
    fd = _font(fr, 29)
    dl = 37
    room = max(0, min(2, (500 - y) // dl))  # 2-line titles get 1 description line
    if desc and room:
        for ln in wrap(desc, fd, R - L, room)[0]:
            d.text((L, y), ln, font=fd, fill=MUTED, anchor='la')
            y += dl

    # footer
    d.text((L, 560), spec.get('foot_left') or 'commonworld.one/atlas', font=_font(fb, 23), fill=OLIVE, anchor='ls')
    if spec.get('foot_right'):
        d.text((R, 560), spec['foot_right'], font=_font(fr, 21), fill=MUTED, anchor='rs')

    pal = im.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal.save(path, format='PNG', optimize=True)


def render_all(jobs, dest_dir, prune=True):
    """jobs: {name: (spec, key)} -> writes dest_dir/<name>.png. Returns (rendered, cached)."""
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(dest_dir, exist_ok=True)
    rendered = cached = 0
    used = set()
    for name, (spec, key) in jobs.items():
        cp = os.path.join(CACHE, key + '.png')
        used.add(key + '.png')
        if os.path.exists(cp):
            cached += 1
        else:
            tmp = cp + '.tmp'
            render(spec, tmp)
            os.replace(tmp, cp)
            rendered += 1
        shutil.copyfile(cp, os.path.join(dest_dir, name + '.png'))
    if prune:
        for f in os.listdir(CACHE):
            if f.endswith('.png') and f not in used:
                os.remove(os.path.join(CACHE, f))
    return rendered, cached
