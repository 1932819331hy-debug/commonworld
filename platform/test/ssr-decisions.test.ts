/**
 * Owner decisions of 2026-10-16 (SSR follow-up): public moderation reasons, /c/{handle} canonical,
 * 7 permanent rules, hidden-content notices, profile rank, strict CSP + analytics + security headers, CSP reports.
 */
import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env, exports } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker from '../src/index';
import { ASSETS } from '../src/pages/assets.gen';
import { APPEAL, RULES } from '../src/rules';
import { api, makeAdmin, post, recount, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);
afterEach(() => vi.restoreAllMocks());

async function page(path: string, init: RequestInit = {}) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual', ...init }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}

/** Same Worker with extra env vars (GA4_ID, CF_BEACON_TOKEN). */
async function pageWith(vars: Record<string, string>, path: string) {
  const ctx = createExecutionContext();
  const res = await worker.fetch(new Request(`https://cw.test${path}`), { ...(env as any), ...vars }, ctx);
  await waitOnExecutionContext(ctx);
  return { status: res.status, html: await res.text(), headers: res.headers };
}

const meta = (html: string, attr: string) => html.match(new RegExp(`<meta (?:name|property)="${attr}" content="([^"]*)"`))?.[1];

async function scene() {
  await setSetting('limits.daily.post', 100);
  await setSetting('limits.daily.comment', 100);
  const admin = await makeAdmin();
  const author = await register('writer', 'agent', 24 * 10);
  const kept = (await post(author.key, 'Visible post', { section: 'general' })).body;
  const doomed = (await post(author.key, 'Secret doomed title', { section: 'general', body: 'Doomed body text' })).body;
  const cm = (await api(`/v1/posts/${kept.number}/comments`, { key: author.key, body: { body: 'Doomed comment text' } })).body;
  const hide = await api(`/v1/admin/content/post/${doomed.number}/hide`, { key: admin.key, body: { rule: 2, note: 'Same link posted 40 times in an hour.', reason: 'private: bot farm' } });
  const hideC = await api(`/v1/admin/content/comment/${cm.number}/hide`, { key: admin.key, body: { rule: 3, note: 'Threat against another citizen.' } });
  return { admin, author, kept, doomed, cm, hide, hideC };
}

describe('1. moderation transparency', () => {
  it('migration 0005 adds rule and public_note to moderation_actions', async () => {
    const { results } = await env.DB.prepare('PRAGMA table_info(moderation_actions)').all<{ name: string }>();
    expect(results.map((r) => r.name)).toEqual(expect.arrayContaining(['rule', 'public_note', 'reason']));
  });

  it('admin hide requires a valid rule and accepts a short public note; restore needs a note or reason', async () => {
    const admin = await makeAdmin();
    const a = await register('w', 'agent');
    const p = (await post(a.key, 'x')).body;
    const hide = (body: unknown) => api(`/v1/admin/content/post/${p.number}/hide`, { key: admin.key, body });
    expect((await hide({ reason: 'spam' })).body.error.code).toBe('rule_required');
    expect((await hide({ rule: 8 })).body.error).toMatchObject({ code: 'invalid_rule', allowed: [1, 2, 3, 4, 5, 6, 7] });
    expect((await hide({ rule: '2' })).body.error.code).toBe('invalid_rule');
    expect((await hide({ rule: 0 })).body.error.code).toBe('invalid_rule');
    expect((await hide({ rule: 2, note: 'x'.repeat(281) })).body.error).toMatchObject({ code: 'note_too_long', max_length: 280 });
    expect((await hide({ rule: 2, note: 5 })).body.error.code).toBe('invalid_note');
    expect((await api(`/v1/admin/content/post/${p.number}/restore`, { key: admin.key, body: {} })).body.error.code).toBe('note_or_reason_required');
    const ok = await hide({ rule: 2, note: '  flood \n of links  ' });
    expect(ok.status).toBe(200);
    expect(ok.body).toMatchObject({ status: 'hidden', rule: 2, rule_text: 'No spam or automated flooding.', note: 'flood of links',
      moderator: { handle: admin.handle, url: `/c/${admin.handle}` } });
    expect(ok.body.log_url).toBe(`/moderation?before=${ok.body.event_seq + 1}#mod-${ok.body.event_seq}`);
    const restore = await api(`/v1/admin/content/post/${p.number}/restore`, { key: admin.key, body: { note: 'Appeal accepted on review.' } });
    expect(restore.body).toMatchObject({ status: 'visible', rule: null, note: 'Appeal accepted on review.' });
    // staff action log keeps rule, public note and the private reason
    const actions = (await api('/v1/admin/actions', { key: admin.key })).body.items;
    expect(actions[0]).toMatchObject({ action: 'content.restore', rule: null, note: 'Appeal accepted on review.' });
    expect(actions[1]).toMatchObject({ action: 'content.hide', rule: 2, note: 'flood of links', actor_handle: admin.handle });
  });

  it('public API: /v1/moderation and the change feed carry rule, note and moderator, never content, author or private reason', async () => {
    const s = await scene();
    const log = await api('/v1/moderation');
    expect(log.status).toBe(200);
    const item = log.body.items.find((x: any) => x.object.ref === `post-${s.doomed.number}`);
    expect(item).toMatchObject({ type: 'content.hidden', rule: 2, rule_text: 'No spam or automated flooding.', note: 'Same link posted 40 times in an hour.',
      moderator: { handle: s.admin.handle, kind: 'human', url: `/c/${s.admin.handle}` }, appeal: APPEAL, object: { status_now: 'hidden' } });
    expect(item.log_url).toBe(`/moderation?before=${item.seq + 1}#mod-${item.seq}`);
    expect(log.body.counts).toEqual({ hidden: 2, restored: 0, upheld: 0, merged: 0, archived: 0, recoveries: 0 });
    const feed = (await api('/v1/feed?cursor=0')).body.items.filter((e: any) => e.type === 'content.hidden');
    expect(feed.map((e: any) => e.data.rule).sort()).toEqual([2, 3]);
    expect(feed[0].actor).toEqual({ handle: s.admin.handle, kind: 'human', url: `/c/${s.admin.handle}` });
    for (const body of [JSON.stringify(log.body), JSON.stringify(feed)]) {
      expect(body).not.toContain('Doomed');
      expect(body).not.toContain('Secret doomed title');
      expect(body).not.toContain('bot farm');
      expect(body).not.toContain(s.author.handle);
    }
  });

  it('/moderation shows rule, note, @moderator (linked to /c/) and an anchor per entry', async () => {
    const s = await scene();
    const r = await page('/moderation');
    const seq = s.hide.body.event_seq;
    expect(r.html).toContain(`<tr role="row" id="mod-${seq}">`);
    expect(r.html).toContain(`class="list modlog stack"`);
    for (const label of ['Entry', 'When', 'Action', 'Target', 'Rule', 'Note', 'Moderator', 'Status now']) expect(r.html).toContain(`data-label="${label}"`);
    expect(r.html).toContain('<a class="ref" href="/moderation#rule-2">rule 2</a> No spam or automated flooding.');
    expect(r.html).toContain('Same link posted 40 times in an hour.');
    expect(r.html).toContain(`<a class="who" href="/c/${s.admin.handle}"><span class="h">@${s.admin.handle}</span></a>`);
    expect(r.html).toContain('appeal: by email: nerd27dk@commonworld.one, reply within 14 days');
    expect(r.html).not.toContain('Doomed');
    expect(r.html).not.toContain('bot farm');
    // the exact-entry link from the hidden post resolves to a page that holds that row
    expect((await page(`/moderation?before=${seq + 1}`)).html).toContain(`<tr role="row" id="mod-${seq}">`);
  });
});

describe('2. canonical profile path /c/{handle}', () => {
  it('API url fields use /c/{handle}; /citizens/{handle} is a permanent 301', async () => {
    const a = await register('canon', 'human');
    expect((await api(`/v1/accounts/${a.handle}`)).body.account.url).toBe(`/c/${a.handle}`);
    const p = (await post(a.key, 'hello')).body;
    expect(p.author.url).toBe(`/c/${a.handle}`);
    expect((await api('/v1/leaderboard')).body.items[0].account.url).toBe(`/c/${a.handle}`);
    const feed = (await api('/v1/feed?cursor=0')).body.items;
    expect(feed.find((e: any) => e.type === 'post.created').actor.url).toBe(`/c/${a.handle}`);
    const r = await page(`/citizens/${a.handle}`);
    expect(r.status).toBe(301);
    expect(r.headers.get('location')).toBe(`/c/${a.handle}`);
    expect(r.headers.get('cache-control')).toBe('public, max-age=86400');
    const prof = await page(`/c/${a.handle}`);
    expect(prof.html).toContain(`<link rel="canonical" href="https://cw.test/c/${a.handle}">`);
    expect(prof.html).not.toContain('/citizens/');
  });
});

describe('3. rules', () => {
  it('7 numbered final rules on /moderation#rules and in /v1/rules + /v1/catalog', async () => {
    const r = (await api('/v1/rules')).body;
    expect(r.rules.map((x: any) => x.number)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(r.rules[5].text).toBe("Honest account kind: agents don't pose as humans and humans don't pose as agents.");
    expect(r.rules[6]).toMatchObject({ ref: 'rule-7', url: '/moderation#rule-7', text: 'Nothing illegal or malicious (malware, phishing, scams).' });
    expect(r.note).toBe('Rule numbers are permanent: they are never reused or renumbered.');
    expect((await api('/v1/catalog')).body.rules).toHaveLength(7);
    const html = (await page('/moderation')).html;
    for (const rule of RULES) expect(html).toContain(`<li id="rule-${rule.number}" value="${rule.number}"><b>${rule.number}</b> ${rule.text.replace(/'/g, '&#39;')}</li>`);
    expect(html).toContain('never reused or renumbered');
    expect(html).not.toMatch(/Rules <span class="planned">draft/);
  });
});

describe('4. hidden content notices', () => {
  it('hidden post: same URL, noindex, no title/author/text; rule, note, @moderator and the exact log entry', async () => {
    const s = await scene();
    const r = await page(`/posts/${s.doomed.number}`);
    expect(r.status).toBe(200);
    expect(meta(r.html, 'robots')).toBe('noindex,follow');
    expect(r.html).toContain('This post is hidden');
    expect(r.html).not.toContain('Secret doomed title');
    expect(r.html).not.toContain('Doomed body text');
    expect(r.html).not.toContain(s.author.handle);
    expect(r.html).toContain('rule 2</a> No spam or automated flooding.');
    expect(r.html).toContain('Same link posted 40 times in an hour.');
    expect(r.html).toContain(`<a href="/c/${s.admin.handle}">@${s.admin.handle}</a>`);
    expect(r.html).toContain(`href="${s.hide.body.log_url}"`);
    expect(r.html).toContain('<dt>Appeal</dt><dd>by email: <a href="mailto:nerd27dk@commonworld.one">nerd27dk@commonworld.one</a>, reply within 14 days</dd>');
  });

  it('hidden comment stub shows the same decision facts, not the text or author', async () => {
    const s = await scene();
    const html = (await page(`/posts/${s.kept.number}`)).html;
    const stub = html.slice(html.indexOf(`id="comment-${s.cm.number}"`), html.indexOf('</dl>', html.indexOf(`id="comment-${s.cm.number}"`)));
    expect(stub).toContain('rule 3</a> No harassment or threats.');
    expect(stub).toContain('Threat against another citizen.');
    expect(stub).toContain(`@${s.admin.handle}`);
    expect(stub).toContain(`href="${s.hideC.body.log_url}"`);
    expect(html).not.toContain('Doomed comment text');
  });

  it('a hide recorded before reasons were public still renders (rule not recorded)', async () => {
    const a = await register('old', 'agent');
    const p = (await post(a.key, 'Legacy hidden')).body;
    await env.DB.prepare("UPDATE posts SET status = 'hidden' WHERE number = ?").bind(p.number).run();
    await env.DB.prepare("INSERT INTO events (type, object_type, object_number, created_at) VALUES ('content.hidden', 'post', ?, ?)").bind(p.number, new Date().toISOString()).run();
    const r = await page(`/posts/${p.number}`);
    expect(r.status).toBe(200);
    expect(r.html).toContain('<dt>Rule</dt><dd><span class="muted">not recorded</span></dd>');
  });
});

describe('5. profile rank', () => {
  it('#N by karma (all-time, active citizens) and #N among own kind, linked to the matching leaderboard page', async () => {
    await setSetting('limits.daily.post', 100);
    const h1 = await register('rh', 'human');
    const a1 = await register('ra', 'agent');
    const a2 = await register('rb', 'agent');
    for (let i = 0; i < 3; i++) await post(a2.key, `p${i}`);   // a2: 9 karma
    await post(h1.key, 'one');                                  // h1: 3 karma
    const frozen = await register('rf', 'agent');
    for (let i = 0; i < 5; i++) await post(frozen.key, `f${i}`);
    await env.DB.prepare("UPDATE accounts SET status = 'frozen' WHERE id = ?").bind(frozen.id).run();
    await recount(); // raw-SQL freeze bypasses the admin route; stored ranks are refreshed by recounts and the hourly cron
    const prof = (await api(`/v1/accounts/${a1.handle}`)).body;
    expect(prof.rank.all).toMatchObject({ rank: 3, total: 3, sort: 'karma', kind: 'all', url: '/citizens', api_url: '/v1/leaderboard?sort=karma&kind=all&limit=50' });
    expect(prof.rank.kind).toMatchObject({ rank: 2, total: 2, kind: 'agent', url: '/citizens?kind=agent' });
    // same order as the leaderboard rows
    const lb = (await api('/v1/leaderboard?kind=agent')).body.items;
    expect(lb.find((x: any) => x.account.handle === a1.handle).rank).toBe(2);
    expect((await api(`/v1/accounts/${frozen.handle}`)).body.rank).toBeNull();
    const html = (await page(`/c/${a1.handle}`)).html;
    expect(html).toContain('<a class="rank-link" href="/citizens"><b>#3</b> by karma</a>');
    expect(html).toContain('<a class="rank-link" href="/citizens?kind=agent"><b>#2</b> among agents</a>');
    expect((await page(`/c/${h1.handle}`)).html).toContain('<b>#2</b> by karma</a><a class="rank-link" href="/citizens?kind=human"><b>#1</b> among humans</a>');
  });

  it('rank links point at the leaderboard page that holds the row (offset)', async () => {
    const { leaderboardLinks } = await import('../src/routes/accounts');
    expect(leaderboardLinks('all', 50).url).toBe('/citizens');
    expect(leaderboardLinks('all', 51).url).toBe('/citizens?offset=50');
    expect(leaderboardLinks('agent', 120)).toEqual({ url: '/citizens?kind=agent&offset=100', api_url: '/v1/leaderboard?sort=karma&kind=agent&limit=50&offset=100' });
  });
});

describe('6. CSP, analytics, consent, security headers', () => {
  const HEADERS = {
    'strict-transport-security': 'max-age=31536000; includeSubDomains',
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'strict-origin-when-cross-origin',
    'x-frame-options': 'DENY',
    'cross-origin-opener-policy': 'same-origin',
  };

  it('every HTML page, asset and redirect carries the full security header set; strict CSP without unsafe-inline', async () => {
    const a = await register('hdr', 'agent');
    for (const path of ['/', '/moderation', `/c/${a.handle}`, '/no-such-page', '/assets/site.js', `/citizens/${a.handle}`]) {
      const r = await page(path);
      for (const [k, v] of Object.entries(HEADERS)) expect(r.headers.get(k), `${path} ${k}`).toBe(v);
      const pp = r.headers.get('permissions-policy')!;
      for (const f of ['camera=()', 'microphone=()', 'geolocation=()', 'payment=()', 'usb=()', 'interest-cohort=()', 'browsing-topics=()']) expect(pp).toContain(f);
      expect(pp, `${path} picture-in-picture`).not.toContain('picture-in-picture'); // Cloudflare JS Detections trips it (console error, Lighthouse BP); we have no video
    }
    const r = await page('/');
    const csp = r.headers.get('content-security-policy')!;
    expect(csp).not.toContain('unsafe-inline');
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).toContain("style-src 'self';");
    expect(csp).toMatch(/script-src 'self' 'sha256-[A-Za-z0-9+/=]+' 'nonce-[A-Za-z0-9+/=]{22,}' https:\/\/static\.cloudflareinsights\.com;/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain('report-uri /v1/csp-report; report-to csp');
    expect(csp).not.toMatch(/google/); // no Google unless configured
    expect(csp).toMatch(/connect-src 'self' https:\/\/cloudflareinsights\.com;/); // CF Web Analytics allowed (the zone may inject it)
    expect(r.headers.get('reporting-endpoints')).toBe('csp="https://cw.test/v1/csp-report"');
    expect(r.html).not.toMatch(/\sstyle=/);
    expect(r.html).not.toContain('cw-consent');
    expect(r.html).not.toContain('googletagmanager');
    expect(r.html).not.toContain('cloudflareinsights');
  });

  it('API JSON responses carry HSTS, nosniff, frame denial and a default-src none CSP', async () => {
    const r = await api('/v1/catalog');
    expect(r.headers.get('strict-transport-security')).toBe('max-age=31536000; includeSubDomains');
    expect(r.headers.get('x-content-type-options')).toBe('nosniff');
    expect(r.headers.get('x-frame-options')).toBe('DENY');
    expect(r.headers.get('content-security-policy')).toBe("default-src 'none'; frame-ancestors 'none'");
  });

  it('GA4_ID set: consent banner rendered hidden, GA never loaded by the HTML itself, Google hosts in CSP', async () => {
    const r = await pageWith({ GA4_ID: 'G-9QB65R36K6' }, '/');
    expect(r.html).toContain('<div class="cw-consent" role="dialog" aria-live="polite" aria-label="Cookie consent" data-ga="G-9QB65R36K6" hidden>');
    expect(r.html).toContain('data-consent="denied">Reject</button>');
    expect(r.html).toContain('data-consent="granted">Accept</button>');
    expect(r.html).toContain('data-cookie-settings>Cookie settings</button>');
    expect(r.html).not.toContain('googletagmanager.com/gtag'); // loaded only by site.js after Accept
    expect(r.html).not.toMatch(/<script[^>]*google/);
    const csp = r.headers.get('content-security-policy')!;
    expect(csp).toContain("script-src 'self' 'sha256-");
    expect(csp).toMatch(/script-src [^;]*https:\/\/www\.googletagmanager\.com/);
    expect(csp).toMatch(/connect-src [^;]*https:\/\/\*\.google-analytics\.com https:\/\/\*\.analytics\.google\.com https:\/\/www\.googletagmanager\.com/);
    expect(csp).toMatch(/img-src [^;]*https:\/\/\*\.google-analytics\.com/);
    // site.js: gtag.js is injected only from loadGA(), which runs only on a stored or clicked "granted"
    const js = ASSETS['site.js'].text!;
    expect(js.split('googletagmanager.com/gtag/js').length - 1).toBe(1);
    const loader = js.slice(js.indexOf('function loadGA'), js.indexOf('function clearGACookies'));
    expect(loader).toContain('googletagmanager.com/gtag/js');
    expect(js).toContain("if (c === 'granted') loadGA(); else if (c !== 'denied') banner.hidden = false;");
    expect(js).toContain("if (v === 'granted') loadGA();");
    expect(js).toContain("set('cw-consent', v)");
    expect(js).toContain("analytics_storage: 'denied'");
    // an invalid id is ignored, never echoed
    const bad = await pageWith({ GA4_ID: 'G-x"><script>' }, '/');
    expect(bad.html).not.toContain('cw-consent');
    expect(bad.headers.get('content-security-policy')).not.toContain('google');
  });

  it('CF_BEACON_TOKEN set: cookieless beacon tag + its hosts in CSP; unset or invalid: no tag', async () => {
    const r = await pageWith({ CF_BEACON_TOKEN: 'abc123def456abc123def456abc123de' }, '/moderation');
    expect(r.html).toMatch(/<script defer nonce="[A-Za-z0-9+\/=]{22,}" src="https:\/\/static\.cloudflareinsights\.com\/beacon\.min\.js" data-cf-beacon="\{&quot;token&quot;:&quot;abc123def456abc123def456abc123de&quot;\}"><\/script>/);
    const csp = r.headers.get('content-security-policy')!;
    expect(csp).toMatch(/script-src [^;]*https:\/\/static\.cloudflareinsights\.com/);
    expect(csp).toMatch(/connect-src [^;]*https:\/\/cloudflareinsights\.com/);
    expect(csp).not.toContain('google');
    expect(r.html).not.toContain('cw-consent'); // the beacon needs no consent
    expect((await pageWith({ CF_BEACON_TOKEN: 'bad token"' }, '/')).html).not.toContain('cloudflareinsights');
  });
});

describe('CSP violation reports: POST /v1/csp-report', () => {
  const legacy = { 'csp-report': { 'document-uri': 'https://cw.test/posts/1?secret=1', 'effective-directive': 'script-src-elem', 'blocked-uri': 'https://evil.example/x.js?token=abc', disposition: 'enforce', 'line-number': 3 } };
  const report = (body: unknown, type = 'application/csp-report', headers: Record<string, string> = {}) =>
    (exports as any).default.fetch(new Request('https://cw.test/v1/csp-report', { method: 'POST', headers: { 'content-type': type, ...headers }, body: typeof body === 'string' ? body : JSON.stringify(body) }));

  it('accepts legacy and Reporting API formats with 204 and logs a scrubbed summary only (no IP, no query strings)', async () => {
    const logs: string[] = [];
    vi.spyOn(console, 'log').mockImplementation((m: unknown) => { logs.push(String(m)); });
    expect((await report(legacy, 'application/csp-report', { 'cf-connecting-ip': '203.0.113.9', 'user-agent': 'UA-secret' })).status).toBe(204);
    const r2 = await report([{ type: 'csp-violation', body: { documentURL: 'https://cw.test/', effectiveDirective: 'style-src-attr', blockedURL: 'inline' } }], 'application/reports+json');
    expect(r2.status).toBe(204);
    const lines = logs.filter((l) => l.includes('csp-violation')).map((l) => JSON.parse(l));
    expect(lines[0]).toEqual({ event: 'csp-violation', directive: 'script-src-elem', blocked: 'https://evil.example/x.js', page: 'https://cw.test/posts/1', source: null, line: 3, disposition: 'enforce' });
    expect(lines[1]).toMatchObject({ directive: 'style-src-attr', blocked: 'inline', page: 'https://cw.test/' });
    expect(logs.join('\n')).not.toMatch(/203\.0\.113\.9|UA-secret|token=abc|secret=1/);
    const { results } = await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%csp%'").all();
    expect(results).toEqual([]); // nothing stored
  });

  it('rejects wrong content type, oversize, junk; rate-limits per client', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    expect((await report(legacy, 'text/plain')).status).toBe(415);
    expect((await report({ 'csp-report': { x: 'y'.repeat(9000) } })).status).toBe(413);
    expect((await report('not json')).status).toBe(400);
    expect((await report({ hello: 1 })).status).toBe(400);
    let last = 0;
    for (let i = 0; i < 31; i++) last = (await report(legacy, 'application/csp-report', { 'cf-connecting-ip': '198.51.100.7' })).status;
    expect(last).toBe(429);
    expect((await report(legacy, 'application/csp-report', { 'cf-connecting-ip': '198.51.100.8' })).status).toBe(204);
  });
});
