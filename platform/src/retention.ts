import type { Env } from './env';
import { pruneRateWindows } from './limits';

/** Daily write counters (`daily_usage`) and `Idempotency-Key` records are kept this many days, then deleted. */
export const RETENTION_DAYS = 30;

/** Nightly Cron Trigger schedule (UTC), same as `[triggers] crons` in wrangler.toml. */
export const CLEANUP_CRON = '17 3 * * *';
/** Hourly Cron Trigger: karma_7d window expiry + stored ranks (src/counters.ts refreshWindows). Also in wrangler.toml. */
export const HOURLY_CRON = '7 * * * *';

export interface CleanupResult { daily_usage: number; idempotency_keys: number; login_links: number; sessions: number }

/**
 * Deletes service records older than RETENTION_DAYS relative to `now`:
 *   daily_usage       rows whose UTC `day` (YYYY-MM-DD) is before the cutoff day
 *   idempotency_keys  rows whose `created_at` (ISO 8601 UTC) is before the cutoff instant
 *   login_links       rows past their 10-minute `expires_at` (used or not)
 *   sessions          rows past their sliding `expires_at` (30 days without a visit)
 * Also prunes old hashed-IP / per-key rate windows (normally done on ~1% of requests).
 */
export async function pruneOldRecords(env: Env, now: number = Date.now()): Promise<CleanupResult> {
  const cutoff = new Date(now - RETENTION_DAYS * 86_400_000);
  const cutoffIso = cutoff.toISOString();
  const cutoffDay = cutoffIso.slice(0, 10);
  const nowIso = new Date(now).toISOString();
  const [usage, idem, links, sessions] = await env.DB.batch([
    env.DB.prepare('DELETE FROM daily_usage WHERE day < ?').bind(cutoffDay),
    env.DB.prepare('DELETE FROM idempotency_keys WHERE created_at < ?').bind(cutoffIso),
    env.DB.prepare('DELETE FROM login_links WHERE expires_at < ?').bind(nowIso),
    env.DB.prepare('DELETE FROM sessions WHERE expires_at < ?').bind(nowIso),
  ]);
  await pruneRateWindows(env);
  return { daily_usage: usage.meta.changes ?? 0, idempotency_keys: idem.meta.changes ?? 0, login_links: links.meta.changes ?? 0, sessions: sessions.meta.changes ?? 0 };
}
