/**
 * POST /v1/csp-report — Content-Security-Policy violation reports from browsers.
 * Accepts the legacy `report-uri` format (application/csp-report: {"csp-report": {...}}), the Reporting API
 * format (`report-to`, application/reports+json: [{"type": "csp-violation", "body": {...}}]) and WebKit's
 * report-uri format (application/csp-report: ONE {"type": "csp-violation", "body": {...}} object, no array).
 * Size-limited (8 KB), rate-limited (per hashed client IP and globally), logs only: nothing is stored in D1
 * except the rate-limit counters, and the log line carries no IP, no user agent and no query strings.
 */
import type { Ctx } from './context';
import { hmacHex } from './crypto';
import { HttpError, readTextCapped } from './http';
import { clientNetwork } from './limits';
import { enforceMinuteRate } from './ratelimit';

export const CSP_REPORT_MAX_BYTES = 8 * 1024;
const PER_IP_PER_MINUTE = 30;
const GLOBAL_PER_MINUTE = 600;
const MAX_REPORTS = 10;
const TYPES = /^application\/(csp-report|reports\+json|json)\b/i;

const noContent = () => new Response(null, { status: 204, headers: { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' } });

/** Keeps scheme + host + path of a URL, or a short keyword ("inline", "eval", "data"); drops query and fragment. */
function scrubUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null;
  const v = value.slice(0, 500);
  if (/^[a-z-]{1,20}$/i.test(v)) return v.toLowerCase();
  try {
    const u = new URL(v);
    if (u.protocol === 'http:' || u.protocol === 'https:') return `${u.origin}${u.pathname}`.slice(0, 300);
    return u.protocol.replace(/:$/, '');
  } catch {
    return null;
  }
}

const short = (value: unknown, max = 80): string | null => (typeof value === 'string' && value ? value.replace(/[^\x20-\x7e]/g, '').slice(0, max) : null);
const int = (value: unknown): number | null => (Number.isSafeInteger(value) ? (value as number) : null);

function summarize(r: Record<string, any>) {
  return {
    directive: short(r['effective-directive'] ?? r.effectiveDirective ?? r['violated-directive'] ?? r.violatedDirective),
    blocked: scrubUrl(r['blocked-uri'] ?? r.blockedURL ?? r.blockedUri),
    page: scrubUrl(r['document-uri'] ?? r.documentURL ?? r.documentUri),
    source: scrubUrl(r['source-file'] ?? r.sourceFile),
    line: int(r['line-number'] ?? r.lineNumber),
    disposition: short(r.disposition, 10),
  };
}

/** Body capped at 8 KB while streaming (shared reader in src/http.ts). */
const readCapped = (request: Request): Promise<string> => readTextCapped(request, CSP_REPORT_MAX_BYTES);

const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);

/** One Reporting-API item ({type, url, body}) -> its CSP body, or null for other report types (deprecation, NEL…). */
function fromReportingItem(r: unknown): Record<string, any> | null {
  if (!isObj(r) || !isObj(r.body)) return null;
  if (r.type === 'csp-violation' || r.type === 'csp') return r.body;
  return null;
}

/**
 * Every real browser shape, as seen in the wild:
 *  - legacy report-uri (Chrome, Firefox, old Safari): {"csp-report": {...}}
 *  - Reporting API batch (Chrome/Edge report-to): [{"type":"csp-violation","url":...,"body":{...}}, ...]
 *  - WebKit/Safari report-uri (Safari 16.4+): ONE Reporting-API object, not wrapped and not in an array,
 *    sent as application/csp-report: {"type":"csp-violation","url":...,"body":{"documentURL":...,"effectiveDirective":...}}
 */
export function extractReports(parsed: unknown): Record<string, any>[] {
  const out: Record<string, any>[] = [];
  if (Array.isArray(parsed)) {
    for (const r of parsed.slice(0, MAX_REPORTS)) { const b = fromReportingItem(r); if (b) out.push(b); }
  } else if (isObj(parsed)) {
    if (isObj(parsed['csp-report'])) out.push(parsed['csp-report']);
    else { const b = fromReportingItem(parsed); if (b) out.push(b); }
  }
  return out;
}

export async function cspReport(c: Ctx): Promise<Response> {
  if (!TYPES.test(c.request.headers.get('content-type') || '')) throw new HttpError(415, 'csp_report_content_type_required');
  const ip = clientNetwork(c.request.headers.get('cf-connecting-ip') || 'local');
  const ipKey = c.env.KEY_PEPPER ? (await hmacHex(c.env.KEY_PEPPER, `csp:${ip}`)).slice(0, 32) : 'nopepper';
  await enforceMinuteRate(c.env, 'csp:all', GLOBAL_PER_MINUTE, 'csp_report');
  await enforceMinuteRate(c.env, `csp:${ipKey}`, PER_IP_PER_MINUTE, 'csp_report_ip');
  const text = await readCapped(c.request);
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { throw new HttpError(400, 'invalid_json'); }
  const reports = extractReports(parsed);
  if (!reports.length) throw new HttpError(400, 'no_csp_report');
  for (const r of reports) console.log(JSON.stringify({ event: 'csp-violation', ...summarize(r) }));
  return noContent();
}
