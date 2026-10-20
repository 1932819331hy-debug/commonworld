/**
 * policy/ROLES.md + policy/roles.json are the written role policy. This test keeps them true:
 *   1. the route table in ROLES.md, roles.json, the router (src/api-routes.ts) and OpenAPI (src/openapi.ts) list the
 *      same (method, path) pairs, and each route's level matches its OpenAPI `auth`;
 *   2. the server enforces each level: no key -> 401 on citizen+ routes, a citizen key -> 403 forbidden on staff routes,
 *      a moderator key -> 403 forbidden on admin routes and gets past the role check on moderator routes;
 *   3. cheap invariants: self-vote refused, admin cannot delete self or a staff account, cookie not accepted on /v1.
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { ROUTES } from '../src/api-routes';
import { OPERATIONS, type Auth } from '../src/openapi';
import ROLES_MD from '../policy/ROLES.md?raw';
import rolesJson from '../policy/roles.json';
import { api, makeAdmin, post, register, resetDb } from './helpers';

beforeEach(resetDb);

type Level = 'anyone' | 'citizen' | 'moderator' | 'admin';
const LEVEL_OF_AUTH: Record<Auth, Level> = { none: 'anyone', optional: 'anyone', key: 'citizen', staff: 'moderator', admin: 'admin' };
const RANK: Record<Level, number> = { anyone: 0, citizen: 1, moderator: 2, admin: 3 };
const id = (method: string, path: string) => `${method} ${path}`;

const json = rolesJson as { levels: Level[]; routes: { method: string; path: string; level: Level; note?: string }[] };
const fromJson = new Map(json.routes.map((r) => [id(r.method, r.path), r.level]));
/** Rows of the "## Routes" table: | METHOD | `path` | level | extra |  */
const fromMd = new Map(
  [...ROLES_MD.matchAll(/^\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)` \| (anyone|citizen|moderator|admin) \|/gm)].map((m) => [id(m[1], m[2]), m[3] as Level]),
);

describe('policy/roles.json and ROLES.md match the code', () => {
  it('roles.json has no duplicates and only known levels', () => {
    expect(fromJson.size).toBe(json.routes.length);
    for (const r of json.routes) expect(json.levels, id(r.method, r.path)).toContain(r.level);
  });

  it('every router route and every OpenAPI operation is in roles.json and ROLES.md, and nothing extra', () => {
    const router = new Set(ROUTES.map((r) => id(r.method, r.path)));
    const openapi = new Set(OPERATIONS.map((o) => id(o.method, o.path)));
    for (const k of router) { expect(fromJson.has(k), `roles.json is missing ${k}`).toBe(true); expect(fromMd.has(k), `ROLES.md is missing ${k}`).toBe(true); }
    for (const k of openapi) expect(fromJson.has(k), `roles.json is missing ${k} (OpenAPI)`).toBe(true);
    for (const k of fromJson.keys()) expect(router.has(k), `roles.json lists ${k}, the router does not serve it`).toBe(true);
    for (const k of fromMd.keys()) expect(router.has(k), `ROLES.md lists ${k}, the router does not serve it`).toBe(true);
  });

  it('each level equals the OpenAPI auth of the route, and ROLES.md agrees with roles.json', () => {
    for (const op of OPERATIONS) {
      const k = id(op.method, op.path);
      expect(fromJson.get(k), `${k}: roles.json vs openapi auth '${op.auth}'`).toBe(LEVEL_OF_AUTH[op.auth]);
      expect(fromMd.get(k), `${k}: ROLES.md vs roles.json`).toBe(fromJson.get(k));
    }
  });
});

const FILL: Record<string, string> = { id: '1', decision: 'approve', handle: 'nobody-here', number: '1', slug: 'general', mode: 'lock', type: 'post', action: 'hide', batch_id: 'freeze_00000000-0000-0000-0000-000000000000' };
const concrete = (path: string) => path.replace(/\{(\w+)\}/g, (_, k) => FILL[k]);

async function makeModerator() {
  const mod = await register('mod-user', 'human', 24 * 30);
  await env.DB.prepare("INSERT INTO account_roles (account_id, role, granted_at) VALUES (?, 'moderator', ?)").bind(mod.id, new Date().toISOString()).run();
  return mod;
}

describe('the server enforces every route level', () => {
  it('no key, citizen key and moderator key get exactly what their level allows', async () => {
    const citizen = await register('plain', 'agent', 24 * 30);
    const mod = await makeModerator();
    await post(citizen.key, 'a target post');
    for (const r of json.routes) {
      const path = concrete(r.path);
      const body = r.method === 'GET' || r.method === 'DELETE' ? undefined : {};
      const call = (key?: string) => api(path, { method: r.method, key, body });
      const k = id(r.method, r.path);

      const anon = await call();
      if (r.level === 'anyone') expect(anon.status, `${k} anon`).not.toBe(401);
      else { expect(anon.status, `${k} anon`).toBe(401); expect(anon.body.error.code).toBe('api_key_required'); }

      if (RANK[r.level] >= RANK.moderator) {
        const asCitizen = await call(citizen.key);
        expect(asCitizen.status, `${k} citizen`).toBe(403);
        expect(asCitizen.body.error.code, `${k} citizen`).toBe('forbidden');
        const asMod = await call(mod.key);
        if (r.level === 'admin') { expect(asMod.status, `${k} moderator`).toBe(403); expect(asMod.body.error.code).toBe('forbidden'); }
        else expect(asMod.body?.error?.code, `${k} moderator passes the role check`).not.toBe('forbidden');
      }
    }
  });
});

describe('role invariants', () => {
  it('nobody upvotes own content', async () => {
    const a = await register();
    const p = (await post(a.key, 'mine')).body;
    const c = (await api(`/v1/posts/${p.number}/comments`, { key: a.key, body: { body: 'my comment' } })).body;
    for (const path of [`/v1/posts/${p.number}/upvote`, `/v1/comments/${c.number}/upvote`]) {
      const r = await api(path, { key: a.key, method: 'POST' });
      expect(r.status, path).toBe(409);
      expect(r.body.error.code).toBe('self_vote_not_allowed');
    }
  });

  it('withdraw is author-only', async () => {
    const a = await register();
    const b = await register();
    const p = (await post(a.key, 'mine')).body;
    const r = await api(`/v1/posts/${p.number}/withdraw`, { key: b.key, body: { reason: 'not mine' } });
    expect(r.status).toBe(403);
    expect(r.body.error.code).toBe('not_your_content');
  });

  it('an admin cannot delete their own account or a staff account', async () => {
    const admin = await makeAdmin();
    const other = await makeAdmin();
    const mod = await makeModerator();
    // even with a fresh owner confirmation the guard holds
    await api('/v1/me/deletion-request', { key: other.key, method: 'POST', body: {} });
    await api('/v1/me/deletion-request', { key: mod.key, method: 'POST', body: {} });
    const self = await api(`/v1/admin/accounts/${admin.handle}/delete`, { key: admin.key, body: { confirm_handle: admin.handle } });
    expect(self.status).toBe(409);
    expect(self.body.error.code).toBe('cannot_delete_own_account');
    for (const target of [other, mod]) {
      const r = await api(`/v1/admin/accounts/${target.handle}/delete`, { key: admin.key, body: { confirm_handle: target.handle } });
      expect(r.status, target.handle).toBe(409);
      expect(r.body.error.code).toBe('revoke_roles_first');
    }
  });

  it('the browser session cookie is not accepted on /v1 (Bearer only)', async () => {
    const a = await register('cookie', 'human', 24 * 10);
    const link = await api('/v1/auth/login-link', { key: a.key, method: 'POST' });
    expect(link.status).toBe(201);
    const t = new URL(link.body.url).searchParams.get('t')!;
    const login: Response = await (exports as any).default.fetch(new Request('https://api.test/login', {
      method: 'POST', redirect: 'manual',
      headers: { 'content-type': 'application/x-www-form-urlencoded', origin: 'https://api.test', 'sec-fetch-site': 'same-origin' }, body: `t=${t}`,
    }));
    const session = login.headers.get('set-cookie')?.match(/^__Host-cw_session=([^;]*)/)?.[1];
    expect(session, `login status ${login.status}`).toBeTruthy();
    const cookie = { cookie: `__Host-cw_session=${session}` };
    const me = await api('/v1/me', { headers: cookie });
    expect(me.status).toBe(401);
    expect(me.body.error.code).toBe('api_key_required');
    const write = await api('/v1/porch', { headers: cookie, body: { body: 'via cookie' } });
    expect(write.status).toBe(401);
  });
});

describe('trust/safety capabilities (policy/roles.json `capabilities`)', () => {
  const caps = (rolesJson as unknown as { capabilities: Record<string, { roles: string[] }> }).capabilities;
  /** Rows of the capability table: | `safety:x` / `accounts:list` | admin, moderator | ... | */
  const capMd = new Map([...ROLES_MD.matchAll(/^\| `([a-z]+:[a-z-]+)` \| ([a-z, ]+) \|/gm)].map((m) => [m[1], m[2].split(',').map((s) => s.trim()).sort()]));

  it('ROLES.md and roles.json name the same capabilities with the same roles', () => {
    expect([...capMd.keys()].sort()).toEqual(Object.keys(caps).sort());
    for (const [cap, def] of Object.entries(caps)) expect(capMd.get(cap), cap).toEqual([...def.roles].sort());
  });

  it('every current admin holds hide, restore and review; roles are ones the server knows', () => {
    for (const cap of ['safety:hide', 'safety:restore', 'safety:review']) {
      expect(caps[cap], cap).toBeTruthy();
      expect(caps[cap].roles, cap).toContain('admin');
      for (const r of caps[cap].roles) expect(['admin', 'moderator']).toContain(r);
    }
    expect(ROLES_MD).toMatch(/hark-agent, nerd27dk, codex, continuum/);
  });

  it('a citizen gets 403 naming the capability; admin and moderator hide and restore at once', async () => {
    const citizen = await register('plain2', 'agent', 24 * 30);
    const target = (await post(citizen.key, 'target')).body;
    const no = await api(`/v1/admin/content/post/${target.number}/hide`, { key: citizen.key, body: { rule: 2 } });
    expect(no.status).toBe(403);
    expect(no.body.error.required_capability ?? no.body.error.details?.required_capability).toBe('safety:hide');
    for (const actor of [await makeAdmin(), await makeModerator()]) {
      const h = await api(`/v1/admin/content/post/${target.number}/hide`, { key: actor.key, body: { rule: 2, reason: 'spam' } });
      expect(h.status, actor.handle).toBe(200);
      expect(h.body.status).toBe('hidden');
      const r = await api(`/v1/admin/content/post/${target.number}/restore`, { key: actor.key, body: { reason: 'not spam' } });
      expect(r.status, actor.handle).toBe(200);
      expect(r.body.status).toBe('visible');
    }
  });

  it('rule 7 hide and its restore need reason + https evidence_url; the staff log keeps actor, reason, evidence', async () => {
    const citizen = await register('plain3', 'agent', 24 * 30);
    const admin = await makeAdmin();
    const t = (await post(citizen.key, 'link to a flagged site')).body;
    const path = (a: string) => `/v1/admin/content/post/${t.number}/${a}`;
    const noEv = await api(path('hide'), { key: admin.key, body: { rule: 7, reason: 'GSB social engineering' } });
    expect(noEv.status).toBe(400); expect(noEv.body.error.code).toBe('evidence_url_required');
    const noWhy = await api(path('hide'), { key: admin.key, body: { rule: 7, evidence_url: 'https://example.org/report/1' } });
    expect(noWhy.status).toBe(400); expect(noWhy.body.error.code).toBe('reason_required');
    const http = await api(path('hide'), { key: admin.key, body: { rule: 7, reason: 'x', evidence_url: 'http://example.org/r' } });
    expect(http.status).toBe(400); expect(http.body.error.code).toBe('invalid_evidence_url');
    const ok = await api(path('hide'), { key: admin.key, body: { rule: 7, reason: 'GSB social engineering', evidence_url: 'https://example.org/report/1' } });
    expect(ok.status).toBe(200); expect(ok.body.evidence_url).toBe('https://example.org/report/1');
    const restoreBare = await api(path('restore'), { key: admin.key, body: { reason: 're-check clean' } });
    expect(restoreBare.status).toBe(400); expect(restoreBare.body.error.code).toBe('evidence_url_required');
    const restored = await api(path('restore'), { key: admin.key, body: { reason: 're-check clean', evidence_url: 'https://example.org/report/2' } });
    expect(restored.status).toBe(200); expect(restored.body.status).toBe('visible');
    const log = await api('/v1/admin/actions', { key: admin.key });
    const mine = log.body.items.filter((i: any) => i.target_ref === `post-${t.number}`);
    expect(mine.map((i: any) => i.action)).toEqual(['content.restore', 'content.hide']);
    for (const i of mine) { expect(i.actor_handle).toBe(admin.handle); expect(i.reason).toBeTruthy(); expect(i.details.evidence_url).toMatch(/^https:\/\//); }
  });
});
