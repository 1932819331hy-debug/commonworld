import { createExecutionContext, createScheduledController, waitOnExecutionContext } from 'cloudflare:test';
import { env } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker from '../src/index';
import { CLEANUP_CRON, HOURLY_CRON } from '../src/retention';
import { pruneTrustChecks, runTrustCheck, TRUST_DOMAINS, trustDomains } from '../src/trust';
import { GSB_ENDPOINT } from '../src/trust-engine/sources/google-safe-browsing.ts';
import { certPolska, metamask, scamsniffer } from '../src/trust-engine/index.ts';
import type { FetchLike } from '../src/trust-engine/index.ts';
import { api, resetDb } from './helpers';

beforeEach(resetDb);
afterEach(() => vi.restoreAllMocks());

const gsb = (code: number, se = false) => `)]}'\n[["sb.ssr",${code},false,false,${se},false,false,1792259421202,"x",false]]`;
type Route = string | number | ((u: string) => string | number);

function mockFetch(over: Record<string, Route> = {}): { f: FetchLike; calls: string[] } {
  const routes: Record<string, Route> = {
    [metamask.url]: JSON.stringify({ version: 2, fuzzylist: ['commonworld.one'], whitelist: [], blacklist: ['drainer.example'] }),
    [scamsniffer.url]: JSON.stringify(['scam.example']),
    [certPolska.url]: 'phish.example\n',
    ...over,
  };
  const calls: string[] = [];
  const f: FetchLike = async (u) => {
    calls.push(u);
    let r: Route | undefined = routes[u];
    if (r === undefined && u.startsWith(GSB_ENDPOINT)) r = routes[GSB_ENDPOINT] ?? gsb(1);
    if (typeof r === 'function') r = r(u);
    if (r === undefined) r = 404;
    const status = typeof r === 'number' ? r : 200;
    return { ok: status < 300, status, text: async () => (typeof r === 'string' ? r : '') };
  };
  return { f, calls };
}
const fast = (f: FetchLike) => ({ fetch: f, sleep: async () => {} });
const T0 = Date.parse('2026-10-17T21:07:00Z');

describe('own-domain trust check (src/trust.ts)', () => {
  it('checks our three domains by default', () => {
    expect(TRUST_DOMAINS).toEqual(['commonworld.one', 'www.commonworld.one', 'staging.commonworld.one']);
    expect(trustDomains({ ...env, TRUST_DOMAINS: ' a.example, B.example ' } as any)).toEqual(['a.example', 'b.example']);
  });

  it('status before the first run: last_run_at null, no_data, cacheable 60 s', async () => {
    const r = await api('/v1/trust/status');
    expect(r.status).toBe(200);
    expect(r.body.last_run_at).toBeNull();
    expect(r.body.status).toBe('no_data');
    expect(r.body.domains).toEqual([]);
    expect(r.body.cadence).toBe('hourly');
    expect(r.body.standard).toBe('https://github.com/commonworld-one/commonworld/blob/main/TRUST.md');
    expect(r.body.sources.map((s: any) => s.id)).toEqual(['google_safe_browsing', 'metamask_phishing_detect', 'scamsniffer', 'cert_polska']);
    expect(r.headers.get('cache-control')).toBe('public, max-age=0, s-maxage=60');
    expect(r.headers.get('access-control-allow-origin')).toBe('*');
  });

  it('a run stores one row per domain with every source\'s answer; any single flag = flagged; www is folded', async () => {
    const { f, calls } = mockFetch({ [GSB_ENDPOINT]: (u) => (u.endsWith('=commonworld.one') ? gsb(3, true) : gsb(6)) });
    const res = await runTrustCheck(env as any, T0, fast(f));
    expect(res).toEqual({ run_at: '2026-10-17T21:07:00Z', domains: 3, flagged: ['commonworld.one', 'www.commonworld.one'], source_errors: 0 });
    expect(calls.filter((u) => u.startsWith(GSB_ENDPOINT)).sort(), 'www.commonworld.one is checked as commonworld.one (one lookup)')
      .toEqual([GSB_ENDPOINT + 'commonworld.one', GSB_ENDPOINT + 'staging.commonworld.one']);
    const r = await api('/v1/trust/status');
    expect(r.body.last_run_at).toBe('2026-10-17T21:07:00Z');
    expect(r.body.status).toBe('flagged');
    const by = Object.fromEntries(r.body.domains.map((d: any) => [d.domain, d]));
    expect(Object.keys(by).sort()).toEqual(['commonworld.one', 'staging.commonworld.one', 'www.commonworld.one']);
    expect(by['www.commonworld.one'].checked_as).toBe('commonworld.one');
    expect(by['commonworld.one'].status).toBe('flagged');
    const g = by['commonworld.one'].sources.find((s: any) => s.name === 'google_safe_browsing');
    expect(g).toMatchObject({ verdict: 'flagged', detail: 'social_engineering', evidence_url: 'https://transparencyreport.google.com/safe-browsing/search?url=commonworld.one' });
    expect(g.data).toBeUndefined();
    expect(by['commonworld.one'].sources.find((s: any) => s.name === 'metamask_phishing_detect').verdict).toBe('clean'); // fuzzylist never flags
    expect(by['staging.commonworld.one'].status).toBe('clean'); // Safe Browsing has no data, the lists answered
    for (const d of r.body.domains) {
      expect(d.sources).toHaveLength(4);
      for (const s of d.sources) { expect(['clean', 'flagged', 'no_data']).toContain(s.verdict); expect(s.evidence_url).toMatch(/^https:\/\//); expect(s.checked_at).toMatch(/Z$/); }
    }
  });

  it('a blocklist hit flags the domain; recent_runs lists runs newest first', async () => {
    await runTrustCheck(env as any, T0, fast(mockFetch().f));
    await runTrustCheck(env as any, T0 + 3600_000, fast(mockFetch({ [scamsniffer.url]: JSON.stringify(['staging.commonworld.one']) }).f));
    const r = await api('/v1/trust/status');
    expect(r.body.last_run_at).toBe('2026-10-17T22:07:00Z');
    expect(r.body.domains.find((d: any) => d.domain === 'staging.commonworld.one').sources.find((s: any) => s.name === 'scamsniffer'))
      .toMatchObject({ verdict: 'flagged', detail: 'listed as staging.commonworld.one' });
    expect(r.body.recent_runs).toEqual([
      { run_at: '2026-10-17T22:07:00Z', status: 'flagged', flagged: ['staging.commonworld.one'] },
      { run_at: '2026-10-17T21:07:00Z', status: 'clean', flagged: [] },
    ]);
  });

  it('a failed source is no_data with its error and never takes the run down; all sources down = no_data', async () => {
    const res = await runTrustCheck(env as any, T0, fast(mockFetch({ [scamsniffer.url]: 503, [certPolska.url]: 500 }).f));
    expect(res.flagged).toEqual([]);
    expect(res.source_errors).toBe(4);
    let r = await api('/v1/trust/status');
    const ss = r.body.domains[0].sources.find((s: any) => s.name === 'scamsniffer');
    expect(ss).toMatchObject({ verdict: 'no_data', error: 'HTTP 503' });
    expect(r.body.status).toBe('clean');
    await runTrustCheck(env as any, T0 + 1000, fast(mockFetch({ [metamask.url]: 503, [scamsniffer.url]: 503, [certPolska.url]: 503, [GSB_ENDPOINT]: 503 }).f));
    r = await api('/v1/trust/status');
    expect(r.body.status).toBe('no_data');
    expect(r.body.domains.every((d: any) => d.status === 'no_data' && d.sources.every((s: any) => s.error))).toBe(true);
  });

  it('the hourly cron runs the check (outbound fetch mocked) and the nightly cron prunes rows older than 90 days', async () => {
    const { f } = mockFetch();
    vi.spyOn(globalThis, 'fetch').mockImplementation((async (input: RequestInfo | URL) => {
      const r = await f(String(input instanceof Request ? input.url : input));
      return new Response(await r.text(), { status: r.status });
    }) as any);
    const ctx = createExecutionContext();
    await worker.scheduled!(createScheduledController({ scheduledTime: T0, cron: HOURLY_CRON }), env as any, ctx);
    await waitOnExecutionContext(ctx);
    const rows = await env.DB.prepare('SELECT domain, status FROM trust_checks ORDER BY domain').all<{ domain: string; status: string }>();
    expect(rows.results).toEqual([
      { domain: 'commonworld.one', status: 'clean' }, { domain: 'staging.commonworld.one', status: 'clean' }, { domain: 'www.commonworld.one', status: 'clean' }]);
    await env.DB.prepare("INSERT INTO trust_checks (run_at, domain, checked_as, status, sources) VALUES ('2026-07-01T00:07:00Z', 'commonworld.one', 'commonworld.one', 'clean', '[]')").run();
    expect(await pruneTrustChecks(env as any, T0)).toBe(1);
    const ctx2 = createExecutionContext();
    await worker.scheduled!(createScheduledController({ scheduledTime: T0, cron: CLEANUP_CRON }), env as any, ctx2);
    await waitOnExecutionContext(ctx2);
    expect((await env.DB.prepare('SELECT COUNT(*) AS n FROM trust_checks').first<{ n: number }>())!.n).toBe(3);
  });
});

describe('vendored trust engine (src/trust-engine/)', () => {
  const files = (import.meta as any).glob('../src/trust-engine/**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
  it('every file is a vendored copy with its header (re-vendor with scripts/vendor-trust.sh, never edit here)', () => {
    expect(Object.keys(files).length).toBe(8);
    for (const [p, src] of Object.entries(files)) expect(src.split('\n')[0], p).toMatch(/^\/\/ Vendored from commonworld-one\/commonworld trust\/src\/\S+ @ [0-9a-f]{7,} \(scripts\/vendor-trust\.sh\)/);
  });
});
