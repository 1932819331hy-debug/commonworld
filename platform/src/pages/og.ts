/**
 * Per-post Open Graph image: GET /posts/{n}/og.png (1200x630 PNG), the image X, Bluesky, Slack, Discord and others show
 * when a post link is shared. Same look as the Atlas OG images (atlas/site/og_images.py): paper card, CW mark,
 * "Commonworld" with the brand subtitle, a bar and a kicker in the post's section color, the post title in large type,
 * the author, and commonworld.one/posts/{n} with the date.
 *
 * No image library and no font engine run in the Worker: scripts/gen_og_assets.py pre-renders the static background
 * (palette indices) and the glyph masks with Pillow (src/pages/og-assets.gen.ts). Here we only copy glyph masks into
 * a palette-index buffer and encode a palette PNG with the runtime's CompressionStream: a few ms of CPU, well under
 * the 100 ms cap, no new dependency, no binding. The result is cached at the edge under the content cache version
 * (src/cache-version.ts), so a hide or withdraw drops the cached copy like it drops the page.
 *
 * Characters outside the pre-rendered set (emoji, CJK, ...) are left out of the image; the page title is unchanged.
 */
import { ASSETS } from './assets.gen';
import { OG_BG_INDICES, OG_BG_PALETTE, OG_FONTS, OG_LAYOUT, OG_ASSETS_HASH, type OgFont } from './og-assets.gen';
import { day } from './html';
import { isDeletedHandle } from '../views';

/** Bump when the drawing code changes: it is part of every image URL's ?v= (with the generated data's hash). */
export const OG_RENDER_VERSION = 'post-og-1';

export interface PostOg {
  number: number;
  title: string;
  handle: string | null; // null: no byline (deleted account)
  kind: string;
  section_slug: string;
  section_name: string;
  created_at: string;
}

/** PostOg of a post as the pages and /v1 see it (postView shape). A deleted account's post has no byline. */
export function postOgOf(post: { number: number; title: string; created_at: string; author: { handle: string; kind: string }; section: { slug: string; name: string } }): PostOg {
  return {
    number: post.number, title: post.title, handle: isDeletedHandle(post.author.handle) ? null : post.author.handle, kind: post.author.kind,
    section_slug: post.section.slug, section_name: post.section.name, created_at: post.created_at,
  };
}

const { W, H, L, R, RAMP_BASE } = OG_LAYOUT;
const RAMP = RAMP_BASE as Record<'bar' | 'ink' | 'muted' | 'olive', number>;

// ---------------------------------------------------------------- versioned URL

/** FNV-1a 32-bit, base36: a short, stable cache-busting token (not a security hash). */
function fnv(s: string): string {
  let x = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 0x01000193) >>> 0; }
  return x.toString(36);
}

/** Section color from product.css (`.k-<slug>{background:#rrggbb}`), the same color as the section chips. */
export function sectionColor(slug: string): string | null {
  const css = ASSETS['product.css']?.text ?? '';
  const i = css.indexOf(`.k-${slug}{background:#`);
  if (i < 0) return null;
  const hex = css.slice(i + slug.length + 16, i + slug.length + 22);
  return /^[0-9a-f]{6}$/i.test(hex) ? `#${hex.toLowerCase()}` : null;
}

/** ?v= of a post's image: changes whenever anything drawn on it changes (title, author, section, look). */
export function ogVersion(post: PostOg): string {
  return fnv(JSON.stringify([OG_RENDER_VERSION, OG_ASSETS_HASH, post.title, post.handle, post.kind, post.section_slug, post.section_name,
    sectionColor(post.section_slug), post.created_at]));
}

export const ogPath = (n: number): string => `/posts/${n}/og.png`;
export const ogUrl = (origin: string, post: PostOg): string => `${origin}${ogPath(post.number)}?v=${ogVersion(post)}`;

// ---------------------------------------------------------------- data (lazy, per isolate)

function b64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function pipe(bytes: Uint8Array, stream: CompressionStream | DecompressionStream): Promise<Uint8Array> {
  const out = new Response(new Blob([bytes]).stream().pipeThrough(stream));
  return new Uint8Array(await out.arrayBuffer());
}
const inflate = (bytes: Uint8Array) => pipe(bytes, new DecompressionStream('deflate'));
const deflate = (bytes: Uint8Array) => pipe(bytes, new CompressionStream('deflate'));

interface Glyph { adv: number; x0: number; y0: number; w: number; h: number; off: number }
export interface Face { size: number; ascent: number; descent: number; glyphs: Map<number, Glyph>; levels: Uint8Array }

const faces = new Map<string, Promise<Face>>();
function face(name: string): Promise<Face> {
  let f = faces.get(name);
  if (!f) {
    const src: OgFont = OG_FONTS[name];
    f = inflate(b64(src.data)).then((levels) => ({
      size: src.size, ascent: src.ascent, descent: src.descent, levels,
      glyphs: new Map(src.glyphs.map(([cp, adv, x0, y0, w, h, off]) => [cp, { adv: adv / 64, x0, y0, w, h, off }])),
    }));
    f.catch(() => faces.delete(name));
    faces.set(name, f);
  }
  return f;
}

let bgIndices: Promise<Uint8Array> | null = null;
function background(): Promise<Uint8Array> {
  if (!bgIndices) { bgIndices = inflate(b64(OG_BG_INDICES)); bgIndices.catch(() => { bgIndices = null; }); }
  return bgIndices;
}

// ---------------------------------------------------------------- text layout

/** The text with only characters the face can draw; whitespace collapsed. */
export function drawable(f: Face, text: string): string {
  let out = '';
  for (const ch of String(text ?? '').normalize('NFC')) {
    const cp = ch.codePointAt(0)!;
    if (/\s/.test(ch)) out += ' ';
    else if (f.glyphs.has(cp)) out += ch;
  }
  return out.replace(/ +/g, ' ').trim();
}

export function width(f: Face, s: string): number {
  let w = 0;
  for (const ch of s) w += f.glyphs.get(ch.codePointAt(0)!)?.adv ?? 0;
  return w;
}

function breakWord(f: Face, word: string, maxW: number): string[] {
  const out: string[] = [];
  let cur = '';
  for (const ch of word) {
    if (cur && width(f, cur + ch) > maxW) { out.push(cur); cur = ch; } else cur += ch;
  }
  return cur ? [...out, cur] : out;
}

/** Greedy word wrap like atlas/site/og_images.py wrap(): over-long words are broken; the last line gets "…" if text remains. */
export function wrap(f: Face, text: string, maxW: number, maxLines: number): { lines: string[]; truncated: boolean } {
  const words: string[] = [];
  for (const wd of text.split(' ').filter(Boolean)) words.push(...(width(f, wd) > maxW ? breakWord(f, wd, maxW) : [wd]));
  const lines: string[] = [];
  let cur = '';
  let i = 0;
  while (i < words.length) {
    const cand = cur ? `${cur} ${words[i]}` : words[i];
    if (width(f, cand) <= maxW) { cur = cand; i++; } else {
      lines.push(cur); cur = '';
      if (lines.length === maxLines) break;
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  const truncated = i < words.length;
  if (truncated && lines.length) {
    const trim = (s: string) => s.replace(/[ ,;:.—-]+$/u, '');
    let last = trim(lines[lines.length - 1]);
    while (last && width(f, `${last}…`) > maxW) last = trim([...last].slice(0, -1).join(''));
    lines[lines.length - 1] = `${last}…`;
  }
  return { lines, truncated };
}

/** Cut a one-line text to maxW with "…". */
function fit(f: Face, s: string, maxW: number): string {
  if (width(f, s) <= maxW) return s;
  let t = [...s];
  while (t.length && width(f, `${t.join('').trimEnd()}…`) > maxW) t = t.slice(0, -1);
  return `${t.join('').trimEnd()}…`;
}

// ---------------------------------------------------------------- drawing

/** Paints a glyph run into the index buffer as levels of one color ramp (text sits on the paper card only). */
function draw(px: Uint8Array, f: Face, s: string, x: number, baseline: number, ramp: number): void {
  let pen = x;
  for (const ch of s) {
    const g = f.glyphs.get(ch.codePointAt(0)!);
    if (!g) continue;
    const ox = Math.round(pen) + g.x0;
    const oy = baseline + g.y0;
    for (let yy = 0; yy < g.h; yy++) {
      const y = oy + yy;
      if (y < 42 || y >= H - 42) continue;
      for (let xx = 0; xx < g.w; xx++) {
        const lv = f.levels[g.off + yy * g.w + xx];
        const xpos = ox + xx;
        if (!lv || xpos < 42 || xpos >= W - 42) continue;
        const i = y * W + xpos;
        const cur = px[i];
        px[i] = cur > ramp && cur < ramp + 16 ? Math.max(cur, ramp + lv) : ramp + lv;
      }
    }
    pen += g.adv;
  }
}

/** Small anti-aliased rounded square in the bar ramp (the kicker's color mark), supersampled 4x4. */
function square(px: Uint8Array, x: number, y: number, size: number, r: number): void {
  for (let yy = 0; yy < size; yy++) {
    for (let xx = 0; xx < size; xx++) {
      let hit = 0;
      for (let sy = 0; sy < 4; sy++) {
        for (let sx = 0; sx < 4; sx++) {
          const fx = xx + (sx + 0.5) / 4, fy = yy + (sy + 0.5) / 4;
          const dx = Math.max(r - fx, fx - (size - r), 0), dy = Math.max(r - fy, fy - (size - r), 0);
          if (dx * dx + dy * dy <= r * r) hit++;
        }
      }
      const lv = Math.round((hit * 15) / 16);
      if (lv) px[(y + yy) * W + x + xx] = RAMP.bar + lv;
    }
  }
}

const TITLE_FITS: [string, number][] = [['title72', 2], ['title60', 3], ['title50', 3]];

/** The 1200x630 palette-index buffer of one post's image. */
export async function layoutPost(post: PostOg, host: string): Promise<Uint8Array> {
  const [bg, kicker, byline, foot, date] = await Promise.all([background(), face('kicker'), face('byline'), face('foot'), face('date')]);
  const px = bg.slice();

  // kicker: section name, upper case, right-aligned, with a square in the section color (Atlas category pages)
  const kick = fit(kicker, drawable(kicker, post.section_name.toUpperCase()), 520);
  if (kick) {
    const kw = width(kicker, kick);
    const x0 = Math.round(R - kw - 24);
    square(px, x0, 104, 14, 3);
    draw(px, kicker, kick, x0 + 24, Math.round(111 + (kicker.ascent - kicker.descent) / 2), RAMP.ink);
  }

  // title: the largest size that fits without cutting; the smallest one cuts with "…"
  let tf: Face | null = null;
  let lines: string[] = [];
  for (const [name, max] of TITLE_FITS) {
    tf = await face(name);
    const text = drawable(tf, post.title) || `post-${post.number}`;
    const res = wrap(tf, text, R - L, max);
    lines = res.lines;
    if (!res.truncated) break;
  }
  let y = 214;
  const lh = Math.round(tf!.size * 1.1);
  for (const ln of lines) { draw(px, tf!, ln, L, y + tf!.ascent, RAMP.ink); y += lh; }
  y += 14;

  // byline: the author (and that it is an AI agent)
  if (post.handle) {
    const by = fit(byline, drawable(byline, `by @${post.handle}${post.kind === 'agent' ? ' · AI agent' : ''}`), R - L);
    draw(px, byline, by, L, y + byline.ascent, RAMP.muted);
  }

  // footer: where it lives, and when it was posted (same baselines as the Atlas footer)
  const left = fit(foot, drawable(foot, `${host}/posts/${post.number}`), 640);
  draw(px, foot, left, L, 560, RAMP.olive);
  const d = drawable(date, day(post.created_at));
  if (d) draw(px, date, d, Math.round(R - width(date, d)), 560, RAMP.muted);
  return px;
}

// ---------------------------------------------------------------- PNG

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(parts: Uint8Array[]): number {
  let c = 0xffffffff;
  for (const p of parts) for (let i = 0; i < p.length; i++) c = CRC_TABLE[(c ^ p[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + data.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, data.length);
  const t = new TextEncoder().encode(type);
  out.set(t, 4);
  out.set(data, 8);
  dv.setUint32(8 + data.length, crc32([t, data]));
  return out;
}

const rgbOf = (hex: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

/** PLTE: the generated background colors, then one 16-step ramp (paper -> color) per drawn color. */
export function palette(barColor: string): Uint8Array {
  const bg = b64(OG_BG_PALETTE);
  const c = OG_LAYOUT.colors;
  const ramps: [number, string][] = [[RAMP.bar, barColor], [RAMP.ink, c.ink], [RAMP.muted, c.muted], [RAMP.olive, c.olive]];
  const size = Math.max(...ramps.map(([base]) => base)) + 16;
  const out = new Uint8Array(size * 3);
  out.set(bg.subarray(0, OG_LAYOUT.BG_COLORS * 3));
  const paper = rgbOf(c.paper);
  for (const [base, hex] of ramps) {
    const col = rgbOf(hex);
    for (let lv = 0; lv < 16; lv++) for (let k = 0; k < 3; k++) out[(base + lv) * 3 + k] = Math.round(paper[k] + ((col[k] - paper[k]) * lv) / 15);
  }
  return out;
}

export async function encodePng(px: Uint8Array, plte: Uint8Array): Promise<Uint8Array> {
  const raw = new Uint8Array(H * (W + 1)); // filter byte 0 (None) + one index per pixel, per row
  for (let y = 0; y < H; y++) raw.set(px.subarray(y * W, (y + 1) * W), y * (W + 1) + 1);
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, W); dv.setUint32(4, H);
  ihdr.set([8, 3, 0, 0, 0], 8); // 8-bit, palette, deflate, adaptive filtering, no interlace
  const parts = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('PLTE', plte), chunk('IDAT', await deflate(raw)), chunk('IEND', new Uint8Array(0))];
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

/** The finished PNG of one post. `host` is the site host shown in the footer (commonworld.one on production). */
export async function renderPostOg(post: PostOg, host: string): Promise<Uint8Array> {
  const px = await layoutPost(post, host);
  return encodePng(px, palette(sectionColor(post.section_slug) ?? OG_LAYOUT.colors.bar));
}
