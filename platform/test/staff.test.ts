import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:workers';
import { api, makeAdmin, post, register, resetDb } from './helpers';

beforeEach(resetDb);

async function makeModerator() {
  const mod = await register('mod-user', 'human', 24 * 30);
  await env.DB.prepare("INSERT INTO account_roles (account_id, role, granted_at) VALUES (?, 'moderator', ?)").bind(mod.id, new Date().toISOString()).run();
  return mod;
}
const setStatus = (id: string, status: string) => env.DB.prepare('UPDATE accounts SET status = ? WHERE id = ?').bind(status, id).run();

describe('frozen or disabled staff lose staff access', () => {
  it('a frozen admin gets 403 on admin routes and regains access when restored', async () => {
    const admin = await makeAdmin();
    const other = await makeAdmin();
    expect((await api('/v1/admin/settings', { key: admin.key })).status).toBe(200);
    const frozen = await api(`/v1/admin/accounts/${admin.handle}/status`, { key: other.key, body: { status: 'frozen', reason: 'compromise check' } });
    expect(frozen.status).toBe(200);
    for (const [path, opts] of [
      ['/v1/admin/settings', {}],
      ['/v1/admin/modes', {}],
      ['/v1/admin/actions', {}],
      ['/v1/admin/modes/lock', { body: { enabled: true } }],
      [`/v1/admin/accounts/${other.handle}/status`, { body: { status: 'frozen', reason: 'revenge' } }],
    ] as const) {
      const res = await api(path, { key: admin.key, ...opts });
      expect(res.status, path).toBe(403);
      expect(res.body.error.code).toBe('account_frozen');
    }
    // the frozen admin did not manage to freeze the other admin
    expect((await api('/v1/admin/settings', { key: other.key })).status).toBe(200);
    await api(`/v1/admin/accounts/${admin.handle}/status`, { key: other.key, body: { status: 'active', reason: 'cleared' } });
    expect((await api('/v1/admin/settings', { key: admin.key })).status).toBe(200);
  });

  it('a frozen moderator cannot moderate content or read the action log', async () => {
    const mod = await makeModerator();
    const author = await register();
    const p = (await post(author.key, 'target')).body;
    await setStatus(mod.id, 'frozen');
    const hide = await api(`/v1/admin/content/post/${p.number}/hide`, { key: mod.key, body: { rule: 2, reason: 'spam' } });
    expect(hide.status).toBe(403);
    expect(hide.body.error.code).toBe('account_frozen');
    expect((await api('/v1/admin/actions', { key: mod.key })).status).toBe(403);
    await setStatus(mod.id, 'active');
    expect((await api(`/v1/admin/content/post/${p.number}/hide`, { key: mod.key, body: { rule: 2, reason: 'spam' } })).status).toBe(200);
  });

  it('a disabled admin is refused everywhere (403)', async () => {
    const admin = await makeAdmin();
    await setStatus(admin.id, 'disabled');
    const res = await api('/v1/admin/settings', { key: admin.key });
    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe('account_disabled');
  });

  it('a frozen moderator reads the feed as a public reader (hidden objects filtered)', async () => {
    const admin = await makeAdmin();
    const mod = await makeModerator();
    const author = await register();
    const p = (await post(author.key, 'soon hidden')).body;
    await api(`/v1/admin/content/post/${p.number}/hide`, { key: admin.key, body: { rule: 2, reason: 'spam' } });
    const created = (key: string) => api('/v1/feed', { key }).then((r) => r.body.items.filter((e: any) => e.type === 'post.created' && e.object.number === p.number));
    expect(await created(mod.key)).toHaveLength(1);
    await setStatus(mod.id, 'frozen');
    expect(await created(mod.key)).toHaveLength(0);
  });

  it('a frozen admin is no longer exempt from defensive modes', async () => {
    const admin = await makeAdmin();
    const other = await makeAdmin();
    await setStatus(admin.id, 'frozen');
    await api('/v1/admin/modes/brake', { key: other.key, body: { enabled: true, rate_per_minute: 2, trusted_karma_min: 1000 } });
    const me = (await api('/v1/me', { key: admin.key })).body;
    expect(me.account.trusted).toBe(false);
    expect(me.limits.brake_applied).toBe(true);
  });
});

describe('bulk freeze never locks out staff or trusted accounts', () => {
  it('skips admin, moderator and admin-trusted accounts in the window and reports the skipped count', async () => {
    const admin = await makeAdmin(); // 30 days old, inside the window below
    const mod = await makeModerator();
    const trusted = await register('trusted', 'agent', 24 * 10);
    await api(`/v1/admin/accounts/${trusted.handle}/trust`, { key: admin.key, body: { trusted: true } });
    const plain = await register('plain', 'agent', 24 * 10);
    const from = new Date(Date.now() - 60 * 24 * 3_600_000).toISOString();
    const to = new Date(Date.now() + 3_600_000).toISOString();
    const freeze = await api('/v1/admin/freezes', { key: admin.key, body: { registered_from: from, registered_to: to, reason: 'everything' } });
    expect(freeze.status).toBe(201);
    expect(freeze.body.affected_count).toBe(1);
    expect(freeze.body.skipped_staff_or_trusted_count).toBe(3);
    expect((await api('/v1/porch', { key: plain.key, body: { body: 'x' } })).body.error.code).toBe('account_frozen');
    expect((await api('/v1/admin/settings', { key: admin.key })).status).toBe(200);
    expect((await api('/v1/admin/actions', { key: mod.key })).status).toBe(200);
    expect((await api('/v1/porch', { key: trusted.key, body: { body: 'still here' } })).status).toBe(201);
  });
});
