import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  buildSet, candidates, certPolska, checkDomains, combine, googleSafeBrowsing, listSource, metamask, normalizeDomain,
  openphish, parseAnswer, scamsniffer, substringHas, DEFAULT_SOURCES, type FetchLike, type SourceResult,
} from '../src/index.ts';
import { GSB_ENDPOINT } from '../src/sources/google-safe-browsing.ts';

const NOW = new Date('2026-10-17T20:00:00Z');
const gsb = (code: number, se = false) => `)]}'\n[["sb.ssr",${code},false,false,${se},false,false,1792259421202,"x",false]]`;

/** Mock fetch: url -> body | status number | Error. Records calls. */
function mock(routes: Record<string, string | number | Error | ((u: string) => string | number)>) {
  const calls: string[] = [];
  const f: FetchLike = async (u) => {
    calls.push(u);
    let r = routes[u];
    if (r === undefined) {
      const k = Object.keys(routes).find((p) => p.endsWith('*') && u.startsWith(p.slice(0, -1)));
      r = k ? routes[k] : 404;
    }
    if (typeof r === 'function') r = r(u);
    if (r instanceof Error) throw r;
    const status = typeof r === 'number' ? r : 200;
    const body = typeof r === 'string' ? r : '';
    return { ok: status >= 200 && status < 300, status, text: async () => body };
  };
  return { f, calls };
}
const ctx = (f: FetchLike) => ({ fetch: f, now: () => NOW, sleep: async () => {}, retries: 2 });

const MM = JSON.stringify({ version: 2, fuzzylist: ['metamask.io'], whitelist: ['good.example'], blacklist: ['drainer.example', 'evil-wallet.example'] });
const SS = JSON.stringify(['scam.example', 'claim-airdrop.example']);
const CERT = 'phish.example\nbank-login.example\n';
const OP = 'http://phish-url.example/login\nhttps://other.example:8443/x\n';

function allRoutes(extra: Record<string, string | number | Error | ((u: string) => string | number)> = {}) {
  return {
    [metamask.url]: MM, [scamsniffer.url]: SS, [certPolska.url]: CERT, [openphish.url]: OP,
    [GSB_ENDPOINT + '*']: (u: string) => (u.endsWith('venice.ai') ? gsb(3, true) : u.endsWith('unknown.example') ? gsb(6) : gsb(1)),
    ...extra,
  };
}

test('normalizeDomain and candidates', () => {
  assert.equal(normalizeDomain('HTTPS://WWW.Example.COM./path?q'), 'example.com');
  assert.equal(normalizeDomain('Sub.Example.com:8080/x'), 'sub.example.com');
  assert.equal(normalizeDomain('localhost'), '');
  assert.equal(normalizeDomain('bad domain.com'), '');
  assert.deepEqual(candidates('app.evil.example'), ['app.evil.example', 'www.app.evil.example', 'evil.example']);
  assert.deepEqual(candidates('mysite.vercel.app'), ['mysite.vercel.app', 'www.mysite.vercel.app'], 'never climbs to a shared platform suffix');
  assert.deepEqual(candidates('a.b.co.uk'), ['a.b.co.uk', 'www.a.b.co.uk', 'b.co.uk']);
});

test('combine: any single flag wins; clean needs one answer; else no_data', () => {
  const r = (verdict: SourceResult['verdict']): SourceResult => ({ name: 'x', verdict, checked_at: '', evidence_url: '' });
  assert.equal(combine([r('clean'), r('clean'), r('flagged')]), 'flagged');
  assert.equal(combine([r('no_data'), r('clean')]), 'clean');
  assert.equal(combine([r('no_data'), r('no_data')]), 'no_data');
  assert.equal(combine([]), 'no_data');
});

test('Safe Browsing answer parsing', () => {
  assert.deepEqual(parseAnswer(gsb(3, true)).threats, ['social_engineering']);
  assert.equal(parseAnswer(gsb(3, true)).verdict, 'flagged');
  assert.equal(parseAnswer(gsb(1)).verdict, 'clean');
  assert.equal(parseAnswer(gsb(4)).verdict, 'clean');
  assert.equal(parseAnswer(gsb(6)).verdict, 'no_data');
  assert.match(parseAnswer(gsb(1)).google_updated_at!, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
  assert.throws(() => parseAnswer('<html>rate limited</html>'));
  assert.throws(() => parseAnswer(')]}\'\n[["other",1]]'));
});

test('each default source flags its own listing; result shape per domain', async () => {
  const { f } = mock(allRoutes());
  const doms = ['venice.ai', 'drainer.example', 'scam.example', 'phish.example', 'fine.example', 'unknown.example'];
  const r = await checkDomains(doms, { ctx: ctx(f) });
  assert.deepEqual(r.flagged, ['drainer.example', 'phish.example', 'scam.example', 'venice.ai']);
  const by = (d: string, s: string) => r.results[d].sources.find((x) => x.name === s)!;
  assert.equal(by('venice.ai', 'google_safe_browsing').verdict, 'flagged');
  assert.equal(by('venice.ai', 'google_safe_browsing').detail, 'social_engineering');
  assert.equal(by('venice.ai', 'google_safe_browsing').evidence_url, 'https://transparencyreport.google.com/safe-browsing/search?url=venice.ai');
  assert.equal(by('drainer.example', 'metamask_phishing_detect').verdict, 'flagged');
  assert.equal(by('scam.example', 'scamsniffer').verdict, 'flagged');
  assert.equal(by('phish.example', 'cert_polska').verdict, 'flagged');
  assert.equal(r.results['fine.example'].status, 'clean');
  assert.equal(r.results['unknown.example'].status, 'clean', 'Safe Browsing has no data, but the lists answered');
  for (const d of doms) {
    assert.equal(r.results[d].sources.length, DEFAULT_SOURCES.length);
    for (const s of r.results[d].sources) {
      assert.ok(['clean', 'flagged', 'no_data'].includes(s.verdict));
      assert.equal(s.checked_at, '2026-10-17T20:00:00Z');
      assert.match(s.evidence_url, /^https:\/\//);
    }
  }
  assert.deepEqual(r.summary, { domains: 6, clean: 2, flagged: 4, no_data: 0, source_errors: 0 });
});

test('MetaMask: only the exact blacklist counts (whitelist and fuzzylist never flag)', async () => {
  const { f } = mock(allRoutes());
  const r = await checkDomains(['good.example', 'metamask.io', 'evil-wallet.example'], { sources: [metamask], ctx: ctx(f) });
  assert.deepEqual(r.flagged, ['evil-wallet.example']);
});

test('parent-domain listing flags subdomains, www is matched, shared suffix never climbs', async () => {
  const { f } = mock(allRoutes({ [scamsniffer.url]: JSON.stringify(['scam.example', 'vercel.app', 'www.wwwlisted.example']) }));
  const r = await checkDomains(['app.scam.example', 'mine.vercel.app', 'wwwlisted.example'], { sources: [scamsniffer], ctx: ctx(f) });
  assert.deepEqual(r.flagged, ['app.scam.example', 'wwwlisted.example']);
  assert.equal(r.results['app.scam.example'].sources[0].detail, 'listed as scam.example');
});

test('substring matcher (few domains) and Set matcher (many) agree', async () => {
  const many = Array.from({ length: 30 }, (_, i) => `site${i}.example`);
  for (const src of [metamask, scamsniffer, certPolska, openphish]) {
    const listed = ['drainer.example', 'scam.example', 'phish.example', 'phish-url.example', 'other.example'];
    const { f } = mock(allRoutes());
    const few = await checkDomains(listed, { sources: [src], ctx: ctx(f) });
    const big = await checkDomains([...listed, ...many], { sources: [src], ctx: ctx(f) });
    for (const d of listed) assert.equal(few.results[d].status, big.results[d].status, `${src.id} ${d}`);
  }
  assert.equal(substringHas('\nphish.example\n', { kind: 'lines' }, 'hish.example'), false, 'whole line only');
  assert.equal(substringHas('["xscam.example"]', { kind: 'json-array' }, 'scam.example'), false, 'whole string only');
  assert.equal(substringHas('\nhttp://a.example.evil/x\n', { kind: 'lines', urls: true }, 'a.example'), false);
  assert.deepEqual([...buildSet(OP, { kind: 'lines', urls: true })].sort(), ['other.example', 'phish-url.example']);
});

test('OpenPhish is off by default (terms)', () => {
  assert.ok(!DEFAULT_SOURCES.includes(openphish));
  assert.match(openphish.terms, /NOT ENABLED/);
});

test('a failed source is no_data with the error, retried, and never hides another source\'s flag', async () => {
  const { f, calls } = mock(allRoutes({ [scamsniffer.url]: 503, [certPolska.url]: new Error('ECONNRESET') }));
  const r = await checkDomains(['drainer.example', 'fine.example'], { ctx: ctx(f) });
  assert.equal(calls.filter((u) => u === scamsniffer.url).length, 3, '1 try + 2 retries on 503');
  const ss = r.results['fine.example'].sources.find((s) => s.name === 'scamsniffer')!;
  assert.equal(ss.verdict, 'no_data');
  assert.equal(ss.error, 'HTTP 503');
  assert.match(r.results['fine.example'].sources.find((s) => s.name === 'cert_polska')!.error!, /ECONNRESET/);
  assert.equal(r.results['drainer.example'].status, 'flagged');
  assert.equal(r.results['fine.example'].status, 'clean');
  assert.equal(r.summary.source_errors, 4);
});

test('404 is not retried; garbage list is no_data; all sources down = no_data', async () => {
  const { f, calls } = mock({ [metamask.url]: 404, [scamsniffer.url]: '<html>oops</html>', [certPolska.url]: 500, [GSB_ENDPOINT + '*']: '<html>consent</html>' });
  const r = await checkDomains(['a.example'], { ctx: ctx(f) });
  assert.equal(calls.filter((u) => u === metamask.url).length, 1);
  assert.equal(r.results['a.example'].status, 'no_data');
  assert.ok(r.results['a.example'].sources.every((s) => s.error));
});

test('a throwing plugin does not take the run down', async () => {
  const boom = { ...listSource({ id: 'boom', name: 'Boom', covers: '', url: 'https://x.example/l', evidence_url: 'https://x.example', terms: '', format: { kind: 'lines' } }), check: async () => { throw new Error('bug'); } };
  const { f } = mock(allRoutes());
  const r = await checkDomains(['scam.example'], { sources: [boom, scamsniffer], ctx: ctx(f) });
  assert.equal(r.results['scam.example'].status, 'flagged');
  assert.equal(r.results['scam.example'].sources[0].error, 'bug');
});

test('input is normalised and de-duplicated; report metadata', async () => {
  const { f } = mock(allRoutes());
  const r = await checkDomains(['https://WWW.Fine.example/x', 'fine.example', 'not a domain'], { ctx: ctx(f) });
  assert.deepEqual(Object.keys(r.results), ['fine.example']);
  assert.equal(r.engine, 'Commonworld trust engine');
  assert.deepEqual(r.sources.map((s) => s.id), ['google_safe_browsing', 'metamask_phishing_detect', 'scamsniffer', 'cert_polska']);
  assert.equal(googleSafeBrowsing.id, r.sources[0].id);
});
