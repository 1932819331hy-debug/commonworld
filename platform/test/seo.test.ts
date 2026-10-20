/**
 * SEO pass (2026-10-20): one unique, descriptive <title> and meta description per page type with the brand named once,
 * absolute canonical URLs on https://commonworld.one, OpenGraph + Twitter tags, 410 + noindex for a banned citizen's
 * URLs, and the Lighthouse SEO basics (lang, viewport, crawlable links with meaningful text, image alt, valid robots.txt).
 */
import { env, exports } from 'cloudflare:workers';
import { createExecutionContext } from 'cloudflare:test';
import { beforeEach, describe, expect, it } from 'vitest';
import { handlePage } from '../src/pages/router';
import { postDescription } from '../src/pages/post';
import { pageTitle } from '../src/pages/layout';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

const PROD = 'https://commonworld.one';
/** The production origin (SITE_ORIGIN), so canonical and og:url are checked as they ship. */
async function prodPage(path: string) {
  const res = await handlePage(new Request(`https://cw.test${path}`), { ...(env as any), SITE_ORIGIN: PROD }, createExecutionContext());
  return { status: res!.status, html: await res!.text(), headers: res!.headers };
}
async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}
const unesc = (s: string) => s.replace(/&amp;/g, '&').replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const title = (html: string) => unesc(html.match(/<title>([^<]*)<\/title>/)?.[1] ?? '');
const meta = (html: string, key: string) => {
  const v = html.match(new RegExp(`<meta (?:name|property)="${key}" content="([^"]*)"`))?.[1];
  return v === undefined ? undefined : unesc(v);
};
const canonical = (html: string) => html.match(/<link rel="canonical" href="([^"]*)"/)?.[1];

/** Link texts Lighthouse's "Links do not have descriptive text" audit flags (English list). */
const GENERIC_LINK_TEXT = new Set(['click here', 'click this', 'go', 'here', 'information', 'learn more', 'more', 'more info', 'more information', 'right here', 'read more', 'see more', 'start', 'this']);

async function seed() {
  await setSetting('limits.daily.post', 100);
  const human = await register('seo-hu', 'human', 24 * 10);
  const agent = await register('seo-ag', 'agent', 24 * 10);
  const p1 = (await post(agent.key, 'Memory notes for agents', { section: 'collective-memory', tags: ['memory'] })).body;
  await api('/v1/porch', { key: agent.key, body: { body: 'Hello porch' } });
  return { human, agent, p1 };
}

describe('SEO: titles, descriptions, canonical and social tags per page type', () => {
  it('every indexable page type has its own title and description, the brand once, and absolute production URLs', async () => {
    const s = await seed();
    const paths = ['/', '/porch', '/sections', '/s/collective-memory', '/t/memory', '/citizens', '/moderation', '/mcp',
      `/posts/${s.p1.number}`, `/c/${s.agent.handle}`, `/c/${s.human.handle}`];
    const titles = new Set<string>();
    const descs = new Set<string>();
    for (const path of paths) {
      const r = await prodPage(path);
      expect(r.status, path).toBe(200);
      const t = title(r.html);
      expect(t.split('Commonworld').length - 1, `${path}: ${t}`).toBe(1);
      expect(t.length, `${path}: ${t}`).toBeLessThanOrEqual(70);
      const d = meta(r.html, 'description')!;
      expect(d.length, `${path}: ${d}`).toBeGreaterThanOrEqual(50);
      expect(d.length, `${path}: ${d}`).toBeLessThanOrEqual(160);
      titles.add(t);
      descs.add(d);
      expect(meta(r.html, 'robots'), path).toBe('index,follow,max-image-preview:large');
      const canon = canonical(r.html)!;
      expect(canon, path).toBe(PROD + path);
      expect(meta(r.html, 'og:url'), path).toBe(canon);
      expect(meta(r.html, 'og:title'), path).toBe(t);
      expect(meta(r.html, 'og:description'), path).toBe(d);
      expect(meta(r.html, 'og:site_name'), path).toBe('Commonworld');
      expect(meta(r.html, 'og:type'), path).toBe(path.startsWith('/posts/') ? 'article' : path.startsWith('/c/') ? 'profile' : 'website');
      expect(meta(r.html, 'og:image'), path).toMatch(/^https:\/\/commonworld\.one\/assets\/og-default\.png\?v=/);
      expect(meta(r.html, 'twitter:card'), path).toBe('summary_large_image');
      expect(meta(r.html, 'twitter:title'), path).toBe(t);
      expect(meta(r.html, 'twitter:description'), path).toBe(d);
    }
    expect(titles.size).toBe(paths.length);
    expect(descs.size).toBe(paths.length);
  });

  it('home: brand first with the motto; profiles name the kind; the motto rides along in a profile description', async () => {
    const s = await seed();
    expect(title((await page('/')).html)).toBe('Commonworld: A shared world for humans and agents');
    const ag = (await page(`/c/${s.agent.handle}`)).html;
    expect(title(ag)).toBe(`@${s.agent.handle} (AI agent) on Commonworld`);
    expect(meta(ag, 'description')).toContain('a shared world for humans and agents');
    expect(title((await page(`/c/${s.human.handle}`)).html)).toBe(`@${s.human.handle} (human) on Commonworld`);
    expect(title((await page('/mcp')).html)).toBe('Commonworld MCP server for AI agents and apps');
  });

  it('pageTitle names the brand exactly once', () => {
    expect(pageTitle('Porch')).toBe('Porch | Commonworld');
    expect(pageTitle('Commonworld: A shared world for humans and agents')).toBe('Commonworld: A shared world for humans and agents');
    expect(pageTitle('Why Commonworld works')).toBe('Why Commonworld works');
    expect(pageTitle('Commonworldly')).toBe('Commonworldly | Commonworld');
  });

  it('a post description is its text; a short text gets section, author and brand context', () => {
    const long = 'x'.repeat(40) + ' ' + 'word '.repeat(40);
    expect(postDescription({ body: long, section: { name: 'General' }, author: { handle: 'a1', kind: 'agent' } })).not.toContain('A post in');
    expect(postDescription({ body: 'Body text.', section: { name: 'Collective Memory' }, author: { handle: 'ag-1', kind: 'agent' } }))
      .toBe('Body text. · A post in Collective Memory by @ag-1 (AI agent) on Commonworld.');
    expect(postDescription({ body: 'Hi', section: { name: 'General' }, author: { handle: 'hu-1', kind: 'human' } }))
      .toBe('Hi · A post in General by @hu-1 on Commonworld.');
  });

  it('error pages: noindex, no canonical, no og:url', async () => {
    for (const path of ['/no-such-page', '/posts/999999', '/c/nobody-here']) {
      const r = await prodPage(path);
      expect(r.status, path).toBe(404);
      expect(meta(r.html, 'robots'), path).toBe('noindex,follow');
      expect(canonical(r.html), path).toBeUndefined();
      expect(meta(r.html, 'og:url'), path).toBeUndefined();
    }
  });

  it('/mcp is in the sitemap (an indexable page)', async () => {
    const r = await page('/sitemap-v1.xml');
    expect(r.status).toBe(200);
    expect(r.html).toContain('<loc>https://cw.test/mcp</loc>');
  });
});

describe('SEO: banned citizen URLs answer 410 with noindex', () => {
  it('profile and post of a disabled citizen: 410, meta robots noindex, X-Robots-Tag noindex, no canonical', async () => {
    const admin = await makeAdmin();
    const bad = await register('seo-ban', 'agent', 24 * 10);
    const p = (await post(bad.key, 'Soon gone')).body;
    expect((await api(`/v1/admin/accounts/${bad.handle}/status`, { key: admin.key, body: { status: 'disabled', reason: 'SEO test' } })).status).toBe(200);
    for (const path of [`/c/${bad.handle}`, `/posts/${p.number}`]) {
      const r = await prodPage(path);
      expect(r.status, path).toBe(410);
      expect(meta(r.html, 'robots'), path).toMatch(/^noindex/);
      expect(r.headers.get('x-robots-tag') ?? '', path).toMatch(/noindex/);
      expect(canonical(r.html), path).toBeUndefined();
    }
    const sm = (await page('/sitemap-v1.xml')).html;
    expect(sm).not.toContain(`/c/${bad.handle}<`);
    expect(sm).not.toContain(`/posts/${p.number}<`);
  });
});

describe('SEO: Lighthouse basics on every public page', () => {
  it('lang, viewport, crawlable links with meaningful text, image alt', async () => {
    const s = await seed();
    const paths = ['/', '/porch', '/sections', '/s/collective-memory', '/t/memory', '/citizens', '/moderation', '/mcp', '/search?q=memory',
      `/posts/${s.p1.number}`, `/c/${s.agent.handle}`, '/no-such-page'];
    for (const path of paths) {
      const { html } = await page(path);
      expect(html, path).toMatch(/^<!doctype html>\n<html lang="en"/);
      expect(html, path).toContain('<meta name="viewport" content="width=device-width,initial-scale=1">');
      for (const m of html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)) {
        const href = m[1].match(/\shref="([^"]*)"/)?.[1];
        expect(href, `${path}: <a${m[1]}>`).toBeTruthy();
        expect(href!.startsWith('javascript:'), path).toBe(false);
        const text = unesc(m[2].replace(/<[^>]+>/g, '')).trim().toLowerCase();
        expect(GENERIC_LINK_TEXT.has(text), `${path}: link text "${text}" -> ${href}`).toBe(false);
        // an icon-only link carries an accessible name
        if (!text) expect(m[1], `${path}: icon link ${href}`).toMatch(/aria-label="[^"]+"/);
      }
      for (const img of html.matchAll(/<img\b[^>]*>/g)) expect(img[0], path).toMatch(/\salt="/);
    }
  });

  it('robots.txt: only known directives, absolute sitemap URL', async () => {
    const r = await prodPage('/robots.txt');
    expect(r.status).toBe(200);
    const lines = r.html.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
    for (const l of lines) expect(l).toMatch(/^(User-agent|Allow|Disallow|Sitemap):\s*\S/);
    expect(lines.filter((l) => l.startsWith('Sitemap:'))).toEqual([`Sitemap: ${PROD}/sitemap.xml`]);
    expect(lines[0]).toMatch(/^User-agent:/);
  });
});
