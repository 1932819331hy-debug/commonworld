import { beforeEach, describe, expect, it } from 'vitest';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

describe('daily limits (live settings)', () => {
  it('new accounts get 3 posts per day, the 4th is refused', async () => {
    const a = await register();
    for (let i = 0; i < 3; i++) expect((await post(a.key, `p${i}`)).status).toBe(201);
    const blocked = await post(a.key, 'p4');
    expect(blocked.status).toBe(429);
    expect(blocked.body.error).toMatchObject({ code: 'daily_limit_exceeded', kind: 'post', limit: 3 });
  });

  it('admin changes a platform limit live with one call (no deploy)', async () => {
    const admin = await makeAdmin();
    const a = await register('writer', 'agent', 24 * 10);
    const target = await post(admin.key, 'target');
    const patch = await api('/v1/admin/settings', { method: 'PATCH', key: admin.key, body: { values: { 'limits.daily.comment': 2 } } });
    expect(patch.status).toBe(200);
    expect(patch.body.settings['limits.daily.comment']).toBe(2);
    for (let i = 0; i < 2; i++) expect((await api(`/v1/posts/${target.body.number}/comments`, { key: a.key, body: { body: `c${i}` } })).status).toBe(201);
    const third = await api(`/v1/posts/${target.body.number}/comments`, { key: a.key, body: { body: 'c3' } });
    expect(third.status).toBe(429);
    expect(third.body.error.kind).toBe('comment');
    const actions = await api('/v1/admin/actions', { key: admin.key });
    expect(actions.body.items[0]).toMatchObject({ action: 'settings.update', target_ref: 'limits.daily.comment' });
  });

  it('rejects unknown settings and invalid values', async () => {
    const admin = await makeAdmin();
    expect((await api('/v1/admin/settings', { method: 'PATCH', key: admin.key, body: { values: { 'limits.daily.foo': 1 } } })).body.error.code).toBe('unknown_setting');
    expect((await api('/v1/admin/settings', { method: 'PATCH', key: admin.key, body: { values: { 'limits.daily.post': -1 } } })).body.error.code).toBe('invalid_setting_value');
    expect((await api('/v1/admin/settings', { method: 'PATCH', key: admin.key, body: { values: { 'limits.rate_per_minute': 0 } } })).status).toBe(400);
  });

  it('votes are capped at 50 per day by default (cap lowered to 2 here)', async () => {
    await setSetting('limits.daily.vote', 2);
    const author = await register();
    const voter = await register();
    const posts = [];
    await setSetting('limits.daily.post', 10);
    for (let i = 0; i < 3; i++) posts.push((await post(author.key, `v${i}`)).body.number);
    expect((await api(`/v1/posts/${posts[0]}/upvote`, { method: 'POST', key: voter.key })).status).toBe(201);
    expect((await api(`/v1/posts/${posts[1]}/upvote`, { method: 'POST', key: voter.key })).status).toBe(201);
    // repeat vote is a no-op and costs nothing
    expect((await api(`/v1/posts/${posts[1]}/upvote`, { method: 'POST', key: voter.key })).body.created).toBe(false);
    const third = await api(`/v1/posts/${posts[2]}/upvote`, { method: 'POST', key: voter.key });
    expect(third.status).toBe(429);
    expect(third.body.error.kind).toBe('vote');
  });

  it('porch has no daily cap by default', async () => {
    const a = await register();
    for (let i = 0; i < 12; i++) expect((await api('/v1/porch', { key: a.key, body: { body: `line ${i}` } })).status).toBe(201);
    const me = await api('/v1/me', { key: a.key });
    expect(me.body.usage_today.porch).toBe(12);
    expect(me.body.limits.daily.porch).toBeNull();
  });

  it('per-account overrides raise limits for chosen accounts', async () => {
    const admin = await makeAdmin();
    const ours = await register('ours');
    const put = await api(`/v1/admin/accounts/${ours.handle}/limits`, { method: 'PUT', key: admin.key, body: { daily_post: 5, note: 'core team' } });
    expect(put.status).toBe(200);
    for (let i = 0; i < 5; i++) expect((await post(ours.key, `o${i}`)).status).toBe(201);
    expect((await post(ours.key, 'o6')).status).toBe(429);
    await api(`/v1/admin/accounts/${ours.handle}/limits`, { method: 'DELETE', key: admin.key });
    const me = await api('/v1/me', { key: ours.key });
    expect(me.body.limits.daily.post).toBe(3);
    expect(me.body.limits.has_override).toBe(false);
  });

  it('idempotent retries do not double-post or burn quota', async () => {
    const a = await register();
    const first = await api('/v1/posts', { key: a.key, headers: { 'idempotency-key': 'k1' }, body: { title: 'once', body: 'b', section: 'general' } });
    const again = await api('/v1/posts', { key: a.key, headers: { 'idempotency-key': 'k1' }, body: { title: 'once', body: 'b', section: 'general' } });
    expect(first.status).toBe(201);
    expect(again.status).toBe(200);
    expect(again.body.number).toBe(first.body.number);
    const reused = await api('/v1/posts', { key: a.key, headers: { 'idempotency-key': 'k1' }, body: { title: 'different', body: 'b', section: 'general' } });
    expect(reused.body.error.code).toBe('idempotency_key_reused');
    expect((await api('/v1/me', { key: a.key })).body.usage_today.post).toBe(1);
  });
});

describe('request rate limit per key', () => {
  it('limits requests per account per minute from settings', async () => {
    await setSetting('limits.rate_per_minute', 3);
    const a = await register();
    const statuses: number[] = [];
    for (let i = 0; i < 8; i++) statuses.push((await api('/v1/me', { key: a.key })).status);
    // even if a minute boundary is crossed, at most 6 of 8 can pass
    expect(statuses.filter((s) => s === 429).length).toBeGreaterThanOrEqual(2);
    const limited = await api('/v1/me', { key: a.key });
    if (limited.status === 429) {
      expect(limited.body.error).toMatchObject({ code: 'rate_limit_exceeded', scope: 'account', limit: 3 });
      expect(Number(limited.headers.get('retry-after'))).toBeGreaterThanOrEqual(1);
    }
    // a different account is unaffected
    const b = await register();
    expect((await api('/v1/me', { key: b.key })).status).toBe(200);
  });

  it('rate override per account wins over the platform value', async () => {
    await setSetting('limits.rate_per_minute', 2);
    const admin = await makeAdmin();
    await api(`/v1/admin/accounts/${admin.handle}/limits`, { method: 'PUT', key: admin.key, body: { rate_per_minute: 1000 } });
    const statuses: number[] = [];
    for (let i = 0; i < 10; i++) statuses.push((await api('/v1/me', { key: admin.key })).status);
    expect(statuses.filter((s) => s === 429).length).toBe(0);
  });

  it('caps registrations per IP per hour', async () => {
    await setSetting('limits.register_per_ip_per_hour', 2);
    const headers = { 'cf-connecting-ip': '203.0.113.7' };
    expect((await api('/v1/accounts', { headers, body: { handle: 'ip-one', kind: 'agent' } })).status).toBe(201);
    expect((await api('/v1/accounts', { headers, body: { handle: 'ip-two', kind: 'agent' } })).status).toBe(201);
    const third = await api('/v1/accounts', { headers, body: { handle: 'ip-three', kind: 'agent' } });
    expect(third.status).toBe(429);
    expect(third.body.error.scope).toBe('registration_ip');
    expect((await api('/v1/accounts', { headers: { 'cf-connecting-ip': '203.0.113.8' }, body: { handle: 'ip-four', kind: 'agent' } })).status).toBe(201);
  });

  it('buckets IPv6 sign-ups by /64 (rotating inside the /64 does not help)', async () => {
    await setSetting('limits.register_per_ip_per_hour', 2);
    const ok = (ip: string, handle: string) => api('/v1/accounts', { headers: { 'cf-connecting-ip': ip }, body: { handle, kind: 'agent' } });
    expect((await ok('2001:db8:1:2::1', 'v6-one')).status).toBe(201);
    expect((await ok('2001:0db8:0001:0002:ffff:eeee:dddd:cccc', 'v6-two')).status).toBe(201);
    const third = await ok('2001:db8:1:2:abcd::9', 'v6-three');
    expect(third.status).toBe(429);
    expect(third.body.error.scope).toBe('registration_ip');
    expect((await ok('2001:db8:1:3::1', 'v6-four')).status).toBe(201); // next /64
  });

  it('caps sign-ups per UTC day across all IPs (limits.register_per_day)', async () => {
    await setSetting('limits.register_per_day', 2);
    const ok = (n: number) => api('/v1/accounts', { headers: { 'cf-connecting-ip': `198.51.100.${n}` }, body: { handle: `day-cap-${n}`, kind: 'agent' } });
    expect((await ok(1)).status).toBe(201);
    expect((await ok(2)).status).toBe(201);
    const third = await ok(3);
    expect(third.status).toBe(429);
    expect(third.body.error.scope).toBe('registration_daily');
    // a malformed request does not use up the daily budget
    await setSetting('limits.register_per_day', 3);
    expect((await api('/v1/accounts', { headers: { 'cf-connecting-ip': '198.51.100.9' }, body: { handle: 'X', kind: 'agent' } })).status).toBe(400);
    expect((await ok(4)).status).toBe(201);
    await setSetting('limits.register_per_day', null);
    expect((await ok(5)).status).toBe(201);
  });
});

describe('clientNetwork', () => {
  it('IPv4 full address, IPv6 /64, IPv4-mapped as IPv4', async () => {
    const { clientNetwork } = await import('../src/limits');
    expect(clientNetwork('203.0.113.7')).toBe('203.0.113.7');
    expect(clientNetwork('2001:db8::1')).toBe('2001:db8:0:0::/64');
    expect(clientNetwork('2001:DB8:0:0:1::')).toBe('2001:db8:0:0::/64');
    expect(clientNetwork('::ffff:203.0.113.7')).toBe('203.0.113.7');
    expect(clientNetwork('fe80::1%eth0')).toBe('fe80:0:0:0::/64');
  });
});
