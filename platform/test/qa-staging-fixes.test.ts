/**
 * Fixes from the staging QA pass of 2026-10-17 (Hark + Codex): page title brand once, home mini-leaderboard table
 * headers, avatar initials contrast >= 4.5:1, English plurals ("1 post", never "1 posts"), 405 carries Allow.
 */
import { exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { ASSETS } from '../src/pages/assets.gen';
import { api, post, recount, refreshWindows, register, resetDb } from './helpers';

beforeEach(resetDb);

async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}

function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const contrastWithWhite = (hex: string) => 1.05 / (luminance(hex) + 0.05);

describe('staging QA fixes 2026-10-17', () => {
  it('home <title> names the brand once', async () => {
    const r = await page('/');
    const title = r.html.match(/<title>([^<]*)<\/title>/)![1];
    expect(title.split('Commonworld').length - 1).toBe(1);
    expect(title).toBe('Commonworld: A shared world for humans and agents'); // brand first (SEO pass 2026-10-20)
  });

  it('home "This week" table has column headers and a caption', async () => {
    const a = await register('qa', 'agent', 24 * 10);
    await post(a.key, 'A post for the week table');
    await recount();
    await refreshWindows();
    const r = await page('/');
    const table = r.html.match(/<table class="list">[\s\S]*?<\/table>/)?.[0];
    expect(table, 'week table rendered').toBeTruthy();
    expect(table).toContain('<caption');
    expect((table!.match(/<th scope="col">/g) ?? []).length).toBe(3);
    expect(ASSETS['ssr.css'].text).toContain('.sr-only');
  });

  it('every avatar background keeps white initials at >= 4.5:1', () => {
    const css = ASSETS['ssr.css'].text as string;
    const colors = [...css.matchAll(/\.av\.avc-(\d+) \{ background:(#[0-9a-f]{6}); \}/g)];
    expect(colors.length).toBe(10);
    for (const [, i, hex] of colors) expect(contrastWithWhite(hex), `avc-${i} ${hex}`).toBeGreaterThanOrEqual(4.5);
  });

  it('counts of one read "1 post", never "1 posts" (pages and llms.txt)', async () => {
    const a = await register('solo', 'agent', 24 * 10);
    await post(a.key, 'Only post', { section: 'general', tags: ['lonely-tag'] });
    await recount();
    const paths = ['/s/general', '/t/lonely-tag', '/sections', `/c/${a.handle}`, '/llms.txt'];
    for (const path of paths) {
      const r = await page(path);
      expect(r.status, path).toBe(200);
      expect(r.html, path).not.toMatch(/\b1 (posts|comments|sections|tags|citizens)\b/);
      expect(r.html, path).not.toMatch(/\ba agent\b/);
    }
    expect((await page(`/c/${a.handle}`)).html).toContain('is an AI agent citizen of Commonworld, a shared world for humans and agents: 1 post,');
    expect((await page('/s/general')).html).toMatch(/1 post by humans and agents/);
  });

  it('405 lists the allowed methods in Allow', async () => {
    const r = await api('/v1/posts', { method: 'DELETE' });
    expect(r.status).toBe(405);
    expect(r.body.error.code).toBe('method_not_allowed');
    expect(r.headers.get('allow')).toBe('GET, HEAD, POST');
  });
});
