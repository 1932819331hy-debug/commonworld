import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import worker from '../src/index';
import botsJson from '../policy/ai-bots.json';
import { AI_BOTS, AI_BOT_PATH_MAX, CATEGORY_MAX, verifiedStatus, AI_BOT_RETENTION_DAYS, HEURISTIC, WRITES_PER_MINUTE, classifyUnnamedAgent, matchAiBot, normalizePath, pruneAiBotVisits, resetWriteBudget, takeWriteBudget } from '../src/ai-bots';
import { api, makeAdmin, register, resetDb } from './helpers';

beforeEach(async () => { await resetDb(); resetWriteBudget(); });

/** Real-world User-Agent strings (as published by the operators). */
const SAMPLES: [string, string | null][] = [
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)', 'GPTBot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot', 'OAI-SearchBot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot', 'ChatGPT-User'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)', 'ClaudeBot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)', 'Claude-User'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)', 'PerplexityBot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)', 'Perplexity-User'],
  ['Mozilla/5.0 (compatible; GoogleOther)', 'GoogleOther'],
  ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 Safari/605.1.15 (Applebot/0.1; +http://www.apple.com/go/applebot)', 'Applebot'],
  ['Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)', 'Bytespider'],
  ['CCBot/2.0 (https://commoncrawl.org/faq/)', 'CCBot'],
  ['meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)', 'Meta-ExternalAgent'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot) Chrome/119.0.6045.214 Safari/537.36', 'Amazonbot'],
  ['DuckAssistBot/1.2; (+http://duckduckgo.com/duckassistbot.html)', 'DuckAssistBot'],
  ['Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko; compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent) Chrome/141.0.0.0 Safari/537.36', 'Google-Agent'],
  ['Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 (compatible; Google-GeminiNotebook; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-gemininotebook)', 'Google-GeminiNotebook'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; KimiBot/1.0; +https://www.kimi.com/policies/kimi-crawlers', 'KimiBot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Kimi-User/1.0; +https://www.kimi.com/policies/kimi-crawlers', 'Kimi-User'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Kimi-SearchBot/1.0; +https://www.kimi.com/policies/kimi-crawlers', 'Kimi-SearchBot'],
  ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36; Manus-User/1.0', 'Manus-User'],
  ['Mozilla/5.0 (compatible; ImagesiftBot; +imagesift.com)', 'ImagesiftBot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Bravebot/1.0; +https://search.brave.com/help/brave-search-crawler) Chrome/141.0.0.0 Safari/537.36', 'Bravebot'],
  ['Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; TikTokSpider; ttspider-feedback@tiktok.com)', 'TikTokSpider'],
  ['Timpibot/1.0 (+http://timpi.io/crawler)', 'Timpibot'],
  ['Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; MistralAI-User/1.0; +https://docs.mistral.ai/robots)', 'MistralAI-User'],
  // ordinary browsers and classic search crawlers are never recorded
  ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36', null],
  ['Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1', null],
  ['Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)', null],
  ['curl/8.5.0', null],
];

async function visit(path: string, ua: string | null, cf?: Record<string, unknown>) {
  const ctx = createExecutionContext();
  const headers: Record<string, string> = ua ? { 'user-agent': ua } : {};
  const res = await worker.fetch(new Request(`https://api.test${path}`, cf ? { headers, cf } as any : { headers }), env as any, ctx);
  await res.arrayBuffer();
  await waitOnExecutionContext(ctx);
  return res;
}
const rows = async () => (await env.DB.prepare('SELECT day, bot, path, status, count FROM ai_bot_visits ORDER BY bot, path, status').all<any>()).results;

describe('policy/ai-bots.json', () => {
  it('has unique names and tokens, known purposes, a version', () => {
    expect((botsJson as any).version).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const names = AI_BOTS.map((b) => b.name);
    const tokens = AI_BOTS.map((b) => b.token.toLowerCase());
    expect(new Set(names).size).toBe(names.length);
    expect(new Set(tokens).size).toBe(tokens.length);
    for (const b of AI_BOTS) {
      expect(b.token.trim()).toBe(b.token);
      expect(b.token.length).toBeGreaterThan(2);
      expect(['training', 'search', 'user', 'mixed']).toContain(b.purpose);
      expect(b.operator).toBeTruthy();
      expect(b.info, `${b.name} needs a source URL`).toMatch(/^https:\/\//);
      expect(b.evidence, `${b.name} needs evidence`).toBeTruthy();
    }
  });

  it('a more specific token is never shadowed by an earlier, shorter one', () => {
    const active = AI_BOTS.filter((b) => b.match !== false);
    active.forEach((b, i) => {
      for (const earlier of active.slice(0, i)) expect(b.token.toLowerCase().includes(earlier.token.toLowerCase()), `${earlier.name} shadows ${b.name}`).toBe(false);
    });
  });

  it('lists every AI agent named in robots.txt', async () => {
    const text = await (await worker.fetch(new Request('https://api.test/robots.txt'), env as any, createExecutionContext())).text();
    const named = [...text.matchAll(/^User-agent: (.+)$/gm)].map((m) => m[1].trim()).filter((a) => a !== '*');
    expect(named.length).toBeGreaterThan(5);
    const tokens = new Set(AI_BOTS.map((b) => b.token.toLowerCase()));
    for (const a of named) expect(tokens.has(a.toLowerCase()), `robots.txt names ${a}`).toBe(true);
  });

  it('matches real User-Agent strings and ignores browsers, Googlebot and curl', () => {
    for (const [ua, bot] of SAMPLES) expect(matchAiBot(ua), ua).toBe(bot);
    expect(matchAiBot(null)).toBeNull();
    expect(matchAiBot('')).toBeNull();
  });

  it('robots-only tokens (Google-Extended, Applebot-Extended) are never counted as visitors', () => {
    expect(matchAiBot('Google-Extended')).toBeNull();
    expect(matchAiBot('Applebot-Extended/1.0')).toBe('Applebot');
  });
});

describe('AI bot visit log', () => {
  it('counts AI bot visits per day, bot, path and status; ordinary visitors leave nothing', async () => {
    const gpt = SAMPLES[0][0];
    await visit('/health', gpt);
    await visit('/health?secret=abc', gpt);
    await visit('/no-such-page', gpt);
    await visit('/v1/posts', SAMPLES[3][0]);
    await visit('/health', SAMPLES.find(([, b]) => b === null)![0]);
    await visit('/health', null);
    const day = new Date().toISOString().slice(0, 10);
    expect(await rows()).toEqual([
      { day, bot: 'ClaudeBot', path: '/v1/posts', status: 200, count: 1 },
      { day, bot: 'GPTBot', path: '/health', status: 200, count: 2 },
      { day, bot: 'GPTBot', path: '/no-such-page', status: 404, count: 1 },
    ]);
  });

  it('stores no IP, no User-Agent, no query string', async () => {
    await visit('/health?token=cwl_secret', `${SAMPLES[0][0]} extra-identifying-bits`);
    const cols = (await env.DB.prepare('PRAGMA table_info(ai_bot_visits)').all<{ name: string }>()).results.map((c) => c.name);
    expect(cols).toEqual(['day', 'bot', 'verified', 'category', 'path', 'status', 'count']);
    const dump = JSON.stringify(await rows());
    expect(dump).not.toContain('cwl_secret');
    expect(dump).not.toContain('extra-identifying-bits');
    expect(dump).not.toContain('Mozilla');
  });

  it('caps the stored path and drops control characters', () => {
    expect(normalizePath('/a\u0000b\nc')).toBe('/abc');
    const long = normalizePath(`/${'x'.repeat(500)}`);
    expect(long.length).toBe(AI_BOT_PATH_MAX);
    expect(long.endsWith('…')).toBe(true);
  });

  it('stops writing above the per-isolate budget', () => {
    const t = 1_000_000;
    for (let i = 0; i < WRITES_PER_MINUTE; i++) expect(takeWriteBudget(t)).toBe(true);
    expect(takeWriteBudget(t + 1)).toBe(false);
    expect(takeWriteBudget(t + 60_000)).toBe(true);
  });

  it('nightly prune keeps 400 days', async () => {
    const now = Date.parse('2026-10-17T03:17:00Z');
    const day = (d: number) => new Date(now - d * 86_400_000).toISOString().slice(0, 10);
    await env.DB.batch([401, 400, 10].map((d) => env.DB.prepare("INSERT INTO ai_bot_visits (day, bot, path, status, count) VALUES (?, 'GPTBot', '/', 200, 1)").bind(day(d))));
    expect(AI_BOT_RETENTION_DAYS).toBe(400);
    expect(await pruneAiBotVisits(env as any, now)).toBe(1);
    expect((await rows()).length).toBe(2);
  });
});

describe('GET /v1/admin/ai-bots', () => {
  it('admin only', async () => {
    expect((await api('/v1/admin/ai-bots')).status).toBe(401);
    const citizen = await register();
    expect((await api('/v1/admin/ai-bots', { key: citizen.key })).status).toBe(403);
  });

  it('returns totals, per-day rows and top paths; validates params', async () => {
    const admin = await makeAdmin();
    await visit('/health', SAMPLES[0][0]);
    await visit('/health', SAMPLES[0][0]);
    await visit('/llms.txt', SAMPLES[5][0]);
    const res = await api('/v1/admin/ai-bots?days=7', { key: admin.key });
    expect(res.status).toBe(200);
    expect(res.headers.get('cache-control')).toBe('no-store');
    expect(res.body.total_hits).toBe(3);
    expect(res.body.bots[0]).toEqual({ bot: 'GPTBot', operator: 'OpenAI', purpose: 'training', cloudflare_radar: 'gptbot', hits: 2, verified_hits: 0, not_verified_hits: 0, unknown_hits: 2, categories: [], paths: 1 });
    expect(res.body.top_paths[0]).toEqual({ bot: 'GPTBot', verified: 'unknown', path: '/health', status: 200, hits: 2 });
    expect(res.body.unknown_hits).toBe(3);
    expect(res.body.by_day).toHaveLength(2);
    const one = await api('/v1/admin/ai-bots?bot=PerplexityBot', { key: admin.key });
    expect(one.body.total_hits).toBe(1);
    expect(one.body.bot).toBe('PerplexityBot');
    expect((await api('/v1/admin/ai-bots?days=0', { key: admin.key })).body.error.code).toBe('invalid_days');
    expect((await api('/v1/admin/ai-bots?days=401', { key: admin.key })).status).toBe(400);
    expect((await api('/v1/admin/ai-bots?bot=Nope', { key: admin.key })).body.error.code).toBe('unknown_bot');
    expect((await api('/v1/admin/ai-bots?limit=9999', { key: admin.key })).body.error.code).toBe('invalid_limit');
    expect((await api('/v1/admin/ai-bots?verified=yes', { key: admin.key })).body.error.code).toBe('invalid_verified');
  });
});

describe('Cloudflare verified-bot signal', () => {
  it('reads request.cf.verifiedBotCategory: set = verified, empty = not_verified, missing = unknown', () => {
    expect(verifiedStatus({ verifiedBotCategory: 'AI Crawler' })).toEqual({ verified: 'verified', category: 'AI Crawler' });
    expect(verifiedStatus({ verifiedBotCategory: '' })).toEqual({ verified: 'not_verified', category: '' });
    expect(verifiedStatus({ verifiedBotCategory: '   ' })).toEqual({ verified: 'not_verified', category: '' });
    expect(verifiedStatus({ asn: 13335 })).toEqual({ verified: 'unknown', category: '' });
    expect(verifiedStatus(undefined)).toEqual({ verified: 'unknown', category: '' });
    expect(verifiedStatus({ verifiedBotCategory: 7 })).toEqual({ verified: 'unknown', category: '' });
    // botManagement.verifiedBot is ignored (absent or always false without Enterprise Bot Management)
    expect(verifiedStatus({ botManagement: { verifiedBot: true } })).toEqual({ verified: 'unknown', category: '' });
    const long = verifiedStatus({ verifiedBotCategory: `AI\u0000 ${'x'.repeat(200)}` });
    expect(long.verified).toBe('verified');
    expect(long.category.length).toBe(CATEGORY_MAX);
    expect(long.category).not.toContain('\u0000');
  });

  it('stores the verdict per row and splits counts per bot in the admin answer', async () => {
    const admin = await makeAdmin();
    const gpt = SAMPLES[0][0];
    await visit('/llms.txt', gpt, { verifiedBotCategory: 'AI Crawler' });
    await visit('/llms.txt', gpt, { verifiedBotCategory: 'AI Crawler' });
    await visit('/llms.txt', gpt, { verifiedBotCategory: '' });
    await visit('/llms.txt', gpt);
    await visit('/', SAMPLES.find(([, b]) => b === 'KimiBot')![0], { verifiedBotCategory: '' });
    const day = new Date().toISOString().slice(0, 10);
    const all = (await env.DB.prepare('SELECT day, bot, verified, category, path, status, count FROM ai_bot_visits ORDER BY bot, verified').all<any>()).results;
    expect(all).toEqual([
      { day, bot: 'GPTBot', verified: 'not_verified', category: '', path: '/llms.txt', status: 200, count: 1 },
      { day, bot: 'GPTBot', verified: 'unknown', category: '', path: '/llms.txt', status: 200, count: 1 },
      { day, bot: 'GPTBot', verified: 'verified', category: 'AI Crawler', path: '/llms.txt', status: 200, count: 2 },
      { day, bot: 'KimiBot', verified: 'not_verified', category: '', path: '/', status: 200, count: 1 },
    ]);
    const res = await api('/v1/admin/ai-bots?days=1', { key: admin.key });
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ total_hits: 5, verified_hits: 2, not_verified_hits: 2, unknown_hits: 1, verified: null });
    expect(res.body.bots[0]).toEqual({ bot: 'GPTBot', operator: 'OpenAI', purpose: 'training', cloudflare_radar: 'gptbot', hits: 4, verified_hits: 2, not_verified_hits: 1, unknown_hits: 1,
      categories: [{ category: 'AI Crawler', hits: 2 }], paths: 1 });
    expect(res.body.by_day[0]).toEqual({ day, bot: 'GPTBot', hits: 4, verified_hits: 2, not_verified_hits: 1, unknown_hits: 1 });
    expect(res.body.note).toContain('cloudflare_radar');
    const only = await api('/v1/admin/ai-bots?days=1&verified=verified', { key: admin.key });
    expect(only.body).toMatchObject({ total_hits: 2, verified_hits: 2, not_verified_hits: 0, verified: 'verified' });
    expect(only.body.bots.map((b: any) => b.bot)).toEqual(['GPTBot']);
  });

  it('every bot names its Cloudflare Radar slug or null; robots-only tokens are null', () => {
    for (const b of AI_BOTS) {
      expect(Object.hasOwn(b, 'cloudflare_radar'), b.name).toBe(true);
      if (b.cloudflare_radar !== null) expect(b.cloudflare_radar, b.name).toMatch(/^[a-z0-9-]+$/);
      if (b.match === false) expect(b.cloudflare_radar, b.name).toBeNull();
    }
    const slugs = AI_BOTS.map((b) => b.cloudflare_radar).filter(Boolean);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('migration 0018 keeps old rows as unknown', async () => {
    await env.DB.prepare("INSERT INTO ai_bot_visits (day, bot, path, status, count) VALUES ('2026-10-01', 'GPTBot', '/', 200, 3)").run();
    const r = await env.DB.prepare("SELECT verified, category FROM ai_bot_visits WHERE day = '2026-10-01'").first<any>();
    expect(r).toEqual({ verified: 'unknown', category: '' });
  });
});

/** Request helpers for the heuristic counter. */
const BROWSER = { 'user-agent': SAMPLES.find(([, b]) => b === null)![0], 'accept-language': 'en-US,en;q=0.9', 'sec-fetch-site': 'none', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document' };
const req = (path: string, headers: Record<string, string> = {}, method = 'GET') => new Request(`https://api.test${path}`, { method, headers });
const cls = (path: string, headers: Record<string, string> = {}, method = 'GET') => classifyUnnamedAgent(req(path, headers, method), path);
async function visitWith(path: string, headers: Record<string, string>) {
  const ctx = createExecutionContext();
  const res = await worker.fetch(req(path, headers), env as any, ctx);
  await res.arrayBuffer();
  await waitOnExecutionContext(ctx);
  return res;
}
const unnamedRows = async () => (await env.DB.prepare('SELECT day, class, family, path, status, count FROM unnamed_agent_visits ORDER BY class, family, path, status').all<any>()).results;

describe('unnamed agents (heuristic, not verified)', () => {
  it('generic HTTP clients are classed by family token only', () => {
    expect(cls('/llms.txt', { 'user-agent': 'curl/8.5.0' })).toEqual({ cls: 'generic-http-client', family: 'curl' });
    expect(cls('/', { 'user-agent': 'python-requests/2.32.3' })).toEqual({ cls: 'generic-http-client', family: 'python-requests' });
    expect(cls('/', { 'user-agent': 'Go-http-client/1.1' })).toEqual({ cls: 'generic-http-client', family: 'go-http-client' });
    expect(cls('/', { 'user-agent': 'node' })).toEqual({ cls: 'generic-http-client', family: 'node' });
    expect(cls('/', { 'user-agent': 'node-fetch/1.0 (+https://github.com/bitinn/node-fetch)' })).toEqual({ cls: 'generic-http-client', family: 'node-fetch' });
    expect(cls('/', { 'user-agent': 'nodejs-something' })).toEqual({ cls: 'unnamed-agent', family: '' });
  });

  it('headless requests and markdown/llms requests count as unnamed-agent', () => {
    expect(cls('/', {})).toEqual({ cls: 'unnamed-agent', family: '' });
    expect(cls('/', { 'user-agent': 'MyResearchAgent/0.1' })).toEqual({ cls: 'unnamed-agent', family: '' });
    const withLang = { 'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0.0.0 Safari/537.36', 'accept-language': 'en' };
    expect(cls('/', withLang)).toBeNull();
    expect(cls('/llms-full.txt', withLang)).toEqual({ cls: 'unnamed-agent', family: '' });
    expect(cls('/post/1.md', withLang)).toEqual({ cls: 'unnamed-agent', family: '' });
    expect(cls('/', { ...withLang, accept: 'text/markdown, text/html;q=0.5' })).toEqual({ cls: 'unnamed-agent', family: '' });
  });

  it('browsers, cookies, keys, named AI bots, search engines, monitors, /health and writes are never counted', () => {
    expect(cls('/llms.txt', BROWSER)).toBeNull();
    expect(cls('/llms.txt', { 'user-agent': 'curl/8.5.0', 'sec-fetch-mode': 'navigate' })).toBeNull();
    expect(cls('/', { 'user-agent': 'curl/8.5.0', cookie: 'a=b' })).toBeNull();
    expect(cls('/v1/posts', { 'user-agent': 'curl/8.5.0', authorization: 'Bearer cwk_x' })).toBeNull();
    expect(cls('/llms.txt', { 'user-agent': SAMPLES[0][0] })).toBeNull();
    for (const ua of ['Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)', 'Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)',
      'Mozilla/5.0 (compatible; YandexBot/3.0)', 'Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)', 'Pingdom.com_bot_version_1.4',
      'commonworld-heartbeat/1', 'CommonworldTrust/0.1 (+https://github.com/commonworld-one/commonworld/blob/main/TRUST.md)', 'Better Stack Better Uptime Bot Mozilla/5.0', 'facebookexternalhit/1.1', 'Mozilla/5.0 (compatible; AhrefsBot/7.0)']) {
      expect(cls('/llms.txt', { 'user-agent': ua }), ua).toBeNull();
    }
    expect(cls('/health', {})).toBeNull();
    expect(cls('/', { 'user-agent': 'curl/8.5.0' }, 'POST')).toBeNull();
    expect(cls('/', { 'user-agent': 'curl/8.5.0' }, 'HEAD')).toEqual({ cls: 'generic-http-client', family: 'curl' });
  });

  it('list sanity: not_agents never hides a named AI bot sample, families are unique', () => {
    const fam = HEURISTIC.http_clients.map((c) => c.family);
    expect(new Set(fam).size).toBe(fam.length);
    for (const [ua, bot] of SAMPLES) if (bot) expect(classifyUnnamedAgent(req('/llms.txt', { 'user-agent': ua }), '/llms.txt')).toBeNull();
  });

  it('writes day, class, family, path, status, count only; named bots go to the other table', async () => {
    await visitWith('/llms.txt?x=cwl_secret', { 'user-agent': 'curl/8.5.0 extra-identifying-bits' });
    await visitWith('/llms.txt', { 'user-agent': 'curl/8.5.0' });
    await visitWith('/no-such-page', { 'user-agent': 'MyResearchAgent/0.1' });
    await visitWith('/llms.txt', BROWSER);
    await visitWith('/llms.txt', { 'user-agent': SAMPLES[0][0] });
    const day = new Date().toISOString().slice(0, 10);
    expect(await unnamedRows()).toEqual([
      { day, class: 'generic-http-client', family: 'curl', path: '/llms.txt', status: 200, count: 2 },
      { day, class: 'unnamed-agent', family: '', path: '/no-such-page', status: 404, count: 1 },
    ]);
    expect((await rows()).map((r: any) => r.bot)).toEqual(['GPTBot']);
    const cols = (await env.DB.prepare('PRAGMA table_info(unnamed_agent_visits)').all<{ name: string }>()).results.map((c) => c.name);
    expect(cols).toEqual(['day', 'class', 'family', 'path', 'status', 'count']);
    const dump = JSON.stringify(await unnamedRows());
    expect(dump).not.toContain('cwl_secret');
    expect(dump).not.toContain('extra-identifying-bits');
    expect(dump).not.toContain('8.5.0');
  });

  it('shares the write budget and the 400-day prune', async () => {
    resetWriteBudget();
    const t = Date.now();
    for (let i = 0; i < WRITES_PER_MINUTE; i++) takeWriteBudget(t);
    await visitWith('/llms.txt', { 'user-agent': 'curl/8.5.0' });
    expect(await unnamedRows()).toEqual([]);
    resetWriteBudget();
    const now = Date.parse('2026-10-17T03:17:00Z');
    const day = (d: number) => new Date(now - d * 86_400_000).toISOString().slice(0, 10);
    await env.DB.batch([401, 10].map((d) => env.DB.prepare("INSERT INTO unnamed_agent_visits (day, class, family, path, status, count) VALUES (?, 'unnamed-agent', '', '/', 200, 1)").bind(day(d))));
    expect(await pruneAiBotVisits(env as any, now)).toBe(1);
    expect((await unnamedRows()).length).toBe(1);
  });

  it('admin endpoint shows a separate section labelled heuristic, not verified', async () => {
    const admin = await makeAdmin();
    await visitWith('/llms.txt', { 'user-agent': 'curl/8.5.0' });
    await visitWith('/', { 'user-agent': 'MyResearchAgent/0.1' });
    await visitWith('/llms.txt', { 'user-agent': SAMPLES[0][0] });
    const res = await api('/v1/admin/ai-bots?days=7', { key: admin.key });
    expect(res.status).toBe(200);
    expect(res.body.total_hits).toBe(1);
    const u = res.body.unnamed_agents;
    expect(u.label).toBe('heuristic, not verified');
    expect(u.total_hits).toBe(2);
    expect(u.classes).toEqual(expect.arrayContaining([{ class: 'generic-http-client', family: 'curl', hits: 1, paths: 1 }, { class: 'unnamed-agent', family: '', hits: 1, paths: 1 }]));
    expect(u.top_paths).toEqual(expect.arrayContaining([{ class: 'generic-http-client', family: 'curl', path: '/llms.txt', status: 200, hits: 1 }]));
    expect(u.by_day).toHaveLength(2);
    expect(u.rule).toContain('Sec-Fetch');
    // the admin call itself carries a key, so it is never counted
    expect((await unnamedRows()).reduce((s: number, r: any) => s + r.count, 0)).toBe(2);
  });
});
