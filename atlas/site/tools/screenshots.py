#!/usr/bin/env python3
"""Optional: screenshots of the built site (needs `pip install playwright` + `playwright install chromium`,
or a system Chromium: set CHROMIUM=/path/to/chromium; /usr/bin/chromium is used automatically if present).
Starts the local server in-process on a free port and writes PNGs to ../screenshots/.

    python3 atlas/site/tools/screenshots.py [platform-slug]
"""
import os, sys, threading, http.server
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import serve  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def launch(p):
    exe = os.environ.get('CHROMIUM') or ('/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else None)
    return p.chromium.launch(**({'executable_path': exe} if exe else {}))


OUT = os.path.join(HERE, '..', 'screenshots')
slug = sys.argv[1] if len(sys.argv) > 1 else 'the-colony'
serve.H.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), serve.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'
# name, path, theme, width, height, full page
shots = [
    ('index-light-desktop', '/atlas/', 'light', 1440, 1000, True),
    ('index-dark-desktop', '/atlas/', 'dark', 1440, 1000, False),
    ('platform-light-desktop', f'/atlas/platforms/{slug}/', 'light', 1440, 1000, True),
    ('index-mobile', '/atlas/', 'light', 390, 844, False),
    ('index-tablet', '/atlas/', 'light', 820, 1180, False),
    ('platform-mobile', f'/atlas/platforms/{slug}/', 'light', 390, 844, False),
    ('platform-mobile-share', f'/atlas/platforms/{slug}/', 'light', 390, 844, False),
    ('index-tags-open-dark', '/atlas/?tag=x402', 'dark', 1440, 1000, False),
    ('category-light', '/atlas/categories/payments/', 'light', 1440, 1000, False),
    ('index-mobile-drawer', '/atlas/', 'light', 390, 844, False),
    ('about-light-desktop', '/atlas/about/', 'light', 1440, 1000, True),
    ('privacy-light-desktop', '/atlas/privacy/', 'light', 1440, 1000, True),
    ('terms-light-desktop', '/atlas/terms/', 'light', 1440, 1000, False),
]
os.makedirs(OUT, exist_ok=True)
with sync_playwright() as p:
    b = launch(p)
    for name, path, theme, w, h, full in shots:
        ctx = b.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1)
        # pre-set the visitor's choices: theme, and consent already answered so the banner doesn't cover content
        ctx.add_init_script(f"try{{localStorage.setItem('cw-theme','{theme}');localStorage.setItem('cw-consent','denied')}}catch(e){{}}")
        pg = ctx.new_page()
        pg.goto(base + path, wait_until='networkidle')
        if name == 'index-tags-open-dark':
            pg.click('.cw-tags-more'); pg.evaluate("document.getElementById('catalog').scrollIntoView()")
        if name == 'platform-mobile-share':
            pg.evaluate("document.querySelector('.cw-share').scrollIntoView({block:'center'})")
        if name == 'index-mobile-drawer':
            pg.click('.cw-menu')
        pg.wait_for_timeout(250)
        pg.screenshot(path=os.path.join(OUT, name + '.png'), full_page=full)
        print('wrote', name)
        ctx.close()
    b.close()
srv.shutdown()
