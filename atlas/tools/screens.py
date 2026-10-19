#!/usr/bin/env python3
"""Capture Atlas homepage screenshots into a checkout of the orphan branch `atlas-screens` (weekly CI + manual recaptures).

    python3 atlas/tools/screens.py --screens-dir DIR [--only a,b] [--force] [--summary out.md] [--review-dir R] [--dry-run]

DIR holds `manifest.json` + `<slug>.webp` (the branch's `atlas/screens/`). The site build reads that branch
(atlas/site/screens.py); this script only writes it. Playwright + Chromium (+ Pillow) are needed only here.

Capture rules (owner decision 2026-10-17; atlas screens PLAN "Standing capture rules"), applied to every capture:
 1. Cookie banners, consent walls, modals, popups and chat widgets are dismissed or hidden before the shot.
 2. Network idle (capped) + 4 s settle; reduced motion and animations/transitions off; a shot that still shows a
    loading placeholder (skeletons, spinners, "Loading…") is rejected, never stored.
 3. Same viewport and format for every card: 1280x800 viewport -> 1200x750 WebP, best quality that fits 64 KB;
    an honest bot User-Agent; muse.ai (and *.muse.ai) is never opened: every request to it is aborted.
 4. A new image replaces a stored one only when it is OK and (a) --force names the slug after a reviewer compared both,
    or (b) it changed visibly (dHash distance >= 6/64) and the stored one is >= 28 days old. --review-dir writes an
    old|new side-by-side PNG for every replacement; the weekly PR is the review step and is never merged automatically.
 5. A card whose own URL is not a human page (raw JSON/markdown, wallet wall) is shot on the operator's public human
    page from atlas/tools/screens-overrides.json `shot_url`; the manifest records it as `shot_url`.
 6. A failed capture (challenge, HTTP error, error/parked page, blank, loading placeholder, timeout) never overwrites
    the stored image; it is listed in the summary as a possible card/site issue. A card whose site keeps rendering
    without its data gets `hold` in the overrides file: it is still captured (for the summary) but never stored until a
    reviewer passes --force. The placeholder check only sees class-based skeletons/spinners and loading-only text, so
    empty boxes drawn without such classes still need the human/agent review of the PR.
Only live cards are captured; closed cards keep their last capture and no slug is ever removed from the manifest.
"""
import argparse, asyncio, glob, hashlib, io, json, os, sys, time, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DATA = os.path.join(ROOT, 'atlas', 'data')
OVERRIDES = os.path.join(HERE, 'screens-overrides.json')
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 '
      'CommonworldAtlasBot/1.0 (+https://commonworld.one/atlas/about/)')
VIEW_W, VIEW_H, SHOT_W, SHOT_H, TARGET = 1280, 800, 1200, 750, 64_000
SETTLE_MS, IDLE_MS, NAV_MS, HARD_S = 4000, 10_000, 35_000, 110
DHASH_MIN, MIN_AGE_DAYS = 6, 28
BLOCKED_HOSTS = ('muse.ai',)

CHALLENGE = ('just a moment', 'attention required', 'access denied', 'verify you are human', 'checking your browser',
             'security checkpoint', 'performing security verification', 'ddos-guard', 'one moment, please')
ERROR_TITLE = ('404', 'not found', 'bad gateway', '503 service', '500 internal', 'application error', 'deployment not found',
               'site not found', 'server error', 'suspended', 'domain for sale', 'is for sale', 'parked')
ERROR_BODY = ('deployment_not_found', 'this deployment cannot be found', 'domain is for sale', 'buy this domain',
              "there isn't a github pages site here", 'application error: a client-side exception', 'no such app', '404: not_found')

KILL_ANIM = ('*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;animation-iteration-count:1!important;'
             'transition:none!important;scroll-behavior:auto!important;caret-color:transparent!important}')
HIDE_CSS = """
#transcend-consent-manager,#onetrust-consent-sdk,#onetrust-banner-sdk,.onetrust-pc-dark-filter,#CybotCookiebotDialog,
#CybotCookiebotDialogBodyUnderlay,.cky-consent-container,.cky-overlay,.cky-modal,#cookiescript_injected,#cookie-law-info-bar,
.cc-window,.cc-banner,#usercentrics-root,#usercentrics-cmp-ui,.osano-cm-window,.osano-cm-dialog,#truste-consent-track,
.truste_overlay,.truste_box_overlay,#hs-eu-cookie-confirmation,.fc-consent-root,#qc-cmp2-container,.qc-cmp2-container,
#didomi-host,.didomi-popup-backdrop,#termly-code-snippet-support,#ketch-consent-banner,#lanyard_root,.iubenda-cs-container,
#iubenda-cs-banner,[id^="sp_message_container"],#axeptio_overlay,.klaro,#cmpbox,#cmpbox2,.cmpboxBG,
[aria-label*="cookie" i][role="dialog"],[aria-label*="consent" i][role="dialog"],[class*="cookie-banner" i],[class*="cookieBanner" i],
[class*="cookie-consent" i],[id*="cookie-consent" i],[id*="cookie-banner" i],[class*="CookieConsent" i],[id*="CookieConsent" i],
[class*="consent-banner" i],[id*="consent-banner" i],[data-testid*="cookie" i],
#intercom-container,.intercom-lightweight-app,#hubspot-messages-iframe-container,#crisp-chatbox,.crisp-client,#tidio-chat,
#drift-widget-container,#drift-frame-controller,.drift-frame-controller,#launcher[title*="chat" i],iframe[title*="chat" i],
[id*="chat-widget" i],[class*="chat-widget" i],#fc_frame,.zsiq_floatmain,#zsiq_float,[data-testid="chat-widget"],
#gorgias-chat-container,.tawk-min-container,iframe[src*="tawk.to"],#beacon-container,.BeaconFabButtonFrame
{display:none!important;visibility:hidden!important}
html,body{overflow:auto!important}
"""
BTN_TEXTS = ('Accept all cookies', 'Accept All Cookies', 'Accept all', 'Accept All', 'Allow all', 'Allow All', 'Accept cookies',
             'Accept Cookies', 'I agree', 'I Agree', 'Agree', 'Accept', 'Got it', 'OK', 'Okay', 'Only necessary',
             'Only necessary cookies', 'Necessary only', 'Reject all', 'Reject All', 'Decline')
CLOSE_SEL = ('[aria-label="Close" i]', '[aria-label*="dismiss" i]', 'button.close', '[data-dismiss="modal"]',
             '[role="dialog"] button[class*="close" i]', 'button:has-text("×")', 'button:has-text("✕")',
             'button:has-text("No thanks")', 'button:has-text("Maybe later")', 'button:has-text("Skip")')
UNBLUR_JS = """() => {
 for (const el of document.querySelectorAll('body *')) {
   const cs = getComputedStyle(el), r = el.getBoundingClientRect();
   if (r.width < innerWidth*0.9 || r.height < innerHeight*0.9) continue;
   if ((cs.backdropFilter && cs.backdropFilter !== 'none') || (cs.filter && cs.filter.includes('blur'))) {
     el.style.setProperty('filter','none','important'); el.style.setProperty('backdrop-filter','none','important'); }
 }
 document.documentElement.style.overflow=''; if (document.body) document.body.style.overflow='';
}"""
# share of the viewport covered by visible loading placeholders, and whether the visible text is only a loading line
PLACEHOLDER_JS = """() => {
 const vis = el => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
   return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.05; };
 let area = 0;
 for (const el of document.querySelectorAll('[class*="skeleton" i],[class*="shimmer" i],[class*="placeholder-glow" i],[class*="animate-pulse" i],[aria-busy="true"],[class*="spinner" i],[class*="loader" i]')) {
   if (!vis(el)) continue; const r = el.getBoundingClientRect();
   area += Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
 }
 const t = (document.body ? document.body.innerText : '').trim();
 return {share: area / (innerWidth * innerHeight), text_len: t.length, loading_only: t.length < 200 && /(loading|please wait|initiali[sz]ing|authenticating)/i.test(t)};
}"""


def utc_iso(t=None):
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_iso(s):
    try:
        return datetime.strptime(str(s), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def proxy_cfg():
    v = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
    if not v:
        return None
    u = urllib.parse.urlparse(v)
    cfg = {'server': f'{u.scheme}://{u.hostname}:{u.port}'}
    if u.username:
        cfg.update(username=urllib.parse.unquote(u.username), password=urllib.parse.unquote(u.password or ''))
    return cfg


def blocked(url):
    h = (urllib.parse.urlsplit(url).hostname or '').lower()
    return any(h == b or h.endswith('.' + b) for b in BLOCKED_HOSTS)


def live_cards(data_dir=DATA):
    snap = sorted(glob.glob(os.path.join(data_dir, 'snapshot-verified-*.json')))[-1]
    out = {}
    for p in json.load(open(snap, encoding='utf-8'))['platforms']:
        if p.get('status') == 'live' and str(p.get('canonical_url') or '').startswith('https://'):
            out[p['slug']] = p['canonical_url']
    return out


def dhash(img):
    from PIL import Image
    g = img.convert('L').resize((9, 8), Image.LANCZOS)
    px = list(g.tobytes())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (px[y * 9 + x] > px[y * 9 + x + 1])
    return f'{bits:016x}'


def hamming(a, b):
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except (TypeError, ValueError):
        return 64


def to_webp(png):
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert('RGB').resize((SHOT_W, SHOT_H), Image.LANCZOS)
    for q in (82, 74, 66, 58, 50, 42, 34, 26, 20):
        buf = io.BytesIO()
        img.save(buf, 'WEBP', quality=q, method=6)
        if buf.tell() <= TARGET:
            break
    return buf.getvalue(), q, img


def classify(status, title, body, img, ph):
    from PIL import ImageStat
    t, b = (title or '').lower().strip(), (body or '').lower()
    if any(k in t for k in CHALLENGE) or (len(b) < 1500 and any(k in b for k in CHALLENGE)):
        return 'challenge'
    if status is not None and status >= 400:
        return f'http_{status}'
    if (any(k in t for k in ERROR_TITLE) and len(b) < 3000) or (len(b) < 2000 and any(k in b for k in ERROR_BODY)):
        return 'error_page'
    if ImageStat.Stat(img.convert('L')).stddev[0] < 3.0 and len(b.strip()) < 40:
        return 'blank_page'
    if ph.get('loading_only') or ph.get('share', 0) > 0.12:
        return 'loading_placeholder'
    return None


async def _click_consent(page):
    done = []
    for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
        for t in BTN_TEXTS:
            try:
                loc = fr.get_by_role('button', name=t, exact=True)
                if await loc.count() and await loc.first.is_visible():
                    await loc.first.click(timeout=2500)
                    done.append(t)
                    break
            except Exception:
                pass
    for sel in CLOSE_SEL:
        try:
            loc = page.locator(sel)
            for i in range(min(await loc.count(), 3)):
                if await loc.nth(i).is_visible():
                    await loc.nth(i).click(timeout=2000)
                    done.append(sel)
                    break
        except Exception:
            pass
    try:
        await page.keyboard.press('Escape')
    except Exception:
        pass
    return done


async def shoot(browser, url, o):
    """-> (record, webp bytes or None, PIL image or None)."""
    ctx = await browser.new_context(viewport={'width': VIEW_W, 'height': VIEW_H}, user_agent=UA, locale='en-US',
                                    reduced_motion='reduce', bypass_csp=True)
    await ctx.route('**/*', lambda r: r.abort() if blocked(r.request.url) else r.continue_())
    page = await ctx.new_page()
    rec = {'website': url}
    try:
        resp = None
        try:
            resp = await page.goto(url, wait_until='load', timeout=NAV_MS)
        except Exception as ex:
            if 'Timeout' not in str(ex):
                raise
            rec['note'] = 'load event timed out; continued after domcontentloaded'
        for _ in range(2):  # idle, dismiss, hide, idle again
            try:
                await page.wait_for_load_state('networkidle', timeout=IDLE_MS)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            clicked = await _click_consent(page)
            for k in o.get('keys', []):
                await page.keyboard.press(k)
                await page.wait_for_timeout(1500)
            for t in o.get('click_text', []):
                try:
                    loc = page.get_by_text(t, exact=True)
                    if await loc.count():
                        await loc.first.click(timeout=3000)
                        clicked.append('text:' + t)
                except Exception:
                    pass
            await page.add_style_tag(content=KILL_ANIM + HIDE_CSS)
            rec.setdefault('dismissed', []).extend(clicked)
        await page.wait_for_timeout(SETTLE_MS + int(o.get('wait', 0)))
        try:
            await page.evaluate(UNBLUR_JS)
        except Exception:
            pass
        await page.evaluate('() => window.scrollTo(0, 0)')
        await page.wait_for_timeout(600)
        title = await page.title()
        body = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 5000) : ''")
        ph = await page.evaluate(PLACEHOLDER_JS)
        png = await page.screenshot(type='png', timeout=15_000)
        webp, q, img = to_webp(png)
        rec.update(final_url=page.url, http_status=resp.status if resp else None, title=(title or '')[:200], webp_quality=q,
                   placeholder_share=round(ph.get('share', 0), 3))
        reason = classify(rec['http_status'], title, body, img, ph)
        if reason:
            rec.update(ok=False, reason=reason)
            return rec, None, img
        rec['ok'] = True
        return rec, webp, img
    except Exception as ex:
        rec.update(ok=False, reason='error', error=str(ex).split('\n')[0][:200])
        return rec, None, None
    finally:
        rec['captured_at'] = utc_iso()
        await ctx.close()


def side_by_side(old_path, new_img, out_path):
    from PIL import Image, ImageDraw
    old = Image.open(old_path).convert('RGB') if old_path and os.path.exists(old_path) else Image.new('RGB', (SHOT_W, SHOT_H), 'white')
    w = 600
    a, b = old.resize((w, 375)), new_img.convert('RGB').resize((w, 375))
    c = Image.new('RGB', (2 * w + 10, 375 + 24), 'white')
    c.paste(a, (0, 24)); c.paste(b, (w + 10, 24))
    d = ImageDraw.Draw(c)
    d.text((4, 4), 'stored', fill='black'); d.text((w + 14, 4), 'new capture', fill='black')
    c.save(out_path)


def decide(slug, rec, old, now, force, hold=''):
    """'add' | 'replace' | 'keep:<why>'."""
    if hold and slug not in force:
        return f'keep:held ({hold})'
    if not rec.get('ok'):
        return 'keep:capture failed'
    if not old:
        return 'add'
    if slug in force:
        return 'replace'
    dist = hamming(rec.get('dhash'), old.get('dhash'))
    age = (now - parse_iso(old.get('captured_at'))) / 86400
    rec['dhash_distance'] = dist
    if dist < DHASH_MIN:
        return 'keep:no visible change'
    if age < MIN_AGE_DAYS:
        return f'keep:stored image only {age:.0f} days old'
    return 'replace'


async def run(a):
    from playwright.async_api import async_playwright
    mf_path = os.path.join(a.screens_dir, 'manifest.json')
    manifest = json.load(open(mf_path, encoding='utf-8')) if os.path.exists(mf_path) else {'screens': {}}
    screens = manifest.setdefault('screens', {})
    ovr = json.load(open(a.overrides, encoding='utf-8')).get('overrides', {}) if os.path.exists(a.overrides) else {}
    cards = live_cards(a.data)
    slugs = [s for s in (a.only.split(',') if a.only else sorted(cards)) if s]
    unknown = [s for s in slugs if s not in cards]
    slugs = [s for s in slugs if s in cards and not blocked(cards[s])]
    force = set(filter(None, (a.force or '').split(',')))
    now, results = time.time(), {}
    if a.review_dir:
        os.makedirs(a.review_dir, exist_ok=True)
    sem = asyncio.Semaphore(a.conc)
    async with async_playwright() as p:
        args = ['--no-sandbox', '--disable-dev-shm-usage', '--hide-scrollbars', '--mute-audio']
        browser = await p.chromium.launch(executable_path=a.chromium or None, proxy=proxy_cfg(), args=args)
        gl_browser = None

        async def one(slug):
            nonlocal gl_browser
            o = ovr.get(slug, {})
            url = o.get('shot_url') or cards[slug]
            async with sem:
                b = browser
                if o.get('gl'):
                    if gl_browser is None:
                        gl_browser = await p.chromium.launch(executable_path=a.chromium or None, proxy=proxy_cfg(),
                                                             args=args + ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
                    b = gl_browser
                rec = webp = img = None
                for attempt in (1, 2):  # one retry
                    try:
                        rec, webp, img = await asyncio.wait_for(shoot(b, url, o), HARD_S)
                    except asyncio.TimeoutError:
                        rec, webp, img = {'website': url, 'ok': False, 'reason': 'timeout', 'captured_at': utc_iso()}, None, None
                    if rec.get('ok'):
                        break
                rec['attempts'] = attempt
            if webp:
                rec.update(dhash=dhash(img), sha256=hashlib.sha256(webp).hexdigest(), bytes=len(webp))
            old = screens.get(slug)
            act = decide(slug, rec, old, now, force, o.get('hold', ''))
            rec['action'] = act
            if act in ('add', 'replace') and not a.dry_run:
                if a.review_dir and old:
                    side_by_side(os.path.join(a.screens_dir, old['file']), img, os.path.join(a.review_dir, f'{slug}.png'))
                with open(os.path.join(a.screens_dir, f'{slug}.webp'), 'wb') as f:
                    f.write(webp)
                new = {'file': f'{slug}.webp', 'sha256': rec['sha256'], 'dhash': rec['dhash'], 'website': cards[slug],
                       'source_url': rec['final_url'], 'http_status': rec['http_status'], 'title': rec['title'],
                       'captured_at': rec['captured_at'], 'width': SHOT_W, 'height': SHOT_H, 'bytes': rec['bytes']}
                if o.get('shot_url'):
                    new['shot_url'] = o['shot_url']
                screens[slug] = new
            elif a.review_dir and img is not None and not rec.get('ok'):
                img.convert('RGB').resize((600, 375)).save(os.path.join(a.review_dir, f'{slug}.rejected.webp'), 'WEBP', quality=40)
            results[slug] = rec
            print(f"{slug}: {act} ({rec.get('reason') or rec.get('http_status')})", flush=True)

        await asyncio.gather(*(one(s) for s in slugs))
        await browser.close()
        if gl_browser:
            await gl_browser.close()
    if not a.dry_run and any(r['action'] in ('add', 'replace') for r in results.values()):
        manifest['screens'] = dict(sorted(screens.items()))
        manifest['updated_at'] = utc_iso()
        with open(mf_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n')
    return results, unknown


def summary_md(results, unknown):
    by = lambda pred: sorted(s for s, r in results.items() if pred(r['action']))
    added, replaced = by(lambda x: x == 'add'), by(lambda x: x == 'replace')
    failed = sorted(s for s, r in results.items() if not r.get('ok'))
    L = ['## Atlas homepage screenshots', '',
         f'Captured {len(results)} live card(s): {len(added)} added, {len(replaced)} replaced, '
         f'{len(results) - len(added) - len(replaced) - len(failed)} unchanged, {len(failed)} failed (stored image kept).', '']
    if added or replaced:
        L += ['Every new image must be looked at next to the stored one before merging (old|new previews are in the run artifact).', '',
              '| entry | action | dHash distance | page |', '|---|---|---|---|']
        L += [f"| `{s}` | {results[s]['action']} | {results[s].get('dhash_distance', '-')} | {results[s].get('final_url', '')} |" for s in added + replaced]
        L.append('')
    if failed:
        L += ['### Not captured (possible card or site issue, stored image kept)', '', '| entry | reason | page |', '|---|---|---|']
        L += [f"| `{s}` | {results[s].get('reason')} {results[s].get('error', '')} | {results[s].get('website')} |" for s in failed]
        L.append('')
    if unknown:
        L += ['Not a live card (skipped): ' + ', '.join(f'`{s}`' for s in unknown), '']
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--screens-dir', required=True, help="checkout of the atlas-screens branch's atlas/screens/")
    ap.add_argument('--data', default=DATA)
    ap.add_argument('--overrides', default=OVERRIDES)
    ap.add_argument('--only', default='', help='comma-separated slugs (default: every live card)')
    ap.add_argument('--force', default='', help='slugs whose new capture a reviewer has compared and accepted')
    ap.add_argument('--conc', type=int, default=6)
    ap.add_argument('--chromium', default=os.environ.get('CHROMIUM_PATH', ''), help='browser binary (default: Playwright Chromium)')
    ap.add_argument('--summary', default='')
    ap.add_argument('--report', default='', help='JSON with every capture record')
    ap.add_argument('--review-dir', default='', help='write old|new previews and rejected shots here')
    ap.add_argument('--dry-run', action='store_true', help='capture and decide, write nothing to --screens-dir')
    a = ap.parse_args(argv)
    results, unknown = asyncio.run(run(a))
    md = summary_md(results, unknown)
    if a.summary:
        open(a.summary, 'w', encoding='utf-8').write(md)
    if a.report:
        json.dump(results, open(a.report, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
