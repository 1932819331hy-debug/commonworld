/**
 * D1 allows at most 100 bound parameters per query. A post page with more than 100 hidden comments used to bind one
 * parameter per comment in `IN (?, ?, …)` (lastModerationMany) and failed with a 500. The numbers now go in as one
 * JSON array (json_each), so any count works.
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { lastModerationMany } from '../src/routes/moderation';
import { makeAdmin, post, register, resetDb } from './helpers';

beforeEach(resetDb);

async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text() };
}

describe('more than 100 hidden comments on one post', () => {
  it('renders the post page and finds the moderation entry for every hidden comment', async () => {
    const admin = await makeAdmin();
    const a = await register('busy', 'agent', 240);
    const p = (await post(a.key, 'many hidden')).body;
    const now = new Date().toISOString();
    const N = 130;
    const stmts: D1PreparedStatement[] = [];
    for (let i = 0; i < N; i++) {
      stmts.push(env.DB.prepare(`INSERT INTO comments (id, post_number, parent_number, author_id, body, depth, status, created_at)
        VALUES (?, ?, NULL, ?, 'x', 1, 'hidden', ?)`).bind(`cmt_bulk_${i}`, p.number, a.id, now));
    }
    await env.DB.batch(stmts);
    const { results } = await env.DB.prepare('SELECT number FROM comments WHERE post_number = ? ORDER BY number').bind(p.number).all<{ number: number }>();
    expect(results.length).toBe(N);
    await env.DB.batch(results.map((r) => env.DB.prepare(`INSERT INTO events (type, object_type, object_number, actor_id, data_json, created_at)
      VALUES ('content.hidden', 'comment', ?, ?, '{"rule":2,"reason":"bulk"}', ?)`).bind(r.number, admin.id, now)));

    const map = await lastModerationMany(env as any, 'comment', results.map((r) => r.number));
    expect(map.size).toBe(N);

    const res = await page(`/posts/${p.number}`);
    expect(res.status).toBe(200);
    expect(res.html.split('Hidden comment').length - 1).toBe(N);
  });
});
