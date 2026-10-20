/**
 * AI crawler / agent visit log (agent-SEO plan step 4, our own tool, $0 extra services).
 *
 * Every response the Worker gives to a request whose User-Agent names a known AI crawler or agent
 * (policy/ai-bots.json) adds 1 to an aggregated D1 row: UTC day x bot name x path x status.
 * Stored: the bot NAME from our list, the path without query string, the status, a count. Not stored: IP, full
 * User-Agent, query string, cookies, headers, account. Ordinary visitors (no AI token in the User-Agent) are not
 * recorded at all. Names are what the visitor claimed in its User-Agent (anyone can send "GPTBot"). Each row also keeps
 * Cloudflare's own verdict for that request (verifiedStatus): 'verified' when Cloudflare matched it to a bot in its
 * verified-bot list (request.cf.verifiedBotCategory is set; available on every plan, no Bot Management needed),
 * 'not_verified' when Cloudflare checked and it is not a verified bot, 'unknown' when there is no Cloudflare signal
 * (local dev, tests, rows from before migration 0018). Stored with it: Cloudflare's category string (e.g. 'AI Crawler').
 *
 * The write happens after the response (ctx.waitUntil), so it never slows a page. Guard against floods of fake bot
 * User-Agents: at most WRITES_PER_MINUTE writes per isolate per minute; the rest are skipped (they are only counts).
 * Kept AI_BOT_RETENTION_DAYS days (nightly cron). Read with GET /v1/admin/ai-bots (admin key).
 *
 * Second counter, HEURISTIC and NOT VERIFIED ("unnamed agents", table unnamed_agent_visits): requests that look like a
 * non-browser program but do not name a known AI bot. See classifyUnnamedAgent for the exact rule. Stored: UTC day,
 * a coarse class ('unnamed-agent' | 'generic-http-client'), the HTTP-client family name from our own list (e.g. 'curl',
 * never the User-Agent), path without query, status, count. Same write budget, same 400-day retention.
 */
import botsJson from '../policy/ai-bots.json';
import type { Env } from './env';
import type { Ctx } from './context';
import { requireRole } from './auth';
import { HttpError, json } from './http';

export interface AiBot { name: string; token: string; operator: string; purpose: 'training' | 'search' | 'user' | 'mixed'; match?: boolean; info?: string; evidence?: string; cloudflare_radar?: string | null }
interface HttpClient { family: string; token: string; exact?: boolean }
interface Heuristic { not_agents: string[]; http_clients: HttpClient[] }

export const AI_BOTS: AiBot[] = (botsJson as { bots: AiBot[] }).bots;
const MATCHERS = AI_BOTS.filter((b) => b.match !== false).map((b) => ({ name: b.name, token: b.token.toLowerCase() }));
const BY_NAME = new Map(AI_BOTS.map((b) => [b.name, b]));
export const HEURISTIC: Heuristic = (botsJson as unknown as { heuristic: Heuristic }).heuristic;
const NOT_AGENTS = HEURISTIC.not_agents.map((t) => t.toLowerCase());
const HTTP_CLIENTS = HEURISTIC.http_clients.map((c) => ({ ...c, token: c.token.toLowerCase() }));

export const AI_BOT_RETENTION_DAYS = 400;
export const AI_BOT_PATH_MAX = 200;
export const WRITES_PER_MINUTE = 600;
export const AI_BOT_MAX_DAYS = 400;

/** Bot name for a User-Agent header, or null for everything that is not a listed AI crawler/agent. */
export function matchAiBot(userAgent: string | null | undefined): string | null {
  if (!userAgent) return null;
  const ua = userAgent.slice(0, 512).toLowerCase();
  for (const m of MATCHERS) if (ua.includes(m.token)) return m.name;
  return null;
}

/** Path as stored: no query or fragment, control characters dropped, at most AI_BOT_PATH_MAX chars. */
export function normalizePath(pathname: string): string {
  const clean = pathname.replace(/[\u0000-\u001f\u007f]/g, '') || '/';
  return clean.length > AI_BOT_PATH_MAX ? `${clean.slice(0, AI_BOT_PATH_MAX - 1)}…` : clean;
}

export type Verified = 'verified' | 'not_verified' | 'unknown';
export const VERIFIED_VALUES: Verified[] = ['verified', 'not_verified', 'unknown'];
export const CATEGORY_MAX = 64;

/**
 * Cloudflare's verdict for one request, from request.cf.verifiedBotCategory (a string on every plan: Cloudflare's
 * verified-bot category such as 'AI Crawler', or '' when the request is not from a verified bot). We do NOT use
 * request.cf.botManagement.verifiedBot: without Enterprise Bot Management it is absent or always false.
 * No cf object, or no such field → 'unknown'. Category is kept to printable ASCII, at most CATEGORY_MAX chars.
 */
export function verifiedStatus(cf: unknown): { verified: Verified; category: string } {
  const raw = cf && typeof cf === 'object' ? (cf as { verifiedBotCategory?: unknown }).verifiedBotCategory : undefined;
  if (typeof raw !== 'string') return { verified: 'unknown', category: '' };
  const category = raw.replace(/[^\x20-\x7e]/g, '').trim().slice(0, CATEGORY_MAX);
  return category ? { verified: 'verified', category } : { verified: 'not_verified', category: '' };
}

export type UnnamedClass = 'unnamed-agent' | 'generic-http-client';
export const UNNAMED_CLASSES: UnnamedClass[] = ['unnamed-agent', 'generic-http-client'];
const SEC_FETCH = ['sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest', 'sec-fetch-user'];
const MARKDOWN_PATHS = new Set(['/llms.txt', '/llms-full.txt']);
export const UNNAMED_RULE = 'GET/HEAD, not a named AI bot, not a known search engine / link preview / SEO crawler / uptime monitor, '
  + 'not /health, no Authorization header, no Sec-Fetch-* headers and no Cookie (so not a browser), and then: a known HTTP-client '
  + 'User-Agent family (class generic-http-client), or no Accept-Language, or a request for /llms.txt, /llms-full.txt, *.md or '
  + 'Accept: text/markdown (class unnamed-agent).';

/**
 * Heuristic class for a request that is NOT a named AI bot, or null (= not counted). Conservative on purpose: anything
 * that looks like a browser (any Sec-Fetch-* header, or a Cookie) is never counted, and neither are known search
 * engines, link previews, SEO crawlers, uptime/monitor/heartbeat checks, /health, or API calls with a key.
 */
export function classifyUnnamedAgent(request: Request, path: string): { cls: UnnamedClass; family: string } | null {
  if (request.method !== 'GET' && request.method !== 'HEAD') return null;
  if (path === '/health') return null;
  const h = request.headers;
  if (h.has('authorization') || h.has('cookie')) return null;
  if (SEC_FETCH.some((k) => h.has(k))) return null;
  const ua = (h.get('user-agent') ?? '').slice(0, 512).toLowerCase().trim();
  if (matchAiBot(ua)) return null;
  if (ua && NOT_AGENTS.some((t) => ua.includes(t))) return null;
  for (const c of HTTP_CLIENTS) if (c.exact ? ua === c.token : ua.includes(c.token)) return { cls: 'generic-http-client', family: c.family };
  const markdown = MARKDOWN_PATHS.has(path) || path.endsWith('.md') || (h.get('accept') ?? '').toLowerCase().includes('text/markdown');
  if (markdown || !h.has('accept-language')) return { cls: 'unnamed-agent', family: '' };
  return null;
}

export async function recordUnnamedAgentVisit(env: Env, cls: UnnamedClass, family: string, path: string, status: number, now = Date.now()): Promise<void> {
  const day = new Date(now).toISOString().slice(0, 10);
  await env.DB.prepare(`INSERT INTO unnamed_agent_visits (day, class, family, path, status, count) VALUES (?, ?, ?, ?, ?, 1)
    ON CONFLICT(day, class, family, path, status) DO UPDATE SET count = count + 1`).bind(day, cls, family, normalizePath(path), status).run();
}

let windowStart = 0;
let windowWrites = 0;
/** Per-isolate write budget (resets every minute). Exported for tests. */
export function takeWriteBudget(now = Date.now()): boolean {
  if (now - windowStart >= 60_000) { windowStart = now; windowWrites = 0; }
  if (windowWrites >= WRITES_PER_MINUTE) return false;
  windowWrites += 1;
  return true;
}
export function resetWriteBudget(): void { windowStart = 0; windowWrites = 0; }

export async function recordAiBotVisit(env: Env, bot: string, path: string, status: number, now = Date.now(),
  v: { verified: Verified; category: string } = { verified: 'unknown', category: '' }): Promise<void> {
  const day = new Date(now).toISOString().slice(0, 10);
  await env.DB.prepare(`INSERT INTO ai_bot_visits (day, bot, verified, category, path, status, count) VALUES (?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(day, bot, verified, category, path, status) DO UPDATE SET count = count + 1`)
    .bind(day, bot, v.verified, v.category, normalizePath(path), status).run();
}

/** Called from the fetch handler with the final response. Never throws, never delays the response. */
export function logAiBotVisit(request: Request, response: Response, env: Env, exec: ExecutionContext): void {
  const bot = matchAiBot(request.headers.get('user-agent'));
  const path = new URL(request.url).pathname;
  if (bot) {
    if (!takeWriteBudget()) return;
    const v = verifiedStatus((request as { cf?: unknown }).cf);
    exec.waitUntil(recordAiBotVisit(env, bot, path, response.status, Date.now(), v).catch((error) => console.error('ai-bot log failed', String(error))));
    return;
  }
  const unnamed = classifyUnnamedAgent(request, path);
  if (!unnamed || !takeWriteBudget()) return;
  exec.waitUntil(recordUnnamedAgentVisit(env, unnamed.cls, unnamed.family, path, response.status)
    .catch((error) => console.error('unnamed-agent log failed', String(error))));
}

export async function pruneAiBotVisits(env: Env, now = Date.now()): Promise<number> {
  const cutoffDay = new Date(now - AI_BOT_RETENTION_DAYS * 86_400_000).toISOString().slice(0, 10);
  const [named, unnamed] = await env.DB.batch([
    env.DB.prepare('DELETE FROM ai_bot_visits WHERE day < ?').bind(cutoffDay),
    env.DB.prepare('DELETE FROM unnamed_agent_visits WHERE day < ?').bind(cutoffDay),
  ]);
  return (named.meta.changes ?? 0) + (unnamed.meta.changes ?? 0);
}

export const VERIFIED_NOTE = 'Bot names come from the User-Agent header (claimed by the visitor). verified = Cloudflare matched the request to that '
  + 'kind of bot in its verified-bot list (request.cf.verifiedBotCategory; category = Cloudflare\'s label); not_verified = Cloudflare checked and it '
  + 'is not a verified bot: for a bot with cloudflare_radar null (Cloudflare does not list it) that is expected even when genuine, for a listed bot it '
  + 'suggests a fake name; unknown = no Cloudflare signal (rows before 2026-10-18, local runs). Stored per UTC day: bot name, verified, category, '
  + 'path, status, count. No IPs, no full User-Agents, no query strings.';

/**
 * GET /v1/admin/ai-bots?days=30&bot=GPTBot&limit=100 (admin key).
 * days 1-400 (default 30, counted back from today UTC, today included); bot = one name from the list (optional);
 * verified = verified | not_verified | unknown (optional).
 */
export async function adminAiBots(c: Ctx): Promise<Response> {
  requireRole(c.principal, 'admin');
  const daysRaw = c.url.searchParams.get('days');
  const days = daysRaw === null ? 30 : Number(daysRaw);
  if (!Number.isInteger(days) || days < 1 || days > AI_BOT_MAX_DAYS) throw new HttpError(400, 'invalid_days', { min: 1, max: AI_BOT_MAX_DAYS });
  const limitRaw = c.url.searchParams.get('limit');
  const limit = limitRaw === null ? 100 : Number(limitRaw);
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new HttpError(400, 'invalid_limit', { min: 1, max: 500 });
  const bot = c.url.searchParams.get('bot');
  if (bot !== null && !BY_NAME.has(bot)) throw new HttpError(400, 'unknown_bot', { known: AI_BOTS.map((b) => b.name) });
  const verified = c.url.searchParams.get('verified');
  if (verified !== null && !VERIFIED_VALUES.includes(verified as Verified)) throw new HttpError(400, 'invalid_verified', { allowed: VERIFIED_VALUES });

  const to = new Date().toISOString().slice(0, 10);
  const from = new Date(Date.now() - (days - 1) * 86_400_000).toISOString().slice(0, 10);
  let where = 'day >= ? AND day <= ?';
  const args: string[] = [from, to];
  if (bot) { where += ' AND bot = ?'; args.push(bot); }
  if (verified) { where += ' AND verified = ?'; args.push(verified); }
  const split = `SUM(CASE WHEN verified = 'verified' THEN count ELSE 0 END) AS verified_hits,
    SUM(CASE WHEN verified = 'not_verified' THEN count ELSE 0 END) AS not_verified_hits,
    SUM(CASE WHEN verified = 'unknown' THEN count ELSE 0 END) AS unknown_hits`;
  const [totals, byDay, paths, cats, uTotals, uByDay, uPaths] = await c.env.DB.batch([
    c.env.DB.prepare(`SELECT bot, SUM(count) AS hits, ${split}, COUNT(DISTINCT path) AS paths FROM ai_bot_visits WHERE ${where} GROUP BY bot ORDER BY hits DESC, bot`).bind(...args),
    c.env.DB.prepare(`SELECT day, bot, SUM(count) AS hits, ${split} FROM ai_bot_visits WHERE ${where} GROUP BY day, bot ORDER BY day DESC, hits DESC, bot`).bind(...args),
    c.env.DB.prepare(`SELECT bot, verified, path, status, SUM(count) AS hits FROM ai_bot_visits WHERE ${where} GROUP BY bot, verified, path, status ORDER BY hits DESC, bot, verified, path LIMIT ?`).bind(...args, limit),
    c.env.DB.prepare(`SELECT bot, category, SUM(count) AS hits FROM ai_bot_visits WHERE ${where} AND verified = 'verified' GROUP BY bot, category ORDER BY hits DESC, bot, category`).bind(...args),
    // second counter (heuristic, not verified): not filtered by ?bot=
    c.env.DB.prepare('SELECT class, family, SUM(count) AS hits, COUNT(DISTINCT path) AS paths FROM unnamed_agent_visits WHERE day >= ? AND day <= ? GROUP BY class, family ORDER BY hits DESC, class, family').bind(from, to),
    c.env.DB.prepare('SELECT day, class, SUM(count) AS hits FROM unnamed_agent_visits WHERE day >= ? AND day <= ? GROUP BY day, class ORDER BY day DESC, hits DESC, class').bind(from, to),
    c.env.DB.prepare('SELECT class, family, path, status, SUM(count) AS hits FROM unnamed_agent_visits WHERE day >= ? AND day <= ? GROUP BY class, family, path, status ORDER BY hits DESC, class, family, path LIMIT ?').bind(from, to, limit),
  ]);
  const uRows = uTotals.results as { class: string; family: string; hits: number; paths: number }[];
  const meta = (name: string) => { const b = BY_NAME.get(name); return { operator: b?.operator ?? null, purpose: b?.purpose ?? null, cloudflare_radar: b?.cloudflare_radar ?? null }; };
  type Split = { hits: number; verified_hits: number; not_verified_hits: number; unknown_hits: number };
  const catRows = cats.results as { bot: string; category: string; hits: number }[];
  const botRows = (totals.results as (Split & { bot: string; paths: number })[]).map((r) => ({
    bot: r.bot, ...meta(r.bot), hits: r.hits, verified_hits: r.verified_hits, not_verified_hits: r.not_verified_hits, unknown_hits: r.unknown_hits,
    categories: catRows.filter((x) => x.bot === r.bot).map((x) => ({ category: x.category, hits: x.hits })), paths: r.paths,
  }));
  const sum = (k: keyof Split) => botRows.reduce((s, r) => s + r[k], 0);
  return json(200, {
    from, to, days, bot, verified,
    total_hits: sum('hits'),
    verified_hits: sum('verified_hits'),
    not_verified_hits: sum('not_verified_hits'),
    unknown_hits: sum('unknown_hits'),
    bots: botRows,
    by_day: byDay.results,
    top_paths: paths.results,
    note: VERIFIED_NOTE,
    list: { version: (botsJson as { version: string }).version, bots: AI_BOTS.length },
    unnamed_agents: {
      label: 'heuristic, not verified',
      rule: UNNAMED_RULE,
      total_hits: uRows.reduce((s, r) => s + r.hits, 0),
      classes: uRows,
      by_day: uByDay.results,
      top_paths: uPaths.results,
      note: 'Guesses from request headers, not identities: a hand-written script, a monitor we do not know, or a privacy tool can land here, and agents that imitate a browser do not. family is the HTTP-client name from our list (\'\' when none matched), never the User-Agent. No IPs, no full User-Agents, no query strings. Not filtered by ?bot=.',
    },
  });
}
