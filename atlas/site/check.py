#!/usr/bin/env python3
"""Static checks for the built Atlas (stdlib only). Exit code 1 on any failure.

    python3 atlas/site/check.py

Checks: every internal link/asset resolves (incl. #fragments), trailing-slash consistency, every page has
lang=en, <title>, meta description, canonical (= its own clean URL), robots meta, JSON-LD that parses
(+ BreadcrumbList), unique titles/descriptions, external links carry rel nofollow+noopener (sponsored links
rel sponsored), sitemap lists exactly the indexable pages, robots.txt references the sitemap, 404 is noindex,
no page over 150 KB raw (catalog index: 320 KB, it server-renders every card) and none over 60 KB gzipped.
Open Graph: every indexable page has its own og:image (/atlas/og/<name>.png, exists, 1200x630 PNG, <= 100 KB),
width/height/alt, twitter:card=summary_large_image, twitter:image = og:image, twitter:site = @commonworldone.
Official channels: every page's footer shows X + GitHub (icon + label, rel="me noopener"); landing and llms.txt/llms-full.txt carry an
"Official channels" line; landing and /about/ Organization JSON-LD sameAs = [X, GitHub org]. Share bars: every platform page (and the
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
Growth guard: the sitemap URL set may only grow against atlas/data/sitemap-urls.txt (a removed URL fails unless atlas/data/redirects.json
maps it to a published page, emitted as a 301 in _redirects); every slug of the committed snapshot must still exist.
`--update-baseline` adds new URLs to the baseline (never removes any).
Also: native ad cards sit after every 12th card, the tag shelf exists with its expander, every card links to its page.
"""
import gzip, json, os, re, struct, sys, xml.etree.ElementTree as ET
from urllib.parse import quote, unquote
from html.parser import HTMLParser
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, 'dist')
ORIGIN = json.load(open(os.path.join(HERE, 'site-config.json')))['site']['origin'].rstrip('/')
X_HANDLE, X_URL = '@commonworldone', 'https://x.com/commonworldone'  # official X account: twitter:site on every page, footer, sameAs
REPO_URL, GITHUB_ORG_URL = 'https://github.com/commonworld-one/commonworld', 'https://github.com/commonworld-one'
OFFICIAL_URLS = {X_URL, REPO_URL}  # own accounts: linked with rel="me noopener" (no nofollow)
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


# --- growth guard: published URLs and slugs may only grow (pages are never deleted; moves need an explicit 301)
DATA_DIR = os.path.normpath(os.path.join(HERE, '..', 'data'))
BASELINE = os.path.join(DATA_DIR, 'sitemap-urls.txt')
REDIRECTS = os.path.join(DATA_DIR, 'redirects.json')


def load_redirects():
    """atlas/data/redirects.json: {"redirects": {"/old/path/": "/new/path/"}} -> dict (paths, emitted by build.py into _redirects as 301s)."""
    if not os.path.exists(REDIRECTS):
        return {}
    return {k: v for k, v in (json.load(open(REDIRECTS)).get('redirects') or {}).items()}


def _git_snapshot_slugs():
    """Slugs of every committed snapshot-verified-*.json at HEAD (and HEAD^1 on a merge commit, i.e. the PR base)."""
    import subprocess
    slugs, revs = set(), ['HEAD']
    try:
        par = subprocess.run(['git', 'rev-list', '--parents', '-n', '1', 'HEAD'], cwd=HERE, capture_output=True, text=True, check=True).stdout.split()
        if len(par) > 2:
            revs.append('HEAD^1')
        for rev in revs:
            names = subprocess.run(['git', 'ls-tree', '--name-only', rev, 'atlas/data/'], cwd=os.path.join(HERE, '..', '..'),
                                   capture_output=True, text=True, check=True).stdout.split()
            for n in names:
                if re.search(r'snapshot-verified-.*\.json$', n):
                    raw = subprocess.run(['git', 'show', f'{rev}:{n}'], cwd=os.path.join(HERE, '..', '..'), capture_output=True, text=True, check=True).stdout
                    slugs |= {c['slug'] for c in json.loads(raw).get('platforms', [])}
    except Exception as ex:  # not a git checkout: the sitemap baseline still guards every platform page
        print(f'note: previous-snapshot slug check skipped ({ex.__class__.__name__})', file=sys.stderr)
    return slugs


def growth_guard(locs, update=False):
    fails = []
    red = load_redirects()
    redfile = open(os.path.join(DIST, '_redirects')).read() if os.path.exists(os.path.join(DIST, '_redirects')) else ''
    for old, new in red.items():
        if f'{old} {new} 301' not in redfile: fails.append(f'_redirects lacks 301 {old} -> {new} from atlas/data/redirects.json')
        if ORIGIN + new not in locs: fails.append(f'redirect target {new} (for {old}) is not a published page')
    base = {l.strip() for l in open(BASELINE) if l.strip() and not l.startswith('#')} if os.path.exists(BASELINE) else set()
    if not base:
        fails.append(f'missing URL baseline {os.path.relpath(BASELINE, HERE)} (run check.py --update-baseline once)')
    removed = sorted(u for u in base - locs if u[len(ORIGIN):] not in red)
    if removed:
        fails.append(f'{len(removed)} published URL(s) disappeared from the sitemap (pages are never removed; add a 301 in atlas/data/redirects.json if moved): {removed[:10]}')
    cur = {c['slug'] for c in json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms']}
    gone = sorted(s for s in _git_snapshot_slugs() - cur if f'/atlas/platforms/{s}/' not in red)
    if gone:
        fails.append(f'slug(s) of the previous committed snapshot missing now: {gone[:10]}')
    added = len(locs - base)
    print(f'growth guard: baseline {len(base)} URLs, now {len(locs)} (+{added}, removed {len(removed)}), redirects {len(red)}')
    if update and not fails and added:
        with open(BASELINE, 'w') as f:
            f.write('# Published URL baseline for check.py: the sitemap may only grow (removals need atlas/data/redirects.json).\n')
            f.write(''.join(u + '\n' for u in sorted(base | locs)))
        print(f'baseline updated: {len(base | locs)} URLs')
    return fails


SVG_NS = '{http://www.w3.org/2000/svg}'


def badge_checks(parsed, pages, locs):
    """Status badges: both SVGs per card (valid XML, <title>, no script/links/external refs), the card page block,
    /atlas/badge/ page in sitemap + llms.txt, per-entry JSON badge URLs, _headers rule."""
    fails = []
    snap = json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms']
    slugs = {c['slug'] for c in snap}
    bdir = os.path.join(DIST, 'atlas', 'badge')
    clash = sorted(s for s in slugs if s + '-dark' in slugs)
    if clash: fails.append(f'badge file name clash (<slug>-dark is another slug): {clash}')
    n_ok = 0
    for c in snap:
        slug = c['slug']
        for fn in (f'{slug}.svg', f'{slug}-dark.svg'):
            fp = os.path.join(bdir, fn)
            if not os.path.isfile(fp):
                fails.append(f'missing badge /atlas/badge/{fn}'); continue
            raw = open(fp, encoding='utf-8').read()
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as ex:
                fails.append(f'badge {fn}: invalid XML ({ex})'); continue
            if root.tag != SVG_NS + 'svg': fails.append(f'badge {fn}: root is {root.tag}')
            t = root.find(SVG_NS + 'title')
            if t is None or not (t.text or '').startswith('Commonworld Atlas: '): fails.append(f'badge {fn}: no <title>')
            if root.get('role') != 'img' or not root.get('aria-label'): fails.append(f'badge {fn}: no role=img/aria-label')
            want = {'closed': 'Closed · history'}.get(c.get('status'))
            if want and t is not None and not (t.text or '').endswith(want): fails.append(f'badge {fn}: closed card shows {t.text!r}')
            if c.get('status') == 'live' and t is not None and not re.search(r': (Verified · \d{4}-\d{2}-\d{2}|Listed)$', t.text or ''):
                fails.append(f'badge {fn}: live card shows {t.text!r}')
            bad = [el.tag for el in root.iter() if el.tag.split('}')[-1] in ('script', 'foreignObject', 'image', 'use', 'a', 'style', 'iframe')]
            if bad: fails.append(f'badge {fn}: forbidden elements {bad}')
            for el in root.iter():
                for k, v in el.attrib.items():
                    if k.split('}')[-1] == 'href' or k.lower().startswith('on') or re.search(r'url\((?!#)|https?:|//|javascript:', v):
                        fails.append(f'badge {fn}: external/active attribute {k}={v[:60]!r}')
            if re.search(r'<script|@import|https?://(?!www\.w3\.org/2000/svg")', raw, re.I): fails.append(f'badge {fn}: script or external reference')
            if len(raw) > 4096: fails.append(f'badge {fn}: {len(raw)} bytes > 4 KB')
            n_ok += 1
        u = f'/atlas/platforms/{slug}/'
        if u in pages:
            h = open(pages[u], encoding='utf-8').read()
            for need in ('id="badge"', '>Add this badge to your site<', 'Free. Never sold. Updates itself with every weekly check.',
                         f'src="/atlas/badge/{slug}.svg"', f'src="/atlas/badge/{slug}-dark.svg"',
                         f'&lt;a href=&quot;{ORIGIN}/atlas/platforms/{slug}/&quot;&gt;&lt;img src=&quot;{ORIGIN}/atlas/badge/{slug}.svg&quot; alt=&quot;Commonworld Atlas: ',
                         f']({ORIGIN}/atlas/badge/{slug}.svg)]({ORIGIN}/atlas/platforms/{slug}/)', 'href="/atlas/badge/"'):
                if need not in h: fails.append(f'{u}: badge block lacks {need[:70]!r}')
        else:
            fails.append(f'card page missing for badge {slug}')
        jp = os.path.join(DIST, 'atlas', 'platforms', f'{slug}.json')
        if os.path.isfile(jp):
            j = json.load(open(jp, encoding='utf-8'))
            if j.get('badge_svg') != f'{ORIGIN}/atlas/badge/{slug}.svg' or j.get('badge_svg_dark') != f'{ORIGIN}/atlas/badge/{slug}-dark.svg' \
                    or j.get('badge_page') != f'{ORIGIN}/atlas/badge/':
                fails.append(f'{slug}.json: badge_svg/badge_svg_dark/badge_page wrong or missing')
    extra = sorted(f for f in os.listdir(bdir) if f.endswith('.svg') and f[:-4].removesuffix('-dark') not in slugs) if os.path.isdir(bdir) else []
    if extra: fails.append(f'badge files without a card: {extra[:5]}')
    if '/atlas/badge/' not in parsed: fails.append('missing /atlas/badge/ page')
    else:
        bh = open(pages['/atlas/badge/'], encoding='utf-8').read()
        for need in ('<h1>Commonworld Atlas badges</h1>', 'Cannot be bought', 'Does not affect ranking or inclusion', 'No tracking', 'Verified · date',
                     '>Listed<', 'Closed · history', '-dark.svg', 'href="/atlas/about/#corrections"', 'the-spawn'):
            if need not in bh: fails.append(f'/atlas/badge/: lacks {need!r}')
    if ORIGIN + '/atlas/badge/' not in locs: fails.append('/atlas/badge/ not in sitemap')
    for f_ in ('llms.txt', 'llms-full.txt'):
        if ORIGIN + '/atlas/badge/' not in open(os.path.join(DIST, f_), encoding='utf-8').read(): fails.append(f'/{f_}: no /atlas/badge/ link')
    if 'href="/atlas/badge/"' not in open(pages['/atlas/about/'], encoding='utf-8').read(): fails.append('/atlas/about/ does not link /atlas/badge/')
    hd = open(os.path.join(DIST, '_headers')).read()
    if '/atlas/badge/*.svg\n  Cache-Control: public, max-age=3600\n  Access-Control-Allow-Origin: *\n  Content-Type: image/svg+xml' not in hd:
        fails.append('_headers lacks the /atlas/badge/*.svg rule')
    print(f'badges: {n_ok} SVG files checked for {len(snap)} cards')
    return fails


REFRESH_TOOL = 'atlas/refresh.py'


def api_checks(parsed, locs):
    """Static API v1 (/api/v1/): every JSON file in dist parses; every path promised by openapi.json exists; every API data
    document validates against its JSON Schema and equals its legacy /atlas/*.json twin (+ schema_version); counts agree
    across old and new endpoints; CORS/content-type headers; docs page /atlas/api/ is linked from footer, About, llms files, README, sitemap."""
    sys.path.insert(0, HERE)
    import api_v1
    fails = []
    V = os.path.join(DIST, 'api', 'v1')
    if not os.path.isdir(V):
        return ['api: dist/api/v1 missing']
    docs = {}
    for root, _, files in os.walk(DIST):
        for fn in files:
            if fn.endswith('.json'):
                fp = os.path.join(root, fn)
                try:
                    obj = json.load(open(fp, encoding='utf-8'))
                except Exception as ex:
                    fails.append(f'invalid JSON {os.path.relpath(fp, DIST)}: {ex}'); continue
                rel = '/' + os.path.relpath(fp, DIST).replace(os.sep, '/')
                if rel.startswith('/api/v1/'):
                    docs[rel[len('/api/v1'):]] = obj
    spec = docs.get('/openapi.json') or {}
    if not str(spec.get('openapi', '')).startswith('3.1'): fails.append('api: openapi.json is not OpenAPI 3.1')
    if spec.get('info', {}).get('version') != api_v1.SCHEMA_VERSION: fails.append('api: openapi info.version != schema_version')
    legacy_list = json.load(open(os.path.join(DIST, 'atlas', 'platforms.json')))
    ids = [r['id'] for r in legacy_list['platforms']]
    cats = [r['id'] for r in (docs.get('/atlas/index.json') or {}).get('categories', [])]
    for p in api_v1.expand_paths(spec, ids, cats) if spec else []:
        if p not in docs: fails.append(f'api: openapi path {p} not in dist')
    for p, op in (spec.get('paths') or {}).items():
        for code, r in op['get']['responses'].items():
            ref = (((r.get('content') or {}).get('application/json') or {}).get('schema') or {}).get('$ref')
            if ref and ref.lstrip('./').replace('schemas/', '/schemas/', 1) not in docs and '/' + ref.lstrip('./') not in docs:
                fails.append(f'api: {p} {code} references missing schema {ref}')
    reg = {k[len('/schemas/'):]: v for k, v in docs.items() if k.startswith('/schemas/')}
    for name, sch in reg.items():
        if sch.get('$schema') != 'https://json-schema.org/draft/2020-12/schema': fails.append(f'api: {name} not JSON Schema 2020-12')
        if sch.get('$id') != f"{ORIGIN}/api/v1/schemas/{name}": fails.append(f'api: {name} $id wrong')
    n_valid = 0
    for p, obj in docs.items():
        if not obj or not isinstance(obj, dict) or 'schema' not in obj or p.startswith('/schemas/'):
            continue
        sch = obj['schema'].rsplit('/', 1)[-1]
        if sch not in reg:
            fails.append(f'api: {p} names unknown schema {obj["schema"]}'); continue
        if obj.get('schema_version') != api_v1.SCHEMA_VERSION: fails.append(f'api: {p} schema_version {obj.get("schema_version")}')
        errs = api_v1.validate(obj, reg[sch], reg, sch, limit=5)
        n_valid += 1
        if errs: fails.append(f'api: {p} fails {sch}: {errs[:3]}')
        twin = os.path.join(DIST, p.lstrip('/'))
        if not os.path.isfile(twin):
            fails.append(f'api: {p} has no legacy twin'); continue
        old = json.load(open(twin, encoding='utf-8'))
        if {k: v for k, v in obj.items() if k not in ('schema_version', 'schema')} != old:
            fails.append(f'api: {p} drifted from legacy {p}')
    want = {'/atlas/platforms.json', '/atlas/earn.json'} | {f'/atlas/platforms/{i}.json' for i in ids} | {f'/atlas/categories/{k}.json' for k in cats}
    missing = [p for p in want if p not in docs]
    if missing: fails.append(f'api: data documents missing: {sorted(missing)[:5]}')
    if n_valid != len(want): fails.append(f'api: validated {n_valid} data documents, expected {len(want)}')
    # counts equal across old and new endpoints
    ai, root = docs.get('/atlas/index.json') or {}, docs.get('/index.json') or {}
    n = len(ids)
    new_list = docs.get('/atlas/platforms.json') or {}
    snap_n = len(json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms'])
    counts = {'legacy platforms.json count': legacy_list['count'], 'api platforms.json count': new_list.get('count'), 'api platforms.json items': len(new_list.get('platforms', [])),
              'api atlas/index counts.platforms': (ai.get('counts') or {}).get('platforms'), 'api index modules.atlas.count': ((root.get('modules') or {}).get('atlas') or {}).get('count'),
              'sum of api categories': sum(c['count'] for c in ai.get('categories', [])), 'snapshot.json': snap_n,
              'legacy per-entry files': len([f for f in os.listdir(os.path.join(DIST, 'atlas', 'platforms')) if f.endswith('.json')]),
              'api per-entry files': len([f for f in os.listdir(os.path.join(V, 'atlas', 'platforms')) if f.endswith('.json')])}
    bad = {k: v for k, v in counts.items() if v != n}
    if bad: fails.append(f'api: counts differ from {n}: {bad}')
    for k in cats:
        c_old = json.load(open(os.path.join(DIST, 'atlas', 'categories', f'{k}.json')))['count']
        c_idx = next(c['count'] for c in ai['categories'] if c['id'] == k)
        if not c_old == c_idx == (docs.get(f'/atlas/categories/{k}.json') or {}).get('count'): fails.append(f'api: category {k} counts differ')
    if (ai.get('counts') or {}).get('earn_rows') != (docs.get('/atlas/earn.json') or {}).get('count'): fails.append('api: earn row counts differ')
    if root.get('schema_version') != api_v1.SCHEMA_VERSION or root.get('version') != 'v1': fails.append('api: index.json version/schema_version')
    if not re.match(api_v1.UTC_PATTERN, str(root.get('generated_at'))): fails.append('api: index.json generated_at not ISO UTC')
    for k in ('openapi', 'docs', 'llms_txt', 'license', 'github_mirror', 'changelog'):
        if not (root.get('links') or {}).get(k): fails.append(f'api: index.json links.{k} missing')
    if not os.path.isfile(os.path.join(V, 'CHANGELOG.md')): fails.append('api: CHANGELOG.md missing')
    # headers
    hd = open(os.path.join(DIST, '_headers')).read()
    if not re.search(r'^/api/\*\n  Access-Control-Allow-Origin: \*$', hd, re.M): fails.append('_headers: /api/* lacks CORS *')
    # no forced Content-Type on /api/v1/*.json: Cloudflare serves .json as application/json by itself, and a forced header would
    # also label the HTML 404 page of a wrong ID as JSON
    if re.search(r'^/api/v1/\*\.json$', hd, re.M): fails.append('_headers: do not force Content-Type on /api/v1/*.json (404 pages are HTML)')
    # docs page + links to it
    D = '/atlas/api/'
    if D not in parsed: fails.append('api: docs page /atlas/api/ missing')
    if ORIGIN + D not in locs: fails.append('api: /atlas/api/ not in sitemap')
    for u, p in parsed.items():
        if u != '/404.html' and D not in [h for t, h, r in p.links]: fails.append(f'{u}: footer lacks link to {D}'); break
    if '/api/v1/index.json' not in [h for t, h, r in parsed.get('/atlas/about/', P()).links]: fails.append('/atlas/about/: no link to /api/v1/')
    for f in ('llms.txt', 'llms-full.txt'):
        if ORIGIN + D not in open(os.path.join(DIST, f), encoding='utf-8').read(): fails.append(f'{f}: no link to {D}')
    readme = os.path.normpath(os.path.join(HERE, '..', '..', 'README.md'))
    if os.path.exists(readme) and ORIGIN + D not in open(readme, encoding='utf-8').read(): fails.append(f'README.md: no link to {D}')
    print(f'api: {len(docs)} JSON files under /api/v1, {n_valid} data documents schema-valid and equal to their legacy twins, '
          f'{len(api_v1.expand_paths(spec, ids, cats)) if spec else 0} OpenAPI paths resolved')
    return fails


def closure_checks(pages):
    """Closure wording matches atlas/refresh.py: two routes (human review / automated weekly check), auto-closed cards labelled."""
    fails = []
    ch = open(pages['/atlas/closed/'], encoding='utf-8').read()
    for need in ('Human review:', 'Automated weekly check:', '2 consecutive weekly checks', 'reopen automatically if the site answers again',
                 'never reopened automatically', 'A single failed page load is never treated as proof.'):
        if need not in ch: fails.append(f'/atlas/closed/: lacks {need!r}')
    ab = open(pages['/atlas/about/'], encoding='utf-8').read()
    for need in ('id="closures"', 'Automated weekly check', 'Human review', 'A single failed page load is never treated as proof'):
        if need not in ab: fails.append(f'/atlas/about/: closure section lacks {need!r}')
    if 'a failed page load alone is never treated as proof' in ch: fails.append('/atlas/closed/: old one-route closure wording')
    for c in json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms']:
        hist = c.get('status_history') or []
        auto = c.get('status') == 'closed' and hist and hist[-1].get('to') == 'closed' and hist[-1].get('by') == REFRESH_TOOL
        h = open(pages[f"/atlas/platforms/{c['slug']}/"], encoding='utf-8').read()
        if auto and '<b>Closed by automated check since' not in h: fails.append(f"{c['slug']}: auto-closed card lacks 'Closed by automated check since'")
        if not auto and 'Closed by automated check' in h and c.get('status') == 'closed': fails.append(f"{c['slug']}: human-closed card labelled automated")
        if auto and f"Closed by automated check since" not in ch: fails.append(f"/atlas/closed/: {c['slug']} lacks the automated-check note")
    return fails


def _share_expectations():
    """Expected share text per entry page, by badge status (verified / listed / closed), and the live count for the index."""
    snap = json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms']
    exp = {}
    for c in snap:
        if c.get('status') == 'closed':
            t = f"{c['name']} (closed) — history on Commonworld Atlas"
        elif c.get('verdict') == 'include_verified':
            t = f"{c['name']} — verified on Commonworld Atlas"
        else:
            t = f"{c['name']} on Commonworld Atlas"
        exp[f"/atlas/platforms/{c['slug']}/"] = t
    return sum(1 for c in snap if c.get('status') == 'live'), exp


def main():
    global SHARE_LIVE, SHARE_ENTRY
    SHARE_LIVE, SHARE_ENTRY = _share_expectations()
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
            if f.endswith(('.html', '.json', '.xml', '.txt', '.js', '.css', '.svg')) or f in ('_headers', '_redirects'):
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
            if p.meta.get('twitter:site') != X_HANDLE: fails.append(f'{u}: twitter:site={p.meta.get("twitter:site")} != {X_HANDLE}')
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
                            '/about/': 'About Commonworld — A shared world for humans and agents',
                            '/atlas/': f'Atlas of Agent Platforms: {SHARE_LIVE} places where AI agents work and get paid',
                            '/atlas/earn/': 'Where AI agents get paid — Commonworld Atlas'}.get(u) or SHARE_ENTRY.get(u)
                if not btext or btext != want_txt: fails.append(f'{u}: share text {btext!r} != {want_txt!r}')
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
                if href in OFFICIAL_URLS and 'me' in rel.split():
                    if 'noopener' not in rel.split(): fails.append(f'{u}: official link without noopener: {href}')
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
        for url_, lab_ in ((X_URL, 'X'), (REPO_URL, 'GitHub')):
            if not re.search(rf'<a class="cw-foot-official" href="{re.escape(url_)}" rel="me noopener"><svg[^>]*>.*?</svg><span>{lab_}</span></a>', foot):
                fails.append(f'{u}: footer lacks official {lab_} link (icon + label, rel="me noopener")')
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
                     'class="cw-btn cw-btn-primary landing-cta" href="/atlas/"', 'cw-mark-light.png', 'cw-mark-dark.png', 'class="cw-consent"', 'Official channels:', f'href="{X_URL}" rel="me noopener"',
                     '<a aria-current="page" href="' + (CFG['site'].get('product_url') or '/') + '" data-xnav="Commonworld"', '"WebSite"'):
            if need not in lh: fails.append(f'/: landing lacks {need!r}')
        if (lp_.meta.get('og:image') or '').split('?')[0] != ORIGIN + '/atlas/og/page-home.png': fails.append('/: og:image is not its own page-home.png')
        if str(len(json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))['platforms'])) not in lh: fails.append('/: Atlas entry count missing')
        if CFG['site'].get('product_url', '/').rstrip('/') not in ('', ORIGIN): fails.append('site.product_url does not point to the landing')
        if (CFG['site'].get('home_url') or '/') != '/': fails.append('site.home_url != /')
        if f'"@type":"Organization","name":"Commonworld","url":"{ORIGIN}/","sameAs":["{X_URL}","{GITHUB_ORG_URL}"]' not in lh:
            fails.append('/: no Organization JSON-LD with sameAs [X, GitHub]')
    for f_ in ('llms.txt', 'llms-full.txt'):
        fp_ = os.path.join(DIST, f_)
        if os.path.exists(fp_) and f'Official channels: site {ORIGIN}/ · X {X_URL} ({X_HANDLE}) · GitHub {REPO_URL}' not in open(fp_, encoding='utf-8').read():
            fails.append(f'/{f_}: lacks the Official channels line')
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
            if org.get('sameAs') != [X_URL, GITHUB_ORG_URL]: fails.append(f'/about/: Organization sameAs {org.get("sameAs")}')
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
    fails += growth_guard(locs, update='--update-baseline' in sys.argv)
    try:
        json.load(open(os.path.join(DIST, 'atlas', 'data', 'snapshot.json')))
    except Exception as ex:
        fails.append(f'snapshot.json: {ex}')
    # machine-readable files: timestamps are ISO 8601 UTC, money-flow items carry a basis
    for root, _, files in [w for d in ('atlas', 'api') for w in os.walk(os.path.join(DIST, d))]:
        for fn in files:
            if fn.endswith('.json'):
                raw = open(os.path.join(root, fn), encoding='utf-8').read()
                if re.search(r'"(observed_at|verified_at|last_checked|generated_at)":\s*"(?!\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z")[^"]', raw):
                    fails.append(f'{fn}: timestamp not ISO 8601 UTC')
    for r in json.load(open(os.path.join(DIST, 'atlas', 'platforms.json')))['platforms']:
        if any('basis' not in f for f in r.get('money_flow') or []):
            fails.append(f"platforms.json {r['id']}: money_flow item without basis")
    fails += badge_checks(parsed, pages, locs)
    fails += api_checks(parsed, locs)
    fails += closure_checks(pages)
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
