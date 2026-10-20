/**
 * One R2 backup bucket per environment (owner decision 2026-10-20): wrangler.toml binds staging and production to
 * different buckets, and src/backup.ts refuses (fail closed, one log line) when ENVIRONMENT, BACKUPS_BUCKET and the key
 * prefix do not match BACKUP_TARGETS, so a misconfigured staging Worker can never read or write production backups.
 */
import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  BACKUP_TARGETS, BackupTargetError, PRODUCTION_BACKUP_BUCKET, backupStatus, backupTarget, backupTargetProblems, runBackup, runRestoreCheck,
} from '../src/backup';
import worker from '../src/index';
import { makeAdmin, resetDb } from './helpers';

const E = env as any;
const NOW = Date.parse('2026-10-19T03:00:00Z');

beforeEach(async () => { await resetDb(); });
afterEach(() => vi.restoreAllMocks());

/** Minimal TOML reader for wrangler.toml: table header -> list of `key = "string"` pairs ([[array]] tables repeat). */
function tomlTables(toml: string): { table: string; keys: Record<string, string> }[] {
  const out: { table: string; keys: Record<string, string> }[] = [{ table: '', keys: {} }];
  for (const line of toml.split('\n')) {
    const h = /^\[\[?([^\]]+)\]\]?\s*$/.exec(line);
    if (h) { out.push({ table: h[1], keys: {} }); continue; }
    const kv = /^(\w+)\s*=\s*"([^"]*)"\s*$/.exec(line);
    if (kv) out[out.length - 1].keys[kv[1]] = kv[2];
  }
  return out;
}

describe('wrangler.toml: separate backup bucket per environment', () => {
  const tables = tomlTables(E.TEST_WRANGLER_TOML);
  const r2 = (prefix: string) => tables.filter((t) => t.table === `${prefix}r2_buckets` && t.keys.binding === 'BACKUPS').map((t) => t.keys.bucket_name);
  const vars = (prefix: string) => tables.find((t) => t.table === `${prefix}vars`)!.keys;

  it('production uses commonworld-backups, staging a different bucket, local neither', () => {
    const prod = r2('env.production.');
    const staging = r2('env.staging.');
    const local = r2('');
    expect(prod).toEqual(['commonworld-backups']);
    expect(staging).toEqual(['commonworld-backups-staging']);
    expect(local).toHaveLength(1);
    expect(staging[0]).not.toBe(prod[0]);
    expect(local[0]).not.toBe(prod[0]);
    expect(PRODUCTION_BACKUP_BUCKET).toBe('commonworld-backups');
  });

  it('every environment: BACKUPS_BUCKET var = bound bucket = BACKUP_TARGETS entry for its ENVIRONMENT', () => {
    for (const [prefix, name] of [['', 'local'], ['env.staging.', 'staging'], ['env.production.', 'production']] as const) {
      const v = vars(prefix);
      expect(v.ENVIRONMENT, prefix || 'default').toBe(name);
      expect(v.BACKUPS_BUCKET, prefix || 'default').toBe(r2(prefix)[0]);
      expect(v.BACKUPS_BUCKET, prefix || 'default').toBe(BACKUP_TARGETS[name].bucket);
    }
  });
});

describe('backupTargetProblems', () => {
  it('allows exactly the configured pairs', () => {
    expect(backupTargetProblems('production', 'commonworld-backups', 'prod')).toEqual([]);
    expect(backupTargetProblems('staging', 'commonworld-backups-staging', 'staging')).toEqual([]);
    expect(backupTargetProblems('local', 'commonworld-backups-local', 'local')).toEqual([]);
  });

  it('refuses an unset or unknown ENVIRONMENT before anything else', () => {
    expect(backupTargetProblems(undefined, 'commonworld-backups-local', 'local')).toEqual(['ENVIRONMENT (unset) is not one of production, staging, local']);
    expect(backupTargetProblems('', 'commonworld-backups-local', 'local').join()).toMatch(/is not one of production, staging, local/);
    expect(backupTargetProblems('Production', 'commonworld-backups', 'prod').join()).toMatch(/is not one of production, staging, local/);
  });

  it('refuses staging writing the prod/ prefix, staging on the production bucket, and the reverse', () => {
    expect(backupTargetProblems('staging', 'commonworld-backups-staging', 'prod').join('; ')).toMatch(/key prefix prod\/ is not the staging prefix staging\/.*must never touch the production backups/);
    expect(backupTargetProblems('staging', 'commonworld-backups', 'staging').join('; ')).toMatch(/bucket commonworld-backups is not the staging backup bucket.*must never touch the production backups/);
    expect(backupTargetProblems('production', 'commonworld-backups-staging', 'prod').join('; ')).toMatch(/bucket commonworld-backups-staging is not the production backup bucket commonworld-backups/);
    expect(backupTargetProblems('production', 'commonworld-backups', 'staging').join('; ')).toMatch(/key prefix staging\/ is not the production prefix prod\//);
    expect(backupTargetProblems('local', 'commonworld-backups', 'local').join('; ')).toMatch(/must never touch the production backups/);
    expect(backupTargetProblems('weird', 'commonworld-backups-local', 'prod').join('; ')).toMatch(/is not one of production, staging, local/);
    expect(backupTargetProblems('staging', undefined, 'staging')).toEqual(['BACKUPS_BUCKET is not set']);
  });
});

describe('jobs fail closed on a mismatch', () => {
  async function keys(): Promise<string[]> { return ((await E.BACKUPS.list()).objects as R2Object[]).map((o) => o.key); }

  it('runBackup / runRestoreCheck / backupStatus refuse with one clear log line and write nothing', async () => {
    const errors: string[] = [];
    vi.spyOn(console, 'error').mockImplementation((...a) => { errors.push(a.join(' ')); });
    const before = await keys();
    const stagingAsProd = { ...E, ENVIRONMENT: 'staging', BACKUPS_BUCKET: 'commonworld-backups' };
    await expect(runBackup(stagingAsProd, NOW)).rejects.toBeInstanceOf(BackupTargetError);
    await expect(runRestoreCheck(stagingAsProd, NOW)).rejects.toBeInstanceOf(BackupTargetError);
    await expect(backupStatus(stagingAsProd, NOW)).rejects.toBeInstanceOf(BackupTargetError);
    const stagingPrefixProd = { ...E, ENVIRONMENT: 'staging', BACKUPS_BUCKET: 'commonworld-backups-staging' };
    await expect(runBackup(stagingPrefixProd, NOW, 'worker-cron', 'prod')).rejects.toThrow(/key prefix prod\/ is not the staging prefix/);
    await expect(runRestoreCheck({ ...E, BACKUPS_BUCKET: undefined }, NOW)).rejects.toThrow(/BACKUPS_BUCKET is not set/);
    expect(await keys()).toEqual(before);
    expect(errors).toHaveLength(5);
    for (const line of errors) expect(line).toMatch(/^d1 backup REFUSED backup target mismatch \(env=\S+ bucket=\S+ prefix=\S+\/\): /);
  });

  it('backupTarget returns the bound bucket for the matching local config', () => {
    const t = backupTarget(E);
    expect(t).toMatchObject({ bucket: 'commonworld-backups-local', prefix: 'local' });
    expect(t.r2).toBe(E.BACKUPS);
  });

  it('admin endpoints answer 503 backup_target_mismatch', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const admin = await makeAdmin();
    const call = async (path: string, body?: unknown) => {
      const ctx = createExecutionContext();
      const headers: Record<string, string> = { authorization: `Bearer ${admin.key}` };
      if (body) headers['content-type'] = 'application/json';
      const res = await worker.fetch(new Request(`https://api.test${path}`, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined }),
        { ...E, BACKUPS_BUCKET: 'commonworld-backups' } as any, ctx);
      await waitOnExecutionContext(ctx);
      return { status: res.status, body: await res.json<any>() };
    };
    const status = await call('/v1/admin/backups');
    const run = await call('/v1/admin/backups/run', { job: 'backup' });
    expect([status.status, status.body.error?.code]).toEqual([503, 'backup_target_mismatch']);
    expect([run.status, run.body.error?.code]).toEqual([503, 'backup_target_mismatch']);
  });
});
