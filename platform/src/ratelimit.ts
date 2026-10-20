/**
 * Per-minute rate limits on the Cloudflare Workers Rate Limiting binding (wrangler.toml `ratelimits`), so the hot path
 * (every keyed API request, CSP reports) writes nothing to D1. Hourly/daily caps that are product rules
 * (sign-ups per IP per hour, sign-ups per day, login links per hour, new tags per day, daily write quotas) stay in D1.
 *
 * A binding has a fixed limit, while ours come from settings, overrides, Shield and Brake. So there is one binding per
 * tier of RATE_TIERS (60 s period, own namespace_id per environment) and a limit L is enforced on the largest tier <= L
 * (rounded down, never up). The binding counts per Cloudflare location and is eventually consistent (permissive by a
 * few requests under bursts) — fine for an abuse guard; exact quotas are the D1 daily counters.
 *
 * Tests (and any env with RATE_LIMIT_DOUBLE = "1") use an in-memory fixed-window double with the same contract.
 */
import type { Env } from './env';
import { HttpError } from './http';

export const RATE_TIERS = [1, 2, 3, 5, 10, 20, 30, 60, 120, 240, 600, 1200, 6000] as const;
export type RateTier = typeof RATE_TIERS[number];
export const tierBinding = (tier: RateTier) => `RL_${tier}` as const;

/** Largest tier <= limit (limits below 1 block everything). */
export function tierFor(limit: number): RateTier | 0 {
  let out: RateTier | 0 = 0;
  for (const t of RATE_TIERS) if (t <= limit) out = t;
  return out;
}

export interface RateLimiter { limit(options: { key: string }): Promise<{ success: boolean }> }

// ---- test double: fixed 60 s windows in this isolate
const windows = new Map<string, { start: number; count: number }>();
export const resetRateLimitDouble = (): void => { windows.clear(); seen.clear(); };
function doubleFor(tier: RateTier): RateLimiter {
  return {
    async limit({ key }) {
      const now = Date.now(), start = Math.floor(now / 60_000) * 60_000, id = `${tier}|${key}`;
      const w = windows.get(id);
      if (!w || w.start !== start) { windows.set(id, { start, count: 1 }); return { success: true }; }
      if (w.count >= tier) return { success: false };
      w.count += 1;
      return { success: true };
    },
  };
}

function limiter(env: Env, tier: RateTier): RateLimiter {
  if (env.RATE_LIMIT_DOUBLE === '1') return doubleFor(tier);
  const binding = (env as unknown as Record<string, RateLimiter | undefined>)[tierBinding(tier)];
  if (!binding || typeof binding.limit !== 'function') throw new Error(`rate limit binding ${tierBinding(tier)} missing (wrangler.toml ratelimits)`);
  return binding;
}

/**
 * What a client may know about its current window, sent on every keyed /v1 response as the IETF draft headers
 * (draft-ietf-httpapi-ratelimit-headers): RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset (seconds) and
 * RateLimit-Policy ("<limit>;w=60").
 *
 * The binding only answers allowed/refused, so Remaining is an estimate from a count kept in this isolate for the
 * same key and minute (the double's own count in tests). Requests served by other isolates or locations are not in
 * it, so the real remaining can be lower; a 429 always carries Remaining 0 and Retry-After. Reset = seconds to the
 * end of the current minute window.
 */
export interface RateInfo { limit: number; remaining: number; reset: number }

const seen = new Map<string, { start: number; count: number }>();
function localCount(key: string, start: number): number {
  const w = seen.get(key);
  if (!w || w.start !== start) {
    if (seen.size > 5000) seen.clear(); // bounded: one entry per active key per isolate
    seen.set(key, { start, count: 1 });
    return 1;
  }
  w.count += 1;
  return w.count;
}

export function rateLimitHeaders(info: RateInfo): Record<string, string> {
  return {
    'ratelimit-limit': String(info.limit),
    'ratelimit-remaining': String(Math.max(0, info.remaining)),
    'ratelimit-reset': String(info.reset),
    'ratelimit-policy': `${info.limit};w=60`,
  };
}

/** Throws 429 rate_limit_exceeded when `key` is over `limit` requests in the current minute. No D1 access. */
export async function enforceMinuteRate(env: Env, key: string, limit: number, scope: string): Promise<RateInfo> {
  const tier = tierFor(limit);
  const ok = tier > 0 && (await limiter(env, tier as RateTier).limit({ key })).success;
  const now = Date.now();
  const reset = Math.max(1, Math.ceil((60_000 - (now % 60_000)) / 1000));
  if (!ok) {
    const info: RateInfo = { limit: tier || limit, remaining: 0, reset };
    throw new HttpError(429, 'rate_limit_exceeded', { scope, limit: tier || limit, window_seconds: 60, retry_after_seconds: reset }, { 'retry-after': String(reset), ...rateLimitHeaders(info) });
  }
  const used = localCount(`${tier}|${key}`, Math.floor(now / 60_000) * 60_000);
  return { limit: tier, remaining: tier - used, reset };
}
