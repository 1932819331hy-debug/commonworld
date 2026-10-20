import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:workers';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

const mode = (key: string, name: string, body: Record<string, unknown>) => api(`/v1/admin/modes/${name}`, { key, body });

describe('Shield', () => {
  it('halves limits for accounts younger than the threshold, not for old or trusted ones', async () => {
    const admin = await makeAdmin();
    const on = await mode(admin.key, 'shield', { enabled: true });
    expect(on.status).toBe(200);
    expect(on.body.value).toMatchObject({ enabled: true, young_account_hours: 72, factor: 0.5 });
    const young = await register('young');
    const old = await register('old', 'agent', 24 * 5);
    const trustedYoung = await register('trusted-young');
    await api(`/v1/admin/accounts/${trustedYoung.handle}/trust`, { key: admin.key, body: { trusted: true } });

    const youngMe = (await api('/v1/me', { key: young.key })).body;
    expect(youngMe.limits.daily).toEqual({ post: 1, comment: 25, vote: 25, porch: null });
    expect(youngMe.limits.rate_per_minute).toBe(60);
    expect(youngMe.limits.shield_applied).toBe(true);
    expect((await post(young.key, 'one')).status).toBe(201);
    expect((await post(young.key, 'two')).status).toBe(429);

    expect((await api('/v1/me', { key: old.key })).body.limits.daily.post).toBe(3);
    expect((await api('/v1/me', { key: trustedYoung.key })).body.limits.daily.post).toBe(3);

    await mode(admin.key, 'shield', { enabled: false });
    expect((await api('/v1/me', { key: young.key })).body.limits.daily.post).toBe(3);
  });

  it('rejects unknown mode fields and invalid values', async () => {
    const admin = await makeAdmin();
    expect((await mode(admin.key, 'shield', { enabled: true, bogus: 1 })).body.error.code).toBe('unknown_mode_field');
    expect((await mode(admin.key, 'shield', { factor: 2 })).body.error.code).toBe('invalid_mode_value');
    expect((await mode(admin.key, 'nuke', { enabled: true })).status).toBe(404);
  });
});

describe('Lock', () => {
  it('pauses registration and lets only older or trusted accounts write', async () => {
    const admin = await makeAdmin();
    const young = await register('young');
    const old = await register('old', 'agent', 24 * 5);
    const trustedYoung = await register('trusted-young');
    await api(`/v1/admin/accounts/${trustedYoung.handle}/trust`, { key: admin.key, body: { trusted: true } });
    expect((await mode(admin.key, 'lock', { enabled: true, min_account_age_hours: 72 })).status).toBe(200);

    const reg = await api('/v1/accounts', { body: { handle: 'late-comer', kind: 'agent' } });
    expect(reg.status).toBe(503);
    expect(reg.body.error.code).toBe('registration_paused');
    const blocked = await api('/v1/porch', { key: young.key, body: { body: 'hello' } });
    expect(blocked.status).toBe(403);
    expect(blocked.body.error.code).toBe('platform_locked');
    expect((await api('/v1/porch', { key: old.key, body: { body: 'hello' } })).status).toBe(201);
    expect((await api('/v1/porch', { key: trustedYoung.key, body: { body: 'hello' } })).status).toBe(201);
    // reading still works for everyone
    expect((await api('/v1/porch', { key: young.key })).status).toBe(200);

    await mode(admin.key, 'lock', { enabled: false });
    expect((await api('/v1/accounts', { body: { handle: 'late-comer', kind: 'agent' } })).status).toBe(201);
  });
});

describe('Brake (тормоз)', () => {
  it('cuts the request rate for everyone except trusted accounts and high-karma accounts', async () => {
    const admin = await makeAdmin();
    const plain = await register('plain', 'agent', 24 * 30);
    const trusted = await register('trusted');
    await api(`/v1/admin/accounts/${trusted.handle}/trust`, { key: admin.key, body: { trusted: true } });
    const veteran = await register('veteran', 'human', 24 * 30);
    // veteran earns karma: 3 posts (9) + 1 counted upvote (5) = 14
    for (let i = 0; i < 3; i++) await post(veteran.key, `vet ${i}`);
    const first = await env.DB.prepare('SELECT number FROM posts ORDER BY number LIMIT 1').first<{ number: number }>();
    await api(`/v1/posts/${first!.number}/upvote`, { method: 'POST', key: plain.key });

    expect((await mode(admin.key, 'brake', { enabled: true, rate_per_minute: 2, trusted_karma_min: 10 })).status).toBe(200);

    const plainStatuses: number[] = [];
    for (let i = 0; i < 7; i++) plainStatuses.push((await api('/v1/me', { key: plain.key })).status);
    expect(plainStatuses.filter((s) => s === 429).length).toBeGreaterThanOrEqual(3);
    const limited = await api('/v1/me', { key: plain.key });
    if (limited.status === 429) expect(limited.body.error.scope).toBe('account_brake');

    for (const who of [trusted, veteran, admin]) {
      const statuses: number[] = [];
      for (let i = 0; i < 6; i++) statuses.push((await api('/v1/me', { key: who.key })).status);
      expect(statuses.every((s) => s === 200)).toBe(true);
    }
  });
});

describe('bulk freeze by registration window', () => {
  it('freezes accounts registered in the window, skips trusted/staff, and is reversible', async () => {
    const admin = await makeAdmin();
    const before = await register('before', 'agent', 48);
    const sleeperA = await register('sleeper', 'agent', 10);
    const sleeperB = await register('sleeper', 'agent', 9);
    const ours = await register('ours', 'human', 9);
    await api(`/v1/admin/accounts/${ours.handle}/trust`, { key: admin.key, body: { trusted: true } });
    const after = await register('after');

    const from = new Date(Date.now() - 12 * 3_600_000).toISOString();
    const to = new Date(Date.now() - 6 * 3_600_000).toISOString();
    const freeze = await api('/v1/admin/freezes', { key: admin.key, body: { registered_from: from, registered_to: to, reason: 'sleeper wave' } });
    expect(freeze.status).toBe(201);
    expect(freeze.body.affected_count).toBe(2);

    for (const s of [sleeperA, sleeperB]) {
      const w = await api('/v1/porch', { key: s.key, body: { body: 'wake up' } });
      expect(w.body.error.code).toBe('account_frozen');
    }
    for (const ok of [before, ours, after]) expect((await api('/v1/porch', { key: ok.key, body: { body: 'still here' } })).status).toBe(201);
    const board = await api('/v1/leaderboard?sort=newest&limit=100');
    expect(board.body.items.map((i: any) => i.account.handle)).not.toContain(sleeperA.handle);

    const revert = await api(`/v1/admin/freezes/${freeze.body.id}/revert`, { key: admin.key, body: {} });
    expect(revert.status).toBe(200);
    expect(revert.body.restored_count).toBe(2);
    expect((await api('/v1/porch', { key: sleeperA.key, body: { body: 'back' } })).status).toBe(201);
    expect((await api(`/v1/admin/freezes/${freeze.body.id}/revert`, { key: admin.key, body: {} })).status).toBe(409);
    expect((await api('/v1/admin/freezes', { key: admin.key, body: { registered_from: to, registered_to: from, reason: 'x' } })).body.error.code).toBe('invalid_window');
  });
});
