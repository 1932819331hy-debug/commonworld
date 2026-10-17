#!/usr/bin/env python3
"""Live CSP check: opens production pages in headless Chromium and fails on any Content Security Policy report.

Production differs from the local build in one way that matters here: Cloudflare injects scripts at the edge
(JavaScript Detections bootstrap + /cdn-cgi/challenge-platform/scripts/jsd/main.js, email decoding). This check
confirms they run under our strict CSP (the per-request nonce from functions/_middleware.js) without a single
console violation, and reports which Cloudflare scripts actually loaded.

    python3 atlas/site/tools/live_csp_check.py [https://commonworld.one]
"""
import sys
from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'https://commonworld.one').rstrip('/')
PATHS = ['/', '/atlas/', '/atlas/about/', '/atlas/decisions/', '/atlas/platforms/bountybook/', '/privacy/']
HOOK = ("document.addEventListener('securitypolicyviolation',function(e){console.error('CSP-VIOLATION '+e.violatedDirective+' '"
        "+(e.blockedURI||'inline')+' '+(e.sourceFile||'')+':'+(e.lineNumber||0))});")

bad, cf, nonce_ok = [], set(), []
with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={'width': 1280, 'height': 900})
    ctx.add_init_script(HOOK)
    for path in PATHS:
        pg = ctx.new_page()
        pg.on('console', lambda m, path=path: bad.append(f'{path}: {m.text[:300]}')
              if m.type == 'error' and ('Content Security Policy' in m.text or 'CSP-VIOLATION' in m.text) else None)
        pg.on('request', lambda r: cf.add(r.url.split('?')[0].replace(BASE, '')) if '/cdn-cgi/' in r.url else None)
        resp = pg.goto(BASE + path, wait_until='load')
        pg.wait_for_timeout(4000)  # the challenge script loads after DOMContentLoaded, inside a hidden iframe
        csp = (resp.headers or {}).get('content-security-policy', '') if resp else ''
        nonce_ok.append((path, resp.status if resp else None, "'nonce-" in csp, "'unsafe-inline'" in csp))
        pg.close()
    br.close()

for path, st, has_nonce, unsafe in nonce_ok:
    print(f'{path}: HTTP {st}, per-request nonce {"yes" if has_nonce else "NO"}, unsafe-inline {"YES" if unsafe else "no"}')
print('Cloudflare scripts/requests seen:', ', '.join(sorted(cf)) or 'none')
if bad:
    print(f'FAIL: {len(bad)} CSP report(s)'); [print('  -', b) for b in bad]
fails = bad or any(u for *_, u in nonce_ok) or not all(n for _, _, n, _ in nonce_ok)
print('LIVE CSP OK' if not fails else 'LIVE CSP FAILED')
sys.exit(1 if fails else 0)
