/**
 * MCP server (/mcp, src/mcp/*): tool/REST parity, transport and routing, auth gating, tool calls through the same
 * /v1 handlers, destructive confirmation, rate limits, docs (page, Markdown twin, JSON, docs/MCP.md, llms.txt).
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { OPERATIONS, schemaOf } from '../src/openapi';
import { REST_EXCLUDED, REST_TOOLS, TOOLS, TOOL_BY_NAME, CONFIRM_ARG, IDEMPOTENCY_ARG } from '../src/mcp/tools';
import { MCP_MAX_BODY_BYTES, MCP_PROTOCOL_VERSIONS, validateArgs } from '../src/mcp/server';
import { resetAtlasCache } from '../src/mcp/atlas';
import MCP_DOC from '../docs/MCP.md?raw';
import { api, makeAdmin, register, resetDb, setSetting } from './helpers';

beforeEach(async () => { await resetDb(); resetAtlasCache(); });

const ORIGIN = 'https://api.test';
let seq = 0;

async function raw(init: RequestInit & { path?: string } = {}) {
  const res = await (exports as any).default.fetch(new Request(`${ORIGIN}${init.path ?? '/mcp'}`, init));
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  return { status: res.status, headers: res.headers, body, text };
}

async function rpc(method: string, params?: unknown, opts: { key?: string; headers?: Record<string, string> } = {}) {
  const headers: Record<string, string> = { 'content-type': 'application/json', accept: 'application/json, text/event-stream', ...(opts.headers ?? {}) };
  if (opts.key) headers.authorization = `Bearer ${opts.key}`;
  return raw({ method: 'POST', headers, body: JSON.stringify({ jsonrpc: '2.0', id: ++seq, method, ...(params !== undefined ? { params } : {}) }) });
}

async function call(name: string, args: Record<string, unknown> = {}, key?: string) {
  const r = await rpc('tools/call', { name, arguments: args }, { key, headers: { 'mcp-protocol-version': '2025-06-18' } });
  expect(r.status, JSON.stringify(r.body)).toBe(200);
  const result = r.body.result;
  return { ...result, data: result?.structuredContent, http: r };
}

const toolNames = (r: { body: any }) => (r.body.result.tools as { name: string }[]).map((t) => t.name);

describe('tool / REST parity', () => {
  it('every /v1 operation has exactly one tool or a documented exclusion, and nothing else', () => {
    const keys = OPERATIONS.map((o) => `${o.method} ${o.path}`);
    for (const k of keys) expect(Object.hasOwn(REST_TOOLS, k) !== Object.hasOwn(REST_EXCLUDED, k), k).toBe(true);
    expect(new Set([...Object.keys(REST_TOOLS), ...Object.keys(REST_EXCLUDED)])).toEqual(new Set(keys));
    expect(TOOLS.filter((t) => t.source.type === 'rest')).toHaveLength(keys.length - Object.keys(REST_EXCLUDED).length);
    expect(new Set(TOOLS.map((t) => t.name)).size).toBe(TOOLS.length);
  });

  it('each tool schema is the operation: path + query params + body fields, same required set, nothing extra', () => {
    for (const op of OPERATIONS) {
      const spec = REST_TOOLS[`${op.method} ${op.path}`];
      if (!spec) continue;
      const tool = TOOL_BY_NAME.get(spec.name)!;
      const props = tool.inputSchema.properties as Record<string, any>;
      const expected = new Set<string>();
      const required = new Set<string>();
      for (const p of op.params ?? []) {
        const name = p.in === 'header' ? IDEMPOTENCY_ARG : p.name;
        expected.add(name);
        if (p.in === 'path' || p.required) required.add(name);
        if (p.in !== 'header') expect(props[name].type, `${spec.name}.${name}`).toEqual(p.schema.type);
      }
      const body = op.body ? (schemaOf(op.body, op.bodyRequired ?? []) as any) : { properties: {} };
      for (const k of Object.keys(body.properties)) expected.add(k);
      for (const k of op.bodyRequired ?? []) required.add(k);
      if (tool.confirm) { expected.add(CONFIRM_ARG); required.add(CONFIRM_ARG); }
      expect(new Set(Object.keys(props)), spec.name).toEqual(expected);
      expect(new Set((tool.inputSchema.required as string[] | undefined) ?? []), spec.name).toEqual(required);
      expect(tool.inputSchema.additionalProperties).toBe(false);
      expect(tool.annotations.readOnlyHint, spec.name).toBe(op.method === 'GET');
      expect(tool.description).toContain(`REST: ${op.method} ${op.path}`);
      const access = op.auth === 'none' ? (op.method === 'GET' ? 'public' : 'keyless') : op.auth === 'optional' ? 'public' : op.auth;
      expect(tool.access, spec.name).toBe(access);
    }
  });

  it('destructive tools require confirm=true; read tools are never destructive', () => {
    for (const t of TOOLS) {
      if (t.annotations.readOnlyHint) expect(t.annotations.destructiveHint, t.name).toBe(false);
      expect(t.confirm, t.name).toBe(t.annotations.destructiveHint);
      if (t.confirm) expect((t.inputSchema.properties as any)[CONFIRM_ARG]).toMatchObject({ type: 'boolean', const: true });
    }
    for (const n of ['platform_withdraw_post', 'account_rotate_key', 'account_confirm_deletion', 'admin_delete_account', 'admin_moderate_content']) expect(TOOL_BY_NAME.get(n)!.confirm, n).toBe(true);
  });

  it('argument validation: unknown, missing and mistyped arguments', () => {
    const schema = TOOL_BY_NAME.get('platform_get_post')!.inputSchema;
    expect(validateArgs(schema, { number: 3 })).toEqual([]);
    expect(validateArgs(schema, {})).toEqual(['number: required']);
    expect(validateArgs(schema, { number: '3' })[0]).toMatch(/expected integer/);
    expect(validateArgs(schema, { number: 0 })[0]).toMatch(/at least 1/);
    expect(validateArgs(schema, { number: 1, extra: true })).toEqual(['extra: unknown argument']);
  });
});

describe('transport and routing', () => {
  it('initialize negotiates the protocol version and names the server', async () => {
    const r = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '1' } });
    expect(r.status).toBe(200);
    expect(r.headers.get('content-type')).toMatch(/^application\/json/);
    expect(r.body.result.protocolVersion).toBe('2025-06-18');
    expect(r.body.result.serverInfo.name).toBe('commonworld');
    expect(r.body.result.capabilities.tools).toBeDefined();
    expect(r.body.result.instructions).toContain('account_register');
    const other = await rpc('initialize', { protocolVersion: '1999-01-01' });
    expect(other.body.result.protocolVersion).toBe(MCP_PROTOCOL_VERSIONS[0]);
    expect(r.headers.get('mcp-session-id')).toBeNull();
  });

  it('ping, notifications (202), unknown method, batch, parse errors, content type, version header, body cap', async () => {
    expect((await rpc('ping')).body.result).toEqual({});
    const note = await raw({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) });
    expect(note.status).toBe(202);
    expect(note.text).toBe('');
    expect((await rpc('resources/list')).body.error.code).toBe(-32601);
    const batch = await raw({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify([{ jsonrpc: '2.0', id: 1, method: 'ping' }]) });
    expect(batch.status).toBe(400);
    expect(batch.body.error.message).toBe('batch_not_supported');
    const bad = await raw({ method: 'POST', headers: { 'content-type': 'application/json' }, body: '{not json' });
    expect(bad.status).toBe(400);
    expect(bad.body.error.code).toBe(-32700);
    expect((await raw({ method: 'POST', headers: { 'content-type': 'text/plain' }, body: '{}' })).status).toBe(415);
    expect((await rpc('ping', undefined, { headers: { 'mcp-protocol-version': '2020-01-01' } })).status).toBe(400);
    expect((await rpc('ping', undefined, { headers: { accept: 'text/html' } })).status).toBe(406);
    const big = await raw({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping', params: { pad: 'x'.repeat(MCP_MAX_BODY_BYTES) } }) });
    expect(big.status).toBe(413);
  });

  it('GET for a server stream and other methods answer 405; OPTIONS is the CORS preflight', async () => {
    const sse = await raw({ method: 'GET', headers: { accept: 'text/event-stream' } });
    expect(sse.status).toBe(405);
    expect(sse.headers.get('allow')).toBe('POST, OPTIONS');
    expect((await raw({ method: 'GET', headers: { accept: 'application/json' } })).status).toBe(405);
    expect((await raw({ method: 'GET', headers: { accept: 'application/json, text/event-stream' } })).status).toBe(405);
    const plain = await raw({ method: 'GET' });
    expect(plain.status).toBe(200);
    expect(plain.headers.get('content-type')).toMatch(/^text\/html/);
    expect((await raw({ method: 'DELETE' })).status).toBe(405);
    const pre = await raw({ method: 'OPTIONS', headers: { origin: 'https://app.example', 'access-control-request-method': 'POST' } });
    expect(pre.status).toBe(204);
    expect(pre.headers.get('access-control-allow-origin')).toBe('*');
    expect(pre.headers.get('access-control-allow-headers')).toMatch(/Authorization/);
    expect(pre.headers.get('access-control-allow-headers')).toMatch(/Mcp-Protocol-Version/);
  });

  it('Origin: malformed or "null" is refused; MCP_ALLOWED_ORIGINS narrows the list (own origin always allowed)', async () => {
    expect((await rpc('ping', undefined, { headers: { origin: 'null' } })).status).toBe(403);
    expect((await rpc('ping', undefined, { headers: { origin: 'https://app.example' } })).status).toBe(200);
    const worker = (await import('../src/index')).default;
    const { createExecutionContext } = await import('cloudflare:test');
    const send = async (origin: string) => (await worker.fetch(new Request(`${ORIGIN}/mcp`, { method: 'POST', headers: { 'content-type': 'application/json', origin }, body: '{"jsonrpc":"2.0","id":1,"method":"ping"}' }),
      { ...env, MCP_ALLOWED_ORIGINS: 'https://good.example' } as any, createExecutionContext())).status;
    expect(await send('https://good.example')).toBe(200);
    expect(await send(ORIGIN)).toBe(200);
    expect(await send('https://evil.example')).toBe(403);
  });

  it('docs: /mcp in a browser is the page, /mcp.md the Markdown twin, /mcp.json the description', async () => {
    const page = await raw({ method: 'GET', headers: { accept: 'text/html,application/xhtml+xml' } });
    expect(page.status).toBe(200);
    expect(page.headers.get('content-type')).toMatch(/^text\/html/);
    expect(page.text).toContain('Commonworld MCP server');
    expect(page.text).toContain('platform_create_post');
    expect(page.headers.get('link')).toContain('/mcp.md');
    const md = await raw({ method: 'GET', path: '/mcp.md' });
    expect(md.status).toBe(200);
    expect(md.headers.get('content-type')).toMatch(/^text\/markdown/);
    for (const t of TOOLS) expect(md.text, t.name).toContain(`\`${t.name}\``);
    const negotiated = await raw({ method: 'GET', headers: { accept: 'text/markdown' } });
    expect(negotiated.headers.get('content-type')).toMatch(/^text\/markdown/);
    const desc = await raw({ method: 'GET', path: '/mcp.json' });
    expect(desc.status).toBe(200);
    expect(desc.body.endpoint).toBe(`${ORIGIN}/mcp`);
    expect(desc.body.tools.map((t: any) => t.name)).toEqual(TOOLS.map((t) => t.name));
    expect(desc.body.auth.oauth).toMatch(/next phase/);
  });

  it('docs/MCP.md maps every tool to its REST endpoint; llms.txt and openapi point to /mcp', async () => {
    for (const t of TOOLS) {
      expect(MCP_DOC, t.name).toContain(`\`${t.name}\``);
      if (t.source.type === 'rest') expect(MCP_DOC, t.name).toContain(`${t.source.method} ${t.source.path}`);
    }
    const llms = await raw({ method: 'GET', path: '/llms.txt' });
    expect(llms.text).toContain('/mcp');
    const oa = await raw({ method: 'GET', path: '/openapi.json' });
    expect(oa.body['x-mcp'].endpoint).toBe(`${ORIGIN}/mcp`);
  });
});

describe('auth gating', () => {
  it('tools/list: anonymous = public + keyless; a key adds citizen writes; staff tools by role', async () => {
    const anon = toolNames(await rpc('tools/list'));
    expect(anon).toContain('atlas_search_platforms');
    expect(anon).toContain('platform_list_posts');
    expect(anon).toContain('account_register');
    expect(anon).not.toContain('platform_create_post');
    expect(anon.some((n) => n.startsWith('admin_'))).toBe(false);
    const citizen = await register('mcp-cit');
    const mine = toolNames(await rpc('tools/list', undefined, { key: citizen.key }));
    expect(mine).toContain('platform_create_post');
    expect(mine).toContain('account_rotate_key');
    expect(mine.some((n) => n.startsWith('admin_'))).toBe(false);
    const mod = await register('mcp-mod', 'human');
    await env.DB.prepare("INSERT INTO account_roles (account_id, role, granted_at) VALUES (?, 'moderator', ?)").bind(mod.id, new Date().toISOString()).run();
    const modTools = toolNames(await rpc('tools/list', undefined, { key: mod.key }));
    expect(modTools).toContain('admin_moderate_content');
    expect(modTools).not.toContain('admin_delete_account');
    const admin = await makeAdmin();
    const adminTools = toolNames(await rpc('tools/list', undefined, { key: admin.key }));
    expect(adminTools).toEqual(TOOLS.map((t) => t.name));
    const listed = (await rpc('tools/list')).body.result.tools[0];
    expect(Object.keys(listed).sort()).toEqual(['annotations', 'description', 'inputSchema', 'name', 'title']);
  });

  it('an invalid key is 401 with WWW-Authenticate and never echoed', async () => {
    const bogus = 'cw1_' + 'A'.repeat(43);
    const r = await rpc('tools/list', undefined, { key: bogus });
    expect(r.status).toBe(401);
    expect(r.headers.get('www-authenticate')).toMatch(/^Bearer /);
    expect(r.body.error.message).toBe('invalid_api_key');
    expect(r.text).not.toContain(bogus);
  });

  it('a write without a key and a staff tool with a citizen key are refused by the REST handler', async () => {
    const anon = await call('platform_create_post', { title: 'x', body: 'y' });
    expect(anon.isError).toBe(true);
    expect(anon.data).toMatchObject({ status: 401, error: { code: 'api_key_required' } });
    const citizen = await register('mcp-cit');
    const forb = await call('admin_get_modes', {}, citizen.key);
    expect(forb.isError).toBe(true);
    expect(forb.data.status).toBe(403);
    expect(forb.data.error.code).toBe('forbidden');
    expect(JSON.stringify(forb)).not.toContain(citizen.key);
    const admin = await makeAdmin();
    const ok = await call('admin_get_modes', {}, admin.key);
    expect(ok.isError).toBeUndefined();
  });
});

describe('tools/call', () => {
  it('Atlas tools read the static Atlas JSON', async () => {
    const cats = await call('atlas_list_categories');
    expect(cats.data.counts.platforms).toBe(3);
    expect(cats.data.categories.map((c: any) => c.id)).toEqual(['social', 'payments']);
    const found = await call('atlas_search_platforms', { query: 'demo' });
    expect(found.data.total).toBe(1);
    expect(found.data.items[0]).toMatchObject({ id: 'demo', has_first_task: true });
    expect(found.data.items[0].claims).toBeUndefined();
    expect((await call('atlas_search_platforms', { category: 'social', status: 'live' })).data.items.map((p: any) => p.id)).toEqual(['demo']);
    expect((await call('atlas_search_platforms', { tag: 'x402' })).data.items.map((p: any) => p.id)).toEqual(['payhub']);
    expect((await call('atlas_search_platforms', { limit: 1 })).data.next_offset).toBe(1);
    const card = await call('atlas_get_platform', { id: 'demo' });
    expect(card.data.claims[0].source_url).toBe('https://demo.example');
    const missing = await call('atlas_get_platform', { id: 'nope' });
    expect(missing.isError).toBe(true);
    expect(missing.data).toMatchObject({ status: 404, error: { code: 'platform_not_found' } });
    const badId = await call('atlas_get_platform', { id: '../secrets' });
    expect(badId.data.error.code).toBe('invalid_arguments');
    expect((await call('atlas_first_tasks')).data.items.map((p: any) => p.id)).toEqual(['demo']);
    expect((await call('atlas_earn')).data.rows[0].id).toBe('payhub');
    expect((await call('commonworld_stats')).data.metrics[0].status).toBe('coming');
    expect(found.content[0].type).toBe('text');
    expect(JSON.parse(found.content[0].text).total).toBe(1);
  });

  it('register, post, read back, upvote and withdraw through MCP = the REST API', async () => {
    const reg = await call('account_register', { handle: 'mcp-agent', kind: 'agent' });
    expect(reg.isError).toBeUndefined();
    const key = reg.data.api_key.value as string;
    expect(key).toMatch(/^cw1_/);
    const me = await call('account_me', {}, key);
    expect(me.data.account.handle).toBe('mcp-agent');
    expect(JSON.stringify(me)).not.toContain(key);
    const created = await call('platform_create_post', { title: 'Hello from MCP', body: 'Written through the MCP server.', section: 'general', tags: ['agents'], idempotency_key: 'mcp-1' }, key);
    expect(created.isError).toBeUndefined();
    const n = created.data.number;
    const again = await call('platform_create_post', { title: 'Hello from MCP', body: 'Written through the MCP server.', section: 'general', tags: ['agents'], idempotency_key: 'mcp-1' }, key);
    expect(again.data.number).toBe(n);
    const rest = await api(`/v1/posts/${n}`);
    expect(rest.body.title).toBe('Hello from MCP');
    expect(rest.body.author.handle).toBe('mcp-agent');
    const viaMcp = await call('platform_get_post', { number: n });
    expect(viaMcp.data.title).toBe(rest.body.title);
    const listed = await call('platform_list_posts', { author: 'mcp-agent' });
    expect(listed.data.items.map((p: any) => p.number)).toEqual([n]);
    const other = await register('mcp-voter');
    expect((await call('platform_upvote_post', { number: n }, other.key)).data.upvoted).toBe(true);
    const self = await call('platform_upvote_post', { number: n }, key);
    expect(self.data.error.code).toBe('self_vote_not_allowed');
    const comment = await call('platform_create_comment', { number: n, body: 'A reply via MCP.' }, other.key);
    expect(comment.data.post_number).toBe(n);
    const noConfirm = await call('platform_withdraw_post', { number: n, reason: 'Test.' }, key);
    expect(noConfirm.isError).toBe(true);
    expect(noConfirm.data.error.code).toBe('confirmation_required');
    expect((await api(`/v1/posts/${n}`)).body.withdrawn).toBeNull();
    const notMine = await call('platform_withdraw_post', { number: n, reason: 'Test.', confirm: true }, other.key);
    expect(notMine.data.error.code).toBe('not_your_content');
    const done = await call('platform_withdraw_post', { number: n, reason: 'Test.', confirm: true }, key);
    expect(done.data.withdrawn.reason).toBe('Test.');
  });

  it('REST validation errors come back as tool errors with the REST code', async () => {
    const c = await register('mcp-val');
    const r = await call('platform_create_post', { title: '', body: 'b' }, c.key);
    expect(r.isError).toBe(true);
    expect(r.data.status).toBe(400);
    expect(r.data.error.code).toBe('invalid_title');
    expect((await call('platform_get_post', { number: 999999 })).data).toMatchObject({ status: 404, error: { code: 'post_not_found' } });
  });

  it('unknown tool is a protocol error; unknown argument and wrong type are tool errors', async () => {
    const r = await rpc('tools/call', { name: 'no_such_tool', arguments: {} });
    expect(r.body.error.code).toBe(-32602);
    const extra = await call('platform_rules', { surprise: 1 });
    expect(extra.isError).toBe(true);
    expect(extra.data.error.details).toEqual(['surprise: unknown argument']);
  });

  it('the account minute limit of the REST API applies to tool calls (one window, shared)', async () => {
    const c = await register('mcp-rate');
    await setSetting('limits.rate_per_minute', 3);
    expect((await call('account_me', {}, c.key)).isError).toBeUndefined();
    expect((await api('/v1/me', { key: c.key })).status).toBe(200);
    expect((await call('account_me', {}, c.key)).isError).toBeUndefined();
    const over = await call('account_me', {}, c.key);
    expect(over.isError).toBe(true);
    expect(over.data).toMatchObject({ status: 429, error: { code: 'rate_limit_exceeded' } });
    expect(over.http.headers.get('retry-after')).toBeTruthy();
    // non-call methods count too, at the envelope
    const list = await rpc('tools/list', undefined, { key: c.key });
    expect(list.status).toBe(429);
  });

  it('structuredContent only for protocol 2025-06-18 and later', async () => {
    const old = await rpc('tools/call', { name: 'platform_rules', arguments: {} }, { headers: { 'mcp-protocol-version': '2025-03-26' } });
    expect(old.body.result.structuredContent).toBeUndefined();
    expect(JSON.parse(old.body.result.content[0].text).rules.length).toBeGreaterThan(0);
    const now = await call('platform_rules');
    expect(now.data.rules.length).toBeGreaterThan(0);
  });
});
