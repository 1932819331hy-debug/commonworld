/**
 * Public moderation record + rules.
 *   GET /v1/rules       the 7 numbered rules (numbers are permanent) — same list as /moderation#rules
 *   GET /v1/moderation  the public moderation log — same records as the /moderation page
 * A log item is a `content.hidden` / `content.restored` / `content.upheld` event: object ref, time, rule, short note, moderator.
 * `content.upheld` = an appeal was reviewed and the decision stands (the object's visibility does not change).
 * `tag.merged` = staff merged a tag into another (`merged_into`: from/into slugs and refs, posts moved); rule is null.
 * `account.recovered` / `account.recovery_rejected` = an admin approved or rejected a lost-key recovery (`recovery`: request ref,
 *   method, proof provider, account); never codes, tokens or keys.
 * `tag.archived` = staff archived a spam/abusive tag (`archived_tag`: slug, ref, posts untagged); rule is null.
 * Never the hidden content and never its author.
 */
import type { Ctx } from '../context';
import type { Env } from '../env';
import { intParam, json } from '../http';
import { rulesData } from '../rules';
import { citizenPath } from '../views';
import { moderationEventData } from './content';
import { APPEAL } from '../rules';

/** Event types listed in the public moderation log. */
export const MODERATION_LOG_TYPES = ['content.hidden', 'content.restored', 'content.upheld', 'tag.merged', 'tag.archived', 'account.recovered', 'account.recovery_rejected'] as const;
const TYPES_SQL = MODERATION_LOG_TYPES.map((t) => `'${t}'`).join(', ');

export interface ModerationItem {
  seq: number; type: string; object_type: string; object_number: number; created_at: string;
  status_now: string | null; post_number: number | null;
  moderator: { handle: string; kind: string; url: string } | null;
  rule: number | null; rule_text: string | null; note: string | null; log_url: string; appeal: typeof APPEAL;
  /** tag.merged only (null otherwise). */
  merged_into: { from: string; into: string; from_ref: string; into_ref: string; posts_moved: number } | null;
  /** tag.archived only (null otherwise). */
  archived_tag: { slug: string; ref: string; posts_untagged: number } | null;
  /** account.recovered / account.recovery_rejected only: the request ref, method (proof | code), which proof (provider or recovery_code) and the account. No secrets. */
  recovery: { request: string; method: string; proof: string | null; account: { handle: string; ref: string; url: string } | null } | null;
  /** Hidden-content notices only: the newest `content.upheld` entry after this hide (appeal reviewed, decision stands). */
  upheld?: { seq: number; log_url: string; note: string | null; created_at: string } | null;
}

const ROW_SQL = `SELECT e.seq, e.type, e.object_type, e.object_number, e.created_at, e.data_json,
      a.handle AS moderator_handle, a.kind AS moderator_kind,
      CASE e.object_type WHEN 'post' THEN (SELECT status FROM posts WHERE number = e.object_number)
        WHEN 'comment' THEN (SELECT status FROM comments WHERE number = e.object_number)
        WHEN 'porch' THEN (SELECT status FROM porch_lines WHERE number = e.object_number)
        WHEN 'tag' THEN (SELECT status FROM tags WHERE number = e.object_number)
        WHEN 'account' THEN (SELECT status FROM accounts WHERE number = e.object_number) END AS status_now,
      (SELECT handle FROM accounts WHERE e.object_type = 'account' AND number = e.object_number) AS account_handle,
      (SELECT post_number FROM comments WHERE e.object_type = 'comment' AND number = e.object_number) AS post_number
    FROM events e LEFT JOIN accounts a ON a.id = e.actor_id`;

function mergeData(dataJson: string | null): ModerationItem['merged_into'] {
  try {
    const d = dataJson ? JSON.parse(dataJson) : {};
    return { from: String(d.from), into: String(d.into), from_ref: String(d.from_ref), into_ref: String(d.into_ref), posts_moved: Number(d.posts_moved) || 0 };
  } catch { return null; }
}

function archiveData(dataJson: string | null): ModerationItem['archived_tag'] {
  try {
    const d = dataJson ? JSON.parse(dataJson) : {};
    return { slug: String(d.slug), ref: String(d.ref), posts_untagged: Number(d.posts_untagged) || 0 };
  } catch { return null; }
}

function recoveryData(r: any): ModerationItem['recovery'] {
  try {
    const d = r.data_json ? JSON.parse(r.data_json) : {};
    return { request: String(d.request), method: String(d.method), proof: d.proof ? String(d.proof) : null,
      account: r.account_handle ? { handle: r.account_handle, ref: `citizen-${r.object_number}`, url: citizenPath(r.account_handle) } : null };
  } catch { return null; }
}

function toItem(r: any): ModerationItem {
  return {
    seq: r.seq, type: r.type, object_type: r.object_type, object_number: r.object_number, created_at: r.created_at,
    status_now: r.status_now ?? null, post_number: r.post_number ?? null,
    moderator: r.moderator_handle ? { handle: r.moderator_handle, kind: r.moderator_kind, url: citizenPath(r.moderator_handle) } : null,
    ...moderationEventData(r.seq, r.data_json),
    merged_into: r.type === 'tag.merged' ? mergeData(r.data_json) : null,
    archived_tag: r.type === 'tag.archived' ? archiveData(r.data_json) : null,
    recovery: r.type === 'account.recovered' || r.type === 'account.recovery_rejected' ? recoveryData(r) : null,
  };
}

/** Newest first, `before` = event seq cursor (0 = newest). */
export async function moderationLogData(env: Env, before: number, limit = 50) {
  const { results } = await env.DB.prepare(`${ROW_SQL} WHERE e.type IN (${TYPES_SQL}) ${before ? 'AND e.seq < ?' : ''}
    ORDER BY e.seq DESC LIMIT ?`).bind(...(before ? [before] : []), limit + 1).all<any>();
  const counts = await env.DB.prepare(`SELECT
      SUM(CASE WHEN type = 'content.hidden' THEN 1 ELSE 0 END) AS hidden,
      SUM(CASE WHEN type = 'content.restored' THEN 1 ELSE 0 END) AS restored,
      SUM(CASE WHEN type = 'content.upheld' THEN 1 ELSE 0 END) AS upheld,
      SUM(CASE WHEN type = 'tag.merged' THEN 1 ELSE 0 END) AS merged,
      SUM(CASE WHEN type = 'tag.archived' THEN 1 ELSE 0 END) AS archived,
      SUM(CASE WHEN type IN ('account.recovered', 'account.recovery_rejected') THEN 1 ELSE 0 END) AS recoveries FROM events WHERE type IN (${TYPES_SQL})`)
    .first<{ hidden: number | null; restored: number | null; upheld: number | null; merged: number | null; archived: number | null; recoveries: number | null }>();
  return {
    items: results.slice(0, limit).map(toItem),
    next_before: results.length > limit ? results[limit - 1].seq as number : null,
    hidden: counts?.hidden ?? 0, restored: counts?.restored ?? 0, upheld: counts?.upheld ?? 0, merged: counts?.merged ?? 0, archived: counts?.archived ?? 0, recoveries: counts?.recoveries ?? 0,
  };
}

/** Latest moderation event about one object (hidden post page, hidden comment notices). */
export async function lastModeration(env: Env, objectType: string, number: number): Promise<ModerationItem | null> {
  const r = await env.DB.prepare(`${ROW_SQL} WHERE e.type IN ('content.hidden', 'content.restored') AND e.object_type = ? AND e.object_number = ?
    ORDER BY e.seq DESC LIMIT 1`).bind(objectType, number).first<any>();
  if (!r) return null;
  const item = toItem(r);
  if (r.type === 'content.hidden') {
    const u = await env.DB.prepare(`SELECT seq, data_json, created_at FROM events WHERE type = 'content.upheld' AND object_type = ? AND object_number = ? AND seq > ?
      ORDER BY seq DESC LIMIT 1`).bind(objectType, number, r.seq).first<any>();
    item.upheld = u ? upheldRef(u) : null;
  }
  return item;
}

function upheldRef(u: { seq: number; data_json: string | null; created_at: string }) {
  const d = moderationEventData(u.seq, u.data_json);
  return { seq: u.seq, log_url: d.log_url, note: d.note, created_at: u.created_at };
}

/** Latest moderation event for each of several comments (one query). */
export async function lastModerationMany(env: Env, objectType: string, numbers: number[]): Promise<Map<number, ModerationItem>> {
  const out = new Map<number, ModerationItem>();
  if (!numbers.length) return out;
  // One bound JSON array instead of `IN (?, ?, …)`: D1 allows at most 100 bound parameters per query,
  // and a post page can ask about up to 200 hidden comments.
  const list = JSON.stringify(numbers);
  const { results } = await env.DB.prepare(`${ROW_SQL} WHERE e.seq IN (SELECT MAX(x.seq) FROM events x
      WHERE x.type IN ('content.hidden', 'content.restored') AND x.object_type = ? AND x.object_number IN (SELECT value FROM json_each(?)) GROUP BY x.object_number)`)
    .bind(objectType, list).all<any>();
  for (const r of results) out.set(r.object_number, toItem(r));
  const hiddenSeqs = [...out.values()].filter((x) => x.type === 'content.hidden');
  if (hiddenSeqs.length) {
    const { results: ups } = await env.DB.prepare(`SELECT e.seq, e.object_number, e.data_json, e.created_at FROM events e
        WHERE e.seq IN (SELECT MAX(x.seq) FROM events x WHERE x.type = 'content.upheld' AND x.object_type = ? AND x.object_number IN (SELECT value FROM json_each(?)) GROUP BY x.object_number)`)
      .bind(objectType, list).all<any>();
    for (const u of ups) {
      const item = out.get(u.object_number);
      if (item && item.type === 'content.hidden' && u.seq > item.seq) item.upheld = upheldRef(u);
    }
  }
  return out;
}

export async function rules(_c: Ctx): Promise<Response> {
  return json(200, rulesData());
}

export async function moderationLog(c: Ctx): Promise<Response> {
  const before = intParam(c.url, 'before', 0, 0, Number.MAX_SAFE_INTEGER);
  const limit = intParam(c.url, 'limit', 50, 1, 100);
  const log = await moderationLogData(c.env, before, limit);
  return json(200, {
    items: log.items.map(({ status_now, post_number, ...x }) => ({
      ...x, object: { type: x.object_type, number: x.object_number, ref: `${x.object_type === 'account' ? 'citizen' : x.object_type}-${x.object_number}`, status_now },
    })).map(({ object_type, object_number, ...x }) => x),
    next_before: log.next_before, counts: { hidden: log.hidden, restored: log.restored, upheld: log.upheld, merged: log.merged, archived: log.archived, recoveries: log.recoveries },
  });
}
