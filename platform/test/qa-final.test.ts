/**
 * Fixes from the final pre-launch staging QA (Hark, 2026-10-18):
 * - the porch counter is a rolling 24 h window (site_counters.porch24), so it is labeled "in 24 h", never "today"
 *   (staging showed "3 today" above lines grouped under "Yesterday");
 * - /moderation: the Target cell wraps (class mod-target) so long key-recovery targets do not push the Moderator and
 *   Status now columns out of the panel at 1100-1440 px.
 */
import { exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { ASSETS } from '../src/pages/assets.gen';
import { api, makeAdmin, recount, refreshWindows, register, resetDb } from './helpers';

beforeEach(resetDb);

async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text() };
}

describe('final QA fixes 2026-10-18', () => {
  it('porch counter and side box say "24 h", not "today"', async () => {
    const a = await register('porchy', 'agent', 24 * 10);
    const r1 = await api('/v1/porch', { method: 'POST', key: a.key, body: { body: 'hello porch' } });
    expect(r1.status).toBe(201);
    await recount();
    await refreshWindows();
    for (const path of ['/', '/porch']) {
      const r = await page(path);
      expect(r.status).toBe(200);
      expect(r.html).toMatch(/1 in 24 h<\/span>/);
      expect(r.html).not.toMatch(/\d today<\/span>/);
    }
    const porch = await page('/porch');
    expect(porch.html).toContain('<h2>Most active, last 24 h</h2>');
    expect(porch.html).not.toContain('Most active today');
  });

  it('/moderation Target cell has the wrapping class and the CSS lets it wrap', async () => {
    const admin = await makeAdmin();
    const a = await register('modded', 'agent', 24 * 10);
    const line = await api('/v1/porch', { method: 'POST', key: a.key, body: { body: 'a line to hide' } });
    const hide = await api(`/v1/admin/content/porch/${line.body.number}/hide`, { key: admin.key, body: { rule: 1, note: 'QA test' } });
    expect(hide.status).toBe(200);
    const r = await page('/moderation');
    expect(r.status).toBe(200);
    expect(r.html).toContain('class="mod-target" data-label="Target"');
    const css = (ASSETS as any)['ssr.css'].text as string;
    const rule = css.match(/\.modlog td\.mod-target \{([^}]*)\}/)?.[1] ?? '';
    expect(rule).toContain('white-space:normal');
    expect(rule).toMatch(/max-width:\d+px/);
    expect(css).toMatch(/\.modlog td\.mod-when \{[^}]*white-space:normal/);
  });
});
