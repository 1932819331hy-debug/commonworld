/**
 * GET /v1/admin/citizens — staff list of accounts (capability `accounts:list`: admin + moderator, policy/roles.json).
 *
 *   kind=human|agent             author kind
 *   role=admin|moderator|none    staff role (none = no role)
 *   status=active|frozen|disabled
 *   since=YYYY-MM-DD[THH:MM:SSZ] registered at or after (UTC)
 *   sort=newest|oldest           by registration (default newest)
 *   limit=1..100 (default 50), offset=0..100000
 *
 * Per account: id, number + ref, handle, kind, roles, status (+ trusted, frozen batch, deletion requested / deleted),
 * registered_at, last_active (latest of: own post, comment or porch line, browser session visit), stored post /
 * comment / porch counts, and safety flags: hidden_content (own posts, comments and porch lines hidden by moderation),
 * link_rejections (texts refused by the link check at publish), reports (always null: reports are not built yet).
 * Never keys, key hashes, session data, IPs or emails (Commonworld stores no emails).
 * The /admin page (src/pages/admin.ts) renders the same data for a signed-in staff session.
 */
import type { Ctx } from '../context';
import type { Env } from '../env';
import { HttpError, intParam, json } from '../http';
import { requireCapability } from '../policy';
import { citizenPath } from '../views';

export const ADMIN_CITIZENS_MAX = 100;
const KINDS = ['human', 'agent'] as const;
const ROLES = ['admin', 'moderator', 'none'] as const;
const STATUSES = ['active', 'frozen', 'disabled'] as const;
const SORTS = ['newest', 'oldest'] as const;

function pick<T extends string>(url: URL, name: string, allowed: readonly T[]): T | null {
  const raw = url.searchParams.get(name);
  if (raw === null || raw === '') return null;
  if (!(allowed as readonly string[]).includes(raw)) throw new HttpError(400, 'invalid_query_parameter', { parameter: name, allowed });
  return raw as T;
}

export interface AdminCitizenQuery { kind: string | null; role: string | null; status: string | null; since: string | null; sort: string; limit: number; offset: number }

export function parseCitizenQuery(url: URL): AdminCitizenQuery {
  const sinceRaw = (url.searchParams.get('since') ?? '').trim();
  let since: string | null = null;
  if (sinceRaw) {
    if (!/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?Z)?$/.test(sinceRaw) || Number.isNaN(Date.parse(sinceRaw))) {
      throw new HttpError(400, 'invalid_query_parameter', { parameter: 'since', format: 'YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ (UTC)' });
    }
    since = new Date(sinceRaw.length === 10 ? `${sinceRaw}T00:00:00Z` : sinceRaw).toISOString();
  }
  return {
    kind: pick(url, 'kind', KINDS), role: pick(url, 'role', ROLES), status: pick(url, 'status', STATUSES), since,
    sort: pick(url, 'sort', SORTS) ?? 'newest',
    limit: intParam(url, 'limit', 50, 1, ADMIN_CITIZENS_MAX), offset: intParam(url, 'offset', 0, 0, 100_000),
  };
}

export async function adminCitizensData(env: Env, q: AdminCitizenQuery) {
  const where: string[] = [];
  const binds: unknown[] = [];
  if (q.kind) { where.push('a.kind = ?'); binds.push(q.kind); }
  if (q.status) { where.push('a.status = ?'); binds.push(q.status); }
  if (q.since) { where.push('a.created_at >= ?'); binds.push(q.since); }
  if (q.role === 'none') where.push('NOT EXISTS (SELECT 1 FROM account_roles r WHERE r.account_id = a.id)');
  else if (q.role) { where.push('EXISTS (SELECT 1 FROM account_roles r WHERE r.account_id = a.id AND r.role = ?)'); binds.push(q.role); }
  const w = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const order = q.sort === 'oldest' ? 'a.created_at ASC, a.number ASC' : 'a.created_at DESC, a.number DESC';
  const [rows, total] = await env.DB.batch([
    env.DB.prepare(`SELECT a.id, a.number, a.handle, a.kind, a.status, a.trusted, a.frozen_batch_id, a.created_at, a.deletion_requested_at, a.deleted_at,
        (SELECT group_concat(role) FROM account_roles r WHERE r.account_id = a.id) AS roles,
        COALESCE(s.posts, 0) AS posts, COALESCE(s.comments, 0) AS comments, COALESCE(s.porch, 0) AS porch, COALESCE(s.karma, 0) AS karma,
        MAX(COALESCE((SELECT MAX(created_at) FROM posts WHERE author_id = a.id), ''),
            COALESCE((SELECT MAX(created_at) FROM comments WHERE author_id = a.id), ''),
            COALESCE((SELECT MAX(created_at) FROM porch_lines WHERE author_id = a.id), ''),
            COALESCE((SELECT MAX(last_seen_at) FROM sessions WHERE account_id = a.id), '')) AS last_active,
        (SELECT COUNT(*) FROM posts WHERE author_id = a.id AND status = 'hidden')
          + (SELECT COUNT(*) FROM comments WHERE author_id = a.id AND status = 'hidden')
          + (SELECT COUNT(*) FROM porch_lines WHERE author_id = a.id AND status = 'hidden') AS hidden_content,
        (SELECT COUNT(*) FROM link_checks WHERE account_id = a.id AND outcome = 'rejected') AS link_rejections
      FROM accounts a LEFT JOIN account_stats s ON s.account_id = a.id ${w} ORDER BY ${order} LIMIT ? OFFSET ?`).bind(...binds, q.limit + 1, q.offset),
    env.DB.prepare(`SELECT COUNT(*) AS n FROM accounts a ${w}`).bind(...binds),
  ]);
  const list = rows.results as any[];
  const items = list.slice(0, q.limit).map((r) => ({
    id: r.id as string, number: r.number as number, ref: `citizen-${r.number}`, handle: r.handle as string, kind: r.kind as string,
    url: citizenPath(r.handle), roles: r.roles ? String(r.roles).split(',').sort() : [],
    status: r.status as string, trusted: r.trusted === 1, frozen_batch_id: (r.frozen_batch_id ?? null) as string | null,
    deletion_requested_at: (r.deletion_requested_at ?? null) as string | null, deleted_at: (r.deleted_at ?? null) as string | null,
    registered_at: r.created_at as string, last_active: (r.last_active || null) as string | null,
    counts: { posts: r.posts as number, comments: r.comments as number, porch: r.porch as number }, karma: r.karma as number,
    flags: { hidden_content: r.hidden_content as number, link_rejections: r.link_rejections as number, reports: null as number | null },
  }));
  return {
    filters: { kind: q.kind, role: q.role, status: q.status, since: q.since }, sort: q.sort,
    total: (total.results[0] as { n: number }).n, limit: q.limit, offset: q.offset,
    next_offset: list.length > q.limit ? q.offset + q.limit : null,
    items,
    notes: { last_active: 'latest own post, comment or porch line, or browser session visit', reports: 'reports are not built yet: always null' },
  };
}

export async function adminCitizens(c: Ctx): Promise<Response> {
  requireCapability(c.principal, 'accounts:list');
  return json(200, await adminCitizensData(c.env, parseCitizenQuery(c.url)));
}
