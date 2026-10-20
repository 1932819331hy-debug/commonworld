/**
 * Size-capped fetch for the vendored trust engine (src/trust-engine/ is vendored and must not be edited, so the cap
 * sits at the FetchLike boundary instead of inside its getText()).
 *
 * The unsafe-domain lists are big and come from third parties: an endless or hijacked response must never be buffered
 * whole. Every body is read through readUpTo (src/http.ts), which counts bytes as they arrive and cancels the stream as
 * soon as the cap is passed. Caps are about 4x the real list sizes measured on 2026-10-19:
 *
 *   MetaMask eth-phishing-detect config.json   3.07 MB  -> 12 MiB
 *   ScamSniffer blacklist/domains.json         9.12 MB  -> 36 MiB
 *   CERT Polska domains.txt                    2.56 MB  -> 10 MiB
 *   anything else (Safe Browsing lookups)      < 1 KB   ->  1 MiB
 *
 * Over the cap the response counts as a failed download (ok: false, status 413): the engine then answers no_data for
 * that source, exactly as for a network error (TRUST.md: a source that cannot answer never blocks), and a truncated list
 * is never matched against. Status 413 is < 500 and not 429, so getText does not retry the download. One warning per
 * URL per isolate, logged as origin + path only (no query string).
 */
import { readUpTo } from './http';
import { certPolska, metamask, scamsniffer, type FetchLike } from './trust-engine/index.ts';

const MiB = 1024 * 1024;
export const LIST_CAPS: Readonly<Record<string, number>> = {
  [metamask.url]: 12 * MiB,
  [scamsniffer.url]: 36 * MiB,
  [certPolska.url]: 10 * MiB,
};
export const DEFAULT_RESPONSE_CAP = 1 * MiB;
export const OVER_CAP_STATUS = 413;

export const capFor = (url: string): number => LIST_CAPS[url] ?? DEFAULT_RESPONSE_CAP;

const warned = new Set<string>();
/** Origin + path, never the query string (lookup URLs carry the domain being checked). */
export function logSafeUrl(url: string): string {
  try { const u = new URL(url); return u.origin + u.pathname; } catch { return '(invalid url)'; }
}
function warnOnce(url: string, cap: number): void {
  const key = logSafeUrl(url);
  if (warned.has(key)) return;
  warned.add(key);
  console.warn(`trust source response over ${cap} bytes, not used: ${key}`);
}
export const resetCapWarnings = (): void => warned.clear();

type RawResponse = { ok: boolean; status: number; body: ReadableStream<Uint8Array> | null };

/** Body as text, or null when it passed `cap` (the stream is cancelled at the cap, a warning is logged once). */
export async function readCappedText(res: RawResponse, url: string, cap: number = capFor(url)): Promise<string | null> {
  const { bytes, over } = await readUpTo(res.body, cap);
  if (over) { warnOnce(url, cap); return null; }
  return new TextDecoder().decode(bytes);
}

/** Wraps a raw fetch into an engine FetchLike whose bodies are read eagerly under the cap for their URL. */
export function cappedFetchLike(raw: (url: string, init?: { headers?: Record<string, string>; signal?: AbortSignal }) => Promise<RawResponse>): FetchLike {
  return async (u, init) => {
    const res = await raw(u, init);
    if (!res.ok) {
      await res.body?.cancel().catch(() => undefined);
      return { ok: false, status: res.status, text: async () => '' };
    }
    const text = await readCappedText(res, u);
    if (text === null) return { ok: false, status: OVER_CAP_STATUS, text: async () => '' };
    return { ok: true, status: res.status, text: async () => text };
  };
}
