import { afterEach, describe, expect, it, vi } from 'vitest';
import { handleLab, LAB_BEAT_EVENTS, parseBeat } from '../src/lab';

const env = (e: string) => ({ ENVIRONMENT: e, RATE_LIMIT_DOUBLE: '1' }) as any;
const post = (body: string) => handleLab(new Request('https://x/lab/beat', { method: 'POST', body }), env('staging'));
afterEach(() => vi.restoreAllMocks());

describe('staging lab (tab telemetry probe)', () => {
  it('is not served in production', async () => {
    expect(await handleLab(new Request('https://x/lab/tab-telemetry'), env('production'))).toBeNull();
  });
  it('serves a noindex page with a strict CSP and accepts beats on staging', async () => {
    const page = await handleLab(new Request('https://x/lab/tab-telemetry'), env('staging'));
    expect(page!.status).toBe(200);
    expect(page!.headers.get('x-robots-tag')).toContain('noindex');
    expect(page!.headers.get('content-security-policy')).toContain("script-src 'self'");
    const beat = await post('{"sid":"a","n":1,"ev":"load"}');
    expect(beat!.status).toBe(204);
  });
  it('leaves other paths alone', async () => {
    expect(await handleLab(new Request('https://x/atlas/'), env('staging'))).toBeNull();
  });
});

describe('POST /lab/beat: only validated beats are logged (audit 2026-10-19)', () => {
  it('every event name the probe script sends is on the allowlist', async () => {
    const script = await (await handleLab(new Request('https://x/lab/tab-telemetry.js'), env('staging')))!.text();
    const sent = new Set<string>();
    for (const m of script.matchAll(/beat\('([a-z]+)'\)/g)) sent.add(m[1]);
    for (const m of script.matchAll(/\[([^\]]+)\]\)/g)) for (const e of m[1].matchAll(/'([a-z]+)'/g)) sent.add(e[1]);
    expect(sent.size).toBeGreaterThan(10);
    expect([...sent].sort()).toEqual([...LAB_BEAT_EVENTS].sort());
  });

  it('a valid beat -> 204 and one log line with exactly the validated fields', async () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const r = await post('{"sid":"k3j9x0ab","n":7,"ev":"visibilitychange","vis":"hidden","focus":false,"t":1760870400000,"extra":"ignored"}');
    expect(r!.status).toBe(204);
    expect(log).toHaveBeenCalledTimes(1);
    const line = JSON.parse(String(log.mock.calls[0][0]));
    expect(line).toMatchObject({ lab: 'tab-telemetry', sid: 'k3j9x0ab', n: 7, ev: 'visibilitychange', vis: 'hidden', focus: false, client_t: 1760870400000 });
    expect(Object.keys(line).sort()).toEqual(['client_t', 'ev', 'focus', 'lab', 'n', 'server_t', 'sid', 'vis']);
    expect(String(log.mock.calls[0][0])).not.toContain('ignored');
  });

  it('an unknown event -> 400 invalid_beat, nothing logged', async () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const r = await post('{"sid":"abc","n":1,"ev":"exfiltrate"}');
    expect(r!.status).toBe(400);
    expect(((await r!.json()) as any).error.code).toBe('invalid_beat');
    expect(log).not.toHaveBeenCalled();
  });

  it('a URL or query string in any field is never logged', async () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const bodies = [
      '{"sid":"https://evil.example/?token=SECRET","n":1,"ev":"load"}',
      '{"sid":"abc","n":1,"ev":"load?token=SECRET"}',
      '{"sid":"abc","n":1,"ev":"load","vis":"visible?token=SECRET"}',
      '{"sid":"abc","n":"1?token=SECRET","ev":"load"}',
      '{"sid":"abc","n":1,"ev":"load","t":"?token=SECRET"}',
    ];
    for (const b of bodies) expect((await post(b))!.status, b).toBe(400);
    expect(log).not.toHaveBeenCalled();
    // an unknown extra key carrying a URL is ignored: the beat is logged without it
    expect((await post('{"sid":"abc","n":1,"ev":"load","href":"https://x/?token=SECRET"}'))!.status).toBe(204);
    expect(log).toHaveBeenCalledTimes(1);
    expect(String(log.mock.calls[0][0])).not.toContain('token');
    expect(String(log.mock.calls[0][0])).not.toContain('?');
  });

  it('the whole body is parsed, never cut at 400 bytes (review round 3)', async () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    // valid JSON padded to 400 bytes, then junk: before, the cut at 400 made it a valid beat
    const padded = '{"sid":"abc","n":1,"ev":"load"}'.padEnd(400, ' ') + 'INVALID!';
    expect(new TextEncoder().encode(padded).length).toBe(408);
    expect((await post(padded))!.status).toBe(400);
    expect(log).not.toHaveBeenCalled();
    // a fully valid 471-byte beat with an unknown field: accepted, the field is dropped and nothing raw is logged
    const head = '{"sid":"abc","n":7,"ev":"load","extra":"';
    const long = head + 'Z'.repeat(471 - head.length - 2) + '"}';
    expect(new TextEncoder().encode(long).length).toBe(471);
    expect((await post(long))!.status).toBe(204);
    expect(log).toHaveBeenCalledTimes(1);
    const line = String(log.mock.calls[0][0]);
    expect(line).not.toContain('extra');
    expect(line).not.toContain('ZZZ');
    const { server_t, ...rest } = JSON.parse(line);
    expect(typeof server_t).toBe('number');
    expect(rest).toEqual({ lab: 'tab-telemetry', sid: 'abc', n: 7, ev: 'load', vis: null, focus: null, client_t: null });
  });

  it('wrong types and shapes are refused', () => {
    for (const raw of ['', 'not json', '[]', 'null', '{}', '{"sid":"","n":1,"ev":"load"}', '{"sid":"ABC","n":1,"ev":"load"}',
      `{"sid":"${'a'.repeat(17)}","n":1,"ev":"load"}`, '{"sid":"abc","n":1.5,"ev":"load"}', '{"sid":"abc","n":-1,"ev":"load"}',
      '{"sid":"abc","n":2000000,"ev":"load"}', '{"sid":"abc","n":1,"ev":"load","focus":"yes"}', '{"sid":"abc","n":1,"ev":"load","vis":"weird"}',
      '{"sid":"abc","n":1,"ev":"load","t":1e20}', '{"sid":123,"n":1,"ev":"load"}']) {
      expect(parseBeat(raw), raw).toBeNull();
    }
    expect(parseBeat('{"sid":"abc","n":0,"ev":"tick"}')).toEqual({ sid: 'abc', n: 0, ev: 'tick', vis: null, focus: null, client_t: null });
  });
});
