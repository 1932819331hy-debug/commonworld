/**
 * Website writes (src/pages/writes.ts): every UI write path, CSRF and signed-out rejects, limits shared with the API,
 * and the link check at publish (src/link-check.ts) on both the API and the forms.
 */
import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env, exports } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker from '../src/index';
import { linkDomains, MAX_LINK_DOMAINS, resetLinkCheckMemo } from '../src/link-check';
import { GSB_ENDPOINT } from '../src/trust-engine/sources/google-safe-browsing.ts';
import { certPolska, metamask, scamsniffer } from '../src/trust-engine/index.ts';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(async () => { await resetDb(); await env.DB.prepare('DELETE FROM link_checks').run(); resetLinkCheckMemo(); });
afterEach(() => vi.restoreAllMocks());

const ORIGIN = 'https://cw.test';
const SAME = { origin: ORIGIN, 'sec-fetch-site': 'same-origin' };

interface Res { status: number; html: string; headers: Headers }
async function req(path: string, opts: { method?: string; cookie?: string; headers?: Record<string, string>; form?: Record<string, string>; vars?: Record<string, string> } = {}): Promise<Res> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.cookie) headers.cookie = opts.cookie;
  let body: string | undefined;
  if (opts.form) { headers['content-type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(opts.form).toString(); }
  const request = new Request(`${ORIGIN}${path}`, { method: opts.method ?? (body !== undefined ? 'POST' : 'GET'), headers, body, redirect: 'manual' });
  let res: Response;
  if (opts.vars) {
    const ctx = createExecutionContext();
    res = await worker.fetch(request, { ...env, ...opts.vars } as any, ctx);
    await waitOnExecutionContext(ctx);
  } else res = await (exports as any).default.fetch(request);
  return { status: res.status, html: await res.text(), headers: res.headers };
}

async function signIn(key: string): Promise<string> {
  const link = await api('/v1/auth/login-link', { key, method: 'POST' });
  const token = new URL(link.body.url).searchParams.get('t')!;
  const r = await req('/login', { headers: SAME, form: { t: token } });
  expect(r.status).toBe(303);
  return `__Host-cw_session=${r.headers.get('set-cookie')!.match(/^__Host-cw_session=([^;]*)/)![1]}`;
}

/** A signed-in citizen with the CSRF token read from a rendered form. */
async function citizen(prefix = 'writer', ageHours = 24 * 30) {
  const a = await register(prefix, 'human', ageHours);
  const cookie = await signIn(a.key);
  const page = await req('/compose', { cookie });
  const csrf = page.html.match(/name="_csrf" value="([0-9a-f]{64})"/)![1];
  return { ...a, cookie, csrf };
}

const write = (who: { cookie: string; csrf: string }, path: string, form: Record<string, string> = {}, extra: { headers?: Record<string, string>; vars?: Record<string, string> } = {}) =>
  req(path, { cookie: who.cookie, headers: extra.headers ?? SAME, form: { _csrf: who.csrf, ...form }, vars: extra.vars });

const count = async (table: string) => (await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first<{ n: number }>())!.n;

describe('GET /compose', () => {
  it('signed out: friendly sign-in prompt, no form; signed in: private form with CSRF token, labels and limits', async () => {
    const anon = await req('/compose');
    expect(anon.status).toBe(200);
    expect(anon.html).toContain('Sign in to write');
    expect(anon.html).not.toContain('name="_csrf"');
    const me = await citizen();
    const page = await req('/compose', { cookie: me.cookie });
    expect(page.status).toBe(200);
    expect(page.headers.get('cache-control')).toBe('private, no-store');
    for (const id of ['f-title', 'f-body', 'f-section', 'f-tags']) expect(page.html).toContain(`<label for="${id}"`);
    expect(page.html).toContain('maxlength="240"');
    expect(page.html).toContain('maxlength="12000"');
    expect(page.html).toMatch(/name="_idem" value="web-[0-9a-f-]{36}"/);
    expect(page.html).toContain('href="/compose">New post</a>');
    // CSP: per-request nonce kept, no unsafe-inline, forms post to self only
    const csp = page.headers.get('content-security-policy')!;
    expect(csp).toMatch(/'nonce-[A-Za-z0-9+/=]{24}'/);
    expect(csp).not.toContain('unsafe-inline');
    expect(csp).toContain("form-action 'self'");
    expect(page.html).not.toMatch(/\son[a-z]+="/);
  });

  it('has a markdown twin (/compose.md and Accept: text/markdown)', async () => {
    const md = await req('/compose.md');
    expect(md.status).toBe(200);
    expect(md.headers.get('content-type')).toContain('text/markdown');
    expect(md.html).toContain('POST https://cw.test/v1/posts');
    const neg = await req('/compose', { headers: { accept: 'text/markdown' } });
    expect(neg.headers.get('content-type')).toContain('text/markdown');
    const html = await req('/compose');
    expect(html.html).toContain('type="text/markdown" href="https://cw.test/compose.md"');
  });
});

describe('POST /compose (create a post)', () => {
  it('creates the post through the API handler and redirects to it with a success note', async () => {
    const me = await citizen();
    const r = await write(me, '/compose', { title: 'Hello from the browser', body: 'First paragraph.\n\nSecond.', section: 'general', tags: 'memory, #agents', _idem: `web-${crypto.randomUUID()}` });
    expect(r.status).toBe(303);
    const loc = r.headers.get('location')!;
    expect(loc).toMatch(/^\/posts\/\d+\?done=post$/);
    const n = Number(loc.match(/\d+/)![0]);
    const apiView = await api(`/v1/posts/${n}`);
    expect(apiView.body.title).toBe('Hello from the browser');
    expect(apiView.body.author.handle).toBe(me.handle);
    expect(apiView.body.tags.sort()).toEqual(['agents', 'memory']);
    const page = await req(loc, { cookie: me.cookie });
    expect(page.html).toContain('Your post is live');
    // the API daily counter moved: same quota as the key
    const usage = await api('/v1/me', { key: me.key });
    expect(usage.body.usage_today.post).toBe(1);
  });

  it('a double submit with the same form (_idem) publishes once', async () => {
    const me = await citizen();
    const form = { title: 'Once', body: 'Only once.', section: 'general', _idem: `web-${crypto.randomUUID()}` };
    const a = await write(me, '/compose', form);
    const b = await write(me, '/compose', form);
    expect(a.status).toBe(303);
    expect(b.headers.get('location')).toBe(a.headers.get('location'));
    expect(await count('posts')).toBe(1);
  });

  it('validation errors re-show the form with the text kept and the API status', async () => {
    const me = await citizen();
    const r = await write(me, '/compose', { title: '', body: 'Keep this text please', section: 'general' });
    expect(r.status).toBe(400);
    expect(r.html).toContain('The title needs a little work');
    expect(r.html).toContain('Keep this text please');
    expect(r.html).toContain('role="alert"');
    const tags = await write(me, '/compose', { title: 't', body: 'b', tags: 'Bad Tag!' });
    expect(tags.status).toBe(400);
    expect(tags.html).toContain('invalid_tags');
    expect(await count('posts')).toBe(0);
  });

  it('daily limit is the same as the API (429, text kept, nothing written)', async () => {
    await setSetting('limits.daily.post', 1);
    const me = await citizen();
    expect((await post(me.key, 'via api')).status).toBe(201);
    const r = await write(me, '/compose', { title: 'Second', body: 'Over the limit text', section: 'general' });
    expect(r.status).toBe(429);
    expect(r.html).toContain('You reached today’s limit');
    expect(r.html).toContain('Over the limit text');
    expect(await count('posts')).toBe(1);
  });

  it('the per-minute limit is one window shared with the key', async () => {
    await setSetting('limits.rate_per_minute', 2);
    const me = await citizen();
    await api('/v1/me', { key: me.key });
    await api('/v1/me', { key: me.key });
    const r = await write(me, '/compose', { title: 'Too fast', body: 'b', section: 'general' });
    expect(r.status).toBe(429);
    expect(r.html).toContain('A short pause, please');
    expect(await count('posts')).toBe(0);
  });

  it('Lock mode refuses young accounts on the pages exactly like the API', async () => {
    const me = await citizen('young', 1);
    await setSetting('mode.lock', { enabled: true, min_account_age_hours: 72 });
    const r = await write(me, '/compose', { title: 'Hi', body: 'b', section: 'general' });
    expect(r.status).toBe(403);
    expect(r.html).toContain('platform_locked');
    expect((await post(me.key)).status).toBe(403);
  });
});

describe('CSRF and sign-in', () => {
  const form = { title: 'x', body: 'y', section: 'general' };

  it('signed out: 401 with a sign-in link, nothing written (no cookie and a junk cookie)', async () => {
    const r = await req('/compose', { headers: SAME, form });
    expect(r.status).toBe(401);
    expect(r.html).toContain('Sign in to write');
    expect(r.html).toContain('href="/inbox"');
    const junk = await req('/posts/1/upvote', { headers: SAME, cookie: '__Host-cw_session=cws_' + 'a'.repeat(43), form: {} });
    expect(junk.status).toBe(401);
    expect(await count('posts')).toBe(0);
  });

  it('missing, wrong or another session\'s token: 403 csrf_rejected, nothing written', async () => {
    const me = await citizen();
    const other = await citizen('other');
    expect((await req('/compose', { cookie: me.cookie, headers: SAME, form })).status).toBe(403);
    expect((await write({ cookie: me.cookie, csrf: 'f'.repeat(64) }, '/compose', form)).status).toBe(403);
    const cross = await write({ cookie: me.cookie, csrf: other.csrf }, '/compose', form);
    expect(cross.status).toBe(403);
    expect(cross.html).toContain('csrf_rejected');
    expect(await count('posts')).toBe(0);
  });

  it('cross-site requests are refused even with a valid token (Origin / Sec-Fetch-Site)', async () => {
    const me = await citizen();
    const variants: Record<string, string>[] = [{ origin: 'https://evil.example', 'sec-fetch-site': 'cross-site' }, { origin: 'https://evil.example' }, { 'sec-fetch-site': 'cross-site' }, {}];
    for (const headers of variants) {
      const r = await write(me, '/compose', form, { headers });
      expect(r.status, JSON.stringify(headers)).toBe(403);
    }
    expect(await count('posts')).toBe(0);
  });

  it('the token is per session: a new sign-in gets a different token; signing out kills it', async () => {
    const a = await register('twice', 'human', 24 * 30);
    const c1 = await signIn(a.key);
    const c2 = await signIn(a.key);
    const t = async (cookie: string) => (await req('/compose', { cookie })).html.match(/name="_csrf" value="([0-9a-f]{64})"/)![1];
    const t1 = await t(c1);
    expect(t1).not.toBe(await t(c2));
    await req('/logout', { cookie: c1, headers: SAME, form: {} });
    expect((await write({ cookie: c1, csrf: t1 }, '/compose', form)).status).toBe(401);
  });

  it('the cookie still never authenticates the /v1 API', async () => {
    const me = await citizen();
    const r = await (exports as any).default.fetch(new Request(`${ORIGIN}/v1/posts`, { method: 'POST', headers: { cookie: me.cookie, 'content-type': 'application/json' }, body: JSON.stringify(form) }));
    expect(r.status).toBe(401);
  });
});

describe('comments, replies, votes, withdraw, porch', () => {
  it('comment and reply land under the post with anchors; reply forms only where depth allows', async () => {
    const author = await register('author', 'agent', 24 * 30);
    const p = (await post(author.key, 'Talk')).body;
    const me = await citizen();
    const c = await write(me, `/posts/${p.number}/comment`, { body: 'Nice post!' });
    expect(c.status).toBe(303);
    const loc = c.headers.get('location')!;
    expect(loc).toMatch(new RegExp(`^/posts/${p.number}\\?done=comment#comment-\\d+$`));
    const cn = Number(loc.split('#comment-')[1]);
    const r = await write(me, `/posts/${p.number}/comment`, { body: 'And a reply.', parent: String(cn) });
    expect(r.status).toBe(303);
    const rn = Number(r.headers.get('location')!.split('#comment-')[1]);
    expect((await api(`/v1/comments/${rn}`)).body.parent_number).toBe(cn);
    const page = await req(`/posts/${p.number}?done=comment`, { cookie: me.cookie });
    expect(page.html).toContain('Your comment is live');
    expect(page.html).toContain(`<input type="hidden" name="parent" value="${cn}">`);
    expect(page.html).toContain('id="comment-form"');
    // empty comment: 400 with friendly text and the form again
    const empty = await write(me, `/posts/${p.number}/comment`, { body: '   ' });
    expect(empty.status).toBe(400);
    expect(empty.html).toContain('The text needs a little work');
    // anonymous view stays read-only (no forms)
    const anon = await req(`/posts/${p.number}`);
    expect(anon.html).not.toContain('name="_csrf"');
    expect(anon.html).toContain('Sign in to comment');
  });

  it('upvote a post and a comment; own content shows no button and a forged vote is refused (409)', async () => {
    const author = await register('author', 'agent', 24 * 30);
    const p = (await post(author.key, 'Vote me')).body;
    const cm = (await api(`/v1/posts/${p.number}/comments`, { key: author.key, body: { body: 'author comment' } })).body;
    const me = await citizen();
    const v = await write(me, `/posts/${p.number}/upvote`);
    expect(v.status).toBe(303);
    expect(v.headers.get('location')).toBe(`/posts/${p.number}?done=vote`);
    const vc = await write(me, `/comments/${cm.number}/upvote`);
    expect(vc.headers.get('location')).toBe(`/posts/${p.number}?done=vote#comment-${cm.number}`);
    expect(await count('votes')).toBe(2);
    const page = await req(`/posts/${p.number}`, { cookie: me.cookie });
    expect(page.html).toContain('vote-btn voted');
    const mine = (await post(me.key, 'Mine')).body;
    const minePage = await req(`/posts/${mine.number}`, { cookie: me.cookie });
    expect(minePage.html).not.toContain(`action="/posts/${mine.number}/upvote"`);
    const self = await write(me, `/posts/${mine.number}/upvote`);
    expect(self.status).toBe(409);
    expect(self.html).toContain('That one is yours');
    // daily vote limit identical to the API
    await setSetting('limits.daily.vote', 2);
    const p2 = (await post(author.key, 'Another')).body;
    expect((await write(me, `/posts/${p2.number}/upvote`)).status).toBe(429);
  });

  it('withdraw own post and comment with a public reason; someone else\'s is refused', async () => {
    const me = await citizen();
    const mine = (await post(me.key, 'Withdraw me')).body;
    const page = await req(`/posts/${mine.number}`, { cookie: me.cookie });
    expect(page.html).toContain(`action="/posts/${mine.number}/withdraw"`);
    const noReason = await write(me, `/posts/${mine.number}/withdraw`, { reason: '' });
    expect(noReason.status).toBe(400);
    expect(noReason.html).toContain('Please add a short reason');
    const w = await write(me, `/posts/${mine.number}/withdraw`, { reason: 'wrong section' });
    expect(w.status).toBe(303);
    expect((await api(`/v1/posts/${mine.number}`)).body.withdrawn.reason).toBe('wrong section');
    const other = await register('other', 'agent', 24 * 30);
    const theirs = (await post(other.key, 'Not yours')).body;
    const cm = (await api(`/v1/posts/${theirs.number}/comments`, { key: me.key, body: { body: 'my comment' } })).body;
    const wc = await write(me, `/comments/${cm.number}/withdraw`, { reason: 'changed my mind' });
    expect(wc.headers.get('location')).toBe(`/posts/${theirs.number}?done=withdrawn#comment-${cm.number}`);
    const refused = await write(me, `/posts/${theirs.number}/withdraw`, { reason: 'nope' });
    expect(refused.status).toBe(403);
    expect(refused.html).toContain('Only the author can withdraw this');
  });

  it('porch: post a line and withdraw it', async () => {
    const me = await citizen();
    const r = await write(me, '/porch', { body: 'hello porch' });
    expect(r.status).toBe(303);
    const n = Number(r.headers.get('location')!.split('#porch-')[1]);
    const page = await req('/porch?done=porch', { cookie: me.cookie });
    expect(page.html).toContain('Your line is on the porch');
    expect(page.html).toContain(`action="/porch/${n}/withdraw"`);
    expect((await write(me, `/porch/${n}/withdraw`, { reason: 'typo' })).status).toBe(303);
    expect((await api(`/v1/porch/${n}`)).body.withdrawn.reason).toBe('typo');
    // GET /porch still a page, other methods still 405
    expect((await req('/porch', { method: 'PUT' })).status).toBe(405);
  });

  it('staff roles add nothing on the pages: a moderator cannot withdraw others\' content either', async () => {
    const admin = await makeAdmin();
    const cookie = await signIn(admin.key);
    const csrf = (await req('/compose', { cookie })).html.match(/name="_csrf" value="([0-9a-f]{64})"/)![1];
    const other = await register('other', 'agent', 24 * 30);
    const theirs = (await post(other.key, 'Not yours')).body;
    expect((await write({ cookie, csrf }, `/posts/${theirs.number}/withdraw`, { reason: 'x' })).status).toBe(403);
  });
});

// ---------------------------------------------------------------- link check at publish

const gsb = (code: number, se = false) => `)]}'\n[["sb.ssr",${code},false,false,${se},false,false,1792259421202,"x",false]]`;
function sources(flaggedByGsb: string[] = []) {
  const calls: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation((async (input: RequestInfo | URL) => {
    const u = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    calls.push(u);
    const body = u === metamask.url ? JSON.stringify({ version: 2, fuzzylist: [], whitelist: [], blacklist: ['drainer.example'] })
      : u === scamsniffer.url ? JSON.stringify(['scam.example'])
      : u === certPolska.url ? 'phish.example\n'
      : u.startsWith(GSB_ENDPOINT) ? gsb(flaggedByGsb.some((d) => u.endsWith(`=${d}`)) ? 2 : 1, flaggedByGsb.some((d) => u.endsWith(`=${d}`)))
      : null;
    return body === null ? new Response('not found', { status: 404 }) : new Response(body);
  }) as typeof fetch);
  return calls;
}
const ONLINE = { LINK_CHECK_OFFLINE: '0' };

async function apiOnline(path: string, key: string, body: unknown, vars: Record<string, string> = ONLINE) {
  const ctx = createExecutionContext();
  const res = await worker.fetch(new Request(`https://api.test${path}`, { method: 'POST', headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' }, body: JSON.stringify(body) }), { ...env, ...vars } as any, ctx);
  await waitOnExecutionContext(ctx);
  return { status: res.status, body: await res.json<any>() };
}

describe('link check at publish (src/link-check.ts)', () => {
  it('finds http(s) and www. links, normalizes and dedupes', () => {
    expect(linkDomains(['see https://Example.com/a?b, www.other.example. and [x](http://user@sub.example:8080/p)', 'https://example.com again'])).toEqual(['example.com', 'sub.example', 'other.example']);
    expect(linkDomains(['no links here, just file.ts and a@b.example'])).toEqual([]);
  });

  it('API: a flagged domain refuses the post with evidence + appeal (422); nothing written, no quota used; rejection recorded', async () => {
    sources();
    const a = await register('linker', 'agent', 24 * 30);
    const r = await apiOnline('/v1/posts', a.key, { title: 'Free tokens', body: 'claim at https://app.drainer.example/claim', section: 'general' });
    expect(r.status).toBe(422);
    expect(r.body.error.code).toBe('link_flagged');
    expect(r.body.error.domains[0].domain).toBe('app.drainer.example');
    expect(r.body.error.domains[0].sources[0]).toMatchObject({ name: 'metamask_phishing_detect', evidence_url: 'https://github.com/MetaMask/eth-phishing-detect/blob/main/src/config.json' });
    expect(r.body.error.appeal.reply_within_days).toBe(7);
    expect(await count('posts')).toBe(0);
    expect((await api('/v1/me', { key: a.key })).body.usage_today.post).toBe(0);
    const row = await env.DB.prepare('SELECT * FROM link_checks').first<any>();
    expect(row).toMatchObject({ account_id: a.id, object_type: 'post', outcome: 'rejected', decided_by: 'hark' });
    expect(JSON.parse(row.flagged_json)).toEqual(['app.drainer.example']);
    expect(JSON.parse(row.domains_json)[0].sources.length).toBe(4);
    expect(JSON.stringify(row)).not.toContain('claim at');
  });

  it('API: comments and porch lines are checked too; Google Safe Browsing flags count', async () => {
    sources(['bad-gsb.example']);
    const a = await register('linker', 'agent', 24 * 30);
    const p = (await post(a.key, 'Clean')).body;
    expect((await apiOnline(`/v1/posts/${p.number}/comments`, a.key, { body: 'look www.bad-gsb.example' })).status).toBe(422);
    expect((await apiOnline('/v1/porch', a.key, { body: 'https://scam.example' })).status).toBe(422);
    expect(await count('comments')).toBe(0);
    expect(await count('porch_lines')).toBe(0);
  });

  it('clean links publish and are recorded as allowed; own domains and link-free text do no lookup', async () => {
    const calls = sources();
    const a = await register('linker', 'agent', 24 * 30);
    expect((await apiOnline('/v1/posts', a.key, { title: 'ok', body: 'docs: https://good.example/x', section: 'general' })).status).toBe(201);
    expect((await env.DB.prepare('SELECT outcome FROM link_checks').first<any>()).outcome).toBe('allowed');
    const before = calls.length;
    expect((await apiOnline('/v1/posts', a.key, { title: 'own', body: 'https://staging.commonworld.one/posts/1 and no others', section: 'general' })).status).toBe(201);
    expect((await apiOnline('/v1/porch', a.key, { body: 'no links at all' })).status).toBe(201);
    expect(calls.length).toBe(before);
    expect(await count('link_checks')).toBe(1);
  });

  it(`more than ${MAX_LINK_DOMAINS} different domains: 400 too_many_link_domains`, async () => {
    sources();
    const a = await register('linker', 'agent', 24 * 30);
    const body = Array.from({ length: MAX_LINK_DOMAINS + 1 }, (_, i) => `https://d${i}.example`).join(' ');
    const r = await apiOnline('/v1/posts', a.key, { title: 'links', body, section: 'general' });
    expect(r.status).toBe(400);
    expect(r.body.error.code).toBe('too_many_link_domains');
  });

  it('a source that cannot answer never blocks (no_data publishes)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((async () => new Response('down', { status: 503 })) as typeof fetch);
    const a = await register('linker', 'agent', 24 * 30);
    expect((await apiOnline('/v1/posts', a.key, { title: 'ok', body: 'https://unknown.example', section: 'general' })).status).toBe(201);
  });

  it('the offline switch is ignored outside ENVIRONMENT=local', async () => {
    const calls = sources();
    const a = await register('linker', 'agent', 24 * 30);
    const r = await apiOnline('/v1/posts', a.key, { title: 'x', body: 'https://drainer.example', section: 'general' }, { LINK_CHECK_OFFLINE: '1', ENVIRONMENT: 'staging' });
    expect(r.status).toBe(422);
    expect(calls.length).toBeGreaterThan(0);
  });

  it('website: a flagged link re-shows the form with a clear friendly message, the domain and the evidence', async () => {
    sources();
    const me = await citizen();
    const r = await write(me, '/compose', { title: 'Look', body: 'go to https://phish.example now', section: 'general' }, { vars: ONLINE });
    expect(r.status).toBe(422);
    expect(r.html).toContain('One of your links was not published');
    expect(r.html).toContain('<b>phish.example</b>');
    expect(r.html).toContain('https://cert.pl/en/warning-list/');
    expect(r.html).toContain('go to https://phish.example now');
    expect(await count('posts')).toBe(0);
    expect((await env.DB.prepare('SELECT outcome FROM link_checks').first<any>()).outcome).toBe('rejected');
  });
});
