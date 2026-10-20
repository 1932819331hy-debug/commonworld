import type { Env } from './env';
import type { Settings } from './settings';
import { accountAgeHours, isTrustedAccount, type Principal } from './auth';
import { HttpError } from './http';
import { karmaOf } from './stats';

export type WriteKind = 'post' | 'comment' | 'vote' | 'porch';
export const WRITE_KINDS: WriteKind[] = ['post', 'comment', 'vote', 'porch'];

interface OverrideRow {
  daily_post: number | null; daily_comment: number | null; daily_vote: number | null; daily_porch: number | null;
  rate_per_minute: number | null; note: string | null;
}

export interface EffectiveLimits {
  daily: Record<WriteKind, number | null>;
  rate_per_minute: number;
  shield_applied: boolean;
  brake_applied: boolean;
  has_override: boolean;
}

const utcDay = () => new Date().toISOString().slice(0, 10);

export async function effectiveLimits(env: Env, settings: Settings, principal: Principal): Promise<EffectiveLimits> {
  const override = await env.DB.prepare('SELECT * FROM account_limits WHERE account_id = ?').bind(principal.account.id).first<OverrideRow>();
  const trusted = isTrustedAccount(principal);
  const shield = settings['mode.shield'];
  const young = accountAgeHours(principal.account) < shield.young_account_hours;
  const shieldOn = shield.enabled && young && !trusted;
  const halve = (value: number | null) => (value === null || value === 0 ? value : Math.max(1, Math.floor(value * shield.factor)));
  let shieldApplied = false;
  const daily = {} as Record<WriteKind, number | null>;
  for (const kind of WRITE_KINDS) {
    const own = override?.[`daily_${kind}` as keyof OverrideRow] as number | null | undefined;
    if (own !== null && own !== undefined) { daily[kind] = own; continue; }
    const base = settings[`limits.daily.${kind}` as const];
    daily[kind] = shieldOn ? halve(base) : base;
    if (shieldOn && base !== null) shieldApplied = true;
  }
  let rate = override?.rate_per_minute ?? null;
  if (rate === null) {
    rate = settings['limits.rate_per_minute'];
    if (shieldOn) { rate = halve(rate) as number; shieldApplied = true; }
  }
  let brakeApplied = false;
  const brake = settings['mode.brake'];
  if (brake.enabled && !trusted && rate > brake.rate_per_minute) {
    const karma = await karmaOf(env, settings, principal.account.id);
    if (karma < brake.trusted_karma_min) { rate = brake.rate_per_minute; brakeApplied = true; }
  }
  return { daily, rate_per_minute: rate, shield_applied: shieldApplied, brake_applied: brakeApplied, has_override: !!override };
}

/** Fixed window counter. Throws 429 when the bucket is full. */
export async function enforceRate(env: Env, bucket: string, limit: number, windowMs: number, scope: string): Promise<void> {
  await enforceCount(env, bucket, 1, limit, windowMs, scope);
}

/** Fixed window counter that adds `n` at once (all or nothing). Throws 429 when `n` more would exceed `limit`. */
export async function enforceCount(env: Env, bucket: string, n: number, limit: number, windowMs: number, scope: string): Promise<void> {
  const now = Date.now();
  const windowStart = Math.floor(now / windowMs) * windowMs;
  const result = await env.DB.prepare(
    `INSERT INTO rate_windows (bucket, window_start, count) SELECT ?1, ?2, ?4 WHERE ?4 <= ?3
     ON CONFLICT(bucket, window_start) DO UPDATE SET count = count + ?4 WHERE count + ?4 <= ?3`,
  ).bind(bucket, windowStart, limit, n).run();
  if (!result.meta.changes || limit < 1) {
    const retry = Math.max(1, Math.ceil((windowStart + windowMs - now) / 1000));
    throw new HttpError(429, 'rate_limit_exceeded', { scope, limit, window_seconds: windowMs / 1000, retry_after_seconds: retry }, { 'retry-after': String(retry) });
  }
}

/** Buckets whose window is a whole day; they are kept 2 days instead of 2 hours. */
export const DAY_BUCKET_PREFIX = 'day:';

export async function pruneRateWindows(env: Env): Promise<void> {
  const now = Date.now();
  await env.DB.prepare(`DELETE FROM rate_windows WHERE (window_start < ?1 AND bucket NOT LIKE 'day:%')
    OR window_start < ?2`).bind(now - 2 * 3_600_000, now - 2 * 86_400_000).run();
}

/**
 * Client network for per-IP limits: IPv4 = the full address (/32); IPv6 = its /64 prefix, because one subscriber
 * usually gets a whole /64 and can rotate addresses inside it freely. IPv4-mapped IPv6 counts as IPv4.
 */
export function clientNetwork(ip: string): string {
  const raw = ip.trim().toLowerCase();
  const mapped = /^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/.exec(raw);
  if (mapped) return mapped[1];
  if (!raw.includes(':')) return raw;
  const addr = raw.split('%')[0];
  const [head, tail] = addr.includes('::') ? addr.split('::', 2) : [addr, null];
  const h = head ? head.split(':') : [];
  const t = tail === null ? [] : tail ? tail.split(':') : [];
  const groups = tail === null ? h : [...h, ...Array(Math.max(0, 8 - h.length - t.length)).fill('0'), ...t];
  return `${groups.slice(0, 4).map((g) => (parseInt(g || '0', 16) || 0).toString(16)).join(':')}::/64`;
}

/**
 * Atomically reserves one unit of today's quota. Returns a release function
 * to undo the reservation if the write that follows fails or is a no-op.
 */
export async function reserveDaily(env: Env, accountId: string, kind: WriteKind, limit: number | null): Promise<() => Promise<void>> {
  const day = utcDay();
  if (limit !== null && limit < 1) throw dailyLimitError(kind, limit);
  const cap = limit ?? Number.MAX_SAFE_INTEGER;
  const result = await env.DB.prepare(
    `INSERT INTO daily_usage (account_id, day, kind, count) VALUES (?1, ?2, ?3, 1)
     ON CONFLICT(account_id, day, kind) DO UPDATE SET count = count + 1 WHERE count < ?4`,
  ).bind(accountId, day, kind, cap).run();
  if (!result.meta.changes) throw dailyLimitError(kind, limit ?? 0);
  return async () => {
    await env.DB.prepare('UPDATE daily_usage SET count = count - 1 WHERE account_id = ? AND day = ? AND kind = ? AND count > 0').bind(accountId, day, kind).run();
  };
}

/**
 * One unit of a per-account UTC-day cap kept in `rate_windows` (bucket `day:<name>:<account>`), for caps that are not
 * one of the WRITE_KINDS (withdrawals). Over the cap: 429 daily_limit_exceeded with `kind`. Returns a release function.
 */
export async function reserveDayBucket(env: Env, name: string, accountId: string, limit: number | null): Promise<() => Promise<void>> {
  if (limit === null) return async () => {};
  const bucket = `${DAY_BUCKET_PREFIX}${name}:${accountId}`;
  const windowStart = Math.floor(Date.now() / 86_400_000) * 86_400_000;
  const result = limit < 1 ? null : await env.DB.prepare(
    `INSERT INTO rate_windows (bucket, window_start, count) VALUES (?1, ?2, 1)
     ON CONFLICT(bucket, window_start) DO UPDATE SET count = count + 1 WHERE count < ?3`,
  ).bind(bucket, windowStart, limit).run();
  if (!result?.meta.changes) throw dailyLimitError(name, limit);
  return async () => {
    await env.DB.prepare('UPDATE rate_windows SET count = count - 1 WHERE bucket = ? AND window_start = ? AND count > 0').bind(bucket, windowStart).run();
  };
}

function dailyLimitError(kind: string, limit: number): HttpError {
  const resetAt = `${utcDay()}T23:59:59.999Z`;
  return new HttpError(429, 'daily_limit_exceeded', { kind, limit, resets_at: resetAt });
}

export async function usageToday(env: Env, accountId: string): Promise<Record<WriteKind, number>> {
  const { results } = await env.DB.prepare('SELECT kind, count FROM daily_usage WHERE account_id = ? AND day = ?').bind(accountId, utcDay()).all<{ kind: WriteKind; count: number }>();
  const usage = { post: 0, comment: 0, vote: 0, porch: 0 };
  for (const row of results) usage[row.kind] = row.count;
  return usage;
}

/** Write gate: frozen accounts and (in Lock mode) young untrusted accounts cannot write. */
export function assertCanWrite(settings: Settings, principal: Principal): void {
  if (principal.account.status === 'frozen') throw new HttpError(403, 'account_frozen');
  if (principal.account.status !== 'active') throw new HttpError(403, 'account_disabled');
  const lock = settings['mode.lock'];
  if (lock.enabled && !isTrustedAccount(principal) && accountAgeHours(principal.account) < lock.min_account_age_hours) {
    throw new HttpError(403, 'platform_locked', { min_account_age_hours: lock.min_account_age_hours });
  }
}
