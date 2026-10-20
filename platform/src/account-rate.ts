import type { Env } from './env';
import type { Principal } from './auth';
import { effectiveLimits } from './limits';
import { enforceMinuteRate, rateLimitHeaders } from './ratelimit';
import { getSettings } from './settings';

/**
 * Per-account minute limit for every keyed /v1 request AND every website write (src/pages/writes.ts), so a signed-in
 * citizen on the pages shares one window with their key. Rate Limiting binding (src/ratelimit.ts): no D1 write per
 * request. Returns the RateLimit-* headers (IETF draft names); throws 429 rate_limit_exceeded when over.
 */
export async function enforceAccountRate(env: Env, principal: Principal): Promise<Record<string, string>> {
  const settings = await getSettings(env);
  const limits = await effectiveLimits(env, settings, principal);
  return rateLimitHeaders(await enforceMinuteRate(env, `acct:${principal.account.id}`, limits.rate_per_minute, limits.brake_applied ? 'account_brake' : 'account'));
}
