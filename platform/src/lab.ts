/**
 * Staging-only lab: client-telemetry probe for the browser-agent visibility experiment (2026-10-18).
 * GET /lab/tab-telemetry  -> a plain page that loads /lab/tab-telemetry.js
 * The script POSTs /lab/beat every 10 s and on visibility/focus/blur/scroll/pointer/resize/pagehide events.
 * Each beat is one console.log line in Workers Logs (console output only; invocation logs are off again since 2026-10-19).
 * Only validated fields are logged: the event name must be one the script sends (LAB_BEAT_EVENTS), sid/n/vis/focus/t
 * must have their exact shapes; anything else -> 400 invalid_beat and no log line.
 * POST /lab/beat: body capped at 1 KB while streaming (413 past it, also for chunked bodies), 60 beats per minute per
 * client network (hashed) and 600 per minute in total (429 past either), same rate limiter as /v1/csp-report.
 * Nothing is stored in D1. Not served in production. Remove together with the logs switch.
 */
import type { Env } from './env';
import { hmacHex } from './crypto';
import { json, readTextCapped } from './http';
import { clientNetwork } from './limits';
import { enforceMinuteRate } from './ratelimit';

export const LAB_BEAT_MAX_BYTES = 1024;
const BEAT_PER_IP_PER_MINUTE = 60;
const BEAT_GLOBAL_PER_MINUTE = 600;

const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Commonworld lab: tab telemetry probe</title></head>
<body><main><h1>Tab telemetry probe</h1>
<p>This staging page sends a small heartbeat to its own server every 10 seconds and on visibility, focus and input events.
It exists to measure whether a browser agent reading this tab changes anything a server can observe.</p>
<p>Session: <code id="sid">starting</code>. Beats sent: <code id="n">0</code>.</p>
<h2>Sample content</h2><p>Atlas of Agent Platforms lists places where AI agents work, trade and talk. Each entry links to its primary source.</p>
</main><script src="/lab/tab-telemetry.js"></script></body></html>`;

const SCRIPT = `(()=>{const sid=Math.random().toString(36).slice(2,10);let n=0,last=0;
const el=(i)=>document.getElementById(i);el('sid').textContent=sid;
function beat(ev){n++;el('n').textContent=String(n);
const b=JSON.stringify({sid,n,ev,vis:document.visibilityState,focus:document.hasFocus(),t:Date.now()});
try{fetch('/lab/beat',{method:'POST',body:b,keepalive:true,headers:{'content-type':'application/json'}})}catch(e){}}
beat('load');setInterval(()=>beat('tick'),10000);
for(const e of ['visibilitychange','pagehide','pageshow','freeze','resume'])document.addEventListener(e,()=>beat(e));
for(const e of ['focus','blur','resize'])window.addEventListener(e,()=>beat(e));
for(const e of ['scroll','pointermove','keydown','copy','selectionchange'])document.addEventListener(e,()=>{const t=Date.now();if(t-last>2000){last=t;beat(e)}},{passive:true});
})();`;

/** Event names the probe script (SCRIPT above) sends; nothing else is accepted. */
export const LAB_BEAT_EVENTS: ReadonlySet<string> = new Set([
  'load', 'tick',
  'visibilitychange', 'pagehide', 'pageshow', 'freeze', 'resume',
  'focus', 'blur', 'resize',
  'scroll', 'pointermove', 'keydown', 'copy', 'selectionchange',
]);
const VIS_STATES = new Set(['visible', 'hidden', 'prerender']);
const SID_RE = /^[a-z0-9]{1,16}$/; // the script makes 8 base-36 chars (Math.random().toString(36).slice(2, 10))
const MAX_N = 1_000_000;
const MAX_T = 1e13; // ms since the epoch; covers dates up to the year 2286

export interface LabBeat { sid: string; n: number; ev: string; vis: string | null; focus: boolean | null; client_t: number | null }

/**
 * Validated beat or null. Required: sid (short [a-z0-9] id), n (integer 0..1e6), ev (one of LAB_BEAT_EVENTS).
 * Optional, but refused when present with another shape: vis (visible/hidden/prerender), focus (boolean),
 * t (integer ms timestamp). Other keys are ignored and never logged.
 */
export function parseBeat(raw: string): LabBeat | null {
  let d: unknown;
  try { d = JSON.parse(raw); } catch { return null; }
  if (!d || typeof d !== 'object' || Array.isArray(d)) return null;
  const o = d as Record<string, unknown>;
  if (typeof o.sid !== 'string' || !SID_RE.test(o.sid)) return null;
  if (typeof o.n !== 'number' || !Number.isInteger(o.n) || o.n < 0 || o.n > MAX_N) return null;
  if (typeof o.ev !== 'string' || !LAB_BEAT_EVENTS.has(o.ev)) return null;
  if (o.vis !== undefined && (typeof o.vis !== 'string' || !VIS_STATES.has(o.vis))) return null;
  if (o.focus !== undefined && typeof o.focus !== 'boolean') return null;
  if (o.t !== undefined && (typeof o.t !== 'number' || !Number.isInteger(o.t) || o.t < 0 || o.t > MAX_T)) return null;
  return {
    sid: o.sid, n: o.n, ev: o.ev,
    vis: (o.vis as string | undefined) ?? null,
    focus: (o.focus as boolean | undefined) ?? null,
    client_t: (o.t as number | undefined) ?? null,
  };
}

const CSP = "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

export async function handleLab(request: Request, env: Env): Promise<Response | null> {
  const url = new URL(request.url);
  if (!url.pathname.startsWith('/lab/')) return null;
  if (env.ENVIRONMENT !== 'staging' && env.ENVIRONMENT !== 'local') return null;
  const common = { 'x-robots-tag': 'noindex, nofollow', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };
  if (request.method === 'GET' && url.pathname === '/lab/tab-telemetry')
    return new Response(PAGE, { headers: { ...common, 'content-type': 'text/html; charset=utf-8', 'content-security-policy': CSP } });
  if (request.method === 'GET' && url.pathname === '/lab/tab-telemetry.js')
    return new Response(SCRIPT, { headers: { ...common, 'content-type': 'text/javascript; charset=utf-8' } });
  if (request.method === 'POST' && url.pathname === '/lab/beat') {
    const ip = clientNetwork(request.headers.get('cf-connecting-ip') || 'local');
    const ipKey = env.KEY_PEPPER ? (await hmacHex(env.KEY_PEPPER, `lab:${ip}`)).slice(0, 32) : 'nopepper';
    // Rate limits run before the body is read or validated on purpose: a flood of junk bodies costs the same as valid
    // beats and never reaches the parser past the limit.
    await enforceMinuteRate(env, 'lab-beat:all', BEAT_GLOBAL_PER_MINUTE, 'lab_beat');
    await enforceMinuteRate(env, `lab-beat:${ipKey}`, BEAT_PER_IP_PER_MINUTE, 'lab_beat_ip');
    // The whole body (stream cap LAB_BEAT_MAX_BYTES) is parsed; it is never cut short, so a valid JSON prefix followed
    // by junk cannot pass as a beat, and a longer valid beat is not broken mid-way.
    const raw = await readTextCapped(request, LAB_BEAT_MAX_BYTES);
    const beat = parseBeat(raw);
    // Anything that is not exactly a beat our own script sends is refused and never logged (no client strings, URLs
    // or query strings reach Workers Logs).
    if (!beat) return json(400, { error: { code: 'invalid_beat' } }, common);
    console.log(JSON.stringify({ lab: 'tab-telemetry', ...beat, server_t: Date.now() }));
    return new Response(null, { status: 204, headers: common });
  }
  return new Response('not found', { status: 404, headers: common });
}
