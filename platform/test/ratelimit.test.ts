/** Per-minute limits on the Rate Limiting binding (src/ratelimit.ts): tiers, the binding contract, no D1 writes. */
import { env } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { RATE_TIERS, enforceMinuteRate, tierFor } from '../src/ratelimit';
import { api, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

describe('rate limiting binding', () => {
  it('a limit is enforced on the largest tier <= limit (never rounded up)', () => {
    expect(tierFor(120)).toBe(120);
    expect(tierFor(99)).toBe(60);
    expect(tierFor(3)).toBe(3);
    expect(tierFor(0)).toBe(0);
    expect(tierFor(100_000)).toBe(6000);
  });

  it('uses the RL_<tier> binding when the double is off; 429 with scope, tier and retry-after', async () => {
    const calls: string[] = [];
    let allow = true;
    const fake = { limit: async ({ key }: { key: string }) => { calls.push(key); return { success: allow }; } };
    const e = { RL_60: fake } as any;
    await enforceMinuteRate(e, 'acct:x', 99, 'account');
    allow = false;
    const err = await enforceMinuteRate(e, 'acct:x', 99, 'account').catch((x) => x);
    expect(calls).toEqual(['acct:x', 'acct:x']);
    expect(err.status).toBe(429);
    expect(err.code).toBe('rate_limit_exceeded');
    expect(err.extra).toMatchObject({ scope: 'account', limit: 60, window_seconds: 60 });
    expect(Number(err.headers['retry-after'])).toBeGreaterThanOrEqual(1);
    await expect(enforceMinuteRate({} as any, 'k', 120, 'account')).rejects.toThrow(/RL_120 missing/);
  });

  it('wrangler.toml declares every tier (local bindings exist in the test runtime)', async () => {
    for (const t of RATE_TIERS) expect(typeof (env as any)[`RL_${t}`]?.limit).toBe('function');
  });

  it('keyed API reads write nothing to D1 for rate limiting', async () => {
    await setSetting('limits.rate_per_minute', 3);
    const a = await register();
    const statuses: number[] = [];
    for (let i = 0; i < 5; i++) statuses.push((await api('/v1/feed?cursor=0', { key: a.key })).status);
    expect(statuses.filter((s) => s === 429).length).toBeGreaterThanOrEqual(1);
    const rows = await env.DB.prepare("SELECT COUNT(*) AS n FROM rate_windows WHERE bucket LIKE 'acct:%'").first<{ n: number }>();
    expect(rows!.n).toBe(0);
  });

  it('keyed /v1 responses carry RateLimit-* headers; a 429 says Remaining 0; anonymous reads carry none', async () => {
    await setSetting('limits.rate_per_minute', 3);
    const a = await register();
    const r1 = await api('/v1/me', { key: a.key });
    expect(r1.status).toBe(200);
    expect(r1.headers.get('ratelimit-limit')).toBe('3');
    expect(r1.headers.get('ratelimit-remaining')).toBe('2');
    const reset = Number(r1.headers.get('ratelimit-reset'));
    expect(reset).toBeGreaterThanOrEqual(1);
    expect(reset).toBeLessThanOrEqual(60);
    expect(r1.headers.get('ratelimit-policy')).toBe('3;w=60');
    const r2 = await api('/v1/posts/999999', { key: a.key }); // errors carry them too
    expect(r2.status).toBe(404);
    expect(r2.headers.get('ratelimit-remaining')).toBe('1');
    await api('/v1/me', { key: a.key });
    const over = await api('/v1/me', { key: a.key });
    expect(over.status).toBe(429);
    expect(over.headers.get('ratelimit-remaining')).toBe('0');
    expect(over.headers.get('ratelimit-limit')).toBe('3');
    expect(over.headers.get('retry-after')).toBeTruthy();
    const anon = await api('/v1/posts');
    expect(anon.headers.get('ratelimit-limit')).toBeNull();
  });

  it('OpenAPI documents the RateLimit-* headers on keyed operations', async () => {
    const doc = (await api('/openapi.json')).body;
    expect(Object.keys(doc.components.headers)).toEqual(expect.arrayContaining(['RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset']));
    expect(doc.paths['/v1/me'].get.responses['200'].headers['RateLimit-Remaining'].$ref).toBe('#/components/headers/RateLimit-Remaining');
  });
});
