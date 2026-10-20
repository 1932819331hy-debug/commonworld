/**
 * Hourly trust check of our own domains through the Commonworld trust engine (vendored in src/trust-engine/, standard:
 * https://github.com/commonworld-one/commonworld/blob/main/TRUST.md).
 *
 *   runTrustCheck(env, now)   HOURLY_CRON: checks TRUST_DOMAINS against every default source (Google Safe Browsing,
 *                             MetaMask eth-phishing-detect, ScamSniffer, CERT Polska) and stores one row per domain in
 *                             trust_checks (migration 0015). Never throws into the cron.
 *   GET /v1/trust/status      public: latest result per domain with every source's answer, last_run_at, recent runs.
 *
 * No GitHub token lives here: alerts and the heartbeat are a GitHub Action in the public repo that reads this endpoint
 * (.github/workflows/trust-own-domains.yml) and fails when last_run_at is older than 2 hours.
 */
import type { Ctx } from './context';
import type { Env } from './env';
import { cappedFetchLike } from './capped-fetch';
import { json } from './http';
import { checkDomains, DEFAULT_SOURCES, ENGINE, ENGINE_VERSION, normalizeDomain, type CheckContext, type FetchLike, type SourceResult, type Verdict } from './trust-engine/index.ts';

export const TRUST_DOMAINS = ['commonworld.one', 'www.commonworld.one', 'staging.commonworld.one'];
export const TRUST_STANDARD_URL = 'https://github.com/commonworld-one/commonworld/blob/main/TRUST.md';
export const TRUST_RETENTION_DAYS = 90;
const HISTORY_RUNS = 24;

/** Configured domains: env TRUST_DOMAINS (comma separated) or the default list. */
export function trustDomains(env: Env): string[] {
  const raw = (env.TRUST_DOMAINS ?? '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  return raw.length ? raw : TRUST_DOMAINS;
}

export interface TrustRunResult { run_at: string; domains: number; flagged: string[]; source_errors: number }

/** Default fetch for the hourly check: every source body read under its size cap (src/capped-fetch.ts). */
const cappedGlobalFetch = cappedFetchLike((u, init) => globalThis.fetch(u, init as RequestInit));

export async function runTrustCheck(env: Env, now: number = Date.now(), ctx: Partial<CheckContext> = {}): Promise<TrustRunResult> {
  const configured = trustDomains(env);
  const report = await checkDomains(configured, { sources: DEFAULT_SOURCES, ctx: { timeoutMs: 15000, retries: 2, fetch: cappedGlobalFetch, ...ctx } });
  const runAt = new Date(now).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const stmts = [];
  const flagged: string[] = [];
  for (const d of configured) {
    const as = normalizeDomain(d);
    const r = report.results[as];
    const status: Verdict = r?.status ?? 'no_data';
    if (status === 'flagged') flagged.push(d);
    const sources = (r?.sources ?? []).map(({ data: _data, ...s }) => s);  // raw source fields stay out of the public record
    stmts.push(env.DB.prepare('INSERT OR REPLACE INTO trust_checks (run_at, domain, checked_as, status, sources) VALUES (?, ?, ?, ?, ?)')
      .bind(runAt, d, as || d, status, JSON.stringify(sources)));
  }
  if (stmts.length) await env.DB.batch(stmts);
  return { run_at: runAt, domains: configured.length, flagged, source_errors: report.summary.source_errors };
}

/** Nightly: drop rows older than TRUST_RETENTION_DAYS. */
export async function pruneTrustChecks(env: Env, now: number = Date.now()): Promise<number> {
  const cutoff = new Date(now - TRUST_RETENTION_DAYS * 86_400_000).toISOString();
  const r = await env.DB.prepare('DELETE FROM trust_checks WHERE run_at < ?').bind(cutoff).run();
  return r.meta.changes ?? 0;
}

interface Row { run_at: string; domain: string; checked_as: string; status: Verdict; sources: string }

function combined(statuses: Verdict[]): Verdict {
  if (statuses.includes('flagged')) return 'flagged';
  if (statuses.includes('clean')) return 'clean';
  return 'no_data';
}

export async function trustStatusData(env: Env): Promise<Record<string, unknown>> {
  const last = await env.DB.prepare('SELECT MAX(run_at) AS run_at FROM trust_checks').first<{ run_at: string | null }>();
  const lastRunAt = last?.run_at ?? null;
  const rows = lastRunAt
    ? (await env.DB.prepare('SELECT run_at, domain, checked_as, status, sources FROM trust_checks WHERE run_at = ? ORDER BY domain').bind(lastRunAt).all<Row>()).results
    : [];
  const recent = (await env.DB.prepare(
    `SELECT run_at, GROUP_CONCAT(CASE WHEN status = 'flagged' THEN domain END) AS flagged, GROUP_CONCAT(status) AS statuses
       FROM trust_checks GROUP BY run_at ORDER BY run_at DESC LIMIT ?`).bind(HISTORY_RUNS).all<{ run_at: string; flagged: string | null; statuses: string }>()).results;
  const domains = rows.map((r) => {
    let sources: SourceResult[] = [];
    try { sources = JSON.parse(r.sources); } catch { /* keep [] */ }
    return { domain: r.domain, checked_as: r.checked_as, status: r.status, sources };
  });
  return {
    name: 'Commonworld own-domain trust status',
    engine: ENGINE, engine_version: ENGINE_VERSION, standard: TRUST_STANDARD_URL,
    cadence: 'hourly',
    rule: 'A domain is flagged when ANY one source flags it; clean when at least one source answered and none flags it; no_data when no source could answer.',
    sources: DEFAULT_SOURCES.map(({ id, name, covers, url }) => ({ id, name, covers, url })),
    last_run_at: lastRunAt,
    status: rows.length ? combined(rows.map((r) => r.status)) : 'no_data',
    domains,
    recent_runs: recent.map((x) => ({
      run_at: x.run_at,
      status: combined(String(x.statuses || '').split(',') as Verdict[]),
      flagged: x.flagged ? String(x.flagged).split(',').sort() : [],
    })),
  };
}

export async function trustStatus(c: Ctx): Promise<Response> {
  return json(200, await trustStatusData(c.env));
}

export type { FetchLike };
