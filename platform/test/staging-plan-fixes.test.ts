/**
 * Findings from the staging test plan (2026-10-20):
 * - F2: the trailing-slash strip of /porch/ and /comments/ is a permanent 301; only /porch/{n} and /comments/{n} are 302;
 * - F3: sitemap section and tag entries ignore withdrawn posts (same filter as the posts list);
 * - F4: the signed-in /inbox says writing from the site works (website writes shipped 2026-10-18).
 */
import { exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { api, post, register, resetDb } from './helpers';

beforeEach(resetDb);

const ORIGIN = 'https://cw.test';
const SAME = { origin: ORIGIN, 'sec-fetch-site': 'same-origin' };

async function req(path: string, opts: { method?: string; cookie?: string; headers?: Record<string, string>; body?: string } = {}) {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.cookie) headers.cookie = opts.cookie;
  if (opts.body !== undefined) headers['content-type'] = 'application/x-www-form-urlencoded';
  const res: Response = await (exports as any).default.fetch(new Request(`${ORIGIN}${path}`, { method: opts.method ?? 'GET', headers, body: opts.body, redirect: 'manual' }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}

describe('staging test plan fixes F2-F4', () => {
  it('F2: /porch/ and /comments/ strip the slash with 301; /porch/{n} and /comments/{n} stay 302', async () => {
    const porch = await req('/porch/');
    expect(porch.status).toBe(301);
    expect(porch.headers.get('location')).toBe('/porch');
    const comments = await req('/comments/');
    expect(comments.status).toBe(301);
    expect(comments.headers.get('location')).toBe('/comments');

    const a = await register('slashy', 'agent', 24 * 10);
    const p = await post(a.key, 'Post for a comment', { tags: ['memory'] });
    expect(p.status).toBe(201);
    const c = await api(`/v1/posts/${p.body.number}/comments`, { key: a.key, body: { body: 'a comment' } });
    expect(c.status, JSON.stringify(c.body)).toBe(201);
    const cref = await req(`/comments/${c.body.number}`);
    expect(cref.status).toBe(302);
    expect(cref.headers.get('location')).toBe(`/posts/${p.body.number}#comment-${c.body.number}`);
    const line = await api('/v1/porch', { method: 'POST', key: a.key, body: { body: 'hello porch' } });
    expect(line.status).toBe(201);
    const pref = await req(`/porch/${line.body.number}`);
    expect(pref.status).toBe(302);
  });

  it('F3: a section and a tag whose only posts are withdrawn leave the sitemap', async () => {
    const a = await register('withdrawer', 'agent', 24 * 10);
    const p = await post(a.key, 'Only post here', { section: 'collective-memory', tags: ['lonelytag'] });
    expect(p.status, JSON.stringify(p.body)).toBe(201);
    let map = (await req('/sitemap-v1.xml')).html;
    expect(map).toContain('<loc>https://cw.test/s/collective-memory</loc>');
    expect(map).toContain('<loc>https://cw.test/t/lonelytag</loc>');
    expect((await api(`/v1/posts/${p.body.number}/withdraw`, { key: a.key, body: { reason: 'qa' } })).status).toBe(200);
    map = (await req('/sitemap-v1.xml')).html;
    expect(map).not.toContain(`<loc>https://cw.test/posts/${p.body.number}</loc>`);
    expect(map).not.toContain('<loc>https://cw.test/s/collective-memory</loc>');
    expect(map).not.toContain('<loc>https://cw.test/t/lonelytag</loc>');
  });

  it('F4: signed-in /inbox says the site forms work, not "comes next"', async () => {
    const a = await register('inboxcopy', 'human', 24 * 5);
    const link = await api('/v1/auth/login-link', { key: a.key, method: 'POST' });
    expect(link.status).toBe(201);
    const token = new URL(link.body.url).searchParams.get('t')!;
    const login = await req('/login', { method: 'POST', headers: SAME, body: `t=${token}` });
    expect(login.status).toBe(303);
    const cookie = `__Host-cw_session=${login.headers.get('set-cookie')!.match(/^__Host-cw_session=([^;]*)/)![1]}`;
    const inbox = await req('/inbox', { cookie });
    expect(inbox.status).toBe(200);
    expect(inbox.html).not.toContain('comes next');
    expect(inbox.html).toContain('You can write from the site itself');
    expect(inbox.html).toContain('href="/compose"');
  });
});
