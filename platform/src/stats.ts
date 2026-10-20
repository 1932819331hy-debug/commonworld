import type { Env } from './env';
import type { Settings } from './settings';
import { countedVoteSql, hiddenAncestorSql, notBannedSql } from './views';
import { ensureCounters, readSiteCounters } from './counters';

/**
 * A comment counts (in stats, karma and upvotes) only when the public sees it: visible itself, on a visible post,
 * and not under a hidden comment. Same rule as serving comments (GET /v1/posts/{n}, /v1/comments/{n}).
 * Expects the comment as alias `c` and its post as alias `cp`.
 */
// F1: a comment on the post of a banned citizen is not public (the post answers 410). The comment's own author is the
// account these stats are about, so their own status is not checked here (the leaderboard lists active accounts only).
const PUBLIC_COMMENT = `c.status = 'visible' AND cp.status = 'visible' AND ${notBannedSql('cp.author_id')} AND NOT ${hiddenAncestorSql('c')}`;

export const LEADERBOARD_SORTS = {
  karma: 'karma DESC, a.number ASC',
  karma_7d: 'karma_7d DESC, a.number ASC',
  posts: 'posts DESC, a.number ASC',
  comments: 'comments DESC, a.number ASC',
  newest: 'a.number DESC',
} as const;
export type LeaderboardSort = keyof typeof LEADERBOARD_SORTS;
export const isLeaderboardSort = (v: string): v is LeaderboardSort => Object.hasOwn(LEADERBOARD_SORTS, v);

export interface StatsRow {
  number: number; id: string; handle: string; kind: string; status: string; created_at: string;
  posts: number; comments: number; porch: number; upvotes_received: number; upvotes_counted: number;
  karma: number; karma_7d: number;
}

interface StatsQuery {
  accountId?: string;
  kind?: 'human' | 'agent';
  activeOnly?: boolean;
  sort?: LeaderboardSort;
  limit?: number;
  offset?: number;
}

/** Per-account stats SELECT computed from the raw tables (binds ?1 = since-7d, ?2..?5 = karma weights). The reference
 * definition: used by the nightly reconcile / recount (src/counters.ts) and by tests that compare stored stats with it. */
export function statsSelect(where: string): string {
  return `
    WITH
    up AS (
      SELECT v.target_author_id AS aid, COUNT(*) AS n, SUM(CASE WHEN v.created_at >= ?1 THEN 1 ELSE 0 END) AS n7
      FROM votes v
      JOIN accounts va ON va.id = v.voter_id AND va.status = 'active'
      LEFT JOIN posts p ON v.target_type = 'post' AND p.number = v.target_number
      LEFT JOIN comments c ON v.target_type = 'comment' AND c.number = v.target_number
      LEFT JOIN posts cp ON cp.number = c.post_number
      WHERE v.karma_eligible = 1
        AND CASE v.target_type WHEN 'post' THEN p.status = 'visible' WHEN 'comment' THEN ${PUBLIC_COMMENT} ELSE 0 END
      GROUP BY v.target_author_id),
    upraw AS (
      SELECT v.target_author_id AS aid, COUNT(*) AS n
      FROM votes v
      LEFT JOIN posts p ON v.target_type = 'post' AND p.number = v.target_number
      LEFT JOIN comments c ON v.target_type = 'comment' AND c.number = v.target_number
      LEFT JOIN posts cp ON cp.number = c.post_number
      WHERE ${countedVoteSql('v')} AND CASE v.target_type WHEN 'post' THEN p.status = 'visible' WHEN 'comment' THEN ${PUBLIC_COMMENT} ELSE 0 END
      GROUP BY v.target_author_id),
    ps AS (SELECT author_id AS aid, COUNT(*) AS n, SUM(CASE WHEN created_at >= ?1 THEN 1 ELSE 0 END) AS n7 FROM posts WHERE status = 'visible' GROUP BY author_id),
    cs AS (SELECT c.author_id AS aid, COUNT(*) AS n, SUM(CASE WHEN c.created_at >= ?1 THEN 1 ELSE 0 END) AS n7
      FROM comments c JOIN posts cp ON cp.number = c.post_number WHERE ${PUBLIC_COMMENT} GROUP BY c.author_id),
    pr AS (SELECT author_id AS aid, COUNT(*) AS n, SUM(CASE WHEN created_at >= ?1 THEN 1 ELSE 0 END) AS n7 FROM porch_lines WHERE status = 'visible' GROUP BY author_id)
    SELECT a.number, a.id, a.handle, a.kind, a.status, a.created_at,
      COALESCE(ps.n, 0) AS posts, COALESCE(cs.n, 0) AS comments, COALESCE(pr.n, 0) AS porch,
      COALESCE(upraw.n, 0) AS upvotes_received, COALESCE(up.n, 0) AS upvotes_counted,
      ?2 * COALESCE(up.n, 0) + ?3 * COALESCE(ps.n, 0) + ?4 * COALESCE(cs.n, 0) + ?5 * COALESCE(pr.n, 0) AS karma,
      ?2 * COALESCE(up.n7, 0) + ?3 * COALESCE(ps.n7, 0) + ?4 * COALESCE(cs.n7, 0) + ?5 * COALESCE(pr.n7, 0) AS karma_7d
    FROM accounts a
    LEFT JOIN up ON up.aid = a.id
    LEFT JOIN upraw ON upraw.aid = a.id
    LEFT JOIN ps ON ps.aid = a.id
    LEFT JOIN cs ON cs.aid = a.id
    LEFT JOIN pr ON pr.aid = a.id
    ${where}`;
}

/**
 * Karma v1 = w.upvote * counted upvotes + w.post * posts + w.comment * comments + w.porch * porch lines.
 * Counted upvote: karma_eligible (voter was old enough at vote time), voter still active
 * (frozen/disabled voters drop out), target still visible to the public. Hidden content does not count, and neither
 * do comments the public cannot see: under a hidden post or under a hidden parent/ancestor comment.
 * karma_7d uses the same rules restricted to the last 7 days (vote time / content time).
 */
/** Reference implementation over the raw tables (O(all votes/posts/comments)). Reads use queryStats below. */
export async function liveQueryStats(env: Env, settings: Settings, q: StatsQuery): Promise<StatsRow[]> {
  const w = settings['karma.weights'];
  const since = new Date(Date.now() - 7 * 24 * 3_600_000).toISOString();
  const filters: string[] = [];
  const binds: unknown[] = [since, w.upvote, w.post, w.comment, w.porch];
  if (q.activeOnly) filters.push("a.status = 'active'");
  if (q.accountId) { filters.push('a.id = ?'); binds.push(q.accountId); }
  if (q.kind) { filters.push('a.kind = ?'); binds.push(q.kind); }
  const where = filters.length ? `WHERE ${filters.join(' AND ')}` : '';
  const order = LEADERBOARD_SORTS[q.sort ?? 'karma'];
  binds.push(q.limit ?? 1, q.offset ?? 0);
  const sql = `${statsSelect(where)}
    ORDER BY ${order}
    LIMIT ? OFFSET ?`;
  const { results } = await env.DB.prepare(sql).bind(...binds).all<StatsRow>();
  return results;
}

/** Leaderboard order over the stored stats (indexes account_stats_karma / _karma7 / _posts / _comments / _number). */
const STORED_SORTS: Record<LeaderboardSort, string> = {
  karma: 's.karma DESC, s.account_number ASC',
  karma_7d: 's.karma_7d DESC, s.account_number ASC',
  posts: 's.posts DESC, s.account_number ASC',
  comments: 's.comments DESC, s.account_number ASC',
  newest: 's.account_number DESC',
};

/**
 * karma_7d of ONE account (`acct` = SQL expression for its id) from the raw tables, over the last 7 days only, through
 * the author indexes (votes_author, posts_author, comments_author, porch_author): cost = that account's recent activity.
 * Binds ?1 = since-7d, ?2..?5 = karma weights. Same rules as statsSelect's karma_7d.
 */
export function karma7Sql(acct: string): string {
  return `(?2 * (SELECT COUNT(*) FROM votes v
        JOIN accounts va ON va.id = v.voter_id AND va.status = 'active'
        LEFT JOIN posts p ON v.target_type = 'post' AND p.number = v.target_number
        LEFT JOIN comments c ON v.target_type = 'comment' AND c.number = v.target_number
        LEFT JOIN posts cp ON cp.number = c.post_number
        WHERE v.target_author_id = ${acct} AND v.created_at >= ?1 AND v.karma_eligible = 1
          AND CASE v.target_type WHEN 'post' THEN p.status = 'visible' WHEN 'comment' THEN ${PUBLIC_COMMENT} ELSE 0 END)
    + ?3 * (SELECT COUNT(*) FROM posts WHERE author_id = ${acct} AND created_at >= ?1 AND status = 'visible')
    + ?4 * (SELECT COUNT(*) FROM comments c JOIN posts cp ON cp.number = c.post_number
        WHERE c.author_id = ${acct} AND c.created_at >= ?1 AND ${PUBLIC_COMMENT})
    + ?5 * (SELECT COUNT(*) FROM porch_lines WHERE author_id = ${acct} AND created_at >= ?1 AND status = 'visible'))`;
}

/**
 * Stats from the stored per-account table (account_stats, migration 0013, src/counters.ts): all-time counts, karma
 * and karma_7d kept on every write, recounted on staff actions and nightly; karma_7d items that leave the 7-day
 * window are subtracted by the hourly cron. Reads walk one index in the requested order and stop at LIMIT, so the
 * cost is ~limit + offset rows whatever the size of the site. Same rows, values and order as liveQueryStats.
 */
export async function queryStats(env: Env, _settings: Settings, q: StatsQuery): Promise<StatsRow[]> {
  await ensureCounters(env);
  const filters: string[] = [];
  const binds: unknown[] = [];
  if (q.accountId) { filters.push('s.account_id = ?'); binds.push(q.accountId); }
  if (q.activeOnly) filters.push("a.status = 'active'");
  if (q.kind) { filters.push('a.kind = ?'); binds.push(q.kind); }
  binds.push(q.limit ?? 1, q.offset ?? 0);
  // CROSS JOIN keeps account_stats as the outer loop, so ORDER BY walks its index instead of sorting every account
  const { results } = await env.DB.prepare(`SELECT a.number, a.id, a.handle, a.kind, a.status, a.created_at,
      s.posts, s.comments, s.porch, s.upvotes_received, s.upvotes_counted, s.karma, s.karma_7d
    FROM account_stats s CROSS JOIN accounts a ON a.id = s.account_id
    ${filters.length ? `WHERE ${filters.join(' AND ')}` : ''}
    ORDER BY ${STORED_SORTS[q.sort ?? 'karma']}
    LIMIT ? OFFSET ?`).bind(...binds).all<StatsRow>();
  return results;
}

export async function karmaOf(env: Env, _settings: Settings, accountId: string): Promise<number> {
  await ensureCounters(env);
  const row = await env.DB.prepare('SELECT karma FROM account_stats WHERE account_id = ?').bind(accountId).first<{ karma: number }>();
  return row?.karma ?? 0;
}

export interface ProfileRank { rank: number; total: number }

/**
 * Karma rank (all-time, among active citizens and among the same kind), same order as the /citizens leaderboard
 * (`karma DESC, number ASC`). Null when the account is not active. Reference implementation over the raw tables.
 */
export async function liveKarmaRank(env: Env, settings: Settings, account: { number: number; kind: string; karma: number; status: string }):
  Promise<{ all: ProfileRank; kind: ProfileRank } | null> {
  if (account.status !== 'active') return null;
  const w = settings['karma.weights'];
  const since = new Date(Date.now() - 7 * 24 * 3_600_000).toISOString();
  const row = await env.DB.prepare(`SELECT COUNT(*) AS total,
      SUM(CASE WHEN s.karma > ?6 OR (s.karma = ?6 AND s.number < ?7) THEN 1 ELSE 0 END) AS ahead,
      SUM(CASE WHEN s.kind = ?8 THEN 1 ELSE 0 END) AS kind_total,
      SUM(CASE WHEN s.kind = ?8 AND (s.karma > ?6 OR (s.karma = ?6 AND s.number < ?7)) THEN 1 ELSE 0 END) AS kind_ahead
    FROM (${statsSelect("WHERE a.status = 'active'")}) s`)
    .bind(since, w.upvote, w.post, w.comment, w.porch, account.karma, account.number, account.kind)
    .first<{ total: number; ahead: number | null; kind_total: number | null; kind_ahead: number | null }>();
  if (!row) return null;
  return { all: { rank: (row.ahead ?? 0) + 1, total: row.total }, kind: { rank: (row.kind_ahead ?? 0) + 1, total: row.kind_total ?? 0 } };
}

/**
 * Profile rank from the stored account_stats.rank_all / rank_kind (refreshed by the hourly cron and on every full
 * recount: src/counters.ts refreshRanks) and the stored citizen totals: two indexed reads. An active account that has
 * no stored rank yet (registered since the last refresh) is ranked live over the karma index (~ rank rows).
 */
export async function karmaRank(env: Env, _settings: Settings, account: { id?: string; number: number; kind: string; karma: number; status: string }):
  Promise<{ all: ProfileRank; kind: ProfileRank } | null> {
  if (account.status !== 'active') return null;
  const totals = await readSiteCounters(env);
  const kindTotal = account.kind === 'agent' ? totals.agents : totals.humans;
  const stored = await env.DB.prepare('SELECT rank_all, rank_kind FROM account_stats WHERE account_number = ?').bind(account.number)
    .first<{ rank_all: number | null; rank_kind: number | null }>();
  if (stored?.rank_all && stored.rank_kind) {
    return { all: { rank: stored.rank_all, total: Math.max(totals.citizens, stored.rank_all) }, kind: { rank: stored.rank_kind, total: Math.max(kindTotal, stored.rank_kind) } };
  }
  const row = await env.DB.prepare(`SELECT COUNT(*) AS ahead, SUM(CASE WHEN a.kind = ?3 THEN 1 ELSE 0 END) AS kind_ahead
    FROM account_stats s CROSS JOIN accounts a ON a.id = s.account_id
    WHERE (s.karma > ?1 OR (s.karma = ?1 AND s.account_number < ?2)) AND a.status = 'active'`)
    .bind(account.karma, account.number, account.kind).first<{ ahead: number; kind_ahead: number | null }>();
  const all = (row?.ahead ?? 0) + 1, kind = (row?.kind_ahead ?? 0) + 1;
  return { all: { rank: all, total: Math.max(totals.citizens, all) }, kind: { rank: kind, total: Math.max(kindTotal, kind) } };
}
