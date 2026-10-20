/**
 * GET /v1/admin/citizens (capability accounts:list) and the /admin staff page + its markdown twin.
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { api, ageAccount, makeAdmin, post, register, resetDb } from './helpers';

beforeEach(resetDb);

const ORIGIN = 'https://cw.test';
const SAME = { origin: ORIGIN, 'sec-fetch-site': 'same-origin' };

async function req(path: string, opts: { cookie?: string; headers?: Record<string, string>; form?: Record<string, string> } = {}) {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.cookie) headers.cookie = opts.cookie;
  let body: string | undefined;
  if (opts.form) { headers['content-type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(opts.form).toString(); }
  const res: Response = await (exports as any).default.fetch(new Request(`${ORIGIN}${path}`, { method: body ? 'POST' : 'GET', headers, body, redirect: 'manual' }));
  return { status: res.status, text: await res.text(), headers: res.headers };
}
async function signIn(key: string) {
  const link = await api('/v1/auth/login-link', { key, method: 'POST' });
  const r = await req('/login', { headers: SAME, form: { t: new URL(link.body.url).searchParams.get('t')! } });
  return `__Host-cw_session=${r.headers.get('set-cookie')!.match(/^__Host-cw_session=([^;]*)/)![1]}`;
}
async function moderator() {
  const m = await register('mod', 'human', 24 * 30);
  await env.DB.prepare("INSERT INTO account_roles (account_id, role, granted_at) VALUES (?, 'moderator', ?)").bind(m.id, new Date().toISOString()).run();
  return m;
}

describe('GET /v1/admin/citizens', () => {
  it('admin and moderator may list; citizens 403 naming accounts:list; no key 401', async () => {
    const admin = await makeAdmin();
    const mod = await moderator();
    const plain = await register('plain');
    expect((await api('/v1/admin/citizens')).status).toBe(401);
    const no = await api('/v1/admin/citizens', { key: plain.key });
    expect(no.status).toBe(403);
    expect(no.body.error.required_capability).toBe('accounts:list');
    expect((await api('/v1/admin/citizens', { key: admin.key })).status).toBe(200);
    expect((await api('/v1/admin/citizens', { key: mod.key })).status).toBe(200);
  });

  it('fields, counts, flags, last_active; never keys, hashes or sessions', async () => {
    const admin = await makeAdmin();
    const a = await register('writer', 'agent', 24 * 30);
    const p = (await post(a.key, 'hello')).body;
    const p2 = (await post(a.key, 'stays')).body;
    await api(`/v1/posts/${p2.number}/comments`, { key: a.key, body: { body: 'c' } });
    await api(`/v1/admin/content/post/${p.number}/hide`, { key: admin.key, body: { rule: 1, note: 'spam test' } });
    await env.DB.prepare("INSERT INTO link_checks (checked_at, account_id, object_type, outcome, decided_by, domains_json) VALUES (?, ?, 'post', 'rejected', 'hark', '[]')").bind(new Date().toISOString(), a.id).run();
    const r = await api('/v1/admin/citizens', { key: admin.key });
    const row = r.body.items.find((x: any) => x.handle === a.handle);
    expect(row).toMatchObject({ id: a.id, kind: 'agent', roles: [], status: 'active', url: `/c/${a.handle}`, ref: `citizen-${a.number}` });
    expect(row.counts.comments).toBe(1);
    expect(row.flags).toEqual({ hidden_content: 1, link_rejections: 1, reports: null });
    expect(row.last_active).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(r.body.items.find((x: any) => x.handle === admin.handle).roles).toEqual(['admin']);
    const text = JSON.stringify(r.body.items);
    expect(text).not.toMatch(/cw1_|key_hash|session|"email"|pepper/i);
    expect(text).not.toContain(a.key);
  });

  it('filters by kind, role, status, since; sorts by registration; pages with offset', async () => {
    const admin = await makeAdmin();
    const h1 = await register('old-human', 'human'); await ageAccount(h1.handle, 24 * 40);
    const g1 = await register('new-agent', 'agent');
    const g2 = await register('frozen-agent', 'agent');
    await api(`/v1/admin/accounts/${g2.handle}/status`, { key: admin.key, body: { status: 'frozen', reason: 'test' } });
    const list = async (q: string) => (await api(`/v1/admin/citizens${q}`, { key: admin.key })).body;
    expect((await list('?kind=human')).items.every((x: any) => x.kind === 'human')).toBe(true);
    expect((await list('?role=admin')).items.map((x: any) => x.handle)).toEqual([admin.handle]);
    expect((await list('?role=none')).items.some((x: any) => x.handle === admin.handle)).toBe(false);
    expect((await list('?status=frozen')).items.map((x: any) => x.handle)).toEqual([g2.handle]);
    const since = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
    expect((await list(`?since=${since}`)).items.some((x: any) => x.handle === h1.handle)).toBe(false);
    const newest = await list('');
    expect(newest.items[0].handle).toBe(g2.handle);
    expect((await list('?sort=oldest')).items[0].handle).toBe(h1.handle);
    const page1 = await list('?limit=2');
    expect(page1.items).toHaveLength(2);
    expect(page1.total).toBe(4);
    expect(page1.next_offset).toBe(2);
    const page2 = await list('?limit=2&offset=2');
    expect(page2.next_offset).toBeNull();
    expect([...page1.items, ...page2.items].map((x: any) => x.handle).sort()).toEqual([admin.handle, h1.handle, g1.handle, g2.handle].sort());
    for (const bad of ['?kind=robot', '?role=owner', '?status=x', '?since=yesterday', '?sort=karma', '?limit=101']) {
      const r = await api(`/v1/admin/citizens${bad}`, { key: admin.key });
      expect(r.status, bad).toBe(400);
    }
  });
});

describe('/admin staff page', () => {
  it('signed out 401, non-staff 403, staff 200 with a table linking to each profile; private, noindex', async () => {
    expect((await req('/admin')).status).toBe(401);
    const plain = await register('plain', 'human', 24 * 30);
    const pc = await signIn(plain.key);
    const no = await req('/admin', { cookie: pc });
    expect(no.status).toBe(403);
    expect(no.text).not.toContain(`/c/${plain.handle}"`);
    const mod = await moderator();
    const r = await req('/admin', { cookie: await signIn(mod.key) });
    expect(r.status).toBe(200);
    expect(r.headers.get('cache-control')).toBe('private, no-store');
    expect(r.headers.get('x-robots-tag')).toContain('noindex');
    expect(r.text).toContain(`href="/c/${plain.handle}"`);
    expect(r.text).toContain('data-label="Last active"');
    expect(r.text).toContain('<label for="a-kind">');
    expect(r.headers.get('content-security-policy')).not.toContain('unsafe-inline');
    const filtered = await req('/admin?kind=agent', { cookie: await signIn(mod.key) });
    expect(filtered.text).not.toContain(`href="/c/${plain.handle}"`);
  });

  it('markdown twin needs the same staff session', async () => {
    expect((await req('/admin.md')).status).toBe(401);
    const admin = await makeAdmin();
    const cookie = await signIn(admin.key);
    const md = await req('/admin.md', { cookie });
    expect(md.status).toBe(200);
    expect(md.headers.get('content-type')).toContain('text/markdown');
    expect(md.headers.get('cache-control')).toBe('private, no-store');
    expect(md.text).toContain(`[@${admin.handle}](https://cw.test/c/${admin.handle})`);
    const neg = await req('/admin', { cookie, headers: { accept: 'text/markdown' } });
    expect(neg.headers.get('content-type')).toContain('text/markdown');
  });

  it('/v1/admin redirects to /admin', async () => {
    const r = await req('/v1/admin');
    expect(r.status).toBe(301);
    expect(r.headers.get('location')).toBe('/admin');
  });
});
