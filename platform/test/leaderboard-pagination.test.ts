import { beforeEach, describe, expect, it } from 'vitest';
import { exports } from 'cloudflare:workers';
import { api, register, resetDb } from './helpers';

beforeEach(resetDb);

async function page(path: string) {
  const response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`));
  expect(response.status).toBe(200);
  return response.text() as Promise<string>;
}

async function citizens(n: number, kind: 'human' | 'agent' = 'human') {
  for (let i = 0; i < n; i++) await register('pager', kind);
}

async function checkPage(query: string, next: number | null) {
  const html = await page(`/citizens${query}`);
  const md = await page(`/citizens.md${query}`);
  expect(html.includes('Next 50 →')).toBe(next !== null);
  expect(html.includes('<link rel="next"')).toBe(next !== null);
  expect(md.includes('Next page:')).toBe(next !== null);
  if (next !== null) {
    expect(html).toContain(`offset=${next}`);
    expect(md).toContain(`offset=${next}`);
  }
  if (query) {
    expect(html).toContain('content="noindex,follow"');
    // Markdown variants keep the existing noindex header, checked separately below.
  }
}

describe('leaderboard continuation', () => {
  it('returns no continuation for empty, short or exactly full final pages', async () => {
    for (const [add, count] of [[0, 0], [49, 49], [1, 50]]) {
      await citizens(add);
      const res = await api('/v1/leaderboard');
      expect(res.status).toBe(200);
      expect(res.body).toMatchObject({ limit: 50, offset: 0, next_offset: null });
      expect(res.body.items).toHaveLength(count);
      await checkPage('', null);
    }
  });

  it('51 citizens link to a single final row; 100 citizens do not link past the last full page', async () => {
    await citizens(51);
    const first = await api('/v1/leaderboard');
    expect(first.body.items).toHaveLength(50);
    expect(first.body.next_offset).toBe(50);
    await checkPage('', 50);
    const last = await api('/v1/leaderboard?offset=50');
    expect(last.body.items).toHaveLength(1);
    expect(last.body.items[0].rank).toBe(51);
    expect(last.body.next_offset).toBeNull();
    await checkPage('?offset=50', null);
    await citizens(49);
    const fullLast = await api('/v1/leaderboard?offset=50');
    expect(fullLast.body.items).toHaveLength(50);
    expect(fullLast.body.next_offset).toBeNull();
    await checkPage('?offset=50', null);
  });

  it('preserves filter/sort in continuation links and keeps variants noindex', async () => {
    await citizens(51, 'agent');
    await citizens(1, 'human');
    const query = '?kind=agent&sort=newest';
    const html = await page(`/citizens${query}`);
    const md = await page(`/citizens.md${query}`);
    expect(html).toContain('sort=newest&amp;kind=agent&amp;offset=50');
    expect(html).toContain('content="noindex,follow"');
    const next = new URL(md.match(/^Next page: (\S+)$/m)![1]);
    expect(next.pathname).toBe('/citizens.md');
    expect(Object.fromEntries(next.searchParams)).toEqual({ kind: 'agent', sort: 'newest', offset: '50' });
    const response = await (exports as any).default.fetch(new Request(`https://cw.test/citizens.md${query}`));
    expect(response.headers.get('x-robots-tag')).toContain('noindex');
    const last = await api('/v1/leaderboard?kind=agent&sort=newest&offset=50');
    expect(last.body.items).toHaveLength(1);
    expect(last.body.next_offset).toBeNull();
  });

  it('preserves API limits and validation without leaking the lookahead row', async () => {
    await citizens(2);
    const one = await api('/v1/leaderboard?limit=1');
    expect(one.body.items).toHaveLength(1);
    expect(one.body.next_offset).toBe(1);
    const last = await api('/v1/leaderboard?limit=1&offset=1');
    expect(last.body.items).toHaveLength(1);
    expect(last.body.items[0].rank).toBe(2);
    expect(last.body.next_offset).toBeNull();
    expect((await api('/v1/leaderboard?limit=100')).body.limit).toBe(100);
    expect((await api('/v1/leaderboard?offset=10000')).body.next_offset).toBeNull();
    for (const query of ['limit=0', 'limit=101', 'offset=10001', 'offset=-1']) {
      expect((await api(`/v1/leaderboard?${query}`)).status).toBe(400);
    }
    const spec = (await api('/openapi.json')).body;
    const schema = spec.paths['/v1/leaderboard'].get.responses['200'].content['application/json'].schema;
    expect(schema.required).toContain('next_offset');
    expect(schema.properties.next_offset.type).toEqual(['integer', 'null']);
  });
});
