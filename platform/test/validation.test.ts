import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:workers';
import { api, makeAdmin, resetDb } from './helpers';

beforeEach(resetDb);

// Inherited object names must never pass a lookup that guards a user-supplied key.
const INHERITED = ['constructor', '__proto__', 'toString', 'hasOwnProperty'];

describe('own-key validation of user-supplied names', () => {
  it('rejects inherited names as leaderboard sort/kind with 400, not 500', async () => {
    for (const name of INHERITED) {
      const sort = await api(`/v1/leaderboard?sort=${encodeURIComponent(name)}`);
      expect(sort.status).toBe(400);
      expect(sort.body.error.code).toBe('invalid_sort');
      const kind = await api(`/v1/leaderboard?kind=${encodeURIComponent(name)}`);
      expect(kind.status).toBe(400);
      expect(kind.body.error.code).toBe('invalid_kind');
    }
    expect((await api('/v1/leaderboard?sort=karma_7d')).status).toBe(200);
  });

  it('rejects inherited names as setting keys and writes nothing', async () => {
    const admin = await makeAdmin();
    for (const name of INHERITED) {
      const res = await api('/v1/admin/settings', { method: 'PATCH', key: admin.key, raw: `{"values":{"${name}":1}}`, headers: { 'content-type': 'application/json' } });
      expect(res.status).toBe(400);
      expect(res.body.error.code).toBe('unknown_setting');
    }
    const rows = await env.DB.prepare('SELECT key FROM settings').all<{ key: string }>();
    expect(rows.results.map((r) => r.key).filter((k) => INHERITED.includes(k))).toEqual([]);
  });

  it('rejects inherited names as mode fields (400) and mode names (404)', async () => {
    const admin = await makeAdmin();
    for (const name of INHERITED) {
      const res = await api('/v1/admin/modes/shield', { key: admin.key, raw: `{"${name}":1}`, headers: { 'content-type': 'application/json' } });
      expect(res.status).toBe(400);
      expect(res.body.error.code).toBe('unknown_mode_field');
    }
    for (const name of ['constructor', 'tostring']) {
      const res = await api(`/v1/admin/modes/${name}`, { key: admin.key, body: { enabled: true } });
      expect(res.status).toBe(404);
      expect(res.body.error.code).toBe('unknown_mode');
    }
  });

  it('rejects inherited names as account status and limit fields', async () => {
    const admin = await makeAdmin();
    const target = await api('/v1/accounts', { body: { handle: 'target-acct', kind: 'agent' } });
    const handle = target.body.account.handle;
    for (const name of INHERITED) {
      const status = await api(`/v1/admin/accounts/${handle}/status`, { key: admin.key, body: { status: name, reason: 'x' } });
      expect(status.status).toBe(400);
      expect(status.body.error.code).toBe('invalid_status');
      const limits = await api(`/v1/admin/accounts/${handle}/limits`, { method: 'PUT', key: admin.key, raw: `{"${name}":1}`, headers: { 'content-type': 'application/json' } });
      expect(limits.status).toBe(400);
      expect(limits.body.error.code).toBe('unknown_limit_field');
    }
  });
});
