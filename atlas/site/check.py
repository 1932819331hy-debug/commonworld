#!/usr/bin/env python3
"""Static checks for the built Atlas (stdlib only). Exit code 1 on any failure.

    python3 atlas/site/check.py

Checks: every internal link/asset resolves (incl. #fragments), trailing-slash consistency, every page has
lang=en, <title>, meta description, canonical (= its own clean URL), robots meta, JSON-LD that parses
(+ BreadcrumbList), unique titles/descriptions, external links carry rel nofollow+noopener (sponsored links
rel sponsored), sitemap lists exactly the indexable pages, robots.txt references the sitemap, 404 is noindex,
no page over 150 KB raw (catalog index: 320 KB, it server-renders every card) and none over 60 KB gzipped.
Open Graph: every indexable page has its own og:image (/atlas/og/<name>.png, exists, 1200x630 PNG, <= 100 KB),
width/height/alt, twitter:card=summary_large_image, twitter:image = og:image. Share bars: every platform page (and the
index) has one; every share link carries the page's canonical URL; the copy button copies the canonical URL.
Legal + navigation: the site-wide Commonworld legal pages (site.privacy_url /privacy/, site.terms_url /terms/) exist (WebPage JSON-LD,
Last updated, draft note only while legal_draft=true and never after, indexable, scope line, required privacy items); no page loads a third-party
script, image or stylesheet (Google's gtag.js is injected by JS only after Accept); the old /atlas/privacy/ and /atlas/terms/ are noindex redirect stubs
(meta refresh + canonical to the new URL) and dist/_redirects carries their 301s; every page's footer links Privacy and Terms, the
cookie banner links site.privacy_url, the sidebar "Commonworld" item sits above
"Directions" and links site.product_url, and the top-right home icon links site.product_url. About page carries the approved wording.
Platform pages carry exactly one share bar, inside the header card.
Sitemaps: /sitemap.xml (site-level pages) + /atlas/sitemap.xml together list exactly the indexable pages; robots.txt names both.
Forbidden text: no file in dist (HTML, public JSON, JS, XML, TXT) contains any of the operator's private terms (personal names,
locations, local-timezone markers). The list is kept outside the repo: env CW_PRIVATE_TERMS (regex alternatives joined by |) or the
git-ignored file atlas/site/.private-terms (one regex per line); the approved public contact address contact.general is exempt. Site-authored landing, About, legal and Atlas-method copy contains no EU mention or operator-location wording; third-party Atlas catalog records retain their own names and source URLs.
Landing: / exists (dist/index.html), canonical origin + '/', indexable, H1/motto/coming-soon line, primary button to /atlas/, logo marks,
cookie banner, own og:image page-home.png, share bar, Atlas count; site.product_url/home_url point to it.
About Commonworld: /about/ exists (canonical origin + '/about/', indexable, H1 "About Commonworld", motto, AboutPage + Organization
JSON-LD named Commonworld with url and no address, own og:image page-cw-about.png, in the root /sitemap.xml, share bar, live Atlas count,
links to /atlas/, /atlas/about/, /privacy/, /terms/, the GitHub issues and privacy@; future features marked planned/coming, no "sign up"
style wording); every page's sidebar has an "About" link to /about/ right under the Commonworld item (above Directions) and the footer
links "About Commonworld" + "How the Atlas works"; /atlas/about/ opens with a line linking /about/.
Also: native ad cards sit after every 12th card, the tag shelf exists with its expander, every card links to its page.
"""
import gzip, json, os, re, struct, sys, xml.etree.ElementTree as ET
from urllib.parse import quote, unquote
from html.parser import HTMLParser
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, 'dist')
ORIGIN = json.load(open(os.path.join(HERE, 'site-config.json')))['site']['origin'].rstrip('/')
MAX = 150 * 1024          # raw HTML per page
MAX_INDEX = 320 * 1024    # the catalog index server-renders all cards (SEO, works without JS)
MAX_GZ = 60 * 1024        # what actually goes over the wire, every page
MAX_OG = 100 * 1024       # per OG image (target < 80 KB)
SHARE_ON = json.load(open(os.path.join(HERE, 'site-config.json'))).get('share', {}).get('enabled', True)


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.in_title, self.meta, self.links, self.ids, self.ld, self._ld, self.canon, self.lang, self.anchors = '', False, {}, [], set(), [], None, None, None, []
        self.shares, self.share_bars, self._in_share = [], [], 0

    def handle_starttag(self, tag, a):
        a = dict(a)
        if 'id' in a:
            self.ids.add(a['id'])
        if tag == 'html':
            self.lang = a.get('lang')
        if 'cw-share' in (a.get('class') or '').split():
            self.share_bars.append((a.get('data-share-url'), a.get('data-share-text')))
        if a.get('data-share'):
            self.shares.append((a['data-share'], a.get('href'), a.get('aria-label')))
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            k = a.get('name') or a.get('property')
            if k:
                self.meta[k] = a.get('content')
        if tag == 'link' and a.get('rel') == 'canonical':
            self.canon = a.get('href')
        for attr in ('href', 'src'):
            if attr in a and tag in ('a', 'link', 'script', 'img', 'form'):
                self.links.append((tag, a[attr], a.get('rel', '')))
        if tag == 'form' and a.get('action'):
            self.links.append(('form', a['action'], ''))
        if tag == 'script' and a.get('type') == 'application/ld+json':
            self._ld = ''

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'script' and self._ld is not None:
            self.ld.append(self._ld)
            self._ld = None

    def handle_data(self, d):
        if self.in_title:
            self.title += d
        if self._ld is not None:
            self._ld += d


def url_of(rel):
    rel = '/' + rel.replace(os.sep, '/')
    return rel[:-len('index.html')] if rel.endswith('/index.html') else rel


CFG0 = json.load(open(os.path.join(HERE, 'site-config.json')))
PRIV_URL = CFG0['site'].get('privacy_url') or '/privacy/'
TERMS_URL = CFG0['site'].get('terms_url') or '/terms/'
OLD_LEGAL = {'/atlas/privacy/': PRIV_URL, '/atlas/terms/': TERMS_URL}   # redirect stubs
def _private_terms():
    raw = os.environ.get('CW_PRIVATE_TERMS', '')
    fp = os.path.join(HERE, '.private-terms')
    if not raw and os.path.exists(fp):
        raw = '|'.join(l.strip() for l in open(fp, encoding='utf-8') if l.strip() and not l.startswith('#'))
    if not raw:
        print('warning: no private terms (CW_PRIVATE_TERMS / .private-terms); forbidden-text check skipped', file=sys.stderr)
        return re.compile(r'(?!x)x')
    return re.compile(raw, re.I)


FORBIDDEN_ANY = _private_terms()
FORBIDDEN_SITE_TEXT = re.compile(r'\w+ \(EU\)|\bbased in\b|\bEU-based\b|European Union', re.I)
FORBIDDEN_COMMONWORLD_COPY = re.compile(r'\bEU\b', re.I)


def main():
    fails, pages, parsed = [], {}, {}
    for root, _, files in os.walk(DIST):
        for f in files:
            if f.endswith('.html'):
                rel = os.path.relpath(os.path.join(root, f), DIST)
                pages[url_of(rel)] = os.path.join(root, f)
    for u, fp in pages.items():
        size = os.path.getsize(fp)
        lim = MAX_INDEX if u == '/atlas/' else MAX
        if size > lim:
            fails.append(f'{u}: {size} bytes > {lim // 1024} KB')
        gz = len(gzip.compress(open(fp, 'rb').read()))
        if gz > MAX_GZ:
            fails.append(f'{u}: {gz} bytes gzipped > {MAX_GZ // 1024} KB')
        p = P(); p.feed(open(fp, encoding='utf-8').read()); parsed[u] = p
    titles, descs = Counter(), Counter()
    og_seen, og_sizes = {}, []
    jsonld_blocks = 0
    for u, new in OLD_LEGAL.items():
        if u == new:
            continue
        if u not in parsed:
            fails.append(f'missing redirect stub {u}'); continue
        p = parsed[u]; h = open(pages[u], encoding='utf-8').read()
        if 'noindex' not in (p.meta.get('robots') or ''): fails.append(f'{u}: stub not noindex')
        if p.canon != ORIGIN + new: fails.append(f'{u}: stub canonical {p.canon} != {ORIGIN + new}')
        if f'http-equiv="refresh" content="0; url={new}"' not in h: fails.append(f'{u}: stub lacks meta refresh to {new}')
    red = open(os.path.join(DIST, '_redirects')).read() if os.path.exists(os.path.join(DIST, '_redirects')) else ''
    for u, new in OLD_LEGAL.items():
        if u != new and (f'{u} {new} 301' not in red or f'{u.rstrip("/")} {new} 301' not in red):
            fails.append(f'_redirects lacks 301 for {u}')
    for u in OLD_LEGAL:
        parsed.pop(u, None); pages.pop(u, None)
    for root, _, files in os.walk(DIST):
        for f in files:
            if f.endswith(('.html', '.json', '.xml', '.txt', '.js', '.css')) or f in ('_headers', '_redirects'):
                fp = os.path.join(root, f)
                txt = open(fp, encoding='utf-8', errors='replace').read()
                m = FORBIDDEN_ANY.search(txt.replace(CFG0['contact']['general'], ''))
                if m: fails.append(f'forbidden text {m.group(0)!r} in {os.path.relpath(fp, DIST)}: …{txt[max(0, m.start() - 40):m.end() + 40]}…')
    for u in [PRIV_URL, TERMS_URL, '/atlas/about/', '/atlas/', '/404.html', '/', '/about/']:
        if u in pages:
            txt = open(pages[u], encoding='utf-8').read()
            copy = re.sub(r'<script.*?</script>|<style.*?</style>', '', txt, flags=re.S)
            m = FORBIDDEN_SITE_TEXT.search(copy)
            if m: fails.append(f'{u}: operator location wording {m.group(0)!r}')
            if u in (PRIV_URL, TERMS_URL, '/', '/about/', '/atlas/about/'):
                m = FORBIDDEN_COMMONWORLD_COPY.search(copy)
                if m: fails.append(f'{u}: Commonworld-authored copy mentions {m.group(0)!r}')
    for u, p in parsed.items():
        is404 = u == '/404.html'
        if p.lang != 'en': fails.append(f'{u}: lang={p.lang}')
        if not p.title.strip(): fails.append(f'{u}: no title')
        if not p.meta.get('description'): fails.append(f'{u}: no meta description')
        rob = p.meta.get('robots', '')
        if is404:
            if 'noindex' not in rob: fails.append('404 not noindex')
        else:
            if not rob.startswith('index,follow'): fails.append(f'{u}: robots={rob}')
            if p.canon != ORIGIN + u: fails.append(f'{u}: canonical {p.canon}')
            for k in ('og:title', 'og:description', 'og:image', 'og:url', 'twitter:card'):
                if not p.meta.get(k): fails.append(f'{u}: missing {k}')
            titles[p.title] += 1; descs[p.meta.get('description')] += 1
            # --- Open Graph image: unique per page, exists, 1200x630 PNG, small
            img = p.meta.get('og:image') or ''
            if p.meta.get('twitter:card') != 'summary_large_image': fails.append(f'{u}: twitter:card={p.meta.get("twitter:card")}')
            if p.meta.get('twitter:image') != img: fails.append(f'{u}: twitter:image != og:image')
            if (p.meta.get('og:image:width'), p.meta.get('og:image:height')) != ('1200', '630'): fails.append(f'{u}: og:image width/height')
            if not p.meta.get('og:image:alt'): fails.append(f'{u}: no og:image:alt')
            if not img.startswith(ORIGIN + '/atlas/og/'):
                fails.append(f'{u}: og:image not a per-page image: {img}')
            else:
                if img in og_seen: fails.append(f'{u}: og:image shared with {og_seen[img]}')
                og_seen[img] = u
                fp = os.path.join(DIST, img[len(ORIGIN):].split('?')[0].lstrip('/'))
                if not os.path.isfile(fp):
                    fails.append(f'{u}: og:image missing on disk {fp}')
                else:
                    head = open(fp, 'rb').read(24)
                    if head[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', head[16:24]) != (1200, 630):
                        fails.append(f'{u}: og:image is not a 1200x630 PNG')
                    sz = os.path.getsize(fp); og_sizes.append(sz)
                    if sz > MAX_OG: fails.append(f'{u}: og:image {sz} bytes > {MAX_OG // 1024} KB')
            # --- share bar: links carry the canonical URL
            need_share = SHARE_ON and (u.startswith('/atlas/platforms/') and u != '/atlas/platforms/' or u in ('/atlas/', '/', '/about/'))
            if need_share and not p.share_bars: fails.append(f'{u}: no share bar')
            for burl, btext in p.share_bars:
                if burl != p.canon: fails.append(f'{u}: share bar url {burl} != canonical')
                want_txt = {'/': 'Commonworld — A shared world for humans and agents',
                            '/about/': 'About Commonworld — A shared world for humans and agents'}.get(u, 'verified on Commonworld Atlas')
                if not btext or want_txt not in btext: fails.append(f'{u}: share text {btext!r}')
            enc = quote(p.canon or '', safe='')
            for kind, href, label in p.shares:
                if not label: fails.append(f'{u}: share button {kind} without aria-label')
                if href is None:
                    if kind not in ('copy', 'native'): fails.append(f'{u}: share {kind} without href')
                elif enc not in href and p.canon not in unquote(href):
                    fails.append(f'{u}: share link {kind} lacks canonical URL')
            types = []
            for block in p.ld:
                try:
                    obj = json.loads(block); jsonld_blocks += 1; types.append(obj.get('@type'))
                except Exception as ex:
                    fails.append(f'{u}: JSON-LD parse error {ex}')
            if 'BreadcrumbList' not in types: fails.append(f'{u}: no BreadcrumbList')
        for tag, href, rel in p.links:
            if href.startswith(('http://', 'https://')):
                if href.startswith(ORIGIN) or tag != 'a':
                    continue
                need = {'sponsored', 'nofollow'} if 'sponsored' in rel else {'nofollow', 'noopener'}
                if not need <= set(rel.split()): fails.append(f'{u}: external link without rel {need}: {href}')
                continue
            if href.startswith(('mailto:', 'data:')) or href.startswith('#') and href[1:] in p.ids:
                continue
            if href.startswith('#'):
                fails.append(f'{u}: missing anchor {href}'); continue
            path, _, frag = href.split('?', 1)[0].partition('#')
            if not path.startswith('/'):
                fails.append(f'{u}: relative link {href}'); continue
            fs = os.path.join(DIST, path.lstrip('/'))
            if path.endswith('/'):
                fs = os.path.join(fs, 'index.html')
            elif os.path.isdir(fs):
                fails.append(f'{u}: link without trailing slash {href}'); continue
            if path == '/' and not os.path.exists(fs):
                continue  # Commonworld home: owned by the main site, placeholder for now
            if not os.path.isfile(fs):
                fails.append(f'{u}: broken link {href}'); continue
            if frag and path in parsed and frag not in parsed[path].ids:
                fails.append(f'{u}: broken fragment {href}')
    idx = open(pages['/atlas/'], encoding='utf-8').read()
    grid = idx[idx.index('id="grid"'):idx.index('id="f-empty"')]
    seq = re.findall(r'<article class="cw-card[^"]*"( data-ad-card)?', grid)
    ads = [i for i, s in enumerate(seq) if s]
    want_ads = [12 * k + (k - 1) for k in range(1, len([s for s in seq if not s]) // 12 + 1)]
    if ads != want_ads: fails.append(f'native ad positions {ads[:5]} != {want_ads[:5]}')
    if 'class="cw-tagcloud"' not in idx or 'cw-tags-more' not in idx: fails.append('tag shelf missing on index')
    if 'Click tags, statuses or tabs to narrow the list. Tags combine with AND.' not in idx: fails.append('tag hint line missing')
    for k in ('cw-menu', 'cw-theme', 'aria-label="Commonworld home"'):
        if k not in idx: fails.append(f'index missing {k}')
    # --- legal pages, footer links, cross-product navigation
    CFG = json.load(open(os.path.join(HERE, 'site-config.json')))
    product = CFG['site'].get('product_url') or '/'
    if (CFG.get('legal') or {}).get('operator') != 'Commonworld':
        fails.append('site-config legal.operator must be Commonworld')
    for lp in (PRIV_URL, TERMS_URL):
        if lp not in parsed:
            fails.append(f'missing legal page {lp}'); continue
        lpp = parsed[lp]
        if not any('"WebPage"' in blk for blk in lpp.ld): fails.append(f'{lp}: no WebPage JSON-LD')
        txt = open(pages[lp], encoding='utf-8').read()
        if 'is run by <b>Commonworld</b>' not in txt:
            fails.append(f'{lp}: operator is not identified as Commonworld')
        if 'Last updated' not in txt: fails.append(f'{lp}: no Last updated')
        has_draft = 'This policy is a draft' in txt or 'legal-draft' in txt
        if CFG.get('legal_draft') and not has_draft: fails.append(f'{lp}: draft note missing')
        if not CFG.get('legal_draft') and has_draft: fails.append(f'{lp}: draft note present but legal_draft is false (final text)')
        if 'noindex' in (lpp.meta.get('robots') or ''): fails.append(f'{lp}: legal page is noindex')
        if 'Applies to Commonworld and all its sections, including the Atlas.' not in txt: fails.append(f'{lp}: scope line missing')
        if 'accounts, posts and API keys' not in txt: fails.append(f'{lp}: planned-features note missing')
        want_h1 = '<h1>Commonworld Privacy Policy</h1>' if lp == PRIV_URL else '<h1>Commonworld Terms of Use</h1>'
        if want_h1 not in txt: fails.append(f'{lp}: lacks {want_h1}')
        if lp == PRIV_URL:
            for need in (CFG['contact']['privacy'], 'data protection authority in your country of residence', 'Data Privacy Framework', 'cw-consent', 'cw-theme', 'cw-ann-dismissed', '_ga',
                         'Cloudflare, Inc.', 'Zoho', 'Standard Contractual Clauses', 'Art. 6(1)(a)', 'Art. 6(1)(f)', 'withdraw it at any time', 'Share buttons'):
                if need not in txt: fails.append(f'privacy page lacks {need!r}')
    for u, p in parsed.items():
        for tag, href, rel in p.links:
            if tag in ('script', 'img') and re.match(r'(https?:)?//', href or ''):
                fails.append(f'{u}: third-party {tag} {href} (Privacy Policy says no third-party scripts/images before consent)')
            if tag == 'link' and re.match(r'(https?:)?//', href or '') and rel not in ('canonical', 'alternate'):
                fails.append(f'{u}: third-party <link rel={rel}> {href}')
    side_re = re.compile(r'<aside class="cw-side".*?</aside>', re.S)
    for u, fp in pages.items():
        h = open(fp, encoding='utf-8').read()
        foot = h[h.find('<footer class="cw-foot"'):]
        if f'href="{PRIV_URL}">Privacy<' not in foot or f'href="{TERMS_URL}">Terms<' not in foot:
            fails.append(f'{u}: footer lacks Privacy/Terms links')
        m = side_re.search(h)
        side = m.group(0) if m else ''
        xi, di = side.find('data-xnav="Commonworld"'), side.find('>Directions<')
        if xi < 0 or di < 0 or xi > di: fails.append(f'{u}: sidebar Commonworld item not above Directions')
        elif f'href="{product}" data-xnav="Commonworld"' not in side: fails.append(f'{u}: sidebar Commonworld href != product_url')
        ai = side.find('<nav class="cw-nav cw-xsub" aria-label="About Commonworld"><a href="/about/"')
        if ai < 0 or not (xi < ai < di): fails.append(f'{u}: sidebar "About" (/about/) not right under the Commonworld item')
        if '>How the Atlas works<' not in side or 'About &amp; method' in side: fails.append(f'{u}: sidebar Atlas link is not "How the Atlas works"')
        if 'href="/about/">About Commonworld</a>' not in foot or 'href="/atlas/about/">How the Atlas works</a>' not in foot:
            fails.append(f'{u}: footer lacks About Commonworld / How the Atlas works links')
        if f'class="cw-iconbtn cw-product" href="{product}" aria-label="Commonworld home"' not in h:
            fails.append(f'{u}: home icon href != product_url {product}')
        if 'class="cw-consent"' in h and f'href="{PRIV_URL}">Privacy</a></p>' not in h:
            fails.append(f'{u}: cookie banner does not link to {PRIV_URL}')
    # --- Commonworld landing (/)
    if '/' not in parsed:
        fails.append('missing landing page / (dist/index.html)')
    else:
        lp_, lh = parsed['/'], open(pages['/'], encoding='utf-8').read()
        if lp_.canon != ORIGIN + '/': fails.append(f'/: canonical {lp_.canon} != {ORIGIN}/')
        if 'noindex' in (lp_.meta.get('robots') or ''): fails.append('/: landing is noindex')
        for need in ('<h1 id="landing-title">Commonworld</h1>', 'A shared world for humans and agents', 'The platform is coming soon.',
                     'class="cw-btn cw-btn-primary landing-cta" href="/atlas/"', 'cw-mark-light.png', 'cw-mark-dark.png', 'class="cw-consent"',
                     '<a aria-current="page" href="' + (CFG['site'].get('product_url') or '/') + '" data-xnav="Commonworld"', '"WebSite"'):
            if need not in lh: fails.append(f'/: landing lacks {need!r}')
        if (lp_.meta.get('og:image') or '').split('?')[0] != ORIGIN + '/atlas/og/page-home.png': fails.append('/: og:image is not its own page-home.png')
        if str(len(json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms'])) not in lh: fails.append('/: Atlas entry count missing')
        if CFG['site'].get('product_url', '/').rstrip('/') not in ('', ORIGIN): fails.append('site.product_url does not point to the landing')
        if (CFG['site'].get('home_url') or '/') != '/': fails.append('site.home_url != /')
    # --- About Commonworld (/about/)
    if '/about/' not in parsed:
        fails.append('missing /about/ (About Commonworld)')
    else:
        ap_, ah = parsed['/about/'], open(pages['/about/'], encoding='utf-8').read()
        main_ = ah[ah.find('<main'):ah.find('</main>')]
        if ap_.canon != ORIGIN + '/about/': fails.append(f'/about/: canonical {ap_.canon}')
        if 'noindex' in (ap_.meta.get('robots') or ''): fails.append('/about/: noindex')
        if (ap_.meta.get('og:image') or '').split('?')[0] != ORIGIN + '/atlas/og/page-cw-about.png': fails.append('/about/: og:image is not page-cw-about.png')
        n_snap = len(json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms'])
        for need in ('<h1>About Commonworld</h1>', 'A shared world for humans and agents', 'live side by side as citizens', 'work you can verify speaks louder than a CV',
                     'coming soon', 'Citizen profiles', 'Posts and discussion', 'Topics and tags', 'An API for agents', '(planned)',
                     'Money never buys inclusion, verified status or ranking', '<i>Sponsored</i>', 'sources and dates', 'Corrections welcome', 'Privacy-light by default',
                     'href="/atlas/"', 'href="/atlas/about/"', f'href="{PRIV_URL}"', f'href="{TERMS_URL}"', 'href="https://github.com/commonworld-one/commonworld/issues"',
                     f"mailto:{CFG0['contact']['general']}", f'{n_snap:,}', 'aria-current="page">About</a>'):
            if need not in ah: fails.append(f'/about/: lacks {need!r}')
        for bad in re.findall(r'sign up|signup|join now|log in|register now|available now|download the app', main_, re.I):
            fails.append(f'/about/: claims a feature that does not exist yet ({bad!r})')
        lds = [json.loads(x) for x in ap_.ld]
        abt = next((x for x in lds if x.get('@type') == 'AboutPage'), None)
        if not abt: fails.append('/about/: no AboutPage JSON-LD')
        else:
            org = abt.get('mainEntity') or {}
            if org.get('@type') != 'Organization' or org.get('name') != 'Commonworld' or org.get('url') != ORIGIN + '/':
                fails.append(f'/about/: Organization JSON-LD {org}')
            if re.search(r'address|founder|employee|"person"', json.dumps(abt), re.I): fails.append('/about/: JSON-LD carries address/person data')
        if ah.count('class="cw-share') < 1: fails.append('/about/: no share bar')
    atl_about = open(pages['/atlas/about/'], encoding='utf-8').read()
    xr = atl_about.find('class="about-xref"')
    if xr < 0 or 'href="/about/">Read about Commonworld</a>' not in atl_about[xr:xr + 400] or xr > atl_about.find('<h1>'):
        fails.append('/atlas/about/: no top line linking /about/')
    about = atl_about
    for need in ('<h1>How the Atlas works</h1>', 'open, source-checked catalog', 'downloadable JSON', 'coordinating agent', 'written protocol',
                 'not confirmed; they are labelled as such', 'We plan to re-check the whole catalog weekly', '15 Oct 2026 census', 'Money never buys a place'):
        if need not in about: fails.append(f'about page lacks {need!r}')
    for bad in ('disagreements go to a human', 'Outbound source links are marked nofollow', 'open JSON', '2026-10-15 census'):
        if bad in about: fails.append(f'about page still has {bad!r}')
    if CFG['contact']['general'] not in about: fails.append('about page lacks contact.general')
    _pv = open(pages[PRIV_URL], encoding='utf-8').read()
    if CFG['contact']['general'] != CFG['contact']['privacy'] and CFG['contact']['general'] in _pv: fails.append('privacy page shows contact.general; privacy page must use contact.privacy only')
    # share bar sits in the platform header (entry-head), once
    for u, p in parsed.items():
        if u.startswith('/atlas/platforms/') and u != '/atlas/platforms/' and SHARE_ON:
            h = open(pages[u], encoding='utf-8').read()
            head = h[h.find('<header class="entry-head"'):h.find('</header>', h.find('<header class="entry-head"'))]
            if 'cw-share cw-share-head' not in head: fails.append(f'{u}: share bar not in header')
            if len(p.share_bars) != 1: fails.append(f'{u}: {len(p.share_bars)} share bars')
    fails += [f'duplicate title x{n}: {t}' for t, n in titles.items() if n > 1]
    fails += [f'duplicate description x{n}: {d[:60]}' for d, n in descs.items() if n > 1]
    sm_path = os.path.join(DIST, 'atlas', 'sitemap.xml')
    sm_root = os.path.join(DIST, 'sitemap.xml')
    locs = {el.text for el in ET.parse(sm_path).getroot().iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')}
    root_locs = {el.text for el in ET.parse(sm_root).getroot().iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')} if os.path.exists(sm_root) else set()
    if any(not l.startswith(ORIGIN + '/atlas/') for l in locs): fails.append('atlas sitemap lists URLs outside /atlas/')
    for old in OLD_LEGAL:
        if ORIGIN + old in locs | root_locs: fails.append(f'sitemap still lists old {old}')
    locs |= root_locs
    want = {ORIGIN + u for u in parsed if u != '/404.html'}
    if locs != want:
        fails.append(f'sitemap mismatch: missing {sorted(want - locs)[:5]} extra {sorted(locs - want)[:5]}')
    nolm = sum(1 for el in ET.parse(sm_path).getroot() if el.find('{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod') is None)
    robots = open(os.path.join(DIST, 'robots.txt')).read()
    if f'Sitemap: {ORIGIN}/atlas/sitemap.xml' not in robots: fails.append('robots.txt lacks sitemap')
    if f'Sitemap: {ORIGIN}/sitemap.xml' not in robots: fails.append('robots.txt lacks the site-level sitemap')
    try:
        json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))
    except Exception as ex:
        fails.append(f'snapshot.json: {ex}')
    biggest = max(pages, key=lambda u: os.path.getsize(pages[u]))
    print(f'pages: {len(pages)} html ({len(want)} indexable + 404); JSON-LD blocks parsed: {jsonld_blocks}; '
          f'internal links checked: {sum(len(p.links) for p in parsed.values())}; sitemap URLs: {len(locs)} ({nolm} without lastmod); '
          f'largest page: {biggest} {os.path.getsize(pages[biggest]) // 1024} KB ({len(gzip.compress(open(pages[biggest], "rb").read())) // 1024} KB gzipped); '
          f'native ad cards on index: {len(ads)}; OG images: {len(og_sizes)} unique, '
          f'max {max(og_sizes, default=0) // 1024} KB, avg {sum(og_sizes) // max(len(og_sizes), 1) // 1024} KB, total {sum(og_sizes) // 1024} KB; '
          f'share buttons: {sum(len(p.shares) for p in parsed.values())} on {sum(1 for p in parsed.values() if p.share_bars)} pages')
    if fails:
        print(f'FAIL ({len(fails)}):'); [print('  -', f) for f in fails[:80]]
        sys.exit(1)
    print('ALL CHECKS PASSED')


if __name__ == '__main__':
    main()
