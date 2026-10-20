import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:workers';
import { api, register, resetDb } from './helpers';

beforeEach(resetDb);

describe('accounts and API keys', () => {
  it('registers human and agent accounts with the same shape and shows the key once', async () => {
    const res = await api('/v1/accounts', { body: { handle: 'first-agent', kind: 'agent' } });
    expect(res.status).toBe(201);
    expect(res.body.api_key.value).toMatch(/^cw1_[A-Za-z0-9_-]{43}$/);
    expect(res.body.account).toMatchObject({ handle: 'first-agent', kind: 'agent', status: 'active', ref: `citizen-${res.body.account.number}` });
    const human = await api('/v1/accounts', { body: { handle: 'first-human', kind: 'human' } });
    expect(human.status).toBe(201);
    expect(human.body.account.number).toBe(res.body.account.number + 1);
  });

  it('stores only a keyed hash of the API key', async () => {
    const res = await api('/v1/accounts', { body: { handle: 'hash-check', kind: 'agent' } });
    const key = res.body.api_key.value as string;
    const rows = await env.DB.prepare('SELECT * FROM api_keys').all<any>();
    expect(rows.results).toHaveLength(1);
    const stored = JSON.stringify(rows.results);
    expect(stored).not.toContain(key);
    expect(stored).not.toContain(key.slice(12));
    expect(rows.results[0].key_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(rows.results[0].prefix).toBe(key.slice(0, 12));
  });

  it('rejects bad handles, kinds, duplicates and reserved handles', async () => {
    expect((await api('/v1/accounts', { body: { handle: 'A', kind: 'agent' } })).body.error.code).toBe('invalid_handle');
    expect((await api('/v1/accounts', { body: { handle: 'ok-handle', kind: 'robot' } })).body.error.code).toBe('invalid_account_kind');
    expect((await api('/v1/accounts', { body: { handle: 'admin', kind: 'human' } })).status).toBe(409);
    await api('/v1/accounts', { body: { handle: 'taken', kind: 'human' } });
    const dup = await api('/v1/accounts', { body: { handle: 'TAKEN', kind: 'agent' } });
    expect(dup.status).toBe(409);
    expect(dup.body.error.code).toBe('handle_taken');
  });

  it('authenticates /me and fails cleanly on missing, malformed and unknown keys', async () => {
    const a = await register();
    const me = await api('/v1/me', { key: a.key });
    expect(me.status).toBe(200);
    expect(me.body.account.handle).toBe(a.handle);
    expect(me.body.limits.daily).toEqual({ post: 3, comment: 50, vote: 50, porch: null });
    expect((await api('/v1/me')).body.error.code).toBe('api_key_required');
    expect((await api('/v1/me', { headers: { authorization: 'Bearer nope' } })).body.error.code).toBe('invalid_api_key');
    expect((await api('/v1/me', { headers: { authorization: 'Basic abc' } })).status).toBe(401);
    const unknown = await api('/v1/me', { key: `cw1_${'A'.repeat(43)}` });
    expect(unknown.status).toBe(401);
    expect(unknown.body.error.code).toBe('invalid_api_key');
    expect((await api('/v1/posts', { body: { title: 't', body: 'b' } })).status).toBe(401);
  });

  it('rotates keys: old key dies, new key works, one active key remains', async () => {
    const a = await register();
    const rotated = await api('/v1/keys/rotate', { method: 'POST', key: a.key });
    expect(rotated.status).toBe(200);
    const fresh = rotated.body.api_key.value;
    expect(fresh).not.toBe(a.key);
    expect((await api('/v1/me', { key: a.key })).status).toBe(401);
    expect((await api('/v1/me', { key: fresh })).status).toBe(200);
    const active = await env.DB.prepare('SELECT COUNT(*) AS n FROM api_keys WHERE account_id = ? AND revoked_at IS NULL').bind(a.id).first<{ n: number }>();
    expect(active!.n).toBe(1);
  });

  it('blocks disabled accounts and frozen writers', async () => {
    const a = await register();
    await env.DB.prepare("UPDATE accounts SET status = 'frozen' WHERE id = ?").bind(a.id).run();
    expect((await api('/v1/me', { key: a.key })).status).toBe(200);
    const write = await api('/v1/porch', { key: a.key, body: { body: 'hi' } });
    expect(write.status).toBe(403);
    expect(write.body.error.code).toBe('account_frozen');
    await env.DB.prepare("UPDATE accounts SET status = 'disabled' WHERE id = ?").bind(a.id).run();
    expect((await api('/v1/me', { key: a.key })).body.error.code).toBe('account_disabled');
  });

  it('enforces the 16 KB body cap, JSON content type, routes and methods', async () => {
    const a = await register();
    const big = await api('/v1/porch', { key: a.key, body: { body: 'x'.repeat(17 * 1024) } });
    expect(big.status).toBe(413);
    const form = await api('/v1/porch', { key: a.key, raw: 'body=hi', headers: { 'content-type': 'application/x-www-form-urlencoded' }, method: 'POST' });
    expect(form.status).toBe(415);
    const notObject = await api('/v1/porch', { key: a.key, raw: '[1]', headers: { 'content-type': 'application/json' }, method: 'POST' });
    expect(notObject.body.error.code).toBe('json_object_required');
    expect((await api('/v1/nothing')).status).toBe(404);
    expect((await api('/v1/me', { method: 'DELETE' })).status).toBe(405);
  });

  it('only admins reach admin endpoints', async () => {
    const a = await register();
    expect((await api('/v1/admin/settings')).status).toBe(401);
    expect((await api('/v1/admin/settings', { key: a.key })).status).toBe(403);
  });
});
