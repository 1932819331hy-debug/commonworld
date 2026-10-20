/**
 * Tiny XSS-safe HTML builder. Every interpolated value in h`` is HTML-escaped unless it is a Raw
 * (markup built by h`` itself or by raw() for trusted, code-owned strings). Arrays are joined.
 * User content never goes through raw().
 */
export class Raw {
  constructor(readonly html: string) {}
  toString(): string { return this.html; }
}

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (value: unknown): string => String(value).replace(/[&<>"']/g, (ch) => ESC[ch]);

export type Part = Raw | string | number | boolean | null | undefined | Part[];

function render(value: Part): string {
  if (value === null || value === undefined || value === false || value === true) return '';
  if (value instanceof Raw) return value.html;
  if (Array.isArray(value)) return value.map(render).join('');
  return esc(value);
}

export function h(strings: TemplateStringsArray, ...values: Part[]): Raw {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += render(values[i]) + strings[i + 1];
  return new Raw(out);
}

/** Trusted, code-owned markup only (icons, fixed snippets). */
export const raw = (html: string): Raw => new Raw(html);

export const join = (parts: Part[], sep = ''): Raw => new Raw(parts.map(render).join(render(sep)));

/** JSON for a <script type="application/ld+json"> block: cannot break out of the script element. */
export function jsonForScript(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

export const fmt = (n: number): string => Number(n || 0).toLocaleString('en-US');
/** "1 post", "2 posts", "1,200 porch lines" (English plural; `many` defaults to one + 's'). */
export const plural = (n: number, one: string, many = `${one}s`): string => `${fmt(n)} ${Number(n) === 1 ? one : many}`;

/** "38 min", "2 h", "3 d", "2 w", "4 mo", "1 y" from an ISO timestamp. */
export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (!Number.isFinite(s)) return '';
  if (s < 60) return 'just now';
  const m = s / 60;
  if (m < 60) return `${Math.floor(m)} min ago`;
  const hr = m / 60;
  if (hr < 24) return `${Math.floor(hr)} h ago`;
  const d = hr / 24;
  if (d < 14) return `${Math.floor(d)} d ago`;
  if (d < 60) return `${Math.floor(d / 7)} w ago`;
  if (d < 365) return `${Math.floor(d / 30)} mo ago`;
  return `${Math.floor(d / 365)} y ago`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** "4 Sep 2026" (UTC date). */
export function day(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** Plain-text excerpt for cards and meta descriptions: collapses whitespace, cuts at a word boundary. */
export function excerpt(text: string, max: number): string {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  const sp = cut.lastIndexOf(' ');
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:–-]+$/, '') + '…';
}
