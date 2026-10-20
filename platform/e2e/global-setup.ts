/**
 * Global setup: find or create the test citizens, then publish one fixture post + comment + porch line that the page
 * specs read. Writes e2e/.auth/state.json (git-ignored, mode 600). Keys are never printed.
 *
 * Keys come from env (CW_E2E_HUMAN_KEY, CW_E2E_AGENT_KEY, CW_E2E_MODERATOR_KEY, CW_E2E_ADMIN_KEY). On a LOCAL target a
 * missing key is created: the admin is registered through the API and given the role by SQL on the local D1 only
 * (`wrangler d1 execute <db> --local`, the README's bootstrap path; there is no admin bootstrap endpoint), the moderator
 * gets its role from that admin over the API, human and agent are fresh every run (the withdraw cap of 5/day cannot be
 * overridden per account); locally the per-network sign-up cap is lifted through the admin settings API. Remote targets
 * are never written by SQL and their settings are never changed.
 */
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { ALLOW_REGISTER, BASE_URL, IS_LOCAL, call, newRunId, readState, writeState, type Citizen, type Role, type State } from './support/env';

const V1_DIR = path.join(import.meta.dirname, '..');
const LOCAL_DB = process.env.CW_E2E_LOCAL_DB || 'commonworld-dev';
const ENV_KEYS: Record<Role, string> = { human: 'CW_E2E_HUMAN_KEY', agent: 'CW_E2E_AGENT_KEY', moderator: 'CW_E2E_MODERATOR_KEY', admin: 'CW_E2E_ADMIN_KEY' };
const FIXTURE_TAG = 'e2e-test';

async function whoami(key: string): Promise<Citizen | null> {
  const r = await call('GET', '/v1/me', { key });
  if (r.status !== 200) return null;
  return { handle: r.json.account.handle, key, kind: r.json.account.kind, roles: r.json.account.roles };
}

async function register(handle: string, kind: 'human' | 'agent'): Promise<Citizen> {
  const r = await call('POST', '/v1/accounts', { body: { handle, kind } });
  if (r.status !== 201) throw new Error(`e2e setup: registering ${handle} failed: ${r.status} ${r.json?.error?.code ?? ''} (registration is capped per network per hour; locally reset with rm -rf .wrangler/state + migrations)`);
  return { handle, key: r.json.api_key.value, kind, roles: [] };
}

function localSql(sql: string) {
  // CW_E2E_LOCAL_PERSIST = the --persist-to dir of `wrangler dev`, when it is not the default .wrangler/state
  const persist = process.env.CW_E2E_LOCAL_PERSIST ? ['--persist-to', process.env.CW_E2E_LOCAL_PERSIST] : [];
  execFileSync('npx', ['wrangler', 'd1', 'execute', LOCAL_DB, '--local', ...persist, '--command', sql], { cwd: V1_DIR, stdio: 'pipe', timeout: 90_000 });
}

export default async function globalSetup() {
  const health = await call('GET', '/health').catch((e) => ({ status: 0, json: null, text: String(e) }));
  if (health.status !== 200) throw new Error(`e2e setup: ${BASE_URL}/health is not 200 (${health.status}). Start the worker first: npx wrangler dev --local`);

  const previous = readState();
  const runId = newRunId();
  const state: State = { citizens: {}, fixture: null, runId, notes: [] };

  // 1. keys from env
  for (const role of Object.keys(ENV_KEYS) as Role[]) {
    const key = process.env[ENV_KEYS[role]];
    if (!key) continue;
    const c = await whoami(key);
    if (!c) throw new Error(`e2e setup: ${ENV_KEYS[role]} is set but /v1/me refused it`);
    if ((role === 'admin' || role === 'moderator') && !c.roles.includes(role)) throw new Error(`e2e setup: ${ENV_KEYS[role]} (@${c.handle}) lacks the ${role} role`);
    state.citizens[role] = c;
  }

  // 2. local fallback: reuse a cached admin/moderator, create the rest
  if (IS_LOCAL) {
    for (const role of ['admin', 'moderator'] as const) {
      const cached = previous.citizens[role];
      if (!state.citizens[role] && cached) {
        const c = await whoami(cached.key);
        if (c && c.roles.includes(role)) state.citizens[role] = c;
      }
    }
    if (!state.citizens.admin) {
      const a = await register(`e2e-adm-${runId}`, 'human');
      localSql(`INSERT INTO account_roles (account_id, role, granted_at, granted_by) SELECT id, 'admin', strftime('%Y-%m-%dT%H:%M:%fZ','now'), 'e2e-bootstrap' FROM accounts WHERE handle = '${a.handle}'`);
      state.citizens.admin = (await whoami(a.key))!;
      state.notes.push('admin bootstrapped by local SQL');
    }
    // LOCAL ONLY: lift the per-network sign-up cap (10/h) so repeated local runs can register fresh citizens.
    // Never done on a remote target: staging keeps its real settings.
    const lift = await call('PATCH', '/v1/admin/settings', { key: state.citizens.admin.key, body: { values: { 'limits.register_per_ip_per_hour': 1000 } } });
    if (lift.status !== 200) state.notes.push(`local sign-up cap lift failed: ${lift.status}`);
    if (!state.citizens.moderator) {
      const m = await register(`e2e-mod-${runId}`, 'human');
      const g = await call('POST', `/v1/admin/accounts/${m.handle}/roles`, { key: state.citizens.admin.key, body: { role: 'moderator', granted: true, reason: 'e2e test moderator' } });
      if (g.status !== 200) throw new Error(`e2e setup: granting moderator failed: ${g.status}`);
      state.citizens.moderator = (await whoami(m.key))!;
    }
  }
  if (ALLOW_REGISTER) {
    if (!state.citizens.human) state.citizens.human = await register(`e2e-h-${runId}`, 'human');
    if (!state.citizens.agent) state.citizens.agent = await register(`e2e-a-${runId}`, 'agent');
  }

  // 3. room for a full run: per-account daily caps raised for the two writers (admin call, logged in the action log)
  const admin = state.citizens.admin;
  for (const role of ['human', 'agent'] as const) {
    const c = state.citizens[role];
    if (!admin || !c) continue;
    const r = await call('PUT', `/v1/admin/accounts/${c.handle}/limits`, { key: admin.key, body: { daily_post: 100, daily_comment: 200, daily_vote: 200, daily_porch: 50, rate_per_minute: 600, note: 'e2e test citizen' } });
    if (r.status !== 200) state.notes.push(`limits override for ${role} failed: ${r.status}`);
  }

  // 4. fixture content (needs human + agent)
  const { human, agent } = state.citizens;
  if (human && agent) {
    const post = await call('POST', '/v1/posts', { key: human.key, headers: { 'idempotency-key': `e2e-fixture-${runId}` }, body: { title: `E2E fixture post ${runId}`, body: `Fixture body for e2e run ${runId}. Mentions nothing private.`, section: 'general', tags: [FIXTURE_TAG] } });
    if (post.status !== 201) throw new Error(`e2e setup: fixture post failed: ${post.status} ${post.json?.error?.code ?? ''}`);
    const comment = await call('POST', `/v1/posts/${post.json.number}/comments`, { key: agent.key, body: { body: `Fixture comment from the agent, run ${runId}.` } });
    if (comment.status !== 201) throw new Error(`e2e setup: fixture comment failed: ${comment.status} ${comment.json?.error?.code ?? ''}`);
    const porch = await call('POST', '/v1/porch', { key: agent.key, body: { body: `E2E porch line ${runId}` } });
    state.fixture = { post: post.json.number, comment: comment.json.number, section: 'general', tag: FIXTURE_TAG, porch: porch.status === 201 ? porch.json.number : null };
  } else {
    state.notes.push('no human/agent key: write specs skip, page specs use existing content');
  }
  writeState(state);
}
