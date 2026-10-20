import type { Ctx } from '../context';
import { requireRole } from '../auth';
import { HttpError, json, readJson } from '../http';
import { BackupTargetError, backupStatus, logBackup, logCheck, runBackup, runRestoreCheck } from '../backup';

/** A backup target mismatch (src/backup.ts backupTarget) is a configuration error: 503, nothing read or written. */
async function guarded<T>(fn: () => Promise<T>): Promise<T> {
  try { return await fn(); } catch (error) {
    if (error instanceof BackupTargetError) throw new HttpError(503, 'backup_target_mismatch');
    throw error;
  }
}

/** GET /v1/admin/backups (admin): newest D1 backups in R2, the newest restore check, healthy flag (src/backup.ts). */
export async function adminBackups(c: Ctx): Promise<Response> {
  requireRole(c.principal, 'admin');
  if (!c.env.BACKUPS) throw new HttpError(503, 'backups_not_configured');
  return json(200, await guarded(() => backupStatus(c.env)));
}

/** POST /v1/admin/backups/run {"job": "backup" | "restore-check"} (admin): runs one job now, same code as the cron. */
export async function adminRunBackup(c: Ctx): Promise<Response> {
  const p = requireRole(c.principal, 'admin');
  const body = await readJson(c.request);
  const job = body.job;
  if (job !== 'backup' && job !== 'restore-check') throw new HttpError(400, 'invalid_job', { allowed: ['backup', 'restore-check'] });
  if (!c.env.BACKUPS) throw new HttpError(503, 'backups_not_configured');
  console.log(`d1 ${job} started by admin @${p.account.handle}`);
  if (job === 'backup') {
    const r = await guarded(() => runBackup(c.env));
    logBackup(r);
    return json(200, { job, ok: true, backup: r, check: null });
  }
  const r = await guarded(() => runRestoreCheck(c.env));
  logCheck(r);
  return json(200, { job, ok: r.ok, backup: null, check: r });
}
