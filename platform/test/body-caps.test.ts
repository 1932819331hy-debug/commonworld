/**
 * Streaming body caps (Codex audit 2026-10-19, P3 + P4): request bodies on routes that run before the /v1
 * Content-Length check (/lab/beat, /login, website write forms) and the recovery domain-check response are read
 * through the byte-counting readers in src/http.ts. A body without Content-Length (chunked) that passes the cap gets
 * 413 and the rest of the stream is cancelled; normal sizes still work.
 */
import { exports } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readBodyCapped, readUpTo } from '../src/http';
import { LAB_BEAT_MAX_BYTES } from '../src/lab';
import { resetRateLimitDouble } from '../src/ratelimit';
import { findProof, MAX_TEXT } from '../src/recovery';
import { FORM_MAX_BYTES } from '../src/pages/writes';
import { readForm } from '../src/sessions';
import { api, register, resetDb } from './helpers';

beforeEach(async () => { await resetDb(); resetRateLimitDouble(); });
afterEach(() => vi.restoreAllMocks());

const ORIGIN = 'https://cw.test';
const SAME = { origin: ORIGIN, 'sec-fetch-site': 'same-origin' };

/** An endless chunked stream (no Content-Length); `pulled()` = bytes handed out, `cancelled()` = reader cancelled it. */
function endless(chunk = 1024, fill = 'a') {
  const piece = new TextEncoder().encode(fill.repeat(chunk));
  let pulled = 0, cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(c) { pulled += piece.byteLength; c.enqueue(piece); },
    cancel() { cancelled = true; },
  });
  return { stream, pulled: () => pulled, cancelled: () => cancelled };
}

const fetchWorker = (req: Request): Promise<Response> => (exports as any).default.fetch(req);
const chunkedPost = (path: string, body: ReadableStream<Uint8Array>, headers: Record<string, string> = {}) =>
  new Request(`${ORIGIN}${path}`, { method: 'POST', body, headers, redirect: 'manual', duplex: 'half' } as RequestInit);

describe('shared streaming reader (src/http.ts)', () => {
  it('readUpTo stops at the cap, cancels the stream and keeps exactly the first maxBytes bytes', async () => {
    const s = endless(1000);
    const { bytes, over } = await readUpTo(s.stream, 2500);
    expect(over).toBe(true);
    expect(bytes.byteLength).toBe(2500);
    expect(s.cancelled()).toBe(true);
    expect(s.pulled()).toBeLessThanOrEqual(3000 + 1000);
  });
  it('readBodyCapped: chunked over the cap -> 413 with max_bytes; at the cap -> the bytes', async () => {
    const big = endless(512);
    await expect(readBodyCapped(chunkedPost('/x', big.stream), 4096)).rejects.toMatchObject({ status: 413, code: 'request_body_too_large', extra: { max_bytes: 4096 } });
    expect(big.cancelled()).toBe(true);
    const exact = await readBodyCapped(new Request(`${ORIGIN}/x`, { method: 'POST', body: 'b'.repeat(4096) }), 4096);
    expect(exact.byteLength).toBe(4096);
  });
  it('counts bytes, not characters (multi-byte text over the cap is refused)', async () => {
    const text = 'ж'.repeat(3000); // 3000 chars, 6000 bytes
    await expect(readBodyCapped(new Request(`${ORIGIN}/x`, { method: 'POST', body: text }), 4096)).rejects.toMatchObject({ status: 413 });
  });
});

const VALID_BEAT = '{"sid":"a1b2c3d4","n":1,"ev":"tick","vis":"visible","focus":true,"t":1760870400000}';

describe('POST /lab/beat (local/staging only)', () => {
  it('normal beat -> 204', async () => {
    const r = await fetchWorker(new Request(`${ORIGIN}/lab/beat`, { method: 'POST', body: '{"sid":"a","n":1,"ev":"load"}', headers: { 'content-type': 'application/json' } }));
    expect(r.status).toBe(204);
  });
  it('chunked body over 1 KB (no Content-Length) -> 413, stream cancelled', async () => {
    const s = endless(256);
    const r = await fetchWorker(chunkedPost('/lab/beat', s.stream, { 'content-type': 'application/json' }));
    expect(r.status).toBe(413);
    expect(((await r.json()) as any).error).toEqual({ code: 'request_body_too_large', max_bytes: LAB_BEAT_MAX_BYTES });
    expect(s.pulled()).toBeLessThan(64 * 1024);
  });
  it('declared Content-Length over 1 KB -> 413 before reading', async () => {
    const r = await fetchWorker(new Request(`${ORIGIN}/lab/beat`, { method: 'POST', body: 'x'.repeat(LAB_BEAT_MAX_BYTES + 1) }));
    expect(r.status).toBe(413);
  });
  it('per-network rate limit: 60 beats per minute, the 61st -> 429 with Retry-After', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 19, 12, 0, 5));
    const beat = () => fetchWorker(new Request(`${ORIGIN}/lab/beat`, { method: 'POST', body: VALID_BEAT, headers: { 'cf-connecting-ip': '203.0.113.7' } }));
    for (let i = 0; i < 60; i++) expect((await beat()).status).toBe(204);
    const r = await beat();
    expect(r.status).toBe(429);
    expect(r.headers.get('retry-after')).toBeTruthy();
    expect(((await r.json()) as any).error.scope).toBe('lab_beat_ip');
    // another network is not affected
    const other = await fetchWorker(new Request(`${ORIGIN}/lab/beat`, { method: 'POST', body: VALID_BEAT, headers: { 'cf-connecting-ip': '198.51.100.9' } }));
    expect(other.status).toBe(204);
  });
});

describe('forms (readForm): /login and website writes', () => {
  it('readForm: chunked over the cap -> 413; normal form parses', async () => {
    const s = endless(1024);
    await expect(readForm(chunkedPost('/login', s.stream))).rejects.toMatchObject({ status: 413, extra: { max_bytes: 4096 } });
    expect(s.cancelled()).toBe(true);
    const ok = await readForm(new Request(`${ORIGIN}/login`, { method: 'POST', body: 't=abc&x=1' }));
    expect(ok.get('t')).toBe('abc');
  });
  it('POST /login with a chunked body over 4 KB -> 413; a normal login still signs in', async () => {
    const s = endless(1024, 't');
    const big = await fetchWorker(chunkedPost('/login', s.stream, { ...SAME, 'content-type': 'application/x-www-form-urlencoded' }));
    expect(big.status).toBe(413);
    expect(await big.text()).toContain('request_body_too_large');
    expect(s.pulled()).toBeLessThan(64 * 1024);

    const a = await register('capped', 'human', 24 * 30);
    const link = await api('/v1/auth/login-link', { key: a.key, method: 'POST' });
    const token = new URL(link.body.url).searchParams.get('t')!;
    const ok = await fetchWorker(new Request(`${ORIGIN}/login`, { method: 'POST', redirect: 'manual', headers: { ...SAME, 'content-type': 'application/x-www-form-urlencoded' }, body: `t=${token}` }));
    expect(ok.status).toBe(303);
  });
  it('POST /compose (signed in) with a chunked form over 128 KB -> 413 page, stream cancelled', async () => {
    const a = await register('capwriter', 'human', 24 * 30);
    const link = await api('/v1/auth/login-link', { key: a.key, method: 'POST' });
    const token = new URL(link.body.url).searchParams.get('t')!;
    const login = await fetchWorker(new Request(`${ORIGIN}/login`, { method: 'POST', redirect: 'manual', headers: { ...SAME, 'content-type': 'application/x-www-form-urlencoded' }, body: `t=${token}` }));
    const cookie = `__Host-cw_session=${login.headers.get('set-cookie')!.match(/^__Host-cw_session=([^;]*)/)![1]}`;
    const s = endless(8192, 'x');
    const r = await fetchWorker(chunkedPost('/compose', s.stream, { ...SAME, cookie, 'content-type': 'application/x-www-form-urlencoded' }));
    expect(r.status).toBe(413);
    // across the worker boundary the body is piped, so allow some buffering; an unbounded read would never finish
    expect(s.pulled()).toBeLessThan(FORM_MAX_BYTES + 256 * 1024);
  });
});

describe('recovery domain check: response body capped while streaming (P4)', () => {
  function mockWellKnown(make: () => Response) {
    vi.spyOn(globalThis, 'fetch').mockImplementation((async (input: RequestInfo | URL) => {
      const u = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (u.startsWith('https://cloudflare-dns.com/')) return new Response('{"Status":0}', { headers: { 'content-type': 'application/dns-json' } });
      if (u.endsWith('/.well-known/commonworld-proof.txt')) return make();
      return new Response('not found', { status: 404 });
    }) as typeof fetch);
  }

  it('an endless .well-known body is cut at MAX_TEXT and cancelled; a code past the cap is not seen', async () => {
    const code = 'cw-citizen-1-abcdefghjk';
    const s = endless(16 * 1024, 'z');
    let sent = 0;
    // MAX_TEXT bytes of filler, then the code, then endless filler
    const filler = s.stream.getReader();
    const body = new ReadableStream<Uint8Array>({
      async pull(c) {
        if (sent >= MAX_TEXT && sent < MAX_TEXT + 1) { c.enqueue(new TextEncoder().encode(code)); sent += 1; return; }
        const { value } = await filler.read();
        sent += value!.byteLength; c.enqueue(value!);
      },
      cancel() { filler.cancel(); },
    });
    mockWellKnown(() => new Response(body));
    const res = await findProof('domain', 'big.example', code);
    expect(res.ok).toBe(false);
    expect(s.cancelled()).toBe(true);
    expect(s.pulled()).toBeLessThanOrEqual(MAX_TEXT + 2 * 16 * 1024);
  });

  it('an oversized .well-known body is refused as a whole, even with the code BEFORE the cap', async () => {
    const code = 'cw-citizen-3-abcdefghjk';
    const s = endless(16 * 1024, 'z');
    let first = true;
    const filler = s.stream.getReader();
    // the code first, then endless filler: the code is inside the first MAX_TEXT bytes, but the body passes the cap
    const body = new ReadableStream<Uint8Array>({
      async pull(c) {
        if (first) { first = false; c.enqueue(new TextEncoder().encode(`proof: ${code}\n`)); return; }
        const { value } = await filler.read();
        c.enqueue(value!);
      },
      cancel() { filler.cancel(); },
    });
    mockWellKnown(() => new Response(body));
    const res = await findProof('domain', 'early.example', code);
    expect(res.ok).toBe(false);
    expect(s.cancelled()).toBe(true);
    expect(s.pulled()).toBeLessThanOrEqual(MAX_TEXT + 2 * 16 * 1024);
  });

  it('a body of exactly MAX_TEXT bytes is still read', async () => {
    const code = 'cw-citizen-4-abcdefghjk';
    const text = `proof: ${code}\n`;
    mockWellKnown(() => new Response(text + 'z'.repeat(MAX_TEXT - text.length)));
    const res = await findProof('domain', 'exact.example', code);
    expect(res).toMatchObject({ ok: true, method: 'well-known' });
  });

  it('a code inside the cap is still found', async () => {
    const code = 'cw-citizen-2-abcdefghjk';
    mockWellKnown(() => new Response(`proof: ${code}\n`));
    const res = await findProof('domain', 'small.example', code);
    expect(res).toMatchObject({ ok: true, method: 'well-known' });
  });
});
