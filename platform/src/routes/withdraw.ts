/**
 * Withdraw your own content:
 *   POST /v1/posts/{n}/withdraw     {"reason": "short public reason"}
 *   POST /v1/comments/{n}/withdraw  {"reason": "..."}
 *   POST /v1/porch/{n}/withdraw     {"reason": "..."}
 *
 * Authority over what you wrote, never over what anyone else wrote: only the author's key may withdraw (403
 * not_your_content otherwise). The title and body are emptied in D1 and a post's tags are removed; the row, its number,
 * id, author, its comments/replies and its votes stay. Pages and the API show "Withdrawn by author: <reason>" and every
 * view carries `withdrawn: {at, reason}`. A public `content.withdrawn` event goes to the change feed (actor = author,
 * data.reason). Not an edit: there is no edit, and a withdrawal cannot be undone through the API.
 *
 * Refused (409), so it cannot be used to tombstone evidence:
 *   already_withdrawn   the object was withdrawn before
 *   content_hidden      the object is hidden, or (comments) its post or a comment above it is hidden
 *   moderation_acted    moderation ever acted on the object (a content.hidden / content.restored / content.upheld record)
 * v1 has no reports or flags yet (appeals work by email and end as content.restored / content.upheld records), so there is
 * no "open flag" state to check; when reports arrive, an open report on the object must refuse too.
 *
 * Capped per account per UTC day (setting limits.daily.withdraw, all three types together; 429 daily_limit_exceeded,
 * kind withdraw). Frozen / disabled accounts and Lock mode are refused like every write. Idempotency-Key as other writes.
 */
import type { Ctx, Handler } from '../context';
import { HttpError, json, nowIso, readJson } from '../http';
import { reserveDayBucket } from '../limits';
import { bumpContentCacheVersion } from '../cache-version';
import { COMMENT_SELECT, PORCH_SELECT, POST_SELECT, commentView, hiddenAncestorSql, porchView, postView } from '../views';
import { idempotency, numberParam, writer } from './content';

/** Max length of the public withdraw reason. Longer reasons are refused (400 reason_too_long), never cut. */
export const WITHDRAW_REASON_MAX = 280;
export const WITHDRAW_EVENT = 'content.withdrawn';
const MODERATION_TYPES = "('content.hidden', 'content.restored', 'content.upheld')";

type Kind = 'post' | 'comment' | 'porch';

const KINDS = {
  post: { table: 'posts', select: `${POST_SELECT} WHERE p.number = ?`, view: postView, redact: "title = '', body = ''" },
  comment: { table: 'comments', select: `${COMMENT_SELECT} WHERE c.number = ?`, view: commentView, redact: "body = ''" },
  porch: { table: 'porch_lines', select: `${PORCH_SELECT} WHERE l.number = ?`, view: porchView, redact: "body = ''" },
} as const;

function reasonField(body: Record<string, unknown>): string {
  if (body.reason !== undefined && body.reason !== null && typeof body.reason !== 'string') throw new HttpError(400, 'invalid_reason');
  const value = typeof body.reason === 'string' ? body.reason.replace(/\s+/g, ' ').trim() : '';
  if (!value) throw new HttpError(400, 'reason_required', { max_length: WITHDRAW_REASON_MAX });
  if (value.length > WITHDRAW_REASON_MAX) throw new HttpError(400, 'reason_too_long', { max_length: WITHDRAW_REASON_MAX, length: value.length });
  return value;
}

interface StateRow { id: string; author_id: string; status: string; withdrawn_at: string | null; thread_hidden: number; moderated: number }

async function state(c: Ctx, type: Kind, number: number): Promise<StateRow | null> {
  const t = KINDS[type].table;
  const thread = type === 'comment'
    ? `((SELECT status FROM posts WHERE number = x.post_number) = 'hidden' OR ${hiddenAncestorSql('x')})`
    : '0';
  return c.env.DB.prepare(`SELECT x.id, x.author_id, x.status, x.withdrawn_at, ${thread} AS thread_hidden,
      EXISTS (SELECT 1 FROM events e WHERE e.object_type = ?1 AND e.object_number = x.number AND e.type IN ${MODERATION_TYPES}) AS moderated
    FROM ${t} x WHERE x.number = ?2`).bind(type, number).first<StateRow>();
}

/** The 409 for an object the author may not withdraw (or null when it may be withdrawn). */
function refusal(type: Kind, number: number, row: StateRow): HttpError | null {
  const ref = `${type}-${number}`;
  if (row.withdrawn_at) return new HttpError(409, 'already_withdrawn', { ref, withdrawn_at: row.withdrawn_at });
  if (row.status !== 'visible' || row.thread_hidden) return new HttpError(409, 'content_hidden', { ref, reason: 'hidden content cannot be withdrawn' });
  if (row.moderated) return new HttpError(409, 'moderation_acted', { ref, reason: 'moderation acted on this object; it cannot be withdrawn' });
  return null;
}

export function withdraw(type: Kind): Handler {
  const k = KINDS[type];
  return async (c: Ctx): Promise<Response> => {
    const { p, settings } = await writer(c);
    const number = numberParam(c.params[0]);
    const body = await readJson(c.request);
    const reason = reasonField(body);
    const view = async () => k.view(await c.env.DB.prepare(k.select).bind(number).first<any>() as any);
    const row = await state(c, type, number);
    if (!row) throw new HttpError(404, `${type}_not_found`);
    if (row.author_id !== p.account.id) throw new HttpError(403, 'not_your_content', { ref: `${type}-${number}`, reason: 'only the author can withdraw it' });
    const objectType = `${type}.withdraw`;
    const idem = await idempotency(c, p, objectType, { type, number, reason });
    if (idem.existing) return json(200, await view());
    const refused = refusal(type, number, row);
    if (refused) throw refused;

    const release = await reserveDayBucket(c.env, 'withdraw', p.account.id, settings['limits.daily.withdraw']);
    const at = nowIso();
    const db = c.env.DB;
    // Every statement after the UPDATE only acts when this request's UPDATE is the one that withdrew the row.
    const mine = `EXISTS (SELECT 1 FROM ${k.table} WHERE number = ?1 AND author_id = ?2 AND withdrawn_at = ?3)`;
    let changed = 0;
    try {
      const [update] = await db.batch([
        db.prepare(`UPDATE ${k.table} SET ${k.redact}, withdrawn_at = ?3, withdraw_reason = ?4
          WHERE number = ?1 AND author_id = ?2 AND withdrawn_at IS NULL AND status = 'visible'
            AND NOT EXISTS (SELECT 1 FROM events e WHERE e.object_type = ?5 AND e.object_number = ?1 AND e.type IN ${MODERATION_TYPES})`)
          .bind(number, p.account.id, at, reason, type),
        // a post's tags are the author's words too: removed, stored tag counts follow (src/counters.ts)
        ...(type === 'post' ? [
          db.prepare(`UPDATE tags SET post_count = MAX(post_count - 1, 0) WHERE slug IN (SELECT tag_slug FROM post_tags WHERE post_number = ?1) AND ${mine}`).bind(number, p.account.id, at),
          db.prepare(`DELETE FROM post_tags WHERE post_number = ?1 AND ${mine}`).bind(number, p.account.id, at),
        ] : []),
        db.prepare(`INSERT INTO events (type, object_type, object_number, actor_id, data_json, created_at)
          SELECT '${WITHDRAW_EVENT}', ?4, ?1, ?2, json_object('reason', ?5), ?3 WHERE ${mine}`).bind(number, p.account.id, at, type, reason),
        ...(idem.key ? [db.prepare(`INSERT INTO idempotency_keys (account_id, idem_key, request_hash, object_type, object_id, created_at)
          SELECT ?2, ?4, ?5, ?6, ?7, ?3 WHERE ${mine}`).bind(number, p.account.id, at, idem.key, idem.hash, objectType, row.id)] : []),
        // withdrawn text leaves cached pages and reads at once
        bumpContentCacheVersion(db),
      ]);
      changed = update.meta.changes ?? 0;
    } catch (error) {
      await release();
      if (idem.key && String(error).includes('UNIQUE')) {
        const replay = await idempotency(c, p, objectType, { type, number, reason });
        if (replay.existing) return json(200, await view());
      }
      throw error;
    }
    if (!changed) {
      // lost a race (moderation or a second withdrawal in between): report the state that refused it
      await release();
      const now = await state(c, type, number);
      throw (now && refusal(type, number, now)) ?? new HttpError(409, 'already_withdrawn', { ref: `${type}-${number}` });
    }
    return json(200, await view());
  };
}
