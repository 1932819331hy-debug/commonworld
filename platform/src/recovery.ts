/**
 * External proofs for linked identities and account recovery (routes: src/routes/recovery.ts).
 *
 * A challenge code `cw-citizen-<number>-<10 random chars>` is tied to one citizen. The citizen posts it on a resource
 * only they control, and we read it back from public sources:
 *   github  bio (GET api.github.com/users/<login>) or a public gist (description or the first file of the 5 newest)
 *   x       bio, read through the public FxTwitter API (GET api.fxtwitter.com/<handle>)
 *   domain  DNS TXT on _commonworld.<domain> or <domain> (DNS over HTTPS, cloudflare-dns.com), or
 *           https://<domain>/.well-known/commonworld-proof.txt
 * Each lookup has a timeout and a size cap; nothing is stored except the outcome (method + public proof URL).
 * Redirects are never followed (redirect: 'manual'; any 3xx = no proof): the evidence must come from exactly the https URL
 * we asked, so a page on the claimed domain cannot point the check at a host the citizen does not control (or at http).
 *
 * HOOK (planned, not built): agents will be able to prove control with their Ed25519 signing key instead of an
 * external page (`method: "signing_key"` in POST /v1/recovery answers 400 method_not_available until then).
 */
import { normalizeDomain } from './trust-engine/index.ts';
import { trustDomains } from './trust';
import type { Env } from './env';
import { readUpTo } from './http';

export type Provider = 'github' | 'x' | 'domain';
export const PROVIDERS: Provider[] = ['github', 'x', 'domain'];
export interface ProofResult { ok: boolean; method?: string; proof_url?: string; detail?: string }

const TIMEOUT_MS = 5000;
export const MAX_TEXT = 256 * 1024;
const UA = 'CommonworldVerify/1.0 (+https://commonworld.one/llms.txt)';
const ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789';

export function newChallenge(accountNumber: number): string {
  let s = '';
  for (const b of crypto.getRandomValues(new Uint8Array(10))) s += ALPHABET[b % ALPHABET.length];
  return `cw-citizen-${accountNumber}-${s}`;
}

/** Normalized subject or null when it is not a valid name for the provider. */
export function normalizeSubject(env: Env, provider: Provider, raw: unknown): string | null {
  const s = typeof raw === 'string' ? raw.trim().replace(/^@/, '') : '';
  if (provider === 'github') return /^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){0,38}$/i.test(s) ? s.toLowerCase() : null;
  if (provider === 'x') return /^[A-Za-z0-9_]{1,15}$/.test(s) ? s.toLowerCase() : null;
  const d = strictPublicDomain(domainInput(s));
  if (!d) return null;
  const own = trustDomains(env).map(normalizeDomain);
  if (own.some((o) => d === o || d.endsWith(`.${o}`))) return null;
  return d;
}

/**
 * Recovery-local front end to the shared normalizeDomain (the vendored trust-engine copy is not changed):
 * - the IDNA label separators U+3002 (。), U+FF0E (．) and U+FF61 (｡) are first mapped to ASCII '.', so they count as
 *   dots everywhere below (before, a bare "example.com。。" slipped past the trailing-dot rule);
 * - the host name always comes from the WHATWG URL parser, for "https://x" and bare "x" alike (bare input is parsed as
 *   "https://x"), so both forms give the same name: Unicode becomes punycode ("bücher.de" -> xn--bcher-kva.de);
 * - one trailing dot is the DNS root and is dropped as before; two or more ("example.com..") are refused. The count is
 *   made on the parsed host name, so normalizeDomain (which strips trailing dots) only ever sees at most one.
 */
const IDNA_DOTS = /[\u3002\uff0e\uff61]/g;
function domainInput(s: string): string {
  const t = s.replace(IDNA_DOTS, '.');
  let host: string;
  try { host = new URL(t.includes('://') ? t : `https://${t}`).hostname; } catch { return ''; }
  if (/\.\.+$/.test(host)) return '';
  return normalizeDomain(host);
}

/** Reserved / internal names that never denote a public site anyone can own (RFC 6761, RFC 8375, common LAN suffixes). */
const INTERNAL_SUFFIXES = ['localhost', 'local', 'internal', 'intranet', 'lan', 'home', 'corp', 'private', 'invalid', 'arpa', 'onion', 'localdomain'];

/**
 * Strict public DNS name for domain proofs (local to recovery; the shared normalizeDomain used by the trust engine is not
 * changed). Returns the name or null. Rules: the WHATWG URL parser must give back exactly the same lower-case name (so
 * every IPv4 spelling it rewrites, such as 127.1, 0x7f.0.0.1, 0177.0.0.1, 192.168.1 or 2130706433, is refused, and IPv6
 * literals never pass the character set); at least two labels; each label 1-63 of [a-z0-9-] without a leading or
 * trailing hyphen; at most 253 characters; the last label alphabetic (2-63 letters) or punycode (xn--), never numeric
 * or hex; no localhost / .local / .internal style names.
 */
export function strictPublicDomain(input: string): string | null {
  const d = String(input ?? '').trim().toLowerCase();
  if (!d || d.length > 253 || !/^[a-z0-9.-]+$/.test(d)) return null;
  let host: string;
  try { host = new URL(`https://${d}/`).hostname; } catch { return null; }
  if (host !== d) return null;
  const labels = d.split('.');
  if (labels.length < 2) return null;
  if (!labels.every((l) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(l))) return null;
  const tld = labels[labels.length - 1];
  if (!/^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/.test(tld)) return null;
  if (INTERNAL_SUFFIXES.includes(tld) || d === 'home.arpa' || d.endsWith('.home.arpa')) return null;
  return d;
}

export function profileUrl(provider: Provider, subject: string): string {
  return provider === 'github' ? `https://github.com/${subject}` : provider === 'x' ? `https://x.com/${subject}` : `https://${subject}`;
}

/** Where and how to post the code (shown with every challenge). */
export function instructions(provider: Provider, subject: string, code: string): string {
  if (provider === 'github') return `Put ${code} in your GitHub bio (https://github.com/settings/profile) or in a public gist (description or file) of ${subject}.`;
  if (provider === 'x') return `Put ${code} in the bio of @${subject} on X (Edit profile). It can be removed after the check.`;
  return `Add a DNS TXT record "${code}" on _commonworld.${subject} (or ${subject}), or serve ${code} at https://${subject}/.well-known/commonworld-proof.txt.`;
}

/**
 * GET over https only, no redirects followed: a 3xx (same host, another host, or a downgrade to http) counts as "no
 * proof here", and so does a response that says it was redirected or came from another URL. Ownership evidence must come
 * from the exact URL we asked.
 */
/** True when `final` is empty (a constructed Response) or is https on exactly the host of `asked`. */
function sameHttpsHost(final: string, asked: string): boolean {
  if (!final) return true;
  try { const f = new URL(final); return f.protocol === 'https:' && f.host === new URL(asked).host; } catch { return false; }
}
async function fetchText(url: string, accept = '*/*'): Promise<string | null> {
  if (!url.startsWith('https://')) return null;
  try {
    const res = await globalThis.fetch(url, { headers: { 'user-agent': UA, accept }, signal: AbortSignal.timeout(TIMEOUT_MS), redirect: 'manual' });
    if (!res.ok || res.redirected || !sameHttpsHost(res.url, url)) { await res.body?.cancel().catch(() => undefined); return null; }
    // Streams at most MAX_TEXT bytes and cancels the rest of the body (a huge or endless page is never buffered).
    // A response over the cap is refused as a whole: a proof is never read from a truncated page, even when the code
    // sits inside the first MAX_TEXT bytes.
    const { bytes, over } = await readUpTo(res.body, MAX_TEXT);
    if (over) return null;
    return new TextDecoder().decode(bytes);
  } catch { return null; }
}
async function fetchJson(url: string, accept = 'application/json'): Promise<any> {
  const t = await fetchText(url, accept);
  if (t === null) return null;
  try { return JSON.parse(t); } catch { return null; }
}

async function github(login: string, code: string): Promise<ProofResult> {
  const user = await fetchJson(`https://api.github.com/users/${encodeURIComponent(login)}`, 'application/vnd.github+json');
  if (user && typeof user.bio === 'string' && user.bio.includes(code)) return { ok: true, method: 'bio', proof_url: `https://github.com/${login}` };
  const gists = await fetchJson(`https://api.github.com/users/${encodeURIComponent(login)}/gists?per_page=5`, 'application/vnd.github+json');
  if (Array.isArray(gists)) {
    for (const g of gists.slice(0, 5)) {
      if (typeof g?.description === 'string' && g.description.includes(code)) return { ok: true, method: 'gist', proof_url: String(g.html_url) };
      const file = g?.files ? Object.values(g.files)[0] as { raw_url?: string; size?: number } : null;
      if (file?.raw_url && (file.size ?? 0) <= MAX_TEXT && /^https:\/\/gist\.githubusercontent\.com\//.test(file.raw_url)) {
        const text = await fetchText(file.raw_url, 'text/plain');
        if (text?.includes(code)) return { ok: true, method: 'gist', proof_url: String(g.html_url) };
      }
    }
  }
  return { ok: false, detail: user ? 'code not found in the bio or the 5 newest public gists' : 'GitHub user not found or GitHub did not answer' };
}

async function x(handle: string, code: string): Promise<ProofResult> {
  const data = await fetchJson(`https://api.fxtwitter.com/${encodeURIComponent(handle)}`);
  const bio = data?.user?.description;
  if (typeof bio === 'string' && bio.includes(code)) return { ok: true, method: 'bio', proof_url: `https://x.com/${handle}` };
  return { ok: false, detail: data?.user ? 'code not found in the X bio' : 'X account not found or the bio could not be read' };
}

async function domain(name: string, code: string): Promise<ProofResult> {
  for (const host of [`_commonworld.${name}`, name]) {
    const dns = await fetchJson(`https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(host)}&type=TXT`, 'application/dns-json');
    const answers: { data?: string }[] = Array.isArray(dns?.Answer) ? dns.Answer : [];
    if (answers.some((a) => typeof a.data === 'string' && a.data.replace(/"\s*"/g, '').replace(/"/g, '').includes(code))) {
      return { ok: true, method: 'dns', proof_url: `https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(host)}&type=TXT` };
    }
  }
  const wellKnown = `https://${name}/.well-known/commonworld-proof.txt`;
  const text = await fetchText(wellKnown, 'text/plain');
  if (text?.includes(code)) return { ok: true, method: 'well-known', proof_url: wellKnown };
  return { ok: false, detail: 'code not found in DNS TXT (_commonworld or the domain) or in /.well-known/commonworld-proof.txt' };
}

/** Looks for `code` on the provider's public sources for `subject`. */
export async function findProof(provider: Provider, subject: string, code: string): Promise<ProofResult> {
  if (provider === 'github') return github(subject, code);
  if (provider === 'x') return x(subject, code);
  return domain(subject, code);
}
