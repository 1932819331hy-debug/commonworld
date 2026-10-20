/**
 * POST /v1/csp-report must take every real browser report shape (QA 2026-10-17: desktop Safari got 400 three times).
 * WebKit's report-uri sends application/csp-report with ONE Reporting-API object ({type, url, body}), not the legacy
 * {"csp-report": …} wrapper and not an array. The Safari payload below is the exact body WebKit sent to staging.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exports } from 'cloudflare:workers';
import { extractReports } from '../src/csp-report';
import { resetDb } from './helpers';

beforeEach(resetDb);
afterEach(() => vi.restoreAllMocks());

const POLICY = "default-src 'self'; script-src 'self' 'sha256-eSWVSXqZ9UJSICkTUYWT5lohfFMUCZsIomqoYj7aToM=' 'nonce-ON6bZtQWicw1qZvbc5PO9g==' https://static.cloudflareinsights.com; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://cloudflareinsights.com; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; report-uri /v1/csp-report; report-to csp";

/** Captured from WebKit (Safari engine) on staging /citizens, an inline <script> without nonce. */
const SAFARI_INLINE_SCRIPT = { type: 'csp-violation', url: 'https://staging.commonworld.one/citizens', body: { documentURL: 'https://staging.commonworld.one/citizens', disposition: 'enforce', referrer: '', effectiveDirective: 'script-src-elem', blockedURL: 'inline', originalPolicy: POLICY, statusCode: 200, sample: '' } };
const SAFARI_INLINE_STYLE = { type: 'csp-violation', url: 'https://staging.commonworld.one/citizens', body: { documentURL: 'https://staging.commonworld.one/citizens', disposition: 'enforce', referrer: '', effectiveDirective: 'style-src-elem', blockedURL: 'inline', originalPolicy: POLICY, statusCode: 200, sample: '', sourceFile: 'https://staging.commonworld.one/citizens', lineNumber: 1, columnNumber: 1 } };
const SAFARI_BLOB_WORKER = { type: 'csp-violation', url: 'https://staging.commonworld.one/citizens', body: { documentURL: 'https://staging.commonworld.one/citizens', disposition: 'enforce', referrer: '', effectiveDirective: 'worker-src', blockedURL: 'blob', originalPolicy: POLICY, statusCode: 200 } };
/** Firefox / Chrome report-uri (legacy wrapper, kebab-case keys). */
const FIREFOX = { 'csp-report': { 'blocked-uri': 'inline', 'column-number': 1, 'disposition': 'enforce', 'document-uri': 'https://cw.test/citizens', 'effective-directive': 'style-src-elem', 'original-policy': POLICY, 'referrer': '', 'status-code': 200, 'violated-directive': 'style-src-elem', 'source-file': 'https://cw.test/citizens', 'line-number': 1 } };
/** Chrome report-to batch: may mix in other report types (deprecation, NEL), which are skipped. */
const CHROME_BATCH = [
  { age: 10, type: 'deprecation', url: 'https://cw.test/', user_agent: 'Chrome', body: { id: 'x', message: 'y' } },
  { age: 12, type: 'csp-violation', url: 'https://cw.test/citizens', user_agent: 'Chrome', body: { blockedURL: 'inline', columnNumber: 3, disposition: 'enforce', documentURL: 'https://cw.test/citizens', effectiveDirective: 'script-src-elem', lineNumber: 9, originalPolicy: POLICY, referrer: '', sample: '', sourceFile: 'https://cw.test/citizens', statusCode: 200 } },
];

let ip = 0;
const send = (body: unknown, type = 'application/csp-report') =>
  (exports as any).default.fetch(new Request('https://cw.test/v1/csp-report', { method: 'POST', headers: { 'content-type': type, 'cf-connecting-ip': `192.0.2.${++ip % 250}` }, body: typeof body === 'string' ? body : JSON.stringify(body) })) as Promise<Response>;

describe('CSP reports: every real browser format', () => {
  it('Safari (WebKit report-uri: one {type, body} object as application/csp-report) -> 204, with or without charset', async () => {
    const logs: string[] = [];
    vi.spyOn(console, 'log').mockImplementation((m: unknown) => { logs.push(String(m)); });
    expect((await send(SAFARI_INLINE_SCRIPT)).status).toBe(204);
    expect((await send(SAFARI_INLINE_STYLE, 'application/csp-report; charset=utf-8')).status).toBe(204);
    expect((await send(SAFARI_BLOB_WORKER, 'application/csp-report;charset=UTF-8')).status).toBe(204);
    expect((await send(SAFARI_INLINE_SCRIPT, 'application/reports+json')).status).toBe(204);
    const lines = logs.filter((l) => l.includes('csp-violation')).map((l) => JSON.parse(l));
    expect(lines[0]).toEqual({ event: 'csp-violation', directive: 'script-src-elem', blocked: 'inline', page: 'https://staging.commonworld.one/citizens', source: null, line: null, disposition: 'enforce' });
    expect(lines[1]).toMatchObject({ directive: 'style-src-elem', blocked: 'inline', line: 1 });
    expect(lines[2]).toMatchObject({ directive: 'worker-src', blocked: 'blob' });
  });

  it('Firefox / Chrome legacy wrapper and Chrome report-to batches -> 204 (non-CSP items skipped)', async () => {
    const logs: string[] = [];
    vi.spyOn(console, 'log').mockImplementation((m: unknown) => { logs.push(String(m)); });
    expect((await send(FIREFOX)).status).toBe(204);
    expect((await send(CHROME_BATCH, 'application/reports+json')).status).toBe(204);
    expect((await send([SAFARI_INLINE_SCRIPT], 'application/reports+json; charset=utf-8')).status).toBe(204);
    const lines = logs.filter((l) => l.includes('csp-violation'));
    expect(lines).toHaveLength(3);
    expect(logs.join('\n')).not.toContain('deprecation');
  });

  it('bad bodies are 4xx, never 5xx', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const bad: [unknown, string][] = [
      ['', 'application/csp-report'], ['   ', 'application/csp-report'], ['null', 'application/csp-report'], ['[]', 'application/reports+json'],
      ['{"type":"csp-violation"}', 'application/csp-report'], ['{"type":"csp-violation","body":"x"}', 'application/csp-report'],
      ['{"csp-report":null}', 'application/csp-report'], ['[1,"a",null]', 'application/reports+json'], ['{"type":"deprecation","body":{}}', 'application/reports+json'],
      ['\u00ff\u00fe{', 'application/csp-report'], ['{"csp-report":', 'application/csp-report'],
    ];
    for (const [body, type] of bad) {
      const s = (await send(body, type)).status;
      expect(s, `${type} ${String(body)}`).toBeGreaterThanOrEqual(400);
      expect(s, `${type} ${String(body)}`).toBeLessThan(500);
    }
  });

  it('extractReports picks the CSP body out of each shape', () => {
    expect(extractReports(SAFARI_INLINE_SCRIPT)).toEqual([SAFARI_INLINE_SCRIPT.body]);
    expect(extractReports(FIREFOX)).toEqual([FIREFOX['csp-report']]);
    expect(extractReports(CHROME_BATCH)).toEqual([CHROME_BATCH[1].body]);
    expect(extractReports({ hello: 1 })).toEqual([]);
    expect(extractReports(Array.from({ length: 50 }, () => SAFARI_INLINE_SCRIPT))).toHaveLength(10); // MAX_REPORTS
  });
});
