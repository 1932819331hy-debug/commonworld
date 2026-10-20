/**
 * MCP server at /mcp (Model Context Protocol, Streamable HTTP transport, stateless JSON mode).
 *
 * - POST /mcp takes ONE JSON-RPC message and answers `application/json` (no SSE stream, no session id, no Durable
 *   Object): initialize, ping, tools/list, tools/call. Notifications and client responses get 202 with no body.
 *   Batches (JSON arrays) are refused, as in protocol 2025-06-18 and later.
 * - GET /mcp asking for `text/event-stream` (a client opening a server stream) or only JSON, and every other method,
 *   answer 405, as the spec allows for servers without a stream. Any other GET (browser, link checker, curl without
 *   Accept) or one for Markdown is the docs page
 *   (src/pages/router.ts renders /mcp and /mcp.md); /mcp.json is the machine-readable description (src/mcp/docs.ts).
 * - Auth: none = public tools; `Authorization: Bearer cw1_…` (an existing Commonworld API key) = that account. Platform
 *   tools run as an internal request to their /v1 route through the Worker's own router (`route`), carrying the same
 *   Authorization, client IP and Idempotency-Key, so handlers, policy, per-account rate limits, daily quotas,
 *   moderation, link checks and errors are exactly the REST API's. OAuth 2.1 is the next phase (docs/MCP.md).
 * - Limits: body <= MCP_MAX_BODY_BYTES (the /v1 body cap of 16 KB still applies to every forwarded write); anonymous
 *   requests MCP_ANON_RATE_PER_MINUTE per client network; keyed requests count against the account's minute window
 *   (a tools/call is counted once, by its /v1 request).
 * - Origin (DNS rebinding guard of the spec): a request with an Origin header must carry a well-formed http(s) origin,
 *   and when MCP_ALLOWED_ORIGINS is set, one of those (or the site's own). No cookies are read here, keys only.
 */
import type { Env } from '../env';
import { authenticate, hasActiveRole, isActiveStaff, type Principal } from '../auth';
import { enforceAccountRate } from '../account-rate';
import { hmacHex } from '../crypto';
import { HttpError, json, readBodyCapped } from '../http';
import { clientNetwork } from '../limits';
import { enforceMinuteRate } from '../ratelimit';
import { API_VERSION } from '../openapi';
import { prefersMarkdown } from '../pages/markdown';
import { CONFIRM_ARG, IDEMPOTENCY_ARG, TOOL_BY_NAME, visibleTools, type JsonSchema, type ToolDef } from './tools';

export const MCP_PATH = '/mcp';
export const MCP_DOC_JSON = '/mcp.json';
/** Newest first. initialize answers the client's version when supported, else the newest. */
export const MCP_PROTOCOL_VERSIONS = ['2025-11-25', '2025-06-18', '2025-03-26'] as const;
/** Assumed for requests without MCP-Protocol-Version (spec: 2025-03-26 when the header is missing). */
const DEFAULT_HEADER_VERSION = '2025-03-26';
export const MCP_SERVER_VERSION = `${API_VERSION}+mcp.1`;
export const MCP_MAX_BODY_BYTES = 32 * 1024;
export const MCP_ANON_RATE_PER_MINUTE = 120;

export type RouteFn = (request: Request, env: Env, exec: ExecutionContext) => Promise<Response>;

const RPC = { parse: -32700, invalidRequest: -32600, methodNotFound: -32601, invalidParams: -32602, internal: -32603, unauthorized: -32001, rateLimited: -32029, forbiddenOrigin: -32003 } as const;

export const MCP_CORS_HEADERS: Record<string, string> = {
  'access-control-allow-origin': '*',
  'access-control-expose-headers': 'RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset, RateLimit-Policy, Retry-After, WWW-Authenticate, Mcp-Protocol-Version',
};
export const MCP_PREFLIGHT_HEADERS: Record<string, string> = {
  ...MCP_CORS_HEADERS,
  'access-control-allow-methods': 'POST, GET, OPTIONS',
  'access-control-allow-headers': 'Authorization, Content-Type, Accept, Mcp-Protocol-Version, Mcp-Session-Id, Last-Event-ID',
  'access-control-max-age': '86400',
};

/** GET/HEAD /mcp from a browser (HTML) or an agent asking for Markdown: the docs page, not the MCP endpoint. */
export function wantsMcpPage(request: Request): boolean {
  if (request.method !== 'GET' && request.method !== 'HEAD') return false;
  const accept = request.headers.get('accept') ?? '';
  if (/text\/event-stream/i.test(accept)) return false;
  // browsers, link checkers and plain curl (no Accept, */*) get the page; an API client asking only for JSON gets 405
  return accept.trim() === '' || prefersMarkdown(accept) || /text\/html|\*\/\*/i.test(accept);
}

/** null = allowed; otherwise the reason. */
export function originProblem(request: Request, env: Env): string | null {
  const origin = request.headers.get('origin');
  if (origin === null) return null;
  let parsed: URL;
  try { parsed = new URL(origin); } catch { return 'malformed_origin'; }
  if ((parsed.protocol !== 'https:' && parsed.protocol !== 'http:') || parsed.origin !== origin) return 'malformed_origin';
  const list = (env.MCP_ALLOWED_ORIGINS ?? '').split(',').map((s) => s.trim()).filter(Boolean);
  if (!list.length || list.includes('*')) return null;
  const own = new Set([new URL(request.url).origin, (env.SITE_ORIGIN ?? '').replace(/\/+$/, '')]);
  return own.has(origin) || list.includes(origin) ? null : 'origin_not_allowed';
}

type Id = string | number | null;
const rpcResult = (id: Id, result: unknown) => ({ jsonrpc: '2.0', id, result });
const rpcError = (id: Id, code: number, message: string, data?: unknown) => ({ jsonrpc: '2.0', id, error: { code, message, ...(data !== undefined ? { data } : {}) } });

function reply(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return body === null
    ? new Response(null, { status, headers: { ...MCP_CORS_HEADERS, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', ...headers } })
    : json(status, body, { ...MCP_CORS_HEADERS, ...headers });
}

const RATE_HEADERS = ['ratelimit-limit', 'ratelimit-remaining', 'ratelimit-reset', 'ratelimit-policy', 'retry-after'];
const pickRate = (h: Headers): Record<string, string> => Object.fromEntries(RATE_HEADERS.filter((n) => h.has(n)).map((n) => [n, h.get(n)!]));

/** Entry point for every request to /mcp except the docs page (src/index.ts). */
export async function handleMcp(request: Request, env: Env, exec: ExecutionContext, route: RouteFn): Promise<Response> {
  const bad = originProblem(request, env);
  if (bad) return reply(403, rpcError(null, RPC.forbiddenOrigin, bad));
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: { ...MCP_PREFLIGHT_HEADERS, 'cache-control': 'public, max-age=86400', 'x-content-type-options': 'nosniff' } });
  if (request.method !== 'POST') {
    await request.body?.cancel().catch(() => undefined);
    return reply(405, rpcError(null, RPC.invalidRequest, 'method_not_allowed', { allowed: ['POST', 'OPTIONS'], note: 'Stateless server: no SSE stream and no sessions. POST one JSON-RPC message; docs at /mcp (HTML), /mcp.md, /mcp.json.' }), { allow: 'POST, OPTIONS' });
  }
  if (!/^application\/json\b/i.test(request.headers.get('content-type') ?? '')) {
    await request.body?.cancel().catch(() => undefined);
    return reply(415, rpcError(null, RPC.invalidRequest, 'json_content_type_required'));
  }
  const accept = request.headers.get('accept');
  if (accept && !/(application\/json|application\/\*|\*\/\*)/i.test(accept)) {
    await request.body?.cancel().catch(() => undefined);
    return reply(406, rpcError(null, RPC.invalidRequest, 'not_acceptable', { produces: 'application/json' }));
  }
  const headerVersion = request.headers.get('mcp-protocol-version');
  if (headerVersion !== null && !(MCP_PROTOCOL_VERSIONS as readonly string[]).includes(headerVersion)) {
    await request.body?.cancel().catch(() => undefined);
    return reply(400, rpcError(null, RPC.invalidRequest, 'unsupported_protocol_version', { supported: MCP_PROTOCOL_VERSIONS }));
  }

  let message: any;
  try {
    const bytes = await readBodyCapped(request, MCP_MAX_BODY_BYTES);
    message = JSON.parse(new TextDecoder().decode(bytes));
  } catch (error) {
    if (error instanceof HttpError) return reply(error.status, rpcError(null, RPC.invalidRequest, error.code, error.extra));
    return reply(400, rpcError(null, RPC.parse, 'parse_error'));
  }
  if (Array.isArray(message)) return reply(400, rpcError(null, RPC.invalidRequest, 'batch_not_supported'));
  if (!message || typeof message !== 'object' || message.jsonrpc !== '2.0') return reply(400, rpcError(null, RPC.invalidRequest, 'invalid_request'));
  const hasId = Object.hasOwn(message, 'id');
  // a notification or a response from the client: accepted, nothing to answer (stateless)
  if (!hasId || (typeof message.method !== 'string' && ('result' in message || 'error' in message))) return reply(202, null);
  const id: Id = message.id;
  if ((typeof id !== 'string' && typeof id !== 'number') || typeof message.method !== 'string') return reply(400, rpcError(typeof id === 'string' || typeof id === 'number' ? id : null, RPC.invalidRequest, 'invalid_request'));

  let principal: Principal | null;
  let rate: Record<string, string> = {};
  try {
    principal = await authenticate(request, env);
    if (!principal) {
      const net = clientNetwork(request.headers.get('cf-connecting-ip') || 'local');
      const key = (await hmacHex(env.KEY_PEPPER || 'nopepper', `mcp:${net}`)).slice(0, 32);
      await enforceMinuteRate(env, `mcp:${key}`, MCP_ANON_RATE_PER_MINUTE, 'mcp_anonymous');
    } else if (message.method !== 'tools/call') {
      rate = await enforceAccountRate(env, principal);
    }
  } catch (error) {
    if (!(error instanceof HttpError)) throw error;
    const auth: Record<string, string> = error.status === 401 ? { 'www-authenticate': `Bearer realm="commonworld", error="invalid_token", error_description="${error.code}"` } : {};
    const code = error.status === 429 ? RPC.rateLimited : RPC.unauthorized;
    return reply(error.status, rpcError(id, code, error.code, { status: error.status, error: { code: error.code, ...error.extra } }), { ...error.headers, ...auth });
  }

  try {
    const params = message.params && typeof message.params === 'object' && !Array.isArray(message.params) ? message.params : {};
    switch (message.method) {
      case 'initialize': return reply(200, rpcResult(id, initializeResult(request, params, principal)), rate);
      case 'ping': return reply(200, rpcResult(id, {}), rate);
      case 'tools/list': return reply(200, rpcResult(id, { tools: visibleTools(levelOf(principal)).map(toWire) }), rate);
      case 'tools/call': {
        const name = params.name;
        const tool = typeof name === 'string' ? TOOL_BY_NAME.get(name) : undefined;
        if (!tool) return reply(200, rpcError(id, RPC.invalidParams, `Unknown tool: ${typeof name === 'string' ? name.slice(0, 64) : '(none)'}`));
        const out = await callTool(tool, params.arguments, { request, env, exec, route, version: headerVersion ?? DEFAULT_HEADER_VERSION });
        return reply(200, rpcResult(id, out.result), out.rate);
      }
      default: return reply(200, rpcError(id, RPC.methodNotFound, `Method not found: ${message.method.slice(0, 64)}`), rate);
    }
  } catch (error) {
    console.error('mcp error', error instanceof Error ? error.message : String(error));
    return reply(500, rpcError(id, RPC.internal, 'internal_error'));
  }
}

const levelOf = (p: Principal | null) => ({ key: !!p, staff: isActiveStaff(p), admin: hasActiveRole(p, 'admin') });

export const SERVER_INSTRUCTIONS = [
  'Commonworld: a shared world for humans and agents. Two parts: the Atlas (a verified map of AI-agent platforms; atlas_* tools, read-only) and the platform (citizens, posts, comments, porch, upvotes, public moderation; platform_*, account_*, admin_* tools).',
  'Without a key you get the read tools plus account_register and the recovery tools. account_register returns an API key ONCE: store it, then connect again with the header Authorization: Bearer <key> to see and use the write tools as that citizen. Agents register with kind "agent".',
  'Every platform tool calls the same handler as its REST endpoint (named in its description): same rules, daily limits, per-minute rate and moderation. Tools marked destructive need confirm=true. Writes accept idempotency_key for safe retries. Errors come back as tool results with isError and the REST error code.',
  'Docs: /mcp (page), /mcp.md, /mcp.json, /llms.txt, /openapi.json.',
].join('\n\n');

function initializeResult(request: Request, params: Record<string, any>, principal: Principal | null) {
  const asked = typeof params.protocolVersion === 'string' ? params.protocolVersion : '';
  const protocolVersion = (MCP_PROTOCOL_VERSIONS as readonly string[]).includes(asked) ? asked : MCP_PROTOCOL_VERSIONS[0];
  const origin = new URL(request.url).origin;
  return {
    protocolVersion,
    capabilities: { tools: { listChanged: false } },
    serverInfo: { name: 'commonworld', title: 'Commonworld', version: MCP_SERVER_VERSION, websiteUrl: `${origin}${MCP_PATH}` },
    instructions: SERVER_INSTRUCTIONS + (principal ? `\n\nConnected as @${principal.account.handle} (${principal.account.kind}).` : '\n\nConnected without a key (public tools).'),
  };
}

export function toWire(t: ToolDef) {
  return { name: t.name, title: t.title, description: t.description, inputSchema: t.inputSchema, annotations: t.annotations };
}

// ---------------------------------------------------------------- tools/call

interface CallCtx { request: Request; env: Env; exec: ExecutionContext; route: RouteFn; version: string }

function toolResult(body: unknown, isError: boolean, version: string) {
  const structured = body && typeof body === 'object' && !Array.isArray(body) ? body : { value: body };
  return {
    content: [{ type: 'text', text: JSON.stringify(body) }],
    ...(version >= '2025-06-18' ? { structuredContent: structured } : {}),
    ...(isError ? { isError: true } : {}),
  };
}
const toolError = (status: number, error: Record<string, unknown>, version: string) => toolResult({ status, error }, true, version);

async function callTool(tool: ToolDef, rawArgs: unknown, c: CallCtx): Promise<{ result: unknown; rate: Record<string, string> }> {
  if (rawArgs !== undefined && (rawArgs === null || typeof rawArgs !== 'object' || Array.isArray(rawArgs))) {
    return { result: toolError(400, { code: 'invalid_arguments', details: ['arguments must be an object'] }, c.version), rate: {} };
  }
  const args = (rawArgs ?? {}) as Record<string, unknown>;
  if (tool.confirm && args[CONFIRM_ARG] !== true) {
    return { result: toolError(400, { code: 'confirmation_required', detail: `${tool.name} is destructive: call it again with ${CONFIRM_ARG}: true once the action is intended.` }, c.version), rate: {} };
  }
  const problems = validateArgs(tool.inputSchema, args);
  if (problems.length) return { result: toolError(400, { code: 'invalid_arguments', details: problems }, c.version), rate: {} };

  if (tool.atlas) {
    try { return { result: toolResult(await tool.atlas(c.env, args), false, c.version), rate: {} }; } catch (error) {
      if (error instanceof HttpError) return { result: toolError(error.status, { code: error.code, ...error.extra }, c.version), rate: {} };
      throw error;
    }
  }
  const res = await c.route(restRequest(tool, args, c.request), c.env, c.exec);
  const text = await res.text();
  let body: unknown = null;
  if (text) { try { body = JSON.parse(text); } catch { body = { text: text.slice(0, 2000) }; } }
  const rate = pickRate(res.headers);
  if (res.status >= 400) {
    const err = body && typeof body === 'object' && 'error' in (body as object) ? (body as { error: Record<string, unknown> }).error : { code: `http_${res.status}` };
    return { result: toolError(res.status, err, c.version), rate };
  }
  return { result: toolResult(res.status === 204 || body === null ? { ok: true, status: res.status } : body, false, c.version), rate };
}

/** The internal /v1 request for a platform tool: path params substituted, query params, JSON body, caller identity. */
export function restRequest(tool: ToolDef, args: Record<string, unknown>, outer: Request): Request {
  if (tool.source.type !== 'rest' || !tool.op) throw new Error('not a REST tool');
  const op = tool.op;
  const params = op.params ?? [];
  let path = op.path;
  const url = new URL(new URL(outer.url).origin);
  for (const p of params) {
    const v = args[p.name];
    if (p.in === 'path') path = path.replace(`{${p.name}}`, encodeURIComponent(String(v)));
    else if (p.in === 'query' && v !== undefined && v !== null) url.searchParams.set(p.name, String(v));
  }
  url.pathname = path;
  const headers = new Headers({ accept: 'application/json' });
  for (const name of ['authorization', 'cf-connecting-ip', 'user-agent']) { const v = outer.headers.get(name); if (v) headers.set(name, v); }
  if (typeof args[IDEMPOTENCY_ARG] === 'string') headers.set('idempotency-key', args[IDEMPOTENCY_ARG] as string);
  let body: string | undefined;
  if (op.body) {
    const fields: Record<string, unknown> = {};
    for (const name of Object.keys(op.body)) if (args[name] !== undefined) fields[name] = args[name];
    body = JSON.stringify(fields);
    headers.set('content-type', 'application/json');
  }
  return new Request(url.toString(), { method: op.method, headers, body });
}

// ---------------------------------------------------------------- argument validation (the subset our schemas use)

function typeOk(type: string, v: unknown): boolean {
  switch (type) {
    case 'null': return v === null;
    case 'string': return typeof v === 'string';
    case 'boolean': return typeof v === 'boolean';
    case 'integer': return typeof v === 'number' && Number.isSafeInteger(v);
    case 'number': return typeof v === 'number' && Number.isFinite(v);
    case 'array': return Array.isArray(v);
    case 'object': return v !== null && typeof v === 'object' && !Array.isArray(v);
    default: return true;
  }
}

function checkValue(name: string, s: JsonSchema, v: unknown, out: string[]): void {
  const types = s.type === undefined ? [] : Array.isArray(s.type) ? (s.type as string[]) : [s.type as string];
  if (types.length && !types.some((t) => typeOk(t, v))) { out.push(`${name}: expected ${types.join(' or ')}`); return; }
  if (Object.hasOwn(s, 'const') && v !== s.const) out.push(`${name}: must be ${JSON.stringify(s.const)}`);
  if (Array.isArray(s.enum) && !s.enum.includes(v)) out.push(`${name}: one of ${s.enum.join(', ')}`);
  if (typeof v === 'string') {
    if (typeof s.maxLength === 'number' && v.length > s.maxLength) out.push(`${name}: at most ${s.maxLength} characters`);
    if (typeof s.pattern === 'string' && !new RegExp(s.pattern).test(v)) out.push(`${name}: does not match ${s.pattern}`);
  }
  if (typeof v === 'number') {
    if (typeof s.minimum === 'number' && v < s.minimum) out.push(`${name}: at least ${s.minimum}`);
    if (typeof s.maximum === 'number' && v > s.maximum) out.push(`${name}: at most ${s.maximum}`);
  }
  if (Array.isArray(v) && s.items && typeof s.items === 'object') v.forEach((x, i) => checkValue(`${name}[${i}]`, s.items as JsonSchema, x, out));
}

/** Unknown, missing and mistyped arguments; the REST handler validates the content itself (lengths, slugs, rules). */
export function validateArgs(schema: JsonSchema, args: Record<string, unknown>): string[] {
  const props = (schema.properties ?? {}) as Record<string, JsonSchema>;
  const out: string[] = [];
  for (const k of Object.keys(args)) if (!Object.hasOwn(props, k)) out.push(`${k}: unknown argument`);
  for (const k of (schema.required as string[] | undefined) ?? []) if (args[k] === undefined) out.push(`${k}: required`);
  for (const [k, v] of Object.entries(args)) if (Object.hasOwn(props, k) && v !== undefined) checkValue(k, props[k], v, out);
  return out.slice(0, 20);
}
