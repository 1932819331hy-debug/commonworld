import { env } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { api, post, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

async function setup() {
  await setSetting('limits.daily.post', 20);
  const author = await register('case-filter', 'human', 24 * 10);
  const first = await post(author.key, 'first', { section: 'general', tags: ['mcp'] });
  const second = await post(author.key, 'second', { section: 'general', tags: ['mcp'] });
  const other = await post(author.key, 'other', { section: 'protocol', tags: ['memory'] });
  const hidden = await post(author.key, 'hidden', { section: 'general', tags: ['mcp'] });
  for (const result of [first, second, other, hidden]) expect(result.status).toBe(201);
  await env.DB.prepare("UPDATE posts SET status = 'hidden' WHERE number = ?").bind(hidden.body.number).run();
  return { author, numbers: [second.body.number, first.body.number] };
}

describe('post section and tag filters normalize case (#175)', () => {
  for (const sort of ['latest', 'unanswered', 'top', 'discussed']) {
    it(`${sort}: mixed-case filters match canonical slugs without exposing hidden posts`, async () => {
      const { author, numbers } = await setup();
      const prefix = `sort=${sort}${sort === 'top' || sort === 'discussed' ? '&window=all' : ''}`;
      for (const query of [
        'section=general&tag=mcp',
        'section=General',
        'tag=MCP',
        `section=GENERAL&tag=Mcp&author=${author.handle.toUpperCase()}`,
      ]) {
        const result = await api(`/v1/posts?${prefix}&${query}`);
        expect(result.status, query).toBe(200);
        expect(result.body.items.map((p: any) => p.number), query).toEqual(numbers);
      }
    });
  }

  it('normalizes both the merged-tag lookup and its target fallback', async () => {
    const { numbers } = await setup();
    await env.DB.prepare("UPDATE tags SET status = 'merged', merged_into = 'mcp' WHERE slug = 'memory'").run();
    for (const tag of ['memory', 'MeMoRy', 'MCP']) {
      const result = await api(`/v1/posts?tag=${tag}&section=General`);
      expect(result.status).toBe(200);
      expect(result.body.items.map((p: any) => p.number)).toEqual(numbers);
    }
  });

  it('preserves latest and ranked pagination with mixed-case filters', async () => {
    const { numbers } = await setup();
    for (const sort of ['latest', 'top']) {
      const query = `section=General&tag=MCP&limit=1&sort=${sort}${sort === 'top' ? '&window=all' : ''}`;
      const first = await api(`/v1/posts?${query}`);
      expect(first.status).toBe(200);
      expect(first.body.items.map((p: any) => p.number)).toEqual([numbers[0]]);
      const cursor = sort === 'top' ? `offset=${first.body.next_offset}` : `before=${first.body.next_before}`;
      expect(sort === 'top' ? first.body.next_offset : first.body.next_before).not.toBeNull();
      const second = await api(`/v1/posts?${query}&${cursor}`);
      expect(second.status).toBe(200);
      expect(second.body.items.map((p: any) => p.number)).toEqual([numbers[1]]);
    }
  });

  it('keeps unknown slugs empty rather than dropping their filters', async () => {
    await setup();
    for (const query of ['section=No-Such-Section', 'tag=No-Such-Tag']) {
      const result = await api(`/v1/posts?${query}`);
      expect(result.status).toBe(200);
      expect(result.body.items).toEqual([]);
    }
  });
});
