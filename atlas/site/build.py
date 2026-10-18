#!/usr/bin/env python3
"""Commonworld Atlas static site generator. Python 3.9+ standard library only.

    python3 atlas/site/build.py                 # reads atlas/data/snapshot-verified-2026-10-15.json
    python3 atlas/site/build.py --data X.json --out DIR

Output (default atlas/site/dist/) is a plain static tree with clean URLs as directories:
  /atlas/index.html, /atlas/platforms/, /atlas/platforms/<slug>/, /atlas/categories/, /atlas/categories/<cat>/,
  /atlas/closed/, /atlas/earn/ (+ /atlas/earn.json), /atlas/about/, /atlas/decisions/ (+ index.md, /atlas/decisions.json), /atlas/badge/ (+ /atlas/badge/<slug>.svg, <slug>-dark.svg), /atlas/data/snapshot.json, /atlas/platforms.json (+ /atlas/platforms/<slug>.json), /atlas/llms.txt, /atlas/sitemap.xml, /atlas/assets/*,
  /privacy/, /terms/ (site-wide Commonworld legal pages; /atlas/privacy|terms/ are noindex redirect stubs + _redirects 301s),
  / (Commonworld landing), /404.html, /robots.txt, /llms.txt, /llms-full.txt, /sitemap.xml, /_headers, /_redirects
  /api/v1/ (static API: index.json, openapi.json, changelog, schemas/, atlas/{index,platforms,earn}.json, atlas/platforms|categories/<id>.json; docs /atlas/api/)
It deploys unchanged to Cloudflare Pages / Workers static assets.
"""
import argparse, base64, hashlib, html, json, os, re, shutil, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'components'))
import cw_components as cw  # noqa: E402
sys.path.insert(0, HERE)
import og_images as ogi  # noqa: E402  (Pillow optional: per-page OG images)
import badges  # noqa: E402  (status badges: /atlas/badge/<slug>.svg)
import api_v1  # noqa: E402  (static API v1: /api/v1/, schemas, OpenAPI)
import screens  # noqa: E402  (homepage screenshots from the orphan branch atlas-screens)

e = cw.e
DEFAULT_DATA = os.path.normpath(os.path.join(HERE, '..', 'data', 'snapshot-verified-2026-10-15.json'))

CATEGORIES = [  # key, long name (catalog draft wording), short name, color, description
    ('social', 'Social & forums', 'Social', '#e75b3d', 'Forums, feeds and social networks where AI agents post, talk and vote, often alongside humans.'),
    ('worlds', 'Worlds & games', 'Worlds', '#d2a393', 'Persistent virtual worlds, games and simulations inhabited by agents.'),
    ('work', 'Work & bounties', 'Work', '#63705b', 'Marketplaces, bounty boards and job boards where agents take tasks, deliver work and get paid.'),
    ('payments', 'Payments & x402', 'Payments', '#b6793e', 'Payment rails, wallets and paid APIs that let agents pay and get paid (x402, Lightning, stablecoins).'),
    ('research', 'Science & research', 'Research', '#5278a8', 'Venues where agents publish, review or run research: preprint servers, journals, labs.'),
    ('verification', 'Verification', 'Verification', '#48a671', 'Identity, signing and evidence services that make agent activity checkable.'),
    ('arenas', 'Arenas & benchmarks', 'Arenas', '#8a6fb0', 'Competitions, games, benchmarks and leaderboards where agents compete.'),
    ('registries', 'Registries & directories', 'Registries', '#aab8a0', 'Directories, registries and explorers that list agents, skills and MCP servers.'),
    ('wiki', 'Wikis', 'Wiki', '#c2a14a', 'Wikis and knowledge bases written by or for agents.'),
    ('projects', 'Projects (repos & frameworks)', 'Projects', '#5f9ea0', 'Open-source projects, frameworks, facilitators, APIs and data services of the agent economy: things built with, rather than places agents gather.'),
]
CAT_LABEL = {k: l for k, l, _, _, _ in CATEGORIES}
CAT_SHORT = {k: s for k, _, s, _, _ in CATEGORIES}
CAT_COLOR = {k: c for k, _, _, c, _ in CATEGORIES}
CAT_DESC = {k: d for k, _, _, _, d in CATEGORIES}
TAGS_FILE = os.path.normpath(os.path.join(HERE, '..', 'data', 'census-tags-2026-10-15.json'))
TYPE_LABEL = {'platform': 'Platform', 'tool_catalog': 'Tool catalog', 'protocol': 'Protocol', 'project': 'Project'}
KIND_LABEL = {'canonical_url': 'Official URL', 'site_reachable': 'Site reachability', 'description': 'What it is',
              'recent_activity': 'Recent activity', 'metric': 'Metric', 'economic_flow': 'Money flow',
              'announced_closed': 'Closure', 'operator': 'Operator', 'ownership': 'Ownership', 'launch': 'Launch'}
KIND_ORDER = ['announced_closed', 'canonical_url', 'description', 'recent_activity', 'economic_flow', 'metric']
BASIS_LABEL = {'direct_observation': 'Observed directly', 'operator_claim': 'Operator claim',
               'independent_source': 'Independent source', 'inference': 'Inference'}
OUTCOME_LABEL = {'supported': 'Supported', 'contradicted': 'Contradicted', 'unchecked': 'Not checked',
                 'inaccessible': 'Source inaccessible', 'needs_browser': 'Needs browser check'}
OUTCOME_TONE = {'supported': 'ok', 'contradicted': 'bad', 'unchecked': 'warn', 'inaccessible': 'warn', 'needs_browser': 'warn'}
QA_LABEL = {'agree': 'QA agrees', 'disagree': 'QA disagrees', 'cannot_recheck': 'QA could not re-check'}


# ---------------------------------------------------------------- helpers
def parse_time(v):
    """a local time string with a zone abbreviation and '(UTC+HH:MM)' offset, or ISO 'YYYY-MM-DDTHH:MM(:SS)Z' -> aware UTC datetime."""
    if not isinstance(v, str) or not v:
        return None
    m = re.search(r'(\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2}) (AM|PM)[^(]*\(UTC([+-])(\d{2}):(\d{2})\)', v)
    if m:
        h = int(m[2]) % 12 + (12 if m[4] == 'PM' else 0)
        off = timedelta(hours=int(m[6]), minutes=int(m[7])) * (1 if m[5] == '+' else -1)
        return datetime.strptime(f'{m[1]} {h}:{m[3]}', '%Y-%m-%d %H:%M').replace(tzinfo=timezone(off)).astimezone(timezone.utc)
    m = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})', v)
    if m:
        return datetime.strptime(f'{m[1]} {m[2]}:{m[3]}', '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
    return None


def fmt_date(dt):
    return dt.strftime('%-d %b %Y') if dt else 'unknown'


def time_tag(dt):
    return f'<time datetime="{dt.strftime("%Y-%m-%dT%H:%MZ")}" title="{dt.strftime("%Y-%m-%d %H:%M UTC")}">{fmt_date(dt)}</time>' if dt else 'date unknown'


def fmt_value(v):
    if isinstance(v, bool) or v is None:
        return e(v)
    if isinstance(v, int):
        return f'{v:,}'
    if isinstance(v, float):
        return f'{v:,.0f}' if v.is_integer() else f'{v:,.2f}'.rstrip('0').rstrip('.')
    return e(v)


ISO_TS = re.compile(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?Z')


def fmt_window(w):
    """Display form of a claim window: ISO UTC timestamps inside it read '2026-10-15 16:45 UTC' (data unchanged)."""
    return ISO_TS.sub(lambda m: f'{m[1]} {m[2]} UTC', w or '')


def window_html(w):
    """Escaped window text; each date (and 'HH:MM UTC') kept on one line."""
    return re.sub(r'\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2} UTC)?', lambda m: f'<span class="nw">{m[0]}</span>', e(fmt_window(w)))


def domain(u):
    m = re.match(r'https?://([^/]+)', u or '')
    return m[1].removeprefix('www.') if m else (u or '')


def trim(s, n):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1].rsplit(' ', 1)[0].rstrip(',;:.') + '…'


def fit_title(*options, n=65):
    """First candidate title that fits n chars; else the last one, its head trimmed at a word boundary (suffix after ' | ' kept)."""
    for t in options:
        if len(t) <= n:
            return t
    t = options[-1]
    head, sep, tail = t.rpartition(' | ')
    return trim(head, n - len(sep + tail)) + sep + tail if sep else trim(t, n)


def ext_link(url, text, cls=''):
    c = f' class="{cls}"' if cls else ''
    return f'<a{c} href="{e(url)}" rel="nofollow noopener" target="_blank">{text}</a>'


def jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + '</script>'


# ---------------------------------------------------------------- model
class Site:
    def __init__(self, cfg, data):
        self.cfg = cfg
        s = cfg['site']
        self.origin, self.base = s['origin'].rstrip('/'), s['base_path'].rstrip('/')
        self.snapshot = data
        self.cards = sorted(data['platforms'], key=lambda c: c['name'].lower())
        for c in self.cards:
            c['_desc'] = c.get('description_en') or next((x.get('statement') for x in c.get('claims', []) if x.get('kind') == 'description' and x.get('statement')), '') or ''
            ts = [parse_time(x.get('observed_at')) for x in c.get('claims', [])] + [parse_time(q.get('observed_at')) for q in c.get('qa', [])]
            ts = [t for t in ts if t]
            c['_verified'] = max(ts) if ts else None
            c['_url'] = f"{self.base}/platforms/{c['slug']}/"
        self.by_cat = defaultdict(list)
        for c in self.cards:
            self.by_cat[c['category']].append(c)
        unknown = set(self.by_cat) - set(CAT_LABEL)
        if unknown:
            raise SystemExit(f'unknown categories in data: {unknown}')
        self.cats = [k for k, *_ in CATEGORIES if self.by_cat.get(k)]
        self.latest = max((c['_verified'] for c in self.cards if c['_verified']), default=None)
        self.pages = []  # (path, lastmod) for sitemap
        self.og_jobs = {}  # name -> (spec, key): per-page Open Graph images (og_images.py)
        self.og_enabled = ogi.available()
        self.shots, self.shot_dir, self.shot_src, self.thumbs_ok = {}, None, 'not loaded', False  # screens.load() in main()
        self.api_docs = []  # (path under /api/v1, document, schema file, indented): legacy /atlas/*.json documents, re-served in /api/v1/ + schema_version

    def abs(self, path):
        return self.origin + path


# ---------------------------------------------------------------- enrichment
def fmt_num(v):
    """Catalog-draft number style: 3,601 · 1.25M · 2.1B."""
    a = abs(v)
    if a >= 1e9:
        return f'{v / 1e9:,.1f}'.rstrip('0').rstrip('.') + 'B'
    if a >= 1e6:
        return f'{v / 1e6:,.2f}'.rstrip('0').rstrip('.') + 'M'
    return fmt_value(v)


def enrich(site, tags):
    for c in site.cards:
        claims = c.get('claims', [])
        c['_tags'] = tags.get(c['slug'], [])
        c['_money'] = any(x.get('kind') == 'economic_flow' and x.get('outcome') == 'supported' for x in claims)
        c['_num'] = any(x.get('kind') == 'metric' and x.get('value') not in (None, '') for x in claims)
        isnum = lambda x: x.get('outcome') == 'supported' and isinstance(x.get('value'), (int, float)) and not isinstance(x.get('value'), bool)
        # a money figure we observed directly AND re-checked (e.g. a re-count after an audit) is the headline number;
        # otherwise the first supported metric, then the first supported money flow
        key = next((x for x in claims if x.get('kind') == 'economic_flow' and x.get('basis') == 'direct_observation' and x.get('recheck') and isnum(x)), None) \
            or next((x for k in ('metric', 'economic_flow') for x in claims if x.get('kind') == k and isnum(x)), None)
        c['_key'] = key


def keynum_html(c):
    x = c['_key']
    if not x:
        return ''
    dt = parse_time(x.get('observed_at'))
    bits = [x.get('unit') or '', x.get('window') or '', fmt_date(dt) if dt else '']
    return f'<div class="keynum"><b>{fmt_num(x["value"])}</b><span>{e(" · ".join(b for b in bits if b))}</span></div>'


def status_chip(c):
    if c['status'] == 'closed':
        return '<span class="chip closed"><i class="dot closed"></i>closed</span>'
    return '<span class="chip live"><i class="dot"></i>live</span>'


REFRESH_TOOL = 'atlas/refresh.py'  # the automated weekly check (status_history[].by)
AUTO_CLOSE_RULE = 'unreachable in 2 consecutive weekly checks (several attempts plus alternate URLs each week)'


def closure_info(c):
    """How a closed card was closed: ('auto', since_dt) when the automated weekly check closed it (atlas/refresh.py,
    reopens by itself if the site answers again), else ('human', None): human review, never reopened automatically."""
    hist = c.get('status_history') or []
    if c.get('status') == 'closed' and hist and hist[-1].get('to') == 'closed' and hist[-1].get('by') == REFRESH_TOOL:
        return 'auto', parse_time(hist[-1].get('at'))
    return 'human', None


def closure_note(c):
    """Short line for closed lists ('' for live cards)."""
    if c.get('status') != 'closed':
        return ''
    how, dt = closure_info(c)
    if how == 'auto':
        return f'Closed by automated check since {dt.strftime("%Y-%m-%d") if dt else "date unknown"}. '
    return ''


def tag_href(site, t):
    return f'{site.base}/?tag={t}'


# ---------------------------------------------------------------- layout
def sidebar(site, active):
    b = site.base
    closed = sum(1 for c in site.cards if c['status'] == 'closed')
    dirs = [(f'{b}/', 'All', len(site.cards), 'page' if active == 'index' else False, {'data-cat': ''})]
    for k in site.cats:
        act = 'page' if active == 'cat:' + k else (True if active == 'in:' + k else False)
        dirs.append((f'{b}/categories/{k}/', CAT_LABEL[k], len(site.by_cat[k]), act, {'data-cat': k}))
    secs = [(f'{b}/#catalog', 'Catalog', None, False, None),
            (f'{b}/earn/', 'Where agents get paid', len(site.earn['rows']) if getattr(site, 'earn', None) else None, 'page' if active == 'earn' else False, None),
            (f'{b}/closed/', 'Closed history', closed, 'page' if active == 'closed' else False, None),
            (f'{b}/about/', 'How the Atlas works', None, 'page' if active == 'about' else False, None)]
    sc = site.cfg['site']
    xnav = cw.cross_nav_item(sc.get('product_url') or '/', sc.get('product_name') or 'Commonworld', cw.mark_icon(b),
                             title='Commonworld main product')
    if active == 'home':
        xnav = xnav.replace('<a href="', '<a aria-current="page" href="', 1)
    cur = ' class="active" aria-current="page"' if active == 'cw-about' else ''
    cur_s = ' class="active" aria-current="page"' if active == 'cw-stats' else ''
    xnav += f'<nav class="cw-nav cw-xsub" aria-label="About Commonworld"><a href="{CW_ABOUT}"{cur}>About</a><a href="{STATS_PATH}"{cur_s}>Stats</a></nav>'
    ad = '' if active == 'earn' else cw.ad_slot(site.cfg, 'atlas-sidebar')  # no sponsored slots on the earn-now view
    return cw.sidebar(site.cfg, b, [('Directions', dirs), ('Sections', secs)], bottom=ad, top=xnav)


def breadcrumbs(site, trail):
    """trail: list of (name, path); last is the current page."""
    items = [('Commonworld', '/')] + trail
    vis = []
    for i, (n, p) in enumerate(items):
        vis.append(f'<li aria-current="page">{e(n)}</li>' if i == len(items) - 1 else f'<li><a href="{e(p)}">{e(n)}</a></li>')
    ld = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': i + 1, 'name': n, 'item': site.abs(p)} for i, (n, p) in enumerate(items)]}
    return f'<nav class="cw-crumbs" aria-label="Breadcrumb"><ol>{"".join(vis)}</ol></nav>', ld


X_HANDLE = '@commonworldone'  # official X account (twitter:site, footer, Organization sameAs, llms.txt)
X_URL = 'https://x.com/commonworldone'
GITHUB_ORG_URL = 'https://github.com/commonworld-one'
ORG_SAME_AS = [X_URL, GITHUB_ORG_URL]
REPO_URL = 'https://github.com/commonworld-one/commonworld'
OFFICIAL_LINKS = [('X', X_URL, 'x'), ('GitHub', REPO_URL, 'github')]  # footer, side by side
CW_ABOUT = '/about/'  # About Commonworld (site-wide); /atlas/about/ stays "How the Atlas works"
SEARCH_PLACEHOLDER = 'Search: name, category, description, numbers…'


def page(site, *, path, title, description, body, active, ld=(), og_type='website', noindex=False, lastmod=None, index_search=False, og=None, alt_json=None, alt_md=None):
    """og: (image name, spec dict, alt text) -> /atlas/og/<name>.png rendered by og_images.py (static og-atlas.png without Pillow)."""
    cfg = site.cfg
    canon = site.abs(path)
    b = site.base
    description = trim(description, 160)  # search snippets: <=160 chars, cut at a word boundary
    robots = 'noindex,follow' if noindex else 'index,follow,max-image-preview:large'
    og_img = site.abs(f'{b}/assets/og-atlas.png')
    og_alt = 'Commonworld Atlas: verified catalog of AI-agent platforms'
    if og and site.og_enabled and not noindex:
        name, spec, og_alt = og
        if name in site.og_jobs:
            raise SystemExit(f'duplicate OG image name {name}')
        key = ogi.spec_key(spec)
        site.og_jobs[name] = (spec, key)
        og_img = site.abs(f'{b}/og/{name}.png?v={key[:10]}')
    head_ld = ''.join(jsonld(x) for x in ld)
    corr = cfg['site']['corrections_url']
    foot_links = (f'<a href="{b}/platforms/">All entries A–Z</a><a href="{b}/categories/">Categories</a><a href="{CW_ABOUT}">About Commonworld</a><a href="{STATS_PATH}">Stats</a><a href="{b}/about/">How the Atlas works</a><a href="{DECISIONS_PATH}">Decision log</a><a href="{b}/badge/">Badges</a>'
                  f'<a href="{API_DOCS}">API</a><a href="{b}/data/snapshot.json">Data (JSON)</a><a href="{legal_urls(site)[0]}">Privacy</a><a href="{legal_urls(site)[1]}">Terms</a>{cw.cookie_settings_button()}'
                  f'<a href="{e(corr)}" rel="nofollow noopener">Report a correction</a>')
    verified = site.latest.strftime('%Y-%m-%d') if site.latest else ''
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta name="robots" content="{robots}">
{'' if noindex else f'<link rel="canonical" href="{e(canon)}">'}
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f4f1ea">
<meta property="og:site_name" content="Commonworld">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canon)}">
<meta property="og:image" content="{og_img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{e(og_alt)}">
<meta property="og:locale" content="en_US">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="{X_HANDLE}">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(description)}">
<meta name="twitter:image" content="{og_img}">
<meta name="twitter:image:alt" content="{e(og_alt)}">
<link rel="icon" href="{b}/assets/favicon.ico?v={site.img_v}" sizes="any">
<link rel="icon" type="image/svg+xml" href="{b}/assets/favicon.svg?v={site.img_v}">
<link rel="icon" type="image/png" href="{b}/assets/icon-192.png?v={site.img_v}" sizes="192x192">
<link rel="apple-touch-icon" href="{b}/assets/apple-touch-icon.png?v={site.img_v}">
<link rel="alternate" type="application/json" href="{b}/data/snapshot.json" title="Atlas data (JSON)">
<link rel="alternate" type="application/json" href="{b}/platforms.json" title="Atlas platforms (JSON, for agents)">
{f'<link rel="alternate" type="application/json" href="{e(alt_json)}" title="This entry (JSON: claims and sources)">' if alt_json else ''}
{f'<link rel="alternate" type="text/markdown" href="{e(alt_md)}" title="This page (Markdown)">' if alt_md else ''}
{cw.boot_script(cfg)}
<link rel="stylesheet" href="{b}/assets/atlas.css?v={site.asset_v}">
{head_ld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{cw.announcement_bar(cfg)}
<div class="cw-shell">
{sidebar(site, active)}
<div class="cw-col">
{cw.top_row(cw.search_form(f'{b}/', 'Search the Atlas: name, category, description…' if path == '/' else SEARCH_PLACEHOLDER, live=index_search), cfg)}
<main id="main">
{body}
</main>
{cw.footer(f'Commonworld / Atlas of Agent Platforms · verified {verified}', foot_links, OFFICIAL_LINKS)}
</div>
</div>
{cw.consent_banner(cfg)}
<script src="{b}/assets/atlas.js?v={site.asset_v}" defer></script>
</body>
</html>
"""
    if not noindex:
        site.pages.append((path, lastmod or site.latest))
    return html_doc


# ---------------------------------------------------------------- Open Graph image specs + share text
def share_text_index(site):
    live = sum(1 for c in site.cards if c['status'] == 'live')
    return f'Atlas of Agent Platforms: {live} places where AI agents work and get paid'


SHARE_TEXT_EARN = 'Where AI agents get paid — Commonworld Atlas'


def share_text_entry(c):
    """Share text by badge status: only verified cards say 'verified'."""
    tone = badges.status_of(c)[0]
    if tone == 'verified':
        return f"{c['name']} — verified on Commonworld Atlas"
    if tone == 'closed':
        return f"{c['name']} (closed) — history on Commonworld Atlas"
    return f"{c['name']} on Commonworld Atlas"


def og_foot(site, dt=None):
    dt = dt or site.latest
    return f'verified {fmt_date(dt)}' if dt else ''


def og_generic(site, name, title, desc, chips=(), kicker='Atlas', bar=None, alt=None):
    spec = {'kind': 'page', 'title': title, 'kicker': kicker, 'chips': [{'text': t, 'tone': tone} for t, tone in chips],
            'desc': trim(desc, 200), 'bar': bar or [[len(site.by_cat[k]), CAT_COLOR[k]] for k in site.cats], 'foot_right': og_foot(site)}
    return (name, spec, alt or f'{title}: Commonworld Atlas')


def og_platform(site, c):
    n = len(c.get('claims', []))
    tone = 'closed' if c['status'] == 'closed' else 'live'
    chips = [{'text': tone, 'tone': tone}, {'text': TYPE_LABEL.get(c['entity_type'], c['entity_type']), 'tone': None},
             {'text': f'{n} verified claim{"s" if n != 1 else ""}', 'tone': 'olive'}]
    if c.get('qa_status') == 'checked':
        chips.append({'text': 'QA re-checked', 'tone': 'olive'})
    spec = {'kind': 'platform', 'title': c['name'], 'kicker': CAT_LABEL[c['category']].upper(), 'kicker_color': CAT_COLOR[c['category']],
            'bar': [[1, CAT_COLOR[c['category']]]], 'chips': chips, 'desc': trim(c['_desc'], 200), 'foot_right': og_foot(site, c['_verified'])}
    alt = f"{c['name']} ({tone}, {CAT_LABEL[c['category']]}): {n} verified claims in the Commonworld Atlas"
    return (c['slug'], spec, alt)


# ---------------------------------------------------------------- fragments
def chips(c):
    out = [status_chip(c), f'<span class="chip type">{e(TYPE_LABEL.get(c["entity_type"], c["entity_type"]))}</span>']
    if c.get('qa_status') == 'checked':
        out.append('<span class="chip qa" title="A second agent re-checked the key claims">QA re-checked</span>')
    return '<div class="chips">' + ''.join(out) + '</div>'


SHOTS_PATH = '/screens'  # under site.base: /atlas/screens/<slug>.webp, thumbnails /atlas/screens/t/<slug>.webp


def shot_paths(site, c):
    """(full image path, grid thumbnail path) for a card with a screenshot, else None."""
    if c['slug'] not in site.shots:
        return None
    full = f"{site.base}{SHOTS_PATH}/{c['slug']}.webp"
    return full, (f"{site.base}{SHOTS_PATH}/t/{c['slug']}.webp" if site.thumbs_ok else full)


def preview_record(site, c):
    """The `preview` field of the public JSON records (null without a screenshot)."""
    p = shot_paths(site, c)
    if not p:
        return None
    r = site.shots[c['slug']]
    return {'path': p[0], 'url': site.abs(p[0]), 'thumb_url': site.abs(p[1]), 'width': screens.SHOT_W, 'height': screens.SHOT_H,
            'captured_at': r['captured_at'], 'source_url': r['source_url'], 'rights': screens.RIGHTS}


def thumb_html(site, c):
    """Grid thumbnail: the top band of the screenshot (decorative: the card title names it), or a sized placeholder."""
    p = shot_paths(site, c)
    if not p:
        return '<i class="ph" aria-hidden="true"></i>'
    w, h = (screens.THUMB_W, screens.THUMB_H) if site.thumbs_ok else (screens.SHOT_W, screens.SHOT_H)
    return f'<img src="{p[1]}" alt="" width="{w}" height="{h}" loading="lazy">'


def shot_figure(site, c):
    """Card page: the full 8:5 screenshot with a dated caption, or a placeholder note."""
    p = shot_paths(site, c)
    closed = c['status'] == 'closed'
    if not p:
        txt = ('No homepage preview: the site closed before screenshots were taken.' if closed
               else 'No homepage preview yet. A dated screenshot appears here once a capture succeeds.')
        return f'<figure class="entry-shot is-empty"><div class="ph">{txt}</div></figure>'
    r = site.shots[c['slug']]
    dt = parse_time(r['captured_at'])
    alt = f"Homepage of {c['name']} ({domain(c.get('canonical_url') or r['source_url'])}), screenshot captured {dt.strftime('%Y-%m-%d')}"
    href = c.get('canonical_url') or r['source_url']
    lead = (f'<b>Last captured {time_tag(dt)}</b>, before the site was marked closed. Kept as history.' if closed
            else f'Homepage as captured {time_tag(dt)} from {e(domain(r["source_url"]))}.')
    return (f'<figure class="entry-shot{" is-closed" if closed else ""}"><a href="{e(href)}" rel="nofollow noopener">'
            f'<img src="{p[0]}" width="{screens.SHOT_W}" height="{screens.SHOT_H}" loading="lazy" decoding="async" alt="{e(alt)}"></a>'
            f'<figcaption>{lead} Screenshot © the site owner, not part of the CC BY data.</figcaption></figure>')


def card_html(site, c, data=False, note=''):
    d = None
    if data:
        d = {'data-slug': c['slug'], 'data-c': c['category'], 'data-s': c['status'], 'data-t': c['entity_type'],
             'data-money': '1' if c['_money'] else None, 'data-num': '1' if c['_num'] else None,
             'data-claims': len(c.get('claims', [])), 'data-ver': int(c['_verified'].timestamp()) if c['_verified'] else 0,
             'data-tags': ' '.join(c['_tags']) or None}
    return cw.card(href=c['_url'], name=c['name'], cat_label=CAT_LABEL[c['category']], cat_color='k-' + c['category'],
                   status_chip=status_chip(c), desc=note + trim(c['_desc'], 150 - len(note)), keynum=keynum_html(c),
                   tags_html=cw.tag_chips(c['_tags'], lambda t: tag_href(site, t)), closed=c['status'] == 'closed', data=d,
                   thumb=thumb_html(site, c))


def cards_with_ads(site, cs, data=False):
    ad = cw.ad_card(site.cfg, 'atlas-native-card')
    out = []
    for i, c in enumerate(cs, 1):
        out.append(card_html(site, c, data))
        if ad and i % 12 == 0:
            out.append(ad)
    return ''.join(out)


LICENCE_URLS = {'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/'}  # data licence (LICENSE-DATA.md) -> canonical URL


def dataset_ld(site, cards, *, name, description, url, downloads, keywords):
    """schema.org Dataset (Google Dataset Search). downloads: [(path, encodingFormat, name)]; every path is written by this build
    (check.py verifies each contentUrl exists in dist)."""
    lic = site.cfg.get('data_licence')
    obs = [t for c in cards for t in (parse_time(x.get('observed_at')) for x in c.get('claims', [])) if t]
    lm = max((c['_verified'] for c in cards if c['_verified']), default=None)
    live = sum(1 for c in cards if c['status'] == 'live')
    d = {'@context': 'https://schema.org', '@type': 'Dataset', 'name': name, 'description': description, 'url': site.abs(url),
         'sameAs': REPO_URL, 'creator': {'@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/')},
         'publisher': {'@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/')},
         'isAccessibleForFree': True, 'inLanguage': 'en', 'keywords': keywords,
         'dateModified': lm.strftime('%Y-%m-%d') if lm else None,
         'variableMeasured': ['category', 'status (live or closed)', 'entity type', 'verified claims (statement, value, unit, basis, outcome)',
                              'source URL of each claim', 'observation date of each claim', 'money flow figures'],
         'size': f'{len(cards)} entries ({live} live, {len(cards) - live} closed)',
         'distribution': [{'@type': 'DataDownload', 'name': n, 'encodingFormat': f, 'contentUrl': site.abs(path)} for path, f, n in downloads]}
    if obs:
        d['temporalCoverage'] = f"{min(obs).strftime('%Y-%m-%d')}/{max(obs).strftime('%Y-%m-%d')}"
    if lic:
        d['license'] = LICENCE_URLS.get(lic, f'{REPO_URL}/blob/main/LICENSE-DATA.md')
    return {k: v for k, v in d.items() if v is not None}


DATASET_KEYWORDS = ['AI agents', 'agent platforms', 'agent economy', 'agent social networks', 'agent marketplaces', 'agent payments', 'x402',
                    'MCP', 'agent registries', 'verified catalog', 'open data']


def item_list_ld(site, cards, name):
    return {'@type': 'ItemList', 'name': name, 'numberOfItems': len(cards),
            'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'url': site.abs(c['_url'])} for i, c in enumerate(cards)]}


def cat_tabs_links(site, active):
    b = site.base
    items = [('All', len(site.cards), {'href': f'{b}/'}, active == '')]
    items += [(CAT_LABEL[k], len(site.by_cat[k]), {'href': f'{b}/categories/{k}/'}, active == k) for k in site.cats]
    return cw.tabs(items, label='Directions', tag='a')


# ---------------------------------------------------------------- pages
def build_index(site):
    b, cards, cfg = site.base, site.cards, site.cfg
    n = len(cards)
    live = sum(1 for c in cards if c['status'] == 'live')
    money = sum(1 for c in cards if c['_money'])
    nums = sum(1 for c in cards if c['_num'])
    stats = cw.stats_strip([
        (f'{n:,}', 'entries · show all', {'data-filter': 'reset'}, None, True),
        (f'{live:,}', 'live · filter', {'data-filter': 'status:live'}, 'live', True),
        (f'{n - live:,}', 'closed (history) · filter', {'data-filter': 'status:closed'}, 'closed', True),
        (f'{money:,}', 'with money flow · filter', {'data-filter': 'feat:money'}, 'money', True),
        (f'{nums:,}', 'with numbers · filter', {'data-filter': 'feat:num'}, 'num', True)], label='Atlas summary')
    bar = cw.catbar([(len(site.by_cat[k]), 'k-' + k, f'{CAT_LABEL[k]}: {len(site.by_cat[k])}') for k in site.cats])
    leg = cw.legend([(CAT_LABEL[k], len(site.by_cat[k]), sum(1 for c in site.by_cat[k] if c['status'] == 'live'), 'k-' + k,
                      {'data-cat': k}) for k in site.cats])
    verified = site.latest.strftime('%Y-%m-%d') if site.latest else ''
    corr = cfg['site']['corrections_url']
    box = cw.info_box('live', f'{n} entries', 'verified',
                      f'Each claim was checked against the platform’s own pages and public data. No listing is paid for. '
                      f'Spot a mistake? <a href="{e(corr)}" rel="nofollow noopener">Tell us</a>.')
    hero = cw.hero(f'Commonworld · Atlas · verified {verified}', 'Atlas of Agent Platforms',
                   '<p>Where AI agents talk, work, get paid, compete and publish research. Every card is checked against its own sources: '
                   'what it is, whether it’s live, and dated numbers you can trace.</p>', box)
    tabs = cw.tabs([('All', n, {'data-cat': ''}, True)] + [(CAT_LABEL[k], len(site.by_cat[k]), {'data-cat': k}, False) for k in site.cats])
    st = Counter(c['status'] for c in cards)
    ty = Counter(c['entity_type'] for c in cards)
    def pill(attr, k, label, count, dot=None):
        d = f'<i class="dot {dot}"></i>' if dot else ''
        return f'<button class="pill" type="button" {attr}="{k}" aria-pressed="false">{d}{e(label)}<span>{count}</span></button>'
    status_pills = pill('data-f-status', 'live', 'live', st['live'], 'live') + pill('data-f-status', 'closed', 'closed', st['closed'], 'closed')
    type_pills = ''.join(pill('data-f-type', k, TYPE_LABEL.get(k, k).lower(), ty[k]) for k in ('platform', 'project', 'tool_catalog', 'protocol') if ty[k])
    feat_pills = pill('data-f-feat', 'money', 'has money flow', money, 'money') + pill('data-f-feat', 'num', 'has numbers', nums, 'num')
    tagc = Counter(t for c in cards for t in c['_tags'])
    shelf = cw.tag_shelf(sorted(tagc.items(), key=lambda x: (-x[1], x[0]))) if tagc else ''
    body = f"""{stats}
{bar}
{leg}
{hero}
{cw.share_bar(cfg, site.abs(f'{b}/'), share_text_index(site), cls='cw-share-index')}
{cw.ad_slot(cfg, 'atlas-index-top', 'cw-ad-banner')}
<div id="catalog-top">{tabs}</div>
<section class="cw-panel atlas-catalog" id="catalog" aria-labelledby="list-title" data-search-index="{b}/data/search-index.json">
<div class="cw-panel-head"><h2 id="list-title">All platforms</h2><span class="muted" id="list-count" aria-live="polite">{n} of {n}</span><span class="spacer"></span><button class="text-btn" id="f-reset" type="button">Reset filters</button></div>
<div class="cw-panel-body">
<div class="cw-filterbar">
<div class="cw-filtergroup" role="group" aria-label="Status"><span class="lbl">Status</span>{status_pills}</div>
<div class="cw-filtergroup" role="group" aria-label="Type"><span class="lbl">Type</span>{type_pills}</div>
<div class="cw-filtergroup" role="group" aria-label="Features"><span class="lbl">Features</span>{feat_pills}</div>
<div class="cw-sort"><label for="f-sort">Sort</label><select id="f-sort"><option value="name">by name</option><option value="claims">most claims</option><option value="recent">recently verified</option></select></div>
</div>
{shelf}
<div class="cw-active" id="active"><span>Click tags, statuses or tabs to narrow the list. Tags combine with AND.</span></div>
<div class="cw-grid" id="grid">{cards_with_ads(site, cards, data=True)}<p class="cw-empty" id="f-empty" hidden>Nothing found. Remove a tag or clear the search.</p></div>
</div>
</section>
<script type="application/json" id="cat-labels">{json.dumps(CAT_LABEL, ensure_ascii=False)}</script>
<script type="application/json" id="type-labels">{json.dumps({k: v.lower() for k, v in TYPE_LABEL.items()})}</script>"""
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/')])
    ld = [crumb_ld,
          {'@context': 'https://schema.org', '@type': 'WebSite', 'name': 'Commonworld Atlas', 'url': site.abs(f'{b}/'),
           'inLanguage': 'en', 'publisher': {'@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/')},
           'potentialAction': {'@type': 'SearchAction', 'target': {'@type': 'EntryPoint', 'urlTemplate': site.abs(f'{b}/') + '?q={search_term_string}'},
                               'query-input': 'required name=search_term_string'}},
          {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Atlas of Agent Platforms', 'url': site.abs(f'{b}/'),
           'description': 'Verified catalog of AI-agent platforms.', 'dateModified': site.latest.strftime('%Y-%m-%d') if site.latest else None,
           'mainEntity': {'@type': 'ItemList', 'name': 'Atlas categories', 'numberOfItems': len(site.cats), 'itemListElement': [
               {'@type': 'ListItem', 'position': i + 1, 'name': CAT_LABEL[k], 'url': site.abs(f'{b}/categories/{k}/')} for i, k in enumerate(site.cats)]}},
          dataset_ld(site, cards, name='Commonworld Atlas', url=f'{b}/', keywords=DATASET_KEYWORDS,
                     description=f'Verified map of AI-agent platforms: social networks, work and bounty boards, payments, research venues, worlds, '
                                 f'registries and more ({n} entries, {live} live, {len(site.cats)} categories). Every entry has a source link and a check date '
                                 f'for each fact; closed platforms are kept as history.',
                     downloads=[(f'{b}/data/snapshot.json', 'application/json', 'Full published dataset (snapshot.json)'),
                                (f'{b}/platforms.json', 'application/json', 'All entries with stable fields (platforms.json)'),
                                (f'{b}/earn.json', 'application/json', 'Where agents get paid: sourced money figures (earn.json)'),
                                (api_v1.API_BASE + '/atlas/platforms.json', 'application/json', 'API v1: all entries'),
                                (f'{b}/llms.txt', 'text/plain', 'Atlas guide for AI agents (llms.txt)'),
                                (SAFETY_PATH, 'application/json', 'Link safety report: trust engine status of every linked domain, with each source\'s answer (safety.json)'),
                                (DECISIONS_JSON, 'application/json', 'Link safety decision log: every removal and return with who, why and evidence (decisions.json)'),
                                ('/llms-full.txt', 'text/plain', 'One line per entry (llms-full.txt)')])]
    return page(site, path=f'{b}/', title='Atlas of Agent Platforms: verified catalog | Commonworld',
                description=f'{n} places where AI agents talk, work, get paid, compete and publish research, each checked against its own sources, with dated numbers you can trace.',
                body=body, active='index', ld=ld, index_search=True,
                og=og_generic(site, 'atlas', 'Atlas of Agent Platforms',
                              'Where AI agents talk, work, get paid, compete and publish research. Every card is checked against its own sources.',
                              [(f'{n} entries', 'olive'), (f'{live} live', 'live'), (f'{n - live} closed', 'closed'), (f'{len(site.cats)} directions', None)],
                              kicker='VERIFIED CATALOG', alt=f'Commonworld Atlas of Agent Platforms: {n} verified entries, {live} live'))


def build_platform(site, c):
    b = site.base
    cat = c['category']
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), (CAT_LABEL[cat], f'{b}/categories/{cat}/'), (c['name'], c['_url'])])
    claims = card_claims(c)
    labels = qa_labels_for(c, claims, site.claim_labels.get(c['slug'], {}))
    lis = []
    for i, x in enumerate(claims):
        k = x.get('kind')
        val = ''
        if x.get('value') not in (None, ''):
            unit = f' {e(x.get("unit"))}' if x.get('unit') else ''
            win = f' <span class="win">({e(fmt_window(x.get("window")))})</span>' if x.get('window') else ''
            val = f'<p class="val">{fmt_value(x["value"])}{unit}{win}</p>'
        q = trim(x.get('quote'), 280)
        quote = f'<blockquote>“{e(q)}”</blockquote>' if q else ''
        labs = labels.get(i, [])
        lab = ''.join(f'<p class="qa-label {t}"><b>{e(h)}</b> {e(txt)}</p>' for h, txt, t in labs)
        src = ext_link(x['source_url'], 'Source: ' + e(domain(x['source_url']))) if x.get('source_url') else 'No source link'
        dt = parse_time(x.get('observed_at'))
        o = x.get('outcome') or 'unchecked'
        wide = ' wide' if labs else ''
        lis.append(f'<li class="claim o-{e(o)}{wide}"><div class="claim-head"><span class="kind">{e(KIND_LABEL.get(k, (k or "claim").replace("_", " ").capitalize()))}</span>'
                   f'<span class="tag t-{OUTCOME_TONE.get(o, "warn")}">{e(OUTCOME_LABEL.get(o, o))}</span>'
                   f'<span class="tag t-basis">{e(BASIS_LABEL.get(x.get("basis"), x.get("basis") or "basis unknown"))}</span></div>'
                   f'{lab}{val}<p class="stmt">{e(x.get("statement"))}</p>{quote}'
                   f'<p class="claim-meta">Observed {time_tag(dt)} · {src}</p>{history_html(x)}</li>')
    qa_rows = []
    for q in c.get('qa', []):
        dt = parse_time(q.get('observed_at'))
        tone = {'agree': 'ok', 'disagree': 'bad'}.get(q.get('qa_outcome'), 'warn')
        cls = {'agree': 'o-supported', 'disagree': 'o-contradicted'}.get(q.get('qa_outcome'), 'o-unchecked')
        flag = f'<p class="qa-label warn"><b>Scope:</b> {e(q["scope_flag"])}</p>' if q.get('scope_flag') else ''
        src = ext_link(q['source_url'], 'Source: ' + e(domain(q['source_url']))) if q.get('source_url') else ''
        kinds = ', '.join(KIND_LABEL.get(k, k.replace('_', ' ')) for k in re.split(r'[+/]', q.get('claim_kind') or '') if k)
        qa_rows.append(f'<li class="claim {cls}"><div class="claim-head"><span class="kind">{e(kinds or "Claim")}</span>'
                       f'<span class="tag t-{tone}">{e(QA_LABEL.get(q.get("qa_outcome"), q.get("qa_outcome")))}</span></div>{flag}'
                       f'<p class="stmt">{e(trim(q.get("qa_value"), 400))}</p>'
                       + (f'<p class="note">{e(trim(q.get("note"), 500))}</p>' if q.get('note') else '')
                       + f'<p class="claim-meta">Re-checked {time_tag(dt)}{" · " + src if src else ""}</p></li>')
    closed_box = ''
    if c['status'] == 'closed':
        ev = next((x.get('statement') for x in claims if x.get('kind') == 'announced_closed'), None) \
            or next((x.get('statement') for x in claims if x.get('outcome') == 'contradicted'), None)
        how, since = closure_info(c)
        if how == 'auto':
            ev = next((x.get('statement') for x in claims if x.get('kind') == 'site_reachable' and x.get('outcome') == 'contradicted'), None) or ev
            closed_box = (f'<div class="closed-box" role="note"><b>Closed by automated check since {time_tag(since)}.</b> '
                          f'The site could not be reached in 2 consecutive weekly checks (several attempts plus alternate URLs each week). '
                          f'This card is kept as a history record and reopens automatically if the site answers again. {e(ev) if ev else ""}</div>')
        else:
            closed_box = (f'<div class="closed-box" role="note"><b>Closed.</b> This card is kept as a history record. '
                          f'{e(ev) if ev else "See the evidence below."}</div>')
    disclosure_box = f'<p class="disclosure-box" role="note">{e(c["disclosure"])}</p>' if c.get('disclosure') else ''
    rel = [r for r in site.by_cat[cat] if r['slug'] != c['slug']]
    rel.sort(key=lambda r: (r['status'] != 'live', r['name'].lower()))
    idx = sum(1 for r in rel if r['name'].lower() < c['name'].lower())
    rel = (rel[idx:] + rel[:idx])[:6] if rel else []
    rel_html = ''.join(card_html(site, r) for r in rel)
    corr = f"{site.cfg['site']['corrections_url']}?title={e('Atlas correction: ' + c['slug']).replace(' ', '+')}"
    cu = c.get('canonical_url')
    visit = ext_link(cu, ('Former site ' if c['status'] == 'closed' else 'Visit ') + e(domain(cu)) + ' <span aria-hidden="true">↗</span>', 'cw-btn cw-btn-primary visit') if cu else ''
    tl = TYPE_LABEL.get(c['entity_type'], c['entity_type'])
    tags = cw.tag_chips(c['_tags'], lambda t: tag_href(site, t), limit=99)
    body = f"""{crumbs}
<article class="entry">
<header class="entry-head"><div class="cw-meta"><a class="catchip" href="{b}/categories/{cat}/"><i class="k-{cat}"></i>{e(CAT_LABEL[cat])}</a></div>
<h1>{e(c['name'])}</h1>{chips(c)}
<p class="cw-lead">{e(c['_desc'])}</p>{closed_box}{disclosure_box}{tags}<div class="entry-actions">{f'<p class="actions">{visit}</p>' if visit else ''}{cw.share_bar(site.cfg, site.abs(c['_url']), share_text_entry(c), cls='cw-share-head')}</div></header>
{cw.ad_slot(site.cfg, 'atlas-platform-top', 'cw-ad-banner')}
{shot_figure(site, c)}
<dl class="facts">
<div><dt>Permanent ID</dt><dd><code>{e(c['slug'])}</code> · <a href="{b}/platforms/{e(c['slug'])}.json" type="application/json" title="This entry as JSON: all claims with sources">JSON</a></dd></div>
<div><dt>Direction</dt><dd><a href="{b}/categories/{cat}/">{e(CAT_SHORT[cat])}</a></dd></div>
<div><dt>Type</dt><dd>{e(tl)}</dd></div>
<div><dt>Status</dt><dd>{('Closed (history, automated check)' if closure_info(c)[0] == 'auto' else 'Closed (history)') if c['status'] == 'closed' else 'Live'}</dd></div>
<div><dt>Last verified</dt><dd>{time_tag(c['_verified'])}</dd></div>
<div><dt>Checked claims</dt><dd>{len(claims)}</dd></div>
</dl>
<section class="cw-panel" aria-labelledby="h-claims"><div class="cw-panel-head"><h2 id="h-claims">Verified facts</h2><span class="muted">{len(claims)} claims · last verified {time_tag(c['_verified'])}</span></div>
<div class="cw-panel-body"><p class="sec-desc">Each fact shows how it is known (observed directly, operator claim, independent source or inference), whether the source supported it, when it was observed and where. Operator figures are what the platform says about itself.</p>
<ol class="claims">{''.join(lis)}</ol></div></section>
{f'<section class="cw-panel cw-panel-gap" aria-labelledby="h-qa"><div class="cw-panel-head"><h2 id="h-qa">Independent QA re-check</h2><span class="muted">{len(qa_rows)} re-checks</span></div><div class="cw-panel-body"><p class="sec-desc">A second agent re-checked these claims separately.</p><ol class="claims">{"".join(qa_rows)}</ol></div></section>' if qa_rows else ''}
{badge_block(site, c)}
<aside class="correction"><h2>Something wrong or out of date?</h2><p>Atlas corrects cards from sources. <a href="{e(corr)}" rel="nofollow noopener">Tell us</a> with a link that shows the right fact, or read <a href="{b}/about/#corrections">how corrections work</a>.</p></aside>
</article>
{f'<section class="related" aria-labelledby="h-rel" data-nosnippet><div class="sec-head"><h2 id="h-rel">More in {e(CAT_LABEL[cat])}</h2><a href="{b}/categories/{cat}/">All {len(site.by_cat[cat])}</a></div><div class="cw-grid">{rel_html}</div></section>' if rel_html else ''}"""
    mtype = 'WebApplication' if c['entity_type'] in ('platform', 'tool_catalog') else 'SoftwareApplication'
    me = {'@type': mtype, 'name': c['name'], 'description': c['_desc'] or None,
          'applicationCategory': 'DeveloperApplication' if mtype == 'SoftwareApplication' else 'WebApplication', 'operatingSystem': 'Web'}
    if cu:
        me['url'] = cu
        me['sameAs'] = [cu]
    me = {k: v for k, v in me.items() if v}
    vd = c['_verified'].strftime('%Y-%m-%d') if c['_verified'] else None
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'WebPage', 'name': c['name'] + ' in the Commonworld Atlas', 'url': site.abs(c['_url']),
                     'inLanguage': 'en', 'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld Atlas', 'url': site.abs(f'{b}/')},
                     'about': {'@type': 'Thing', 'name': CAT_LABEL[cat]}, 'dateModified': vd, 'lastReviewed': vd, 'mainEntity': me}]
    status = ' (closed)' if c['status'] == 'closed' else ''
    kind_phrase = 'agent-economy project' if cat == 'projects' else f'{CAT_SHORT[cat]} {tl.lower()}'
    title = fit_title(f"{c['name']}{status}: {kind_phrase} | Commonworld Atlas", f"{c['name']}{status} | Commonworld Atlas")
    pre = f"{c['name']}{status}: "
    desc = pre + trim(c['_desc'], 150 - len(pre)) if c['_desc'] else f"{c['name']}{status}, a verified {CAT_SHORT[cat].lower()} {tl.lower()} in the Commonworld Atlas."
    return page(site, path=c['_url'], title=title, description=desc, body=body, active='in:' + cat, ld=ld, og_type='article', lastmod=c['_verified'], og=og_platform(site, c),
                alt_json=site.abs(f"{b}/platforms/{c['slug']}.json"))


def card_claims(c):
    """Claims in the order a platform card shows them."""
    return sorted(c.get('claims', []), key=lambda x: (KIND_ORDER.index(x['kind']) if x.get('kind') in KIND_ORDER else 50 + (x.get('kind') == 'site_reachable')))


def history_html(x):
    """Earlier values of a claim (claim['history'], newest last) as a small 'Previously …' line."""
    hs = x.get('history') or []
    if not hs:
        return ''
    bits = []
    for h in reversed(hs[-3:]):
        v = h.get('value')
        txt = f'{fmt_value(v)}{(" " + e(h["unit"])) if h.get("unit") else ""}' if v not in (None, '') else '“' + e(trim(h.get('statement') or '', 140).rstrip('.')) + '”'
        bits.append(f'{txt} on {time_tag(parse_time(h.get("observed_at")))}')
    return f'<p class="claim-hist">Previously {"; ".join(bits)}</p>'


def qa_labels_for(c, claims, curated):
    """Map claim index -> [(heading, text, tone)] from QA results and curated wording (claim-labels.json)."""
    out = defaultdict(list)
    for kind, txt in curated.items():
        for i, x in enumerate(claims):
            if x.get('kind') == kind:
                out[i].append(('Read as:', txt, 'warn'))
    for q in c.get('qa', []):
        kinds = [k for k in re.split(r'[+/]', q.get('claim_kind') or '') if k]
        idx = [i for i, x in enumerate(claims) if x.get('kind') in kinds]
        if len(idx) > 1 and kinds and kinds[0] in ('metric', 'economic_flow'):
            fav = q.get('first_agent_value') or ''
            digits = re.sub(r'[^\d]', '', fav)
            narrowed = [i for i in idx if any(isinstance(v, (int, float)) and not isinstance(v, bool) and str(int(v)) in digits
                                              for v in [claims[i].get('value')] + [h.get('value') for h in claims[i].get('history') or []])]
            idx = narrowed or idx
        if q.get('qa_outcome') == 'disagree':
            for i in idx:
                out[i].append(('QA disagrees:', trim(q.get('note') or q.get('qa_value'), 240), 'bad'))
        elif q.get('qa_outcome') == 'cannot_recheck':
            for i in idx:
                out[i].append(('QA could not re-check:', trim(q.get('note'), 200), 'warn'))
        elif q.get('scope_flag') and not any(k in curated for k in kinds):
            for i in idx:
                out[i].append(('QA caution:', q['scope_flag'], 'warn'))
    return out



def build_category(site, k):
    b = site.base
    cs = sorted(site.by_cat[k], key=lambda c: (c['status'] != 'live', c['name'].lower()))
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('Categories', f'{b}/categories/'), (CAT_LABEL[k], f'{b}/categories/{k}/')])
    live = sum(1 for c in cs if c['status'] == 'live')
    lm = max((c['_verified'] for c in cs if c['_verified']), default=None)
    box = cw.info_box('live', f'{len(cs)} entries', f'{live} live',
                      f'{len(cs) - live} closed, kept as history. Last verified {time_tag(lm)}. '
                      f'<a href="{b}/?category={k}">Filter and search this direction</a>.')
    body = f"""{crumbs}
{cw.hero('Atlas · direction', CAT_LABEL[k], f'<p>{e(CAT_DESC[k])}</p>', box, small=True, kicker_href=f'{b}/')}
{cw.ad_slot(site.cfg, 'atlas-category-top', 'cw-ad-banner')}
{cat_tabs_links(site, k)}
<div class="cw-grid">{cards_with_ads(site, cs)}</div>"""
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': f'{CAT_LABEL[k]} in the Commonworld Atlas',
                     'url': site.abs(f'{b}/categories/{k}/'), 'description': CAT_DESC[k], 'inLanguage': 'en',
                     'mainEntity': item_list_ld(site, cs, CAT_LABEL[k])},
          dataset_ld(site, cs, name=f'Commonworld Atlas: {CAT_LABEL[k]}', url=f'{b}/categories/{k}/', keywords=DATASET_KEYWORDS + [CAT_LABEL[k]],
                     description=f'{CAT_DESC[k]} {len(cs)} entries ({live} live) in the Commonworld Atlas, a verified map of AI-agent platforms. '
                                 f'Every entry has a source link and a check date for each fact; closed platforms are kept as history.',
                     downloads=[(f'{b}/categories/{k}.json', 'application/json', f'{CAT_LABEL[k]} entries (JSON)'),
                                (f'{api_v1.API_BASE}/atlas/categories/{k}.json', 'application/json', f'API v1: {CAT_LABEL[k]} entries')])]
    return page(site, path=f'{b}/categories/{k}/', title=fit_title(f'{CAT_LABEL[k]}: {len(cs)} verified AI-agent entries | Commonworld Atlas',
                                                          f'{CAT_LABEL[k]}: {len(cs)} verified entries | Commonworld Atlas',
                                                          f'{CAT_SHORT[k]}: {len(cs)} verified entries | Commonworld Atlas'),
                description=trim(f'{CAT_DESC[k]} {len(cs)} entries in the Commonworld Atlas, each checked against its own sources.', 160),
                body=body, active='cat:' + k, ld=ld, lastmod=lm,
                og=('category-' + k, {'kind': 'category', 'title': CAT_LABEL[k], 'kicker': 'DIRECTION', 'kicker_color': CAT_COLOR[k],
                                      'bar': [[1, CAT_COLOR[k]]], 'desc': CAT_DESC[k], 'foot_right': og_foot(site, lm),
                                      'chips': [{'text': f'{len(cs)} entries', 'tone': 'olive'}, {'text': f'{live} live', 'tone': 'live'}]
                                      + ([{'text': f'{len(cs) - live} closed', 'tone': 'closed'}] if len(cs) - live else [])},
                    f'{CAT_LABEL[k]}: {len(cs)} verified entries in the Commonworld Atlas'))


def build_categories_index(site):
    b = site.base
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('Categories', f'{b}/categories/')])
    tiles = ''.join(f'<a class="cat-tile" href="{b}/categories/{k}/"><span class="catchip"><i class="k-{k}"></i>'
                    f'{len(site.by_cat[k])} entries · {sum(1 for c in site.by_cat[k] if c["status"] == "live")} live</span>'
                    f'<b>{e(CAT_LABEL[k])}</b><p>{e(CAT_DESC[k])}</p></a>' for k in site.cats)
    bar = cw.catbar([(len(site.by_cat[k]), 'k-' + k, f'{CAT_LABEL[k]}: {len(site.by_cat[k])}') for k in site.cats])
    body = f"""{crumbs}{cw.hero('Atlas', 'Directions', '<p>Every Atlas entry sits in one direction.</p>', small=True, kicker_href=f'{b}/')}
{bar}<div class="cat-grid">{tiles}</div>"""
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Atlas categories', 'url': site.abs(f'{b}/categories/'),
                     'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(site.cats), 'itemListElement': [
                         {'@type': 'ListItem', 'position': i + 1, 'url': site.abs(f'{b}/categories/{k}/'), 'name': CAT_LABEL[k]} for i, k in enumerate(site.cats)]}}]
    return page(site, path=f'{b}/categories/', title='Directions (categories) | Commonworld Atlas',
                description=trim('Browse the Commonworld Atlas by direction: ' + ', '.join(CAT_SHORT[k].lower() for k in site.cats) + '.', 160),
                body=body, active='categories', ld=ld,
                og=og_generic(site, 'page-categories', 'Directions', 'Browse the Atlas by direction: ' + ', '.join(CAT_LABEL[k].lower() for k in site.cats) + '.',
                              [(f'{len(site.cats)} directions', 'olive'), (f'{len(site.cards)} entries', None)]))


def list_table(site, cs):
    rows = ''.join(f'<tr><td><a href="{c["_url"]}">{e(c["name"])}</a></td><td><a class="catchip" href="{site.base}/categories/{c["category"]}/"><i class="k-{c["category"]}"></i>{e(CAT_LABEL[c["category"]])}</a></td>'
                   f'<td>{e(TYPE_LABEL.get(c["entity_type"], c["entity_type"]))}</td><td>{status_chip(c)}</td><td>{time_tag(c["_verified"])}</td></tr>' for c in cs)
    return f'<div class="table-wrap"><table class="list"><thead><tr><th scope="col">Name</th><th scope="col">Direction</th><th scope="col">Type</th><th scope="col">Status</th><th scope="col">Last verified</th></tr></thead><tbody>{rows}</tbody></table></div>'


def build_all(site):
    b = site.base
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('Entries', f'{b}/platforms/')])
    body = f"""{crumbs}{cw.hero('Atlas', 'All entries', f'<p>All {len(site.cards)} published entries, A to Z. Closed entries stay listed as history.</p>', small=True, kicker_href=f'{b}/')}{list_table(site, site.cards)}"""
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'All Atlas entries', 'url': site.abs(f'{b}/platforms/'),
                     'mainEntity': item_list_ld(site, site.cards, 'All Atlas entries')}]
    return page(site, path=f'{b}/platforms/', title=f'All {len(site.cards)} entries A–Z | Commonworld Atlas',
                description=f'Alphabetical list of all {len(site.cards)} verified AI-agent platforms, protocols, catalogs and projects in the Commonworld Atlas.',
                body=body, active='platforms', ld=ld,
                og=og_generic(site, 'page-platforms', 'All entries A–Z', f'All {len(site.cards)} published entries, A to Z. Closed entries stay listed as history.',
                              [(f'{len(site.cards)} entries', 'olive')]))


def build_closed(site):
    b = site.base
    cs = [c for c in site.cards if c['status'] == 'closed']
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('Closed', f'{b}/closed/')])
    n_auto = sum(1 for c in cs if closure_info(c)[0] == 'auto')
    box = cw.info_box('closed', f'{len(cs)} closed', 'history',
                      'A closure is recorded in one of two ways. <b>Human review:</b> an official shutdown statement or at least two independent signals. '
                      '<b>Automated weekly check:</b> the site could not be reached in 2 consecutive weekly checks (several attempts plus alternate URLs each week); '
                      'such cards say “Closed by automated check” and reopen automatically if the site answers again. Cards closed by human review are never reopened automatically. '
                      'A single failed page load is never treated as proof.')
    lead = ('<p>Platforms that shut down keep their card as a history record, with the evidence of closure and dates.'
            + (f' {n_auto} of them {"was" if n_auto == 1 else "were"} closed by the automated weekly check.' if n_auto else '') + '</p>')
    body = f"""{crumbs}{cw.hero('Atlas · history', 'Closed platforms', lead, box, small=True, kicker_href=f'{b}/')}
<div class="cw-grid mt-22">{''.join(card_html(site, c, note=closure_note(c)) for c in cs)}</div>"""
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Closed AI-agent platforms (history)', 'url': site.abs(f'{b}/closed/'),
                     'mainEntity': item_list_ld(site, cs, 'Closed platforms')}]
    return page(site, path=f'{b}/closed/', title=f'Closed agent platforms: {len(cs)} records | Commonworld Atlas',
                description=f'{len(cs)} AI-agent platforms that have closed, kept as history records with the evidence of closure and dates.',
                body=body, active='closed', ld=ld,
                og=og_generic(site, 'page-closed', 'Closed platforms', 'Platforms that shut down keep their card as a history record, with the evidence of closure and dates.',
                              [(f'{len(cs)} closed', 'closed'), ('history', None)], kicker='HISTORY'))


# ---------------------------------------------------------------- "Where agents get paid" (earn-now view)
USD_FAMILY = re.compile(r'^\$|\b(USD|USDC|USDT|USDe|DAI|PYUSD|EURC|stablecoins?)\b', re.I)
MONEY_UNIT = re.compile(r'^\$|\b(USD|USDC|USDT|DAI|sats?|SOL|ETH|BTC|sBTC|tokens?|credits?)\b', re.I)
BASIS_RANK = {'direct_observation': 0, 'independent_source': 1, 'inference': 2, 'operator_claim': 3}
EARN_TIERS = [('measured', 'Measured', 'Observed directly by the Atlas or measured by an independent source (for example an on-chain decoder).'),
              ('operator', 'Operator claims', 'What the platform says about itself. Shown as stated, not confirmed by us.')]


def num_of(v):
    """Sort key only (never displayed, never combined across units): 1234 -> 1234.0; '$618.6k' -> 618600.0; '145k–390k' -> 145000.0 (low end)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB])?', str(v))
    if not m:
        return None
    return float(m[1].replace(',', '')) * {'k': 1e3, 'm': 1e6, 'b': 1e9}.get((m[2] or '').lower(), 1)


def earn_claim(c):
    """The money figure for one live card: its key number when that is a money figure, else its first numeric
    supported money-flow claim (observed directly first). None when the card has no numeric money figure."""
    k = c['_key']
    if k and (k.get('kind') == 'economic_flow' or MONEY_UNIT.search(k.get('unit') or '')):
        return k
    flows = [x for x in c.get('claims', []) if x.get('kind') == 'economic_flow' and x.get('outcome') == 'supported' and num_of(x.get('value')) is not None]
    flows.sort(key=lambda x: x.get('basis') != 'direct_observation')
    return flows[0] if flows else None


def earn_rows(site):
    rows, no_figure = [], []
    for c in site.cards:
        if c['status'] != 'live' or not c['_money']:
            continue
        x = earn_claim(c)
        if not x:
            no_figure.append(c)
            continue
        claims = card_claims(c)
        labs = qa_labels_for(c, claims, site.claim_labels.get(c['slug'], {}))
        idx = next((i for i, y in enumerate(claims) if y is x), None)
        notes = [(h, t) for h, t, _ in labs.get(idx, [])] if idx is not None else []
        unit = x.get('unit') or ''
        n = num_of(x.get('value'))
        rows.append({'c': c, 'x': x, 'n': n, 'unit': unit, 'notes': notes, 'dt': parse_time(x.get('observed_at')),
                     'family': 'usd' if USD_FAMILY.search(re.sub(r'\(.*?\)', '', unit)) and not re.search(r'\btokens?\b', unit, re.I) else 'other',
                     'tier': 'operator' if x.get('basis') == 'operator_claim' else 'measured', 'zero': not n})
    groups = []
    usd = [r for r in rows if r['family'] == 'usd' and not r['zero']]
    if usd:
        groups.append(('usd', 'US dollar & stablecoins', 'USD, USDC, USDT and other dollar stablecoins, sorted by value within each tier. '
                       'Windows differ (30 days, all time, a prize pool), so compare a row with others of the same window.', usd))
    other = defaultdict(list)
    for r in rows:
        if r['family'] == 'other' and not r['zero']:
            other[r['unit']].append(r)
    for u in sorted(other, key=lambda u: (-len(other[u]), u.lower())):
        groups.append(('unit-' + re.sub(r'[^a-z0-9]+', '-', u.lower()).strip('-'), u, f'Figures in {u}, sorted by value within each tier. Not converted to any other unit.', other[u]))
    zero = [r for r in rows if r['zero']]
    if zero:
        groups.append(('zero', 'Zero at the last observation', 'A money rail exists, but the figure was zero when observed.', zero))
    for _, _, _, rs in groups:
        rs.sort(key=lambda r: (r['tier'] != 'measured', -(r['n'] or 0), BASIS_RANK.get(r['x'].get('basis'), 9), r['c']['name'].lower()))
    return {'rows': rows, 'groups': groups, 'no_figure': no_figure}


def earn_record(site, r):
    c, x = r['c'], r['x']
    return {'id': c['slug'], 'name': c['name'], 'url': site.abs(c['_url']), 'json_url': site.abs(f"{site.base}/platforms/{c['slug']}.json"),
            'category': c['category'], 'value': x.get('value'), 'unit': x.get('unit'), 'window': x.get('window'), 'basis': x.get('basis'),
            'observed_at': iso(r['dt']), 'source_url': x.get('source_url'), 'unit_family': r['family'] if not r['zero'] else 'zero',
            'tier': r['tier'], 'note': ' '.join(f'{h} {t}' for h, t in r['notes']) or None}


def earn_table(site, rs):
    b = site.base
    trs = []
    for r in rs:
        c, x = r['c'], r['x']
        unit = f' {e(x["unit"])}' if x.get('unit') else ''
        note = ''.join(f'<p class="qa-label warn"><b>{e(h)}</b> {e(t)}</p>' for h, t in r['notes'])
        basis = x.get('basis')
        btag = f'<span class="tag {"t-warn" if basis == "operator_claim" else "t-basis"}">{e(BASIS_LABEL.get(basis, basis or "basis unknown"))}</span>'
        src = ext_link(x['source_url'], e(domain(x['source_url']))) if x.get('source_url') else 'No source link'
        trs.append(f'<tr><td><a href="{c["_url"]}"><b>{e(c["name"])}</b></a><br><a class="catchip" href="{b}/categories/{c["category"]}/"><i class="k-{c["category"]}"></i>{e(CAT_SHORT[c["category"]])}</a></td>'
                   f'<td class="earn-val"><b>{fmt_value(x["value"])}</b>{unit}{note}</td><td class="earn-win">{window_html(x.get("window")) or "—"}</td><td class="earn-basis">{btag}</td>'
                   f'<td>{time_tag(r["dt"])}</td><td>{src}</td></tr>')
    return ('<div class="table-wrap"><table class="list earn"><thead><tr><th scope="col">Platform</th><th scope="col">Figure (as on the card)</th>'
            '<th scope="col">Window</th><th scope="col">Basis</th><th scope="col">Observed (UTC)</th><th scope="col">Source</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>')


def build_earn(site):
    b = site.base
    E = site.earn
    rows, groups = E['rows'], E['groups']
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('Where agents get paid', f'{b}/earn/')])
    lm = max((r['dt'] for r in rows if r['dt']), default=None)
    secs, toc = [], []
    for gid, title, desc, rs in groups:
        parts = []
        for tid, tlabel, tdesc in EARN_TIERS:
            tr = [r for r in rs if r['tier'] == tid]
            if tr:
                parts.append(f'<h3 class="earn-tier">{e(tlabel)} <span class="muted">· {len(tr)}</span></h3><p class="sec-desc">{e(tdesc)}</p>{earn_table(site, tr)}')
        toc.append(f'<a href="#{gid}">{e(title)} <span>{len(rs)}</span></a>')
        secs.append(f'<section class="cw-panel cw-panel-gap" id="{gid}" aria-labelledby="h-{gid}"><div class="cw-panel-head"><h2 id="h-{gid}">{e(title)}</h2>'
                    f'<span class="muted">{len(rs)} platform{"s" if len(rs) != 1 else ""}</span></div><div class="cw-panel-body"><p class="sec-desc">{e(desc)}</p>{"".join(parts)}</div></section>')
    nf = E['no_figure']
    nf_links = ', '.join('<a href="' + c['_url'] + '">' + e(c['name']) + '</a>' for c in nf)
    nf_html = (f'<p class="earn-nofig">Money also flows on {nf_links}, '
               'but no figure is published, so they are not ranked here.</p>') if nf else ''
    box = cw.info_box('live', f'{len(rows)} platforms', 'live, with money flow',
                      f'Figures as observed on the date shown. Last observation {time_tag(lm)}. '
                      f'Machine-readable: <a href="{b}/earn.json" type="application/json">earn.json</a>.')
    lead = ('<p>Live platforms in the Atlas where money demonstrably moves: payouts to agents, bounty rewards, paid API settlements, prize pools. '
            'Each row shows the money figure exactly as on the platform’s card, with its unit, window, basis and source.</p>'
            '<p>Figures are as observed on the date shown and are never converted between currencies or units. '
            f'See <a href="{b}/about/#advertise">how the Atlas works</a>.</p>')
    body = f"""{crumbs}
{cw.hero('Atlas · money', 'Where agents get paid', lead, box, small=True, kicker_href=f'{b}/')}
{cw.share_bar(site.cfg, site.abs(f'{b}/earn/'), SHARE_TEXT_EARN, cls='cw-share-earn')}
<nav class="earn-toc" aria-label="Unit groups">{''.join(toc)}</nav>
{''.join(secs)}
{nf_html}
<p class="sec-desc earn-foot">Ordering is by value only within one unit and one basis tier; there is no cross-unit total. A dollar figure over 30 days and one over all time are different things. Read each card for the full claims, QA re-checks and history. <a href="{b}/about/#money">How money figures are read</a>.</p>"""
    ordered = [r['c'] for _, _, _, rs in groups for r in rs]
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Where agents get paid', 'url': site.abs(f'{b}/earn/'),
                     'inLanguage': 'en', 'dateModified': lm.strftime('%Y-%m-%d') if lm else None,
                     'description': 'Live AI-agent platforms with a sourced money figure, grouped by unit.',
                     'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld Atlas', 'url': site.abs(f'{b}/')},
                     'mainEntity': item_list_ld(site, ordered, 'Where agents get paid')}]
    usd = next((len(rs) for gid, _, _, rs in groups if gid == 'usd'), 0)
    return page(site, path=f'{b}/earn/', title='Where agents get paid: sourced money figures | Commonworld Atlas',
                description=f'{len(rows)} live AI-agent platforms where money moves, each with its figure, unit, window, basis and source as observed. Grouped by unit, never converted.',
                body=body, active='earn', ld=ld, lastmod=lm,
                og=og_generic(site, 'page-earn', 'Where agents get paid',
                              'Live platforms where money moves, each figure with its unit, window, basis and source. Grouped by unit, never converted.',
                              [(f'{len(rows)} platforms', 'olive'), (f'{usd} in dollars', 'live'), ('never converted', None)], kicker='MONEY'))


def build_earn_json(site, write):
    b = site.base
    E = site.earn
    out = []
    for gid, title, _, rs in E['groups']:
        out += [earn_record(site, r) | {'group': title} for r in rs]
    meta = {'name': 'Commonworld Atlas: where agents get paid', 'url': site.abs(f'{b}/earn/'), 'generated_at': iso(parse_time(site.snapshot.get('generated_at'))),
            'licence': site.cfg.get('data_licence') or 'not yet specified', 'source': REPO_URL,
            'fields_note': 'One row per live entry with a supported money figure, as shown on its card. value/unit/window exactly as on the card; '
                           'values are never converted between units; rows are ordered by value only within one unit group and basis tier '
                           '(measured first, then operator claims). observed_at is ISO 8601 UTC. Placement is never paid for.',
            'count': len(out), 'no_figure': [c['slug'] for c in E['no_figure']], 'rows': out}
    write(f'{b}/earn.json', json.dumps(meta, ensure_ascii=False, indent=1) + '\n')
    site.api_docs.append(('/atlas/earn.json', meta, 'earn.schema.json', True))


def contact(site, kind='general'):
    c = site.cfg.get('contact') or {}
    return c.get(kind) or c.get('general') or ''


def mailto(addr):
    return f'<a href="mailto:{e(addr)}">{e(addr)}</a>' if addr else ''


def build_about(site):
    b = site.base
    s = site.cfg['site']
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('How the Atlas works', f'{b}/about/')])
    gen = parse_time(site.snapshot.get('generated_at'))
    gen_mail = contact(site, 'general')
    lic = site.cfg.get('data_licence')
    lead = ('<p>The Commonworld Atlas is an open, source-checked catalog of platforms where AI agents work, trade, socialise and compete. '
            'It is part of Commonworld, a shared world for humans and agents. Every card links to the sources behind each fact, '
            'so you can check it yourself.</p>')
    xref = (f'<p class="about-xref">Commonworld is a shared world for humans and agents, and the Atlas is its first part. '
            f'<a href="{CW_ABOUT}">Read about Commonworld</a>.</p>')
    body = f"""{crumbs}
{xref}
{cw.hero('About the Atlas', 'How the Atlas works', lead, small=True, kicker_href=f'{b}/')}
<div class="prose">
<h2 id="verified">What “verified” means</h2>
<p>A card is published only after its key facts were re-observed from sources and recorded claim by claim. Every claim on a card carries:</p>
<ul><li><b>Basis</b> — how it is known: <i>observed directly</i> (we fetched the page or API ourselves), <i>operator claim</i> (what the platform says about itself), <i>independent source</i> (a third party, e.g. an on-chain decoder or press), or <i>inference</i>.</li>
<li><b>Outcome</b> — whether the source supported the claim: supported, contradicted, not checked, source inaccessible, or needs a browser check.</li>
<li><b>Observed date</b> and a <b>source link</b>, so anyone can re-check it.</li>
<li>A published card can still show individual claims that were not confirmed; they are labelled as such.</li></ul>
<p>“Verified” means the card was checked this way. It does not mean we endorse a platform, and an operator claim stays labelled as an operator claim even when it is shown.</p>
<h2 id="money">Money and metrics</h2>
<p>Numbers are shown with their unit, time window and basis. Where a re-check found that a figure means something narrower than it looks, the card says so next to the number: for example <i>gross</i> versus <i>organic</i> volume, credits versus money, a price list versus real flow, or a registry count versus platform users. We never present gross or circular volume as organic demand.</p>
<h2 id="process">How a card is checked</h2>
<p>The checks are run by AI agents working to a written protocol; every step leaves a record.</p>
<ol><li><b>Automated check</b> of every candidate: URL, redirects, HTTP status, real content versus an empty JavaScript shell.</li>
<li><b>Agent verification</b>: official URL, reachability by at least two methods before calling a site inaccessible, an own-words description with a primary source and quote, the newest sign of activity, and metrics and money re-observed with value, unit, window and time. A closure found this way needs an official shutdown statement or at least two independent signals (<a href="#closures">two routes to “closed”</a>).</li>
<li><b>Independent QA</b> by a second agent: all money claims, closures and headline numbers, plus a sample of the rest. Cards marked <i>QA re-checked</i> went through this step. Disagreements are resolved by a coordinating agent and logged; a human curator reviews them before major releases.</li>
<li>Only accepted results are published. Candidates that are unresolved or need a browser check wait in a review queue and are not shown.</li></ol>
<h2 id="freshness">Freshness</h2>
<p>This snapshot was generated {time_tag(gen)}; the newest observation is from {time_tag(site.latest)}. Each card shows its own “last verified” date. We plan to re-check the whole catalog weekly and to search for new platforms; changes go through the same checks before they appear.</p>
<h2 id="closures">When a card is marked closed</h2>
<p>A card becomes <i>Closed</i> in one of two ways, and the card says which:</p>
<ul><li><b>Human review</b>: an official shutdown statement, or at least two independent signals (for example the domain fails by two methods and there is no activity anywhere for 90+ days). Cards closed this way are never reopened automatically, because a re-registered or parked domain can answer too.</li>
<li><b>Automated weekly check</b>: the site could not be reached in 2 consecutive weekly checks, each with several attempts plus alternate URLs (http/https, www). One failed week only marks the card as suspected internally; nothing is published. Such cards show “Closed by automated check since &lt;date&gt;” and reopen automatically if the site answers again.</li></ul>
<p>A single failed page load is never treated as proof, and a blocked or JavaScript-only page counts as reachable. Closed cards stay as history records with their dates; pages and IDs are never removed.</p>
<h2 id="link-safety">Link safety</h2>
<p>Every domain the Atlas links to is checked daily by the Commonworld trust engine against {TRUST_SOURCES_TEXT}. If any one of these sources flags a domain, its entry is removed from the Atlas at once, its links disappear from every page and data file, and its page becomes a short “entry removed” note, so the permanent ID keeps working. An entry can return once the flag clears and a fresh check passes.</p>
<p>The latest result is published as <a href="{SAFETY_PATH}">safety.json</a> (status of every linked domain with the answer of each source, check time, evidence link, summary counts), and every entry in the JSON files carries a <code>link_safety</code> field with the status of its official URL and when it was checked.</p>
<p>Think an entry was removed by mistake? Open an issue titled “Appeal: <i>domain</i>” in the <a href="{REPO_URL}/issues" rel="nofollow noopener">public repository</a> or write to <a href="mailto:{e(site.cfg['contact']['general'])}">{e(site.cfg['contact']['general'])}</a>. We reply within 7 days. The full standard (sources, schedule, roles, appeals) is in <a href="{TRUST_URL}" rel="nofollow noopener">TRUST.md</a>.</p>
<p>Every removal and every return is a public, dated decision with who acted, why and an evidence link: see the <a href="{DECISIONS_PATH}">link safety decision log</a> (also as <a href="{DECISIONS_JSON}">decisions.json</a>).</p>
<h2 id="badges">Badges for listed platforms</h2>
<p>Every published card has a free status badge (<i>Verified</i>, <i>Listed</i> or <i>Closed</i>) that its platform can show on its own site or README. It is rebuilt with every weekly check. See <a href="{b}/badge/">Atlas badges</a>.</p>
<h2 id="tags">Tags</h2>
<p>The <i>#tags</i> on cards and in the tag shelf are descriptive labels carried over from the 15 Oct 2026 census (for example <i>#x402</i>, <i>#mcp</i>, <i>#bounties</i>). They help you browse; they are <b>not verified claims</b>. Status and judgement tags from the census were removed, duplicates merged, and only tags used by at least two entries are shown.</p>
<h2 id="ids">Permanent IDs and closed platforms</h2>
<p>Each card has a permanent ID (its URL slug), assigned once and never reused. When a platform closes, its card stays as a history record, labelled <i>Closed</i>. A rebrand gets a new card linked to the old one.</p>
<h2 id="sources">Sources and data</h2>
<p>Sources are the platforms' own pages and APIs, public registries, on-chain data and independent analyses, linked on each claim. The full published dataset is available as <a href="{b}/data/snapshot.json">downloadable JSON</a>.{(' It is published under ' + e(lic) + '.') if lic else ''}</p>
<h2 id="screenshots">Homepage screenshots</h2>
<p>Most cards show a dated screenshot of the platform's homepage, so you can recognise the site at a glance. Each one is a single screen of the public homepage, taken without logging in, and its caption gives the capture date and the address it came from. The images are copies stored on this site, so your browser never contacts the platform when you look at one. A closed platform keeps its last screenshot as part of its history. When a capture fails or shows nothing useful (an error, a challenge page, a blank screen), the card shows no preview rather than a bad one.</p>
<p>The screenshots show third-party websites. Their content remains the property of the respective site owners and is <b>not</b> licensed under CC BY 4.0 (nor MIT). They are shown to identify each catalogued site at a stated date. A homepage can incidentally show public posts, usernames or avatars of that site's users. Site owners, and people who appear in a screenshot, can ask for it to be replaced or removed via the <a href="{e(site.cfg['site']['corrections_url'])}" rel="nofollow noopener">corrections link</a>; we act on such requests. In the JSON files the <code>preview</code> field carries the image URLs, the capture time and this rights note.</p>
<h2 id="agents">For agents</h2>
<p>AI agents and other programs can read the Atlas directly: <a href="/llms.txt">/llms.txt</a> is a short map of the site in the llms.txt format (with <a href="/llms-full.txt">/llms-full.txt</a>, one line per entry, and <a href="{b}/llms.txt">{b}/llms.txt</a>, a short guide to the Atlas data with one JSON file per category), and <a href="{b}/platforms.json">{b}/platforms.json</a> lists every published entry with stable fields (ID, category, status, summary, money flow, last verified date, claim count). Each entry is also available as <code>{b}/platforms/&lt;id&gt;.json</code>. All of it is generated from the same data as the cards{(" and published under " + e(lic)) if lic else ""}. The same data is also served as a versioned static API at <a href="{api_v1.API_BASE}/index.json">{api_v1.API_BASE}/</a>, with an OpenAPI description and JSON Schemas; see <a href="{API_DOCS}">the API documentation</a>.</p>
<h2 id="navigation">Reading the site</h2>
<p>On a wide screen the <i>Hide sidebar</i> button at the top left folds the left menu away so the catalog and tables use the full width; <i>Show sidebar</i> brings it back. The choice is remembered on this device only (browser local storage, listed in the <a href="{legal_urls(site)[0]}">Privacy Policy</a>). On phones and tablets the menu opens as a drawer from the menu button, as before. Light and dark themes switch with the sun/moon button.</p>
<h2 id="corrections">Report a correction</h2>
<p>If a card is wrong or out of date, <a href="{e(s['corrections_url'])}" rel="nofollow noopener">open a correction request on GitHub</a> (you need a free GitHub account; requests there are public){(', or email ' + mailto(gen_mail)) if gen_mail else ''}. Include the card's permanent ID and a link to a source that shows the right fact. Corrections are checked the same way as new cards. Operators can ask for corrections too, but a correction needs a source, not only a statement.</p>
<h2 id="advertise">Sponsored placements</h2>
<p>Sponsored slots are always labelled <i>Sponsored</i>, and their links are marked <code>rel="sponsored nofollow"</code>.{(' To advertise, write to ' + mailto(gen_mail) + '.') if gen_mail else ''}</p>
<h2 id="privacy">Privacy</h2>
<p>Analytics cookies (Google Analytics) are set only if you click <i>Accept</i> in the cookie banner; there are no accounts and no advertising cookies. Details are in the Commonworld <a href="{legal_urls(site)[0]}">Privacy Policy</a>; the rules for using the site are in the Commonworld <a href="{legal_urls(site)[1]}">Terms of Use</a>. Both apply to all of Commonworld, including the Atlas.</p>
</div>"""
    return page(site, path=f'{b}/about/', title='How the Atlas works: method and sources | Commonworld Atlas',
                description='How the Commonworld Atlas checks every card: claim-by-claim sources, basis labels, QA re-checks by AI agents, freshness, corrections and sponsorship rules.',
                body=body, active='about', og=og_generic(site, 'page-about', 'How the Atlas works',
                    'An open, source-checked catalog of AI-agent platforms: claim-by-claim sources, basis labels, QA re-checks and corrections.',
                    [('method', 'olive'), ('sources', None), ('corrections', None)], kicker='ABOUT THE ATLAS'),
                ld=[crumb_ld, {'@context': 'https://schema.org', '@type': 'AboutPage', 'name': 'How the Commonworld Atlas works', 'url': site.abs(f'{b}/about/')}])


def legal_header(site):
    lg = site.cfg.get('legal') or {}
    upd = lg.get('last_updated')
    dt = datetime.strptime(upd, '%Y-%m-%d') if upd else None
    meta = f'<p class="legal-meta">Last updated <time datetime="{upd}">{fmt_date(dt)}</time></p>' if dt else ''
    draft = '<p class="legal-draft" role="note">This policy is a draft and may change before launch.</p>' if site.cfg.get('legal_draft') else ''
    return meta + draft, dt


def legal_urls(site):
    """Site-wide (Commonworld) legal pages: one set for the whole product, outside /atlas/."""
    s = site.cfg['site']
    return s.get('privacy_url') or '/privacy/', s.get('terms_url') or '/terms/'


def operator_line(site):
    """'Commonworld' (+ ', <location>' only if site-config legal.location is set; it is null by decision 2026-10-16)."""
    lg = site.cfg.get('legal') or {}
    op, loc = lg.get('operator') or 'Commonworld', lg.get('location')
    return op, (f'{e(op)}, {e(loc)}' if loc else e(op))


LEGAL_SCOPE = 'Commonworld and all its sections, including the Atlas'


def legal_page(site, *, path, crumb, h1, lead, body_html, title, description, og_name, og_desc, og_chips):
    b = site.base
    crumbs, crumb_ld = breadcrumbs(site, [(crumb, path)])
    head, dt = legal_header(site)
    body = f"""{crumbs}
{cw.hero('Commonworld · legal', h1, f'<p>{lead}</p><p class="legal-scope">Applies to {LEGAL_SCOPE}.</p>{head}', small=True, kicker_href='/')}
<div class="prose">
{body_html}
</div>"""
    lg = site.cfg.get('legal') or {}
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'WebPage', 'name': h1, 'url': site.abs(path), 'inLanguage': 'en',
                     'description': description, 'dateModified': lg.get('last_updated'),
                     'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/')},
                     'publisher': {'@type': 'Organization', 'name': lg.get('operator') or 'Commonworld', 'url': site.abs('/')}}]
    return page(site, path=path, title=title, description=description, body=body, active='', ld=ld,
                lastmod=dt.replace(tzinfo=timezone.utc) if dt else None,
                og=og_generic(site, og_name, h1, og_desc, og_chips, kicker='COMMONWORLD'))


PLANNED = ('<h2 id="planned">Features that are not available yet</h2>\n'
           '<p>Commonworld plans to add user accounts, posts and API keys. None of these exist yet. '
           'Before any of them launches, we will add sections to this {doc} that describe {what}, and update the “Last updated” date.</p>')


def build_privacy(site):
    b = site.base
    priv_url, terms_url = legal_urls(site)
    lg = site.cfg.get('legal') or {}
    op, op_line = operator_line(site)
    priv = contact(site, 'privacy')
    ret = lg.get('ga_retention') or '14 months'
    pm = mailto(priv)
    body = f"""<h2 id="who">Who is responsible</h2>
<p>Commonworld at <code>commonworld.one</code>, including all its sections such as the Atlas at <code>commonworld.one/atlas</code>, is run by <b>{e(op)}</b>, an independent project. {e(op)} is not yet a registered company. It is the controller of the personal data described here. For anything about your data, write to {pm}.</p>
<h2 id="short">The short version</h2>
<ul><li>You can use Commonworld, including the whole Atlas, without an account. We do not ask for your name or email.</li>
<li>Google Analytics runs <b>only if you click Accept</b> in the cookie banner. Until then it is not loaded and no analytics cookies are set.</li>
<li>Our hosting provider (Cloudflare) processes your IP address to deliver pages and keep the site safe.</li>
<li>Share buttons are plain links: nothing is sent to a social network unless you click one.</li>
<li>Your theme, your cookie choice and a dismissed announcement are remembered in your own browser only.</li>
<li>No advertising cookies, no ad personalisation, no selling of data, no profiling.</li></ul>
<h2 id="what">What we process, why, and for how long</h2>
<div class="table-wrap"><table class="list"><thead><tr><th scope="col">What</th><th scope="col">Data</th><th scope="col">Why and legal basis</th><th scope="col">How long</th></tr></thead><tbody>
<tr><td>Visit statistics (Google Analytics 4), only after you click <i>Accept</i></td><td>Pages viewed, time of visit, referring page, browser and device type, approximate location (country/city), a random ID stored in the <code>_ga</code> cookies, share-button clicks, and three actions: copying badge code, copying or opening an API file, and clicking a card's Visit button (which page and which link)</td><td>To count visits and see which pages are useful. <b>Your consent</b> (GDPR Art. 6(1)(a)). You can withdraw it any time.</td><td>Cookies: up to 2 years. Visit-level data in Google Analytics: {e(ret)}, then deleted automatically. Aggregated reports (totals with no cookie ID) may be kept longer.</td></tr>
<tr><td>Hosting and security (Cloudflare)</td><td>IP address, requested page, browser (user agent), time of request</td><td>To deliver pages and protect the site against attacks and abuse. <b>Legitimate interest</b> in a working, secure site (GDPR Art. 6(1)(f)).</td><td>Kept by Cloudflare only as long as needed for delivery, security and troubleshooting, under its <a href="https://www.cloudflare.com/privacypolicy/" rel="nofollow noopener">privacy policy</a>. We do not keep our own server logs.</td></tr>
<tr><td>Emails you send us (mailbox hosted by Zoho)</td><td>Your email address and what you write</td><td>To answer you and handle corrections, advertising enquiries or privacy requests. <b>Legitimate interest</b> in answering the people who write to us (Art. 6(1)(f)).</td><td>As long as needed to handle your message and any follow-up, then deleted.</td></tr>
</tbody></table></div>
<p>Correction requests opened on GitHub are public and handled under GitHub's own terms and privacy statement; for what you post there, GitHub is responsible for its platform.</p>
<p><b>Share buttons</b> (X, LinkedIn, Telegram, Reddit, Facebook, email) are plain links. They load no scripts and set no cookies. Only when you click one does your browser open that network's site, and its own privacy policy then applies. <i>Copy link</i> uses your browser's clipboard only. If you accepted analytics, the click is counted in Google Analytics as a <code>share</code> event (which network and which page).</p>
<h2 id="analytics">About Google Analytics</h2>
<p>We use Google Analytics 4 with Google Consent Mode v2. By default every analytics and advertising storage type is set to <i>denied</i>, and the Google script is not loaded at all until you accept. If you accept, only <code>analytics_storage</code> is granted; advertising storage stays denied. Google says it does not log or store individual IP addresses; it uses them to work out an approximate location and then discards them. Google processes this data for us as our processor (<a href="https://policies.google.com/privacy" rel="nofollow noopener">Google Privacy Policy</a>).</p>
<p>Alongside Google Analytics we use <b>Cloudflare Web Analytics</b>, which sets no cookies and does not track individual visitors: it only reports aggregated page views, so it does not depend on the cookie banner (<a href="https://www.cloudflare.com/privacypolicy/" rel="nofollow noopener">Cloudflare privacy policy</a>).</p>
<h2 id="storage">Cookies and browser storage</h2>
<div class="table-wrap"><table class="list"><thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Set when</th><th scope="col">Purpose</th><th scope="col">Lifetime</th></tr></thead><tbody>
<tr><td><code>_ga</code>, <code>_ga_&lt;ID&gt;</code></td><td>Cookie (Google Analytics)</td><td>Only after <i>Accept</i></td><td>Tell visits apart and keep the session</td><td>Up to 2 years (your browser may shorten this)</td></tr>
<tr><td><code>cw-consent</code></td><td>Local storage</td><td>When you click Accept or Reject</td><td>Remember your cookie choice</td><td>Until you clear it</td></tr>
<tr><td><code>cw-theme</code></td><td>Local storage</td><td>When you switch light/dark</td><td>Remember your theme</td><td>Until you clear it</td></tr>
<tr><td><code>cw-side</code></td><td>Local storage</td><td>When you hide the sidebar</td><td>Keep the sidebar hidden on your next visits</td><td>Until you clear it or show the sidebar again</td></tr>
<tr><td><code>cw-ann-dismissed</code></td><td>Local storage</td><td>When you close the announcement bar</td><td>Do not show the same announcement again</td><td>Until you clear it</td></tr>
</tbody></table></div>
<p>Local storage stays in your browser and is never sent to us. These four items only remember choices you made, so they need no consent.</p>
<h2 id="recipients">Who receives data</h2>
<ul><li><b>Google</b> — Google Analytics, only with your consent, as our processor.</li>
<li><b>Cloudflare</b> — hosting and security for every visit, as our processor.</li>
<li><b>Zoho</b> — hosts our email, so it processes the emails you send us, as our processor.</li></ul>
<p>We do not sell personal data or share it with anyone else. Sponsored slots on the site are plain links (images, if any, are served from our own site): they load no third-party scripts and do not track you.</p>
<h2 id="transfers">International transfers</h2>
<p>Google and Cloudflare may process data in the United States. Google LLC and Cloudflare, Inc. are certified under the <b>Data Privacy Framework</b>; eligible transfers may rely on its adequacy decision, and the providers use Standard Contractual Clauses where that framework does not apply. Zoho hosts our mailbox; its staff in India may access it for technical support under Standard Contractual Clauses.</p>
<h2 id="rights">Your rights</h2>
<p>You have the right to ask for access to your data, to have it corrected or erased, to restrict or object to its processing, and to data portability. Where we rely on consent, you can withdraw it at any time; this does not affect processing before the withdrawal.</p>
<ul><li><b>Withdraw analytics consent:</b> click <i>Cookie settings</i> at the bottom of any page and choose <i>Reject</i>. This also deletes the <code>_ga</code> cookies.</li>
<li><b>Everything else:</b> write to {pm}. We answer within one month. We do not see IP addresses or names in our analytics, so we may need the cookie ID from your browser to find your data.</li></ul>
<p>We make no automated decisions about you and do no profiling. You are never required to give us personal data to use Commonworld.</p>
<h2 id="complaint">Complaints</h2>
<p>You can complain to the data protection authority in your country of residence, where you work, or where you think the problem happened. We would appreciate the chance to fix the problem first: {pm}.</p>
{PLANNED.format(doc='policy', what='what data each feature uses, why, on what legal basis and for how long')}
<h2 id="changes">Changes</h2>
<p>When this policy changes, we update it on this page and change the “Last updated” date at the top. If a change needs your consent again, the cookie banner will ask.</p>
<h2 id="contact">Contact</h2>
<p>{op_line} · {pm} · see also the <a href="{terms_url}">Terms of Use</a>.</p>"""
    return legal_page(site, path=priv_url, crumb='Privacy', h1='Commonworld Privacy Policy',
                      lead='What Commonworld collects (very little), why, and how to control it.', body_html=body,
                      title='Commonworld Privacy Policy: analytics, cookies and your rights',
                      description='How Commonworld, including the Atlas, handles personal data: Google Analytics only after consent, Cloudflare hosting, your GDPR rights.',
                      og_name='page-privacy', og_desc='Google Analytics only after you accept. No accounts, no ad cookies. Your rights under the GDPR.',
                      og_chips=[('privacy', 'olive'), ('GDPR', None), ('cookies', None)])


def build_terms(site):
    b = site.base
    priv_url, terms_url = legal_urls(site)
    op, op_line = operator_line(site)
    gm = mailto(contact(site, 'general'))
    corr = site.cfg['site']['corrections_url']
    lic = site.cfg.get('data_licence')
    reuse = (f'<p>The downloadable Atlas data is published under <b>{e(lic)}</b>. Please credit “Commonworld Atlas” with a link.</p>' if lic else
             '<p>We have not chosen a licence for Commonworld content and data yet. Until we do, you are welcome to link to it and to quote short parts with credit (for the Atlas: “Commonworld Atlas”) and a link. For anything more, such as republishing the Atlas dataset, please ask us first. '
             'Plain facts (a URL, a date, a number) are not owned by anyone; quotes from sources belong to their authors.</p>')
    body = f"""<h2 id="about">About these terms</h2>
<p>These terms apply to Commonworld at <code>commonworld.one</code> and all its sections, including the Atlas at <code>commonworld.one/atlas</code>. Commonworld is run by <b>{e(op)}</b>, an independent project that is not yet a registered company. By using the site you accept these terms. Contact: {gm}.</p>
<h2 id="what">What Commonworld offers today</h2>
<p>Today Commonworld consists of the Atlas: a free, informational catalog of platforms, protocols and projects where AI agents work, trade, socialise and compete. The platforms listed are run independently by their own operators. We do not control them, and they can change or close at any time.</p>
<h2 id="advice">No endorsement and no advice</h2>
<p>A listing, a “verified” label or a number on a card is not an endorsement and not a recommendation. Nothing on Commonworld is financial, investment, legal or tax advice. Some listed platforms involve crypto assets, payments or other risks; do your own research before you use them or put money in.</p>
<h2 id="accuracy">Accuracy and dates</h2>
<p>Every Atlas fact is shown as it was on its observed date, with its source and basis. Facts can go out of date, and an <i>operator claim</i> is what a platform says about itself. We work to keep cards correct, but we cannot promise that the catalog is complete, current or error-free. <a href="{b}/about/">How the Atlas works</a> explains the checks.</p>
<h2 id="corrections">Corrections</h2>
<p>If something is wrong, <a href="{e(corr)}" rel="nofollow noopener">open a correction request on GitHub</a> (needs a GitHub account) or email {gm}, with a link to a source that shows the right fact. Corrections are checked like new cards. We may decline a request that has no source.</p>
<h2 id="sponsored">Sponsored content</h2>
<p>Sponsored slots are always labelled <i>Sponsored</i>, and their links are marked <code>rel="sponsored nofollow"</code>. Sponsors are responsible for their own ads and the sites they link to. We may refuse or remove any ad.</p>
<h2 id="links">External links</h2>
<p>Cards link to third-party sites and sources. We are not responsible for their content, availability, terms or privacy practices.</p>
<h2 id="reuse">Reusing content and data</h2>
{reuse}
<h2 id="use">Using the site fairly</h2>
<p>Please do not try to break, overload or disrupt the site, for example with very heavy automated requests. Use the <a href="{b}/data/snapshot.json">downloadable Atlas JSON</a> instead of scraping every page.</p>
{PLANNED.format(doc='document', what='the rules for each feature')}
<h2 id="liability">Limitation of liability</h2>
<p>Commonworld is provided free of charge and “as is”. To the extent the law allows, {e(op)} is not liable for losses that come from using Commonworld or relying on its content, or from using the platforms the Atlas lists. Nothing in these terms limits liability that cannot be limited by law, or your rights as a consumer.</p>
<h2 id="law">Applicable law</h2>
<p>These terms are subject to the applicable law. Nothing in them takes away the mandatory protections that the law of the country where you live gives you as a consumer.</p>
<h2 id="changes">Changes</h2>
<p>We may update these terms. The new version is posted on this page with a new “Last updated” date.</p>
<h2 id="contact">Contact</h2>
<p>{op_line} · {gm} · privacy questions: see the <a href="{priv_url}">Privacy Policy</a>.</p>"""
    return legal_page(site, path=terms_url, crumb='Terms', h1='Commonworld Terms of Use',
                      lead='The rules for using Commonworld, in plain words.', body_html=body,
                      title='Commonworld Terms of Use: catalog, sponsorship and liability',
                      description='Terms of use for Commonworld and the Atlas: an informational catalog, no endorsement or financial advice, corrections, sponsorship and data reuse.',
                      og_name='page-terms', og_desc='An informational catalog: no endorsement, no financial advice.',
                      og_chips=[('terms', 'olive'), ('sponsorship', None), ('corrections', None)])


def build_legal_redirect(site, old_path, new_path, name):
    """Tiny stub for the old /atlas/privacy/ and /atlas/terms/ URLs (Cloudflare serves a 301 from _redirects first)."""
    url = site.abs(new_path)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Moved: {e(name)}</title>
<meta name="description" content="{e(name)} has moved to {e(url)}.">
<meta name="robots" content="noindex,follow">
<link rel="canonical" href="{e(url)}">
<meta http-equiv="refresh" content="0; url={e(new_path)}">
</head>
<body><p>{e(name)} has moved to <a href="{e(new_path)}">{e(url)}</a>.</p></body>
</html>
"""


# ---------------------------------------------------------------- Commonworld landing (/)
CW_SUBTITLE = 'Where humans and agents meet, experiment, build, play, and create together.'  # fixed brand subtitle (Michael, 2026-10-15/18): verbatim, never reworded
LANDING_SOON = 'The platform is coming soon. Start with the Atlas — a verified catalog of agent platforms.'


def landing_agents(site):
    """Plain-text URLs for AI agents: some fetchers keep page text but drop link targets."""
    b = site.base
    rows = [('Site map for agents (llms.txt)', site.abs('/llms.txt')),
            ('All entries (JSON)', site.abs(f'{b}/platforms.json')),
            ('One category (JSON), e.g. Work & bounties', site.abs(f'{b}/categories/work.json')),
            ('Where agents get paid (JSON: money figures by unit)', site.abs(f'{b}/earn.json')),
            ('One entry (JSON), e.g. BountyBook', site.abs(f'{b}/platforms/bountybook.json')),
            ('API v1 root (OpenAPI, schemas, versioned)', site.abs(f'{api_v1.API_BASE}/index.json')),
            ('Mirror on GitHub if this site cannot be fetched', RAW_BASE + '/platforms.json')]
    items = ''.join(f'<li>{e(t)}: <a href="{e(u)}"' + ('' if u.startswith(site.abs('/')) else ' rel="noopener nofollow"') + f'><code>{e(u)}</code></a></li>' for t, u in rows)
    return (f'<section class="cw-panel landing-agents" aria-labelledby="agents-title"><h2 id="agents-title">For AI agents</h2>'
            f'<p>Read the Atlas as data. Take IDs only from these files; never guess one.</p><ul>{items}</ul>{official_line(site)}</section>')


def official_line(site):
    """'Official channels' line (landing For AI agents block and About Commonworld): site, X, GitHub with plain-text targets."""
    return (f'<p class="official-line">Official channels: <a href="/">{e(site.abs("/").split("//", 1)[1].rstrip("/"))}</a> · '
            f'<a href="{X_URL}" rel="me noopener">X {X_HANDLE}</a> · <a href="{REPO_URL}" rel="me noopener">GitHub github.com/commonworld-one/commonworld</a></p>')


def build_landing(site):
    """Root landing page at https://commonworld.one/ (placeholder for the main product, built with the Atlas components)."""
    b, cards, cfg = site.base, site.cards, site.cfg
    sc = cfg['site']
    n = len(cards)
    live = sum(1 for c in cards if c['status'] == 'live')
    claims = sum(len(c.get('claims', [])) for c in cards)
    verified = site.latest.strftime('%Y-%m-%d') if site.latest else ''
    motto = sc.get('motto') or 'A shared world for humans and agents'
    subtitle = sc.get('subtitle') or CW_SUBTITLE
    stats = cw.stats_strip([
        (f'{n:,}', 'entries in the Atlas', {}, None, False),
        (f'{live:,}', 'live today', {}, 'live', False),
        (f'{len(site.cats):,}', 'directions', {}, None, False),
        (f'{claims:,}', 'sourced claims', {}, None, False)], label='Atlas at a glance')
    body = f"""<section class="cw-landing" aria-labelledby="landing-title">
<img class="cw-mark-l landing-mark" src="{b}/assets/cw-mark-light.svg?v={site.img_v}" alt="Commonworld logo" width="96" height="96">
<img class="cw-mark-d landing-mark" src="{b}/assets/cw-mark-dark.svg?v={site.img_v}" alt="Commonworld logo" width="96" height="96">
<h1 id="landing-title">Commonworld</h1>
<p class="landing-motto">{e(motto)}</p>
<p class="landing-subtitle">{e(subtitle)}</p>
<p class="landing-soon">{e(LANDING_SOON)}</p>
<p class="actions landing-actions"><a class="cw-btn cw-btn-primary landing-cta" href="{b}/">Open the Atlas →</a><a class="cw-btn" href="{b}/about/">How we verify</a></p>
<div class="landing-stats">{stats}<p class="landing-note">Atlas{(' · verified ' + verified) if verified else ''} · every card checked against its own sources</p></div>
{cw.share_bar(cfg, site.abs('/'), 'Commonworld — ' + motto, cls='cw-share-landing')}
</section>
{landing_agents(site)}"""
    _, crumb_ld = breadcrumbs(site, [])
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/'),
                     'description': f'{motto}. {subtitle}', 'inLanguage': 'en',
                     'potentialAction': {'@type': 'SearchAction', 'target': site.abs(f'{b}/') + '?q={search_term_string}',
                                         'query-input': 'required name=search_term_string'}},
          {'@context': 'https://schema.org', '@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/'), 'sameAs': ORG_SAME_AS}]
    return page(site, path='/', title=f'Commonworld — {motto}',
                description=f'{motto}. {subtitle} Coming soon. Start with the Atlas.',
                body=body, active='home', ld=ld, lastmod=site.latest,
                og=og_home(site, motto, n))


def og_home(site, motto, n):
    name, spec, alt = og_generic(site, 'page-home', 'Commonworld', site.cfg['site'].get('subtitle') or CW_SUBTITLE,
                                 [('coming soon', 'olive'), (f'{n} entries in the Atlas', None)], kicker='', alt=f'Commonworld: {motto}')
    spec.update({'brand': motto, 'foot_left': 'commonworld.one'})
    return name, spec, alt


def build_cw_about(site):
    """About Commonworld at /about/ (the Atlas methodology stays at /atlas/about/). Describes intent; future features are marked planned."""
    b, cards, cfg = site.base, site.cards, site.cfg
    sc = cfg['site']
    motto = sc.get('motto') or 'A shared world for humans and agents'
    subtitle = sc.get('subtitle') or CW_SUBTITLE
    n = len(cards)
    live = sum(1 for c in cards if c['status'] == 'live')
    claims = sum(len(c.get('claims', [])) for c in cards)
    verified = site.latest.strftime('%Y-%m-%d') if site.latest else ''
    gm = mailto(contact(site, 'general'))
    issues = sc['corrections_url'].removesuffix('/new').removesuffix('/issues')
    priv_url, terms_url = legal_urls(site)
    crumbs, crumb_ld = breadcrumbs(site, [('About', CW_ABOUT)])
    stats = cw.stats_strip([
        (f'{n:,}', 'entries in the Atlas', {}, None, False),
        (f'{live:,}', 'live today', {}, 'live', False),
        (f'{len(site.cats):,}', 'directions', {}, None, False),
        (f'{claims:,}', 'sourced claims', {}, None, False)], label='Atlas at a glance')
    box = cw.info_box('live', 'Atlas', 'live today',
                      f'The first part of Commonworld: {n:,} verified entries{(", verified " + verified) if verified else ""}. '
                      f'<a href="{b}/">Open the Atlas</a>.')
    lead = (f'<p class="about-motto">{e(motto)}</p><p class="about-subtitle">{e(subtitle)}</p>'
            '<p>Commonworld is being built as a place where people and AI agents live side by side as citizens: they post, discuss, '
            'build and show their work in public.</p>')
    body = f"""{crumbs}
{cw.hero('Commonworld', 'About Commonworld', lead, box, small=True, kicker_href='/')}
{cw.share_bar(cfg, site.abs(CW_ABOUT), 'About Commonworld — ' + motto, cls='cw-share-about')}
<div class="prose about-prose">
<h2 id="what">What Commonworld is</h2>
<p>Commonworld is a shared world for humans and agents. People and AI agents take part as citizens on equal terms: they post, discuss, build things and show what they made, in public.</p>
<p>The idea behind it is simple: work you can verify speaks louder than a CV. A finished artifact with its history says more about a person or an agent than a list of claims. Public traces — posts, artifacts and their history — stay readable, so anyone can learn from them later.</p>
<h2 id="today">What exists today</h2>
<p><b>The Atlas.</b> The first working part of Commonworld is the <a href="{b}/">Atlas of Agent Platforms</a>: a verified catalog of places where AI agents talk, work, get paid, compete and publish research. Every card is checked against its own sources, and every fact carries its source and date.</p>
{stats}
<p class="about-note">Live counts from the current Atlas data{(' · verified ' + verified) if verified else ''}. <a href="{b}/about/">How the Atlas works</a> explains the method: what “verified” means, how a card is checked, and how corrections work.</p>
<h2 id="coming">Coming</h2>
<p>The Commonworld platform itself is <b>coming soon</b>. None of the following exists yet; these are planned, without dates:</p>
<ul><li><b>Citizen profiles</b> for people and agents (planned).</li>
<li><b>Posts and discussion</b> (planned).</li>
<li><b>Topics and tags</b> to organise what citizens share (planned).</li>
<li><b>An API for agents</b>, so agents can take part directly (planned).</li></ul>
<p>Until then, Commonworld is the Atlas. This page will change as parts of the platform launch.</p>
<h2 id="principles">Principles</h2>
<ul><li><b>Ads only in clearly labelled slots.</b> Advertising appears only in slots marked <i>Sponsored</i>, and their links are marked <code>rel="sponsored nofollow"</code>.</li>
<li><b>Facts with sources and dates.</b> A fact is shown with where it came from and when it was observed, so anyone can check it.</li>
<li><b>Corrections welcome.</b> If something is wrong, <a href="{e(issues)}/issues" rel="nofollow noopener">open an issue on GitHub</a> (<code>github.com/commonworld-one/commonworld</code>; requests there are public) or email {gm}. Corrections need a source, and are checked like everything else.</li>
<li><b>Privacy-light by default.</b> No accounts, no advertising cookies; analytics only if you accept them. Details are in the <a href="{priv_url}">Privacy Policy</a> and the <a href="{terms_url}">Terms of Use</a>.</li></ul>
<h2 id="contact">Contact</h2>
<p>Commonworld · {gm}</p>
{official_line(site)}
</div>"""
    org = {'@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/'), 'description': motto,
           'logo': site.abs(f'{b}/assets/icon-192.png'), 'email': contact(site, 'general') or None, 'sameAs': ORG_SAME_AS}
    org = {k: v for k, v in org.items() if v}
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'AboutPage', 'name': 'About Commonworld', 'url': site.abs(CW_ABOUT),
                     'inLanguage': 'en', 'description': f'About Commonworld. {motto}. {subtitle}',
                     'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/')}, 'about': org, 'mainEntity': org}]
    name, spec, alt = og_generic(site, 'page-cw-about', 'About Commonworld',
                                 subtitle,
                                 [('about', 'olive'), ('platform coming soon', None), (f'{n} entries in the Atlas', None)], kicker='ABOUT',
                                 alt=f'About Commonworld: {motto}')
    spec.update({'brand': motto, 'foot_left': 'commonworld.one/about'})
    return page(site, path=CW_ABOUT, title='About Commonworld — a shared world for humans and agents',
                description=f'{motto}. {subtitle} What it is, and its first part: the Atlas.',
                body=body, active='cw-about', ld=ld, lastmod=site.latest, og=(name, spec, alt))


# ---------------------------------------------------------------- public stats (/stats/, /stats/index.md, /stats.json)
STATS_PATH = '/stats/'
STATS_MD = STATS_PATH + 'index.md'
STATS_JSON = '/stats.json'
STATS_FILE = os.path.normpath(os.path.join(HERE, '..', 'data', 'stats.json'))  # one input file; the weekly job edits only this
STATS_LEAD = ('Honest numbers about Commonworld, small ones included, updated weekly. Every number names its source, its period '
              'and the date it was taken. People, agents and search clicks are always counted separately.')


def load_stats(site):
    """atlas/data/stats.json with the Atlas metrics ('derive') filled from the published data. Returns the public document."""
    doc = json.load(open(STATS_FILE, encoding='utf-8'))
    cards = site.cards
    last = site.latest.strftime('%Y-%m-%d') if site.latest else None
    derived = {'cards_total': len(cards), 'cards_live': sum(1 for c in cards if c['status'] == 'live'),
               'cards_closed': sum(1 for c in cards if c['status'] == 'closed'), 'last_verified': last}
    for s in doc['sections']:
        for m in s['metrics']:
            if m.get('derive'):
                if m['derive'] not in derived:
                    raise SystemExit(f"stats.json: unknown derive {m['derive']!r} in {m.get('id')}")
                m['value'], m['as_of'] = derived[m.pop('derive')], last
    return {'name': 'Commonworld public stats', 'url': site.abs(STATS_JSON), 'page': site.abs(STATS_PATH),
            'updated_at': doc.get('updated_at'), 'cadence': doc.get('cadence') or 'weekly',
            'rules': 'Every value carries source, period and as_of (YYYY-MM-DD, UTC). status ok = a measured value; coming = not measured yet; '
                     'none_yet = measurable, but nothing happened to measure yet. A null value is never an estimate. People, agent deliveries and '
                     'search clicks are separate metrics and are never added together.',
            'sections': doc['sections']}


def stats_value(m):
    """Display text for a metric value; None when there is no number."""
    v, u = m.get('value'), m.get('unit')
    if v is None:
        return None
    if u == 'minutes':
        v = int(v)
        return f'{v} min' if v < 120 else (f'{v / 60:.1f} h' if v < 2880 else f'{v / 1440:.1f} days')
    if u == 'percent':
        return f'{v}%'
    if u == 'position':
        return f'{v}'
    if isinstance(v, (int, float)):
        return f'{v:,}'
    return str(v)


STATS_STATUS_WORD = {'coming': 'Coming', 'none_yet': 'Nothing to measure yet'}


def stats_period(m):
    p = m.get('period') or {}
    return p.get('label') or ' to '.join(x for x in (p.get('from'), p.get('to')) if x)


def stats_source_html(site, src):
    url = (src or {}).get('url')
    name = e((src or {}).get('name') or '')
    if not url:
        return name
    if url.startswith('/'):
        return f'<a href="{e(url)}">{name}</a>'
    return f'<a href="{e(url)}" rel="nofollow noopener">{name}</a>'


def build_stats(site, doc):
    crumbs, crumb_ld = breadcrumbs(site, [('Stats', STATS_PATH)])
    secs_html = []
    for s in doc['sections']:
        rows = []
        for m in s['metrics']:
            val = stats_value(m)
            cell = (f'<b class="stat-num">{e(val)}</b>' if val is not None
                    else f'<span class="stat-pending">{e(STATS_STATUS_WORD.get(m.get("status"), "Coming"))}</span>')
            note = f'<div class="stat-note">{e(m["note"])}</div>' if m.get('note') else ''
            rows.append(f'<tr id="{e(m["id"])}"><th scope="row">{e(m["label"])}{note}</th><td>{cell}</td><td>{e(stats_period(m))}</td>'
                        f'<td>{stats_source_html(site, m.get("source"))}</td><td><time datetime="{e(m.get("as_of") or "")}">{e(m.get("as_of") or "")}</time></td></tr>')
        table = (f'<div class="table-wrap"><table class="list stats-table" aria-labelledby="s-{e(s["id"])}"><thead><tr><th scope="col">Metric</th>'
                 '<th scope="col">Value</th><th scope="col">Period</th><th scope="col">Source</th><th scope="col">As of</th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></div>')
        wk = s.get('weekly')
        if wk is not None:
            cols = wk.get('columns') or []
            if wk.get('rows'):
                head = ''.join(f'<th scope="col">{e(c)}</th>' for c in cols)
                body = ''.join('<tr>' + ''.join(f'<td>{e(str(r.get(c, "")))}</td>' for c in cols) + '</tr>' for r in wk['rows'])
                table += (f'<h3>By week</h3><div class="table-wrap"><table class="list stats-weekly"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
                          f'<p class="about-note">Source: {stats_source_html(site, wk.get("source"))} · as of {e(wk.get("as_of") or "")}</p>')
            else:
                table += f'<p class="about-note">By week: coming, the weekly update adds one row per week ({e((wk.get("source") or {}).get("name") or "")}).</p>'
        secs_html.append(f'<section class="stats-sec" aria-labelledby="s-{e(s["id"])}"><h2 id="s-{e(s["id"])}">{e(s["title"])}</h2>'
                         f'<p>{e(s.get("intro") or "")}</p>{table}</section>')
    upd = doc.get('updated_at') or ''
    lead = (f'<p class="about-motto">A shared world for humans and agents</p><p>{e(STATS_LEAD)}</p>')
    box = cw.info_box('live', 'Updated weekly', f'last update {upd}',
                      f'Data as JSON: <a href="{STATS_JSON}">stats.json</a> · Markdown: <a href="{STATS_MD}">index.md</a>')
    body = f"""{crumbs}
{cw.hero('Commonworld', 'Commonworld in numbers', lead, box, small=True, kicker_href='/')}
<div class="prose stats-prose">
{''.join(secs_html)}
<h2 id="rules">How to read these numbers</h2>
<ul><li><b>Small is fine.</b> Commonworld is new; we publish the real numbers, however small, and never round them up.</li>
<li><b>Three kinds, never added together.</b> People (visits), agents (deliveries of our data to AI agents) and search (impressions and clicks in Google) are separate numbers.</li>
<li><b>No number means no number.</b> “Coming” means we do not measure it yet; “Nothing to measure yet” means it is measured but nothing has happened yet. Neither is an estimate.</li>
<li><b>Every number is dated.</b> Each row names its source, the period it covers and the date it was taken (UTC).</li></ul>
<p>Found a number that looks wrong? <a href="{e(site.cfg['site']['corrections_url'])}" rel="nofollow noopener">Open an issue on GitHub</a>.</p>
</div>"""
    org = {'@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/')}
    measured = [m['label'] for s in doc['sections'] for m in s['metrics']]
    ds = {'@type': 'Dataset', 'name': 'Commonworld public stats', 'description': STATS_LEAD, 'url': site.abs(STATS_PATH),
          'creator': org, 'publisher': org, 'isAccessibleForFree': True, 'inLanguage': 'en', 'dateModified': upd or None,
          'variableMeasured': measured, 'keywords': ['Commonworld', 'open stats', 'search impressions', 'AI features', 'AI agents', 'response time'],
          'distribution': [{'@type': 'DataDownload', 'name': 'Commonworld stats (stats.json)', 'encodingFormat': 'application/json', 'contentUrl': site.abs(STATS_JSON)},
                           {'@type': 'DataDownload', 'name': 'Commonworld stats (Markdown)', 'encodingFormat': 'text/markdown', 'contentUrl': site.abs(STATS_MD)}]}
    lic = site.cfg.get('data_licence')
    if lic:
        ds['license'] = LICENCE_URLS.get(lic, f'{REPO_URL}/blob/main/LICENSE-DATA.md')
    ds = {k: v for k, v in ds.items() if v is not None}
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'Commonworld in numbers', 'url': site.abs(STATS_PATH),
                     'inLanguage': 'en', 'description': STATS_LEAD, 'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/')},
                     'dateModified': upd or None, 'mainEntity': ds}]
    n_ok = sum(1 for s in doc['sections'] for m in s['metrics'] if m.get('value') is not None)
    name, spec, alt = og_generic(site, 'page-cw-stats', 'Commonworld in numbers',
                                 'Honest numbers, small ones included, updated weekly. Source, period and date on every number.',
                                 [('stats', 'olive'), ('updated weekly', None), (f'{n_ok} measured values', None)], kicker='STATS',
                                 alt='Commonworld in numbers: public stats with source and date on every number')
    spec.update({'brand': 'A shared world for humans and agents', 'foot_left': 'commonworld.one/stats'})
    lm = parse_time(upd + 'T00:00:00Z') if upd else site.latest
    return page(site, path=STATS_PATH, title='Commonworld in numbers — public stats, updated weekly',
                description='Honest Commonworld stats, updated weekly: Atlas cards, Google Search and AI features, visits, issue response times. Source and date on every number.',
                body=body, active='cw-stats', ld=ld, lastmod=lm, alt_md=STATS_MD, og=(name, spec, alt))


def build_stats_md(site, doc):
    A = site.abs
    cell = lambda v: str(v if v is not None else '').replace('|', '\\|').replace('\n', ' ')
    lines = ['# Commonworld in numbers', '', '> A shared world for humans and agents', '', STATS_LEAD, '',
             f'Canonical page: {A(STATS_PATH)} · JSON: {A(STATS_JSON)} · Last update: {doc.get("updated_at")} · Cadence: {doc.get("cadence")}', '']
    for s in doc['sections']:
        lines += [f'## {s["title"]}', '', s.get('intro') or '', '',
                  '| Metric | Value | Period | Source | As of |', '|---|---|---|---|---|']
        for m in s['metrics']:
            val = stats_value(m)
            val = val if val is not None else STATS_STATUS_WORD.get(m.get('status'), 'Coming')
            src = m.get('source') or {}
            u = src.get('url')
            srct = cell(src.get('name')) + (f' <{A(u) if u.startswith("/") else u}>' if u else '')
            lines.append(f'| {cell(m["label"])} | {cell(val)} | {cell(stats_period(m))} | {srct} | {cell(m.get("as_of"))} |')
        notes = [f'- {m["label"]}: {m["note"]}' for m in s['metrics'] if m.get('note')]
        if notes:
            lines += [''] + notes
        wk = s.get('weekly')
        if wk is not None:
            if wk.get('rows'):
                cols = wk.get('columns') or []
                lines += ['', '### By week', '', '| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
                lines += ['| ' + ' | '.join(cell(r.get(c)) for c in cols) + ' |' for r in wk['rows']]
            else:
                lines += ['', 'By week: coming, the weekly update adds one row per week.']
        lines.append('')
    lines += ['## How to read these numbers', '',
              '- People (visits), agents (deliveries) and search (impressions, clicks) are separate numbers and are never added together.',
              '- "Coming" = not measured yet. "Nothing to measure yet" = measured, but nothing has happened yet. Neither is an estimate.',
              '- Every number names its source, its period and the date it was taken (UTC).', '']
    return '\n'.join(lines)


def build_404(site):
    b = site.base
    body = f"""{cw.hero('404', 'Page not found', '<p>This address is not in the Atlas. Card IDs are permanent, so if you followed an old link, try searching for the name.</p>'
                      f'<p class="actions"><a class="cw-btn cw-btn-primary" href="{b}/">Go to the Atlas</a> <a class="cw-btn" href="{b}/platforms/">All entries</a></p>', small=True)}"""
    return page(site, path='/404.html', title='Page not found | Commonworld Atlas', description='This page does not exist in the Commonworld Atlas.',
                body=body, active='', noindex=True)


REMOVED_FILE = os.path.normpath(os.path.join(HERE, '..', 'data', 'removed.json'))  # link-safety removals (atlas/CURATION.md#link-safety)


def load_removed():
    """atlas/data/removed.json -> list of {slug, host, removed_on, reason}. Removed entries leave every listing and data file;
    their slug keeps a minimal noindex stub page (slugs are permanent)."""
    if not os.path.exists(REMOVED_FILE):
        return []
    return list(json.load(open(REMOVED_FILE)).get('removed') or [])


LINK_SAFETY_FILE = os.path.normpath(os.path.join(HERE, '..', 'data', 'link-safety.json'))  # written daily by atlas/tools/safebrowsing_check.py
SAFETY_PATH = '/atlas/safety.json'
TRUST_ENGINE = 'Commonworld trust engine'  # trust/ (TRUST.md): one engine, plugin sources, any single flag = flagged
TRUST_URL = REPO_URL + '/blob/main/TRUST.md'
TRUST_SOURCE_NAMES = ['Google Safe Browsing', 'MetaMask eth-phishing-detect', 'ScamSniffer scam-database', 'CERT Polska Warning List']
TRUST_SOURCES_TEXT = 'Google Safe Browsing, MetaMask eth-phishing-detect, ScamSniffer and the CERT Polska Warning List'


def _host(url):
    from urllib.parse import urlsplit
    try:
        h = (urlsplit(url or '').hostname or '').lower().rstrip('.')
    except ValueError:
        return ''
    return h[4:] if h.startswith('www.') else h


def load_link_safety():
    """atlas/data/link-safety.json (latest daily trust engine report, atlas/tools/link_safety.py) -> dict, or {} before the first run."""
    if not os.path.exists(LINK_SAFETY_FILE):
        return {}
    return json.load(open(LINK_SAFETY_FILE, encoding='utf-8'))


def link_safety_of(site, c):
    """`link_safety` of one entry: the latest report's status for the host of its official URL (canonical_url)."""
    r = (site.safety.get('hosts') or {}).get(_host(c.get('canonical_url')))
    if not r:
        return {'status': 'no_data', 'checked_at': None}
    return {'status': r.get('status') or 'no_data', 'checked_at': r.get('checked_at')}


def safety_doc(site):
    """/atlas/safety.json: the published part of the latest report. Only hosts linked from published entries; hosts of removed
    entries are never published (removed_hosts stays in the repository report)."""
    rep_ = site.safety or {}
    live = {c['slug'] for c in site.cards}
    gone = {_host('https://' + r['host']) for r in site.removed if r.get('host')}
    hosts = {}
    for h, r in sorted((rep_.get('hosts') or {}).items()):
        ents = [x for x in r.get('entries') or [] if x in live]
        if h in gone or not ents:
            continue
        srcs = [{k: x[k] for k in ('name', 'verdict', 'checked_at', 'evidence_url', 'detail', 'stale') if x.get(k) is not None}
                for x in r.get('sources') or []]
        hosts[h] = {'status': r.get('status') or 'no_data', 'checked_at': r.get('checked_at'), 'entries': ents, 'sources': srcs}
    cnt = Counter(r['status'] for r in hosts.values())
    return {'name': 'Commonworld Atlas link safety report', 'url': site.abs(SAFETY_PATH),
            'source': TRUST_ENGINE, 'standard': TRUST_URL,
            'sources': [{k: x.get(k) for k in ('id', 'name', 'covers', 'url')} for x in rep_.get('sources') or []],
            'rule': 'A domain is flagged when ANY one source flags it, and every Atlas entry that links to it is removed at once with a public decision. '
                    'clean = at least one source answered and none flags it; no_data = no source could answer.',
            'method': f'Every domain linked from the published Atlas data is checked daily by the {TRUST_ENGINE} against every source listed under sources; '
                      'each domain carries the answer of each source (verdict, checked_at, evidence_url). A flagged domain is removed from the Atlas and '
                      'its entry page becomes a short removed-entry note. Each entry in the JSON exports carries link_safety {status, checked_at} for its official URL.',
            'appeal': f'Open an issue titled "Appeal: <domain>" in {REPO_URL}/issues or email the contact address on /atlas/about/; we reply within 7 days.',
            'policy': site.abs(f'{site.base}/about/#link-safety'), 'decisions': site.abs(DECISIONS_JSON), 'licence': site.cfg.get('data_licence') or 'not yet specified',
            'run_at': rep_.get('run_at'),
            'summary': {'hosts': len(hosts), 'clean': cnt['clean'], 'flagged': cnt['flagged'], 'no_data': cnt['no_data'], 'removed_entries': len(site.removed)},
            'hosts': hosts}


def build_removed_stub(site, slug):
    """Neutral page for a removed entry: no name, no outbound link, noindex, not in the sitemap."""
    b = site.base
    body = f"""{cw.hero('Atlas', 'Entry removed', '<p>This entry was removed from the Atlas after a safety check.</p>'
                      f'<p>Every linked domain is checked daily; see <a href="{b}/about/#link-safety">link safety</a> and the <a href="{DECISIONS_PATH}">decision log</a>.</p>'
                      f'<p class="actions"><a class="cw-btn cw-btn-primary" href="{b}/">Go to the Atlas</a> <a class="cw-btn" href="{b}/platforms/">All entries</a></p>', small=True)}"""
    return page(site, path=f'{b}/platforms/{slug}/', title='Entry removed | Commonworld Atlas',
                description='This entry was removed from the Atlas after a safety check.', body=body, active='', noindex=True)


DECISIONS_PATH = '/atlas/decisions/'  # public log of link-safety decisions (removed.json `decisions`)
DECISIONS_MD = DECISIONS_PATH + 'index.md'  # Markdown twin of the page
DECISIONS_JSON = '/atlas/decisions.json'
TRUST_ROLES_FILE = os.path.normpath(os.path.join(HERE, '..', 'data', 'trust-roles.json'))
EVIDENCE_HOSTS = ('transparencyreport.google.com',)  # third-party checkers whose evidence links may carry a removed host in the query


def load_decisions():
    """removed.json `decisions` (oldest first in the file) and trust-roles.json."""
    doc = json.load(open(REMOVED_FILE)) if os.path.exists(REMOVED_FILE) else {}
    roles = json.load(open(TRUST_ROLES_FILE)) if os.path.exists(TRUST_ROLES_FILE) else {}
    return list(doc.get('decisions') or []), roles


def defang(host):
    """A removed host is shown as plain text that no tool turns into a link: venice.ai -> venice[.]ai."""
    return (host or '').replace('.', '[.]')


def decisions_newest_first(decs):
    return [d for _, d in sorted(enumerate(decs), key=lambda x: (x[1].get('on') or '', x[0]), reverse=True)]


def decision_record(d):
    r = {'on': d.get('on'), 'action': d.get('action'), 'slug': d.get('slug'), 'host': defang(d.get('host')),
         'by': d.get('by'), 'reason': d.get('reason'), 'evidence': d.get('evidence')}
    if d.get('recheck'):
        r['recheck'] = d['recheck']
    return r


ACTION_WORD = {'remove': 'Removed', 'restore': 'Returned'}
DECISIONS_LEAD = ('Every removal and every return in the Atlas is a public, dated decision: what changed, who acted, why, '
                  'and a link to the evidence, so anyone can follow it and check it.')


def build_decisions(site):
    b = site.base
    decs, roles = load_decisions()
    rows = decisions_newest_first(decs)
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('How the Atlas works', f'{b}/about/'), ('Decision log', DECISIONS_PATH)])
    actors = roles.get('actors') or []
    trs = []
    for d in rows:
        ev = d.get('evidence') or ''
        evh = (f'<a href="{e(ev)}" rel="nofollow noopener" target="_blank">{e(_host(ev) or "evidence")}</a>' if ev.startswith('https://') else '—')
        re_ = ' (re-check: clean)' if d.get('recheck') == 'clean' else ''
        trs.append(f'<tr><td><time datetime="{e(d.get("on") or "")}">{e(d.get("on") or "")}</time></td>'
                   f'<td>{e(ACTION_WORD.get(d.get("action"), d.get("action") or ""))}{re_}</td>'
                   f'<td><a href="{b}/platforms/{e(d.get("slug") or "")}/"><code>{e(d.get("slug") or "")}</code></a></td>'
                   f'<td><code>{e(defang(d.get("host")))}</code></td><td><code>{e(d.get("by") or "")}</code></td>'
                   f'<td>{e(d.get("reason") or "")}</td><td>{evh}</td></tr>')
    table = ('<div class="table-wrap"><table class="list decisions" aria-labelledby="log"><thead><tr><th scope="col">Date</th><th scope="col">Action</th>'
             '<th scope="col">Entry ID</th><th scope="col">Domain</th><th scope="col">By</th><th scope="col">Reason</th><th scope="col">Evidence</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table></div>') if trs else '<p>No decisions recorded yet.</p>'
    who = ', '.join(f'<code>{e(a["id"])}</code>' for a in actors)
    lead = f'<p>{e(DECISIONS_LEAD)}</p>'
    body = f"""{crumbs}
{cw.hero('About the Atlas', 'Link safety decision log', lead, small=True, kicker_href=f'{b}/about/')}
<div class="prose">
<p>The Atlas checks every linked domain daily against {TRUST_SOURCES_TEXT} (<a href="{b}/about/#link-safety">how link safety works</a>). When any one source flags a domain, its entry is removed; when the flag clears and a fresh check comes back clean, the entry can return. Each of these steps is written down here, newest first.</p>
<h2 id="who">Who can act</h2>
<p>{len(actors)} trusted actors can remove and restore entries, each on their own: {who}. The list is published in <a href="{REPO_URL}/blob/main/atlas/data/trust-roles.json" rel="nofollow noopener">trust-roles.json</a>. A return needs a clean re-check.</p>
<h2 id="log">Decisions</h2>
{table}
<p>Domains are shown as plain text with <code>[.]</code> in place of the dot, so they never become links. Entry IDs stay permanent: a removed entry's ID shows a short note. Evidence links go to the third-party checker.</p>
<h2 id="data">Data</h2>
<p>The same log as JSON: <a href="{DECISIONS_JSON}">decisions.json</a> (decisions, trust roles, the link safety rule, generated time), and as Markdown: <a href="{DECISIONS_MD}">index.md</a>. Source: <a href="{REPO_URL}/blob/main/atlas/data/removed.json" rel="nofollow noopener">removed.json</a>.</p>
</div>"""
    newest = parse_time((rows[0].get('on') + 'T00:00:00Z')) if rows and rows[0].get('on') else site.latest
    return page(site, path=DECISIONS_PATH, title='Link safety decision log | Commonworld Atlas',
                description='Every removal and return in the Commonworld Atlas as a public, dated decision: who acted, why, and a link to the evidence.',
                body=body, active='decisions', lastmod=newest, alt_md=DECISIONS_MD,
                og=og_generic(site, 'page-decisions', 'Link safety decision log',
                              'Every removal and return in the Atlas is a public, dated decision with who acted, why and an evidence link.',
                              [('decisions', 'olive'), (f'{len(rows)} recorded', None), ('open record', None)], kicker='ABOUT THE ATLAS'),
                ld=[crumb_ld, decisions_ld(site, rows)])


def decisions_ld(site, rows):
    """CollectionPage whose mainEntity is a Dataset (the decision log, with JSON and Markdown downloads) holding an ItemList of
    the decisions, newest first. No item links to a removed entry's page or host."""
    lic = site.cfg.get('data_licence')
    org = {'@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/')}
    items = [{'@type': 'ListItem', 'position': i + 1,
              'name': f"{d.get('on')} · {ACTION_WORD.get(d.get('action'), d.get('action'))} · {d.get('slug')}",
              'description': f"By {d.get('by')}: {d.get('reason')}"} for i, d in enumerate(rows)]
    ds = {'@type': 'Dataset', 'name': 'Commonworld Atlas link safety decision log', 'description': DECISIONS_LEAD,
          'url': site.abs(DECISIONS_PATH), 'sameAs': f'{REPO_URL}/blob/main/atlas/data/removed.json', 'creator': org, 'publisher': org,
          'isAccessibleForFree': True, 'inLanguage': 'en', 'keywords': ['link safety', *TRUST_SOURCE_NAMES, 'phishing', 'crypto scams', 'trust decisions', 'AI agents', 'open data'],
          'dateModified': rows[0].get('on') if rows else None, 'size': f'{len(rows)} decision' + ('' if len(rows) == 1 else 's'),
          'variableMeasured': ['date', 'action (remove or restore)', 'entry ID', 'domain (defanged)', 'actor ID', 'reason', 'evidence link'],
          'distribution': [{'@type': 'DataDownload', 'name': 'Decision log with trust roles (decisions.json)', 'encodingFormat': 'application/json', 'contentUrl': site.abs(DECISIONS_JSON)},
                           {'@type': 'DataDownload', 'name': 'Decision log (Markdown)', 'encodingFormat': 'text/markdown', 'contentUrl': site.abs(DECISIONS_MD)}],
          'hasPart': {'@type': 'ItemList', 'name': 'Decisions, newest first', 'itemListOrder': 'https://schema.org/ItemListOrderDescending',
                      'numberOfItems': len(items), 'itemListElement': items}}
    if lic:
        ds['license'] = LICENCE_URLS.get(lic, f'{REPO_URL}/blob/main/LICENSE-DATA.md')
    ds = {k: v for k, v in ds.items() if v is not None}
    return {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Link safety decision log', 'url': site.abs(DECISIONS_PATH),
            'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/')}, 'about': {'@type': 'Thing', 'name': 'Link safety'},
            'mainEntity': ds}


def build_decisions_md(site):
    A = site.abs
    decs, roles = load_decisions()
    rows = decisions_newest_first(decs)
    cell = lambda v: str(v or '').replace('|', '\\|').replace('\n', ' ')
    lines = ['# Link safety decision log', '', f'> {DECISIONS_LEAD}', '',
             f'Canonical page: {A(DECISIONS_PATH)} · JSON: {A(DECISIONS_JSON)} · How link safety works: {A(site.base + "/about/#link-safety")}', '',
             f'The Atlas checks every linked domain daily against {TRUST_SOURCES_TEXT}. When any one source flags a domain, its entry is removed; it can return once the flag clears and a fresh check comes back clean. Appeals: open an issue titled "Appeal: domain" in {REPO_URL}/issues; we reply within 7 days.', '',
             '## Who can act', '',
             'Each actor below can remove and restore entries on their own (source: trust-roles.json). A return needs a clean re-check.', '']
    lines += [f"- `{a['id']}` ({a.get('kind') or 'actor'})" for a in roles.get('actors') or []]
    lines += ['', '## Decisions (newest first)', '']
    if rows:
        lines += ['| Date | Action | Entry ID | Domain | By | Reason | Evidence |', '|---|---|---|---|---|---|---|']
        for d in rows:
            act = ACTION_WORD.get(d.get('action'), d.get('action') or '') + (' (re-check: clean)' if d.get('recheck') == 'clean' else '')
            ev = d.get('evidence') or ''
            lines.append(f"| {cell(d.get('on'))} | {cell(act)} | `{cell(d.get('slug'))}` | `{cell(defang(d.get('host')))}` | `{cell(d.get('by'))}` | {cell(d.get('reason'))} | <{ev}> |")
    else:
        lines.append('No decisions recorded yet.')
    lines += ['', 'Domains are written with `[.]` in place of the dot, so they never become links. Evidence links go to the third-party checker.', '']
    return '\n'.join(lines)


def decisions_doc(site):
    decs, roles = load_decisions()
    gen = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'name': 'Commonworld Atlas link safety decision log', 'url': site.abs(DECISIONS_JSON), 'page': site.abs(DECISIONS_PATH),
            'generated_at': gen, 'licence': site.cfg.get('data_licence') or 'not yet specified',
            'link_safety': {'policy': site.abs(f'{site.base}/about/#link-safety'), 'report': site.abs(SAFETY_PATH), 'source': TRUST_ENGINE, 'sources': TRUST_SOURCE_NAMES, 'standard': TRUST_URL,
                            'appeal': f'Open an issue titled "Appeal: <domain>" in {REPO_URL}/issues or email the contact address; we reply within 7 days.',
                            'rule': f'Every linked domain is checked daily against {TRUST_SOURCES_TEXT}. When any one source flags a domain, its entry is removed from every listing '
                                    'and data file and its ID shows a short removed-entry note. It can return after the flag clears with a restore decision '
                                    'and a clean re-check. Every removal and return is recorded here.',
                            'host_format': 'Domains are defanged ("." written as "[.]") so they are never turned into links.'},
            'trust_roles': {'version': roles.get('version'), 'actions': roles.get('actions') or [],
                            'actors': [{k: a.get(k) for k in ('id', 'kind', 'commits_as', 'trailer') if a.get(k)} for a in roles.get('actors') or []]},
            'count': len(decs), 'decisions': [decision_record(d) for d in decisions_newest_first(decs)]}


# ---------------------------------------------------------------- machine-readable files for AI agents


# ---------------------------------------------------------------- status badges (/atlas/badge/)
BADGE_WORD = {'verified': 'Verified', 'listed': 'Listed', 'closed': 'Closed'}
BADGE_LINE = 'Free. Never sold. Updates itself with every weekly check.'


def badge_urls(site, c):
    b, slug = site.base, c['slug']
    return {'svg': site.abs(f'{b}/badge/{slug}.svg'), 'svg_dark': site.abs(f'{b}/badge/{slug}-dark.svg'),
            'page': site.abs(f'{b}/badge/'), 'card': site.abs(c['_url'])}


def badge_snippets(site, c):
    """(html, markdown, link) for one card. The alt names the status word only, so a pasted snippet never goes stale."""
    u = badge_urls(site, c)
    alt = f'{badges.LABEL}: {BADGE_WORD[badges.status_of(c)[0]]}'
    html_s = f'<a href="{u["card"]}"><img src="{u["svg"]}" alt="{alt}" height="20"></a>'
    md = f'[![{alt}]({u["svg"]})]({u["card"]})'
    return html_s, md, u['card']


def badge_block(site, c):
    b, slug = site.base, c['slug']
    tone, right = badges.status_of(c)
    html_s, md, link = badge_snippets(site, c)
    what = {'verified': f'This card is published as verified; the date is the newest observation on the card ({right.split(" · ")[-1]}).',
            'listed': 'This card is published but not verified right now, so the badge says Listed.',
            'closed': 'This platform is closed and the card is kept as history, so the badge says Closed · history.'}[tone]
    rows = ''.join(
        f'<div class="badge-snippet"><div class="badge-snippet-head"><span id="badge-l-{k}">{lab}</span>'
        f'<button type="button" class="cw-btn badge-copy" data-copy-for="badge-c-{k}" data-track="badge_copy" data-format="{k}" aria-describedby="badge-l-{k}" hidden>Copy</button></div>'
        f'<pre><code id="badge-c-{k}">{e(txt)}</code></pre></div>'
        for k, lab, txt in (('html', 'HTML', html_s), ('md', 'Markdown (README)', md), ('link', 'Plain link', link)))
    return (f'<section class="cw-panel cw-panel-gap badge-panel" id="badge" aria-labelledby="h-badge"><div class="cw-panel-head"><h2 id="h-badge">Add this badge to your site</h2>'
            f'<span class="muted">{BADGE_LINE}</span></div><div class="cw-panel-body">'
            f'<div class="badge-previews"><figure><img src="{b}/badge/{slug}.svg" alt="{e(badges.alt_text(c))}" height="20"><figcaption>Light backgrounds</figcaption></figure>'
            f'<figure class="badge-on-dark"><img src="{b}/badge/{slug}-dark.svg" alt="{e(badges.alt_text(c))} (dark variant)" height="20"><figcaption>Dark backgrounds: <code>{slug}-dark.svg</code></figcaption></figure></div>'
            f'<p class="sec-desc">{e(what)} The badge links back to this card with its facts and sources. It is a plain SVG image: no scripts, no cookies, no tracking. '
            f'<a href="{b}/badge/">How badges work</a>.</p>{rows}'
            f'<p class="badge-status sr" role="status" aria-live="polite"></p></div></section>')


def build_badge_page(site):
    b = site.base
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('Badges', f'{b}/badge/')])
    ex = next((c for c in site.cards if c['slug'] == 'the-spawn'), None) or next(c for c in site.cards if c['status'] == 'live')
    exc = next((c for c in site.cards if c['status'] == 'closed'), None)
    html_s, md, link = badge_snippets(site, ex)
    corr = site.cfg['site']['corrections_url']
    gm = contact(site, 'general')
    n = len(site.cards)
    st = Counter(badges.status_of(c)[0] for c in site.cards)
    inline = lambda tone, right, dark=False: badges.svg(tone, right, dark=dark, title=False).strip()
    vdate = badges.status_of(ex)[1]
    stat_rows = (f'<tr><td>{inline("verified", vdate if vdate.startswith("Verified") else "Verified · YYYY-MM-DD")}</td><td><b>Verified · date</b></td><td>A live card published as verified. The date is the newest observation on the card (UTC), so it moves forward with each weekly check. Now: {st["verified"]} cards.</td></tr>'
                 f'<tr><td>{inline("listed", "Listed")}</td><td><b>Listed</b></td><td>A published card that is not verified right now, for example while it is under review. Now: {st["listed"]} cards.</td></tr>'
                 f'<tr><td>{inline("closed", "Closed · history")}</td><td><b>Closed · history</b></td><td>The platform closed (by human review, or by the automated weekly check) and the card is kept as a history record. Now: {st["closed"]} cards.</td></tr>')
    lead = (f'<p>Every published Atlas card has a free status badge: a small image a platform can put on its own site or README. '
            f'It shows the card\u2019s real status and last check date, and links to the card with its facts and sources. {BADGE_LINE}</p>')
    box = cw.info_box('live', f'{n} badges', 'one per card', f'Light and dark variant for every card: <code>{b}/badge/&lt;id&gt;.svg</code> and <code>{b}/badge/&lt;id&gt;-dark.svg</code>.')
    body = f"""{crumbs}
{cw.hero('Atlas · badges', 'Commonworld Atlas badges', lead, box, small=True, kicker_href=f'{b}/')}
<div class="prose">
<h2 id="what">What it is</h2>
<p>A badge is a plain SVG image served from <code>commonworld.one</code>. The left half says <i>Commonworld Atlas</i>; the right half shows the status of one card. Example for <a href="{ex['_url']}">{e(ex['name'])}</a> (<code>{ex['slug']}</code>):</p>
<div class="badge-previews"><figure><img src="{b}/badge/{ex['slug']}.svg" alt="{e(badges.alt_text(ex))}" height="20"><figcaption>{ex['slug']}.svg</figcaption></figure>
<figure class="badge-on-dark"><img src="{b}/badge/{ex['slug']}-dark.svg" alt="{e(badges.alt_text(ex))} (dark variant)" height="20"><figcaption>{ex['slug']}-dark.svg</figcaption></figure></div>
<h2 id="updates">How it updates</h2>
<p>All badges are regenerated from the Atlas data every time the site is rebuilt, including after each weekly check. A site that shows the badge loads the current file, so status and date update by themselves; nothing needs to be changed on the platform\u2019s side. Browsers and image proxies may keep a copy for a few hours, so a change can take that long to show.</p>
<h2 id="statuses">Statuses</h2>
<div class="table-wrap"><table class="list badge-table"><thead><tr><th scope="col">Badge</th><th scope="col">Status</th><th scope="col">Meaning</th></tr></thead><tbody>{stat_rows}</tbody></table></div>
<p>How a card is checked and when it is marked closed is explained in <a href="{b}/about/#verified">How the Atlas works</a> and <a href="{b}/about/#closures">When a card is marked closed</a>.</p>
<h2 id="rules">Rules</h2>
<ul><li><b>Free for every published card.</b> Every card that has a page has a badge; nobody has to ask for one.</li>
<li><b>No tracking.</b> The badge is a plain SVG image: no scripts, no cookies, no external fonts or requests, no counters.</li>
<li><b>Honest status.</b> It shows the card\u2019s real status and last check date, and links to the card with its facts and sources.</li></ul>
<h2 id="add">How to add it</h2>
<p>Every card page has a block <i>Add this badge to your site</i> with ready-made code for that card (for example <a href="{ex['_url']}#badge">{e(ex['name'])}</a>). Replace <code>{ex['slug']}</code> with the card\u2019s permanent ID, taken from its page or from <a href="{b}/platforms.json">platforms.json</a>; never guess an ID.</p>
<h3>HTML</h3><pre><code>{e(html_s)}</code></pre>
<h3>Markdown (README)</h3><pre><code>{e(md)}</code></pre>
<h3>Plain link</h3><pre><code>{e(link)}</code></pre>
<h2 id="variants">Light and dark</h2>
<p><code>{b}/badge/&lt;id&gt;.svg</code> is made for light backgrounds, <code>{b}/badge/&lt;id&gt;-dark.svg</code> for dark ones (a lighter edge keeps it readable on black). Both carry the same status. Each entry\u2019s JSON (<code>{b}/platforms/&lt;id&gt;.json</code>) lists its <code>badge_svg</code>, <code>badge_svg_dark</code> and <code>badge_page</code> URLs.</p>
<div class="badge-previews badge-on-dark-row"><span class="badge-on-dark">{inline('verified', vdate, True)} {inline('listed', 'Listed', True)} {inline('closed', 'Closed · history', True)}</span></div>
<h2 id="corrections">Wrong status or date?</h2>
<p>The badge only shows what the card says. If the card is wrong or out of date, <a href="{e(corr)}" rel="nofollow noopener">open a correction request on GitHub</a> (requests there are public){(', or email ' + mailto(gm)) if gm else ''}, with the card\u2019s permanent ID and a link to a source that shows the right fact. When the card is corrected, the badge follows on the next rebuild. See <a href="{b}/about/#corrections">how corrections work</a>.</p>
</div>"""
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'Commonworld Atlas badges', 'url': site.abs(f'{b}/badge/'), 'inLanguage': 'en',
                     'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld Atlas', 'url': site.abs(f'{b}/')}}]
    return page(site, path=f'{b}/badge/', title='Atlas badges: free status badge for every card | Commonworld',
                description='A free status badge for every Commonworld Atlas card: Verified, Listed or Closed. Never sold, no tracking, updated with every weekly check.',
                body=body, active='badge', ld=ld,
                og=og_generic(site, 'page-badge', 'Commonworld Atlas badges',
                              'A free status badge for every published card. Never sold, no tracking, updated with every weekly check.',
                              [(f'{n} badges', 'olive'), ('free', 'live'), ('no tracking', None)], kicker='BADGES'))


def write_badges(site, write):
    for c in site.cards:
        light, dark = badges.card_svgs(c)
        write(f"{site.base}/badge/{c['slug']}.svg", light)
        write(f"{site.base}/badge/{c['slug']}-dark.svg", dark)
    return len(site.cards)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def agent_record(site, c):
    """Stable public fields for one published entry (same set as the site cards)."""
    claims = c.get('claims', [])
    flows = [{'statement': x.get('statement'), 'value': x.get('value'), 'unit': x.get('unit'), 'window': x.get('window'),
              'basis': x.get('basis'), 'observed_at': iso(parse_time(x.get('observed_at'))), 'source_url': x.get('source_url')}
             for x in claims if x.get('kind') == 'economic_flow' and x.get('outcome') == 'supported']
    k = c['_key']
    key = {'kind': k.get('kind'), 'value': k.get('value'), 'unit': k.get('unit'), 'window': k.get('window'),
           'basis': k.get('basis'), 'observed_at': iso(parse_time(k.get('observed_at'))), 'source_url': k.get('source_url')} if k else None
    return {'id': c['slug'], 'name': c['name'], 'url': site.abs(c['_url']), 'json_url': site.abs(f"{site.base}/platforms/{c['slug']}.json"),
            'website': c.get('canonical_url'), 'category': c['category'], 'category_label': CAT_LABEL[c['category']],
            'type': c.get('entity_type'), 'status': c['status'], 'summary': trim(c['_desc'], 300), 'tags': c['_tags'],
            'has_money_flow': c['_money'], 'money_flow': flows, 'key_number': key,
            'verified_at': iso(c['_verified']), 'last_checked': iso(c['_verified']), 'claims_count': len(claims),
            'disclosure': c.get('disclosure'), 'preview': preview_record(site, c), 'link_safety': link_safety_of(site, c)}


MIRROR_DIR = os.path.normpath(os.path.join(HERE, '..', 'public'))
RAW_BASE = 'https://raw.githubusercontent.com/commonworld-one/commonworld/main/atlas/public'


def _mirror_json(src, dst, indent):
    """Copy one agent JSON file into the mirror without the `preview` field: screenshots live on the orphan branch
    atlas-screens, so keeping the field here would make the committed mirror stale whenever that branch moves."""
    doc = json.load(open(src, encoding='utf-8'))
    doc.pop('preview', None)
    doc.pop('link_safety', None)
    for r in doc.get('platforms') or []:
        r.pop('preview', None)
        r.pop('link_safety', None)
    txt = json.dumps(doc, ensure_ascii=False, indent=1) if indent else json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
    with open(dst, 'w', encoding='utf-8') as fh:
        fh.write(txt + '\n')


def write_github_mirror(out, b):
    """Committed copy of the agent data files (atlas/public/), served by GitHub raw as an official fallback
    for agent tools that cannot fetch commonworld.one directly. CI fails if it is stale (git diff)."""
    if os.path.isdir(MIRROR_DIR):
        shutil.rmtree(MIRROR_DIR)
    os.makedirs(os.path.join(MIRROR_DIR, 'platforms'))
    src = os.path.join(out, b.strip('/'))
    shutil.copy(os.path.join(out, 'llms-full.txt'), os.path.join(MIRROR_DIR, 'llms-full.txt'))
    _mirror_json(os.path.join(src, 'platforms.json'), os.path.join(MIRROR_DIR, 'platforms.json'), indent=1)
    shutil.copy(os.path.join(src, 'earn.json'), os.path.join(MIRROR_DIR, 'earn.json'))
    os.makedirs(os.path.join(MIRROR_DIR, 'categories'))
    for f in sorted(os.listdir(os.path.join(src, 'categories'))):
        if f.endswith('.json'):
            _mirror_json(os.path.join(src, 'categories', f), os.path.join(MIRROR_DIR, 'categories', f), indent=None)
    _mirror_json(os.path.join(src, 'data', 'snapshot.json'), os.path.join(MIRROR_DIR, 'snapshot.json'), indent=1)
    pdir = os.path.join(src, 'platforms')
    for f in sorted(os.listdir(pdir)):
        if f.endswith('.json'):
            _mirror_json(os.path.join(pdir, f), os.path.join(MIRROR_DIR, 'platforms', f), indent=1)
    # API v1 description (index, OpenAPI, schemas, changelog); the data documents themselves are the files above
    api_src, api_dst = os.path.join(out, 'api', 'v1'), os.path.join(MIRROR_DIR, 'api', 'v1')
    for rel in ['index.json', 'openapi.json', 'changelog.json', 'CHANGELOG.md', os.path.join('atlas', 'index.json')] + \
            [os.path.join('schemas', f) for f in sorted(os.listdir(os.path.join(api_src, 'schemas')))]:
        os.makedirs(os.path.dirname(os.path.join(api_dst, rel)), exist_ok=True)
        shutil.copy(os.path.join(api_src, rel), os.path.join(api_dst, rel))
    with open(os.path.join(MIRROR_DIR, 'README.md'), 'w', encoding='utf-8') as fh:
        fh.write('# Atlas data mirror\n\nGenerated by `atlas/site/build.py`; do not edit by hand. Same published data as https://commonworld.one '
                 '(platforms.json, earn.json, snapshot.json, llms-full.txt, platforms/<id>.json), mirrored here so agent tools that cannot reach the site '
                 'can read it via raw.githubusercontent.com. The site is canonical; cite Atlas URLs, not this mirror.\n\n'
                 '`api/v1/` holds the API description of https://commonworld.one/api/v1/ (index.json, openapi.json, schemas/, changelog). '
                 'The API data documents carry the same records as the files above, plus `schema_version`.\n\n'
                 'The `preview` field (homepage screenshot URLs on commonworld.one) is left out here: the screenshots live on the '
                 'orphan branch `atlas-screens`, not on main. Read it from the site\'s JSON files.\n\n'
                 'The `link_safety` field and the link safety report (https://commonworld.one/atlas/safety.json) are left out here too: '
                 'they change with every daily check. Read them from the site.\n')


def build_agent_files(site, write):
    """/llms.txt, /atlas/llms.txt, /llms-full.txt, /atlas/platforms.json, /atlas/platforms/<slug>.json (not in sitemaps)."""
    b, cfg = site.base, site.cfg
    sc = cfg['site']
    lic = cfg.get('data_licence') or 'not yet specified'
    gen = parse_time(site.snapshot.get('generated_at'))
    recs = [agent_record(site, c) for c in site.cards]
    meta = {'name': 'Commonworld Atlas of Agent Platforms', 'description': 'Verified catalog of AI-agent platforms',
            'url': site.abs(f'{b}/'), 'generated_at': iso(gen), 'newest_observation': iso(site.latest),
            'licence': lic, 'licence_url': f'{REPO_URL}/blob/main/LICENSE-DATA.md', 'source': REPO_URL,
            'corrections': f'{REPO_URL}/issues/new/choose', 'protocol': f'{REPO_URL}/blob/main/atlas/PROTOCOL.md',
            'full_data': site.abs(f'{b}/data/snapshot.json'), 'count': len(recs),
            'fields_note': 'id = permanent slug; verified_at/last_checked = newest observation on the card (UTC); '
                           'money_flow = supported money-flow claims shown on the card; full claims with sources are in each json_url and in full_data.'}
    write(f'{b}/platforms.json', json.dumps(meta | {'platforms': recs}, ensure_ascii=False, indent=1) + '\n')
    site.api_docs.append(('/atlas/platforms.json', meta | {'platforms': recs}, 'platform-list.schema.json', True))
    # small per-category lists: some agent tools truncate the full platforms.json (~290 KB)
    for k in site.cats:
        sub = [r for c, r in zip(site.cards, recs) if c.get('category') == k]
        cdoc = meta | {'category': k, 'category_label': CAT_LABEL[k], 'count': len(sub), 'platforms': sub}
        write(f'{b}/categories/{k}.json', json.dumps(cdoc, ensure_ascii=False, separators=(',', ':')) + '\n')
        site.api_docs.append((f'/atlas/categories/{k}.json', cdoc, 'category.schema.json', False))
    for c, r in zip(site.cards, recs):
        bu = badge_urls(site, c)
        one = {'licence': lic, 'source': REPO_URL, 'generated_at': iso(gen)} | r | {
            'badge_status': badges.status_of(c)[1], 'badge_svg': bu['svg'], 'badge_svg_dark': bu['svg_dark'], 'badge_page': bu['page'],
            'claims': c.get('claims', []), 'qa_status': c.get('qa_status')}
        write(f"{b}/platforms/{c['slug']}.json", json.dumps(one, ensure_ascii=False, indent=1) + '\n')
        site.api_docs.append((f"/atlas/platforms/{c['slug']}.json", one, 'platform.schema.json', True))

    A = site.abs
    gm = contact(site, 'general')
    # Literal per-entry links for agents that only open URLs they have seen. Several readable slugs on purpose:
    # a single example like '1f916' led one agent to assume IDs are 5-char hex codes and invent entries.
    exs = [c for s in ('dealwork-ai', 'bountybook', 'aibtc-bounty-board') for c in site.cards if c['slug'] == s] or site.cards[:3]
    ex_lines = '\n'.join(f"- [Example entry JSON: {c['slug']}]({A(b + '/platforms/' + c['slug'] + '.json')}): full claims with source URL, basis and observed_at" for c in exs)
    cats = '\n'.join(f'- [{CAT_LABEL[k]}]({A(f"{b}/categories/{k}/")}): {CAT_DESC[k]} ({len(site.by_cat[k])} entries; JSON: {A(f"{b}/categories/{k}.json")})' for k in site.cats)
    live = sum(1 for c in site.cards if c['status'] == 'live')
    txt = f"""# Commonworld

> {sc.get('motto') or 'A shared world for humans and agents'}. {sc.get('subtitle') or CW_SUBTITLE} Its first part, the Atlas, is a verified catalog of AI-agent platforms: {len(recs)} entries ({live} live), every fact checked against its own source and dated.

Commonworld is being built as a place where people and AI agents take part as citizens. Today it is the Atlas: each card is a set of claims with source URL, basis and observation time. Closed platforms stay as history records. IDs (URL slugs) are permanent.

Official channels: site {A('/')} · X {X_URL} ({X_HANDLE}) · GitHub {REPO_URL}

## Atlas

- [Atlas home]({A(f'{b}/')}): the catalog of agent platforms, searchable and filterable
- [Atlas llms.txt]({A(f'{b}/llms.txt')}): short guide to the Atlas data for agents (counts, category JSON endpoints)
- [All entries A-Z]({A(f'{b}/platforms/')}): every published entry
- [Closed history]({A(f'{b}/closed/')}): platforms that shut down
- [Where agents get paid]({A(f'{b}/earn/')}): live platforms with a sourced money figure, grouped by unit (never converted); JSON: {A(f'{b}/earn.json')}
- [How the Atlas works]({A(f'{b}/about/')}): method, basis labels, QA re-checks, freshness, closures, corrections
- [Atlas badges]({A(f'{b}/badge/')}): free status badge for every card (Verified · date / Listed / Closed · history), {A(f'{b}/badge/')}<id>.svg and <id>-dark.svg; never sold, no tracking, rebuilt with every weekly check
- [Verification protocol]({REPO_URL}/blob/main/atlas/PROTOCOL.md): the full protocol each claim goes through
- [Link safety]({A(f'{b}/about/#link-safety')}): every linked domain is checked daily against {TRUST_SOURCES_TEXT}; if any one source flags a domain, its entry is removed and its ID shows a short "entry removed" page
- [Link safety decision log]({A(DECISIONS_PATH)}): every removal and return as a public, dated decision (who acted, why, evidence link); Markdown {A(DECISIONS_MD)}, JSON {A(DECISIONS_JSON)} with the trust roles
- [About Commonworld]({A(CW_ABOUT)}): what Commonworld is and what is coming
- [Commonworld in numbers]({A(STATS_PATH)}): public stats updated weekly (Atlas counts, Google Search and AI features, human visits, GitHub issue response times, agent deliveries after the v1 launch); every value has source, period and as_of; people, agents and search clicks are separate numbers; JSON {A(STATS_JSON)}, Markdown {A(STATS_MD)}

## Categories

{cats}

## Data

- [API v1]({A(api_v1.API_BASE + '/index.json')}): versioned static JSON API (schema_version {api_v1.SCHEMA_VERSION}); Atlas module {A(api_v1.API_BASE + '/atlas/index.json')}; [OpenAPI 3.1]({A(api_v1.API_BASE + '/openapi.json')}); JSON Schemas {A(api_v1.API_BASE + '/schemas/')}<name>.schema.json; [docs]({A(API_DOCS)}). Same records as the files below plus schema_version; breaking changes go to /api/v2/ and v1 keeps working
- Per category: {A(f'{b}/categories/')}<category>.json, the same fields for one category only (small files; use these if your tool truncates long responses)
- [earn.json]({A(f'{b}/earn.json')}): where agents get paid: one row per live entry with a supported money figure (value, unit, window, basis, observed_at, source_url), grouped by unit
- [platforms.json]({A(f'{b}/platforms.json')}): all published entries with stable fields (id, name, url, website, category, type, status, summary, money flow, verified_at, claims_count)
- Per entry: {A(f'{b}/platforms/')}<id>.json with the full claims and sources (every URL is listed in llms-full.txt), plus badge_svg, badge_svg_dark and badge_page
- Closed entries: closed by human review (official statement or at least two independent signals; never reopened automatically) or by the automated weekly check (unreachable in 2 consecutive weekly checks; reopens automatically if the site answers again). A single failed load is never proof.
- IDs are readable slugs made from the platform name (examples: {', '.join(c['slug'] for c in exs)}). Never guess or construct an ID: take it from platforms.json or llms-full.txt. An ID that is not listed there does not exist in the Atlas.
{ex_lines}
- All claims and sources are public; no key needed.
- Homepage previews: most records carry a `preview` field (null when there is none) with a dated screenshot of the platform's homepage: {A(f'{b}/screens/')}<id>.webp (1200x750 WebP) and a 600x250 top-band thumbnail {A(f'{b}/screens/t/')}<id>.webp, plus captured_at and source_url; list: {A(f'{b}/screens/manifest.json')}. Screenshots show third-party websites and are not covered by the data licence. Do not construct these URLs; take them from `preview` (absent from the GitHub mirror)
- [snapshot.json]({A(f'{b}/data/snapshot.json')}): the full published dataset
- [safety.json]({A(SAFETY_PATH)}): link safety report, status of every linked domain with each source's answer (checked daily); records carry link_safety {{status, checked_at}} for their official URL
- [llms-full.txt]({A('/llms-full.txt')}): one line per entry
- [Sitemap (site)]({A('/sitemap.xml')}) and [Sitemap (Atlas)]({A(f'{b}/sitemap.xml')})

## Fallback if commonworld.one cannot be fetched

Some agent tools cannot reach the site directly. The same published files are mirrored in the public GitHub repository (updated with every change to main). Use them instead of guessing; the site stays canonical, so cite the Atlas URLs found inside the data.

- [platforms.json (GitHub mirror)]({RAW_BASE}/platforms.json)
- Per category: {RAW_BASE}/categories/<category>.json
- [earn.json (GitHub mirror)]({RAW_BASE}/earn.json): where agents get paid
- [llms-full.txt (GitHub mirror)]({RAW_BASE}/llms-full.txt)
- Per entry: {RAW_BASE}/platforms/<id>.json (example: [{exs[0]['slug']}.json]({RAW_BASE}/platforms/{exs[0]['slug']}.json))
- [snapshot.json (GitHub mirror)]({RAW_BASE}/snapshot.json): the full published dataset

## Licence

- Data: {lic} ([LICENSE-DATA.md]({REPO_URL}/blob/main/LICENSE-DATA.md)); please credit "Commonworld Atlas" with a link
- Homepage screenshots (`preview`, {A(f'{b}/screens/')}): third-party website content, not covered by {lic} or MIT; removal on request via the corrections link
- Code: MIT ([LICENSE]({REPO_URL}/blob/main/LICENSE))

## Corrections and contact

- [Report a correction or suggest a platform]({REPO_URL}/issues/new/choose): GitHub issue forms "Correct an Atlas card" and "Add a platform"; a correction needs a source
- [Source repository]({REPO_URL})
- Contact: {gm}
"""
    write('/llms.txt', txt)
    cat_json = '\n'.join(f'- {CAT_LABEL[k]}: {len(site.by_cat[k])} entries ({sum(1 for c in site.by_cat[k] if c["status"] == "live")} live): {A(f"{b}/categories/{k}.json")}' for k in site.cats)
    atxt = f"""# Commonworld Atlas

> Verified map of AI-agent platforms: {len(recs)} entries ({live} live, {len(recs) - live} closed and kept as history) in {len(site.cats)} categories. Every fact on a card has a source link and a check date. Newest check: {site.latest.strftime('%Y-%m-%d') if site.latest else 'n/a'}.

- Atlas home: {A(f'{b}/')}
- How the Atlas works: {A(f'{b}/about/')}
- Site-wide guide for agents (full list of files, mirrors, licence): {A('/llms.txt')}

## Data (JSON, no key needed)

- All entries: {A(f'{b}/platforms.json')}
- Full published dataset: {A(f'{b}/data/snapshot.json')}
- Where agents get paid: {A(f'{b}/earn.json')}
- Link safety report: {A(SAFETY_PATH)} (every linked domain checked daily against {TRUST_SOURCES_TEXT}: status clean/flagged/no_data with each source's verdict and evidence link, checked_at UTC, summary counts; each entry in the JSON files carries link_safety {{status, checked_at}})
- Link safety decision log: {A(DECISIONS_JSON)} (every removal and return: date, action, entry ID, domain written with [.], actor id from the trust roles, reason, evidence link); page {A(DECISIONS_PATH)}, Markdown {A(DECISIONS_MD)}
- One line per entry: {A('/llms-full.txt')}
- Versioned API v1: {A(api_v1.API_BASE + '/index.json')}
- Per entry: take json_url from platforms.json; never construct an ID

## Categories (JSON)

{cat_json}

Data licence: {lic}. Please credit "Commonworld Atlas" with a link to {A(f'{b}/')}.
"""
    write(f'{b}/llms.txt', atxt)
    lines = [f'# Commonworld Atlas: all {len(recs)} published entries',
             f'> One line per entry: name, Atlas URL, JSON URL (full claims and sources), category, status, summary. All claims and sources are public; no key needed. Data {lic}; machine-readable: {A(f"{b}/platforms.json")}', '',
             f"Official channels: site {A('/')} · X {X_URL} ({X_HANDLE}) · GitHub {REPO_URL}",
             f"API v1 (versioned, OpenAPI 3.1): {A(api_v1.API_BASE + '/index.json')}; per entry: {A(api_v1.API_BASE + '/atlas/platforms/')}<id>.json; docs: {A(API_DOCS)}",
             f"Badges: every entry has a free status badge at {A(f'{b}/badge/')}<id>.svg (dark: <id>-dark.svg); rules: {A(f'{b}/badge/')}",
             f"Homepage previews: the `preview` field of each entry's JSON (dated screenshot URLs, or null); third-party content, not covered by the data licence", '']
    for r in recs:
        lines.append(f"- [{r['name']}]({r['url']}) · JSON: {r['json_url']} · {r['category_label']} · {r['status']} · {trim(r['summary'], 200)}" + (f" · {r['disclosure']}" if r.get('disclosure') else ''))
    write('/llms-full.txt', '\n'.join(lines) + '\n')


# ---------------------------------------------------------------- static API v1 (/api/v1/)
API_DOCS = '/atlas/api/'  # human documentation page


def api_json(obj, indent=True):
    return json.dumps(obj, ensure_ascii=False, indent=1 if indent else None, separators=None if indent else (',', ':')) + '\n'


def build_api(site, write):
    """/api/v1/: one namespace for the whole platform; the Atlas is its first module. The data documents are the same
    objects as the legacy /atlas/*.json files (collected in site.api_docs while those were written) plus schema_version,
    so the two can never drift."""
    A, b, V = site.abs, site.base, api_v1.API_BASE
    lic = site.cfg.get('data_licence') or 'not yet specified'
    gen = iso(parse_time(site.snapshot.get('generated_at')))
    for path, doc, sch, indent in site.api_docs:
        write(V + path, api_json({'schema_version': api_v1.SCHEMA_VERSION, 'schema': api_v1.schema_url(site.origin, sch)} | doc, indent))
    for name, sch in api_v1.schemas(site.origin, site.cats).items():
        write(f'{V}/schemas/{name}', api_json(sch))
    ids = [c['slug'] for c in site.cards]
    exs = [s for s in ('dealwork-ai', 'bountybook', 'aibtc-bounty-board') if s in ids] or ids[:3]
    write(f'{V}/openapi.json', api_json(api_v1.openapi(site.origin, site.cats, exs, A(API_DOCS), lic)))
    write(f'{V}/changelog.json', api_json({'schema_version': api_v1.SCHEMA_VERSION, 'versioning': api_v1.VERSIONING, 'releases': api_v1.CHANGELOG}))
    write(f'{V}/CHANGELOG.md', api_v1.changelog_md())
    live = sum(1 for c in site.cards if c['status'] == 'live')
    atlas = {'schema_version': api_v1.SCHEMA_VERSION, 'name': 'Commonworld Atlas of Agent Platforms', 'description': 'Verified catalog of AI-agent platforms',
             'url': A(f'{b}/'), 'generated_at': gen, 'newest_observation': iso(site.latest), 'licence': lic,
             'counts': {'platforms': len(site.cards), 'live': live, 'closed': len(site.cards) - live, 'categories': len(site.cats), 'earn_rows': len(site.earn['rows'])},
             'categories': [{'id': k, 'label': CAT_LABEL[k], 'description': CAT_DESC[k], 'count': len(site.by_cat[k]),
                             'url': A(f'{b}/categories/{k}/'), 'json_url': A(f'{V}/atlas/categories/{k}.json')} for k in site.cats],
             'links': {'platforms': A(f'{V}/atlas/platforms.json'), 'platform': A(f'{V}/atlas/platforms/') + '{id}.json',
                       'category': A(f'{V}/atlas/categories/') + '{category}.json', 'earn': A(f'{V}/atlas/earn.json'),
                       'html': A(f'{b}/'), 'method': A(f'{b}/about/'), 'docs': A(API_DOCS), 'openapi': A(f'{V}/openapi.json')},
             'id_rule': 'IDs are permanent readable slugs. Never construct or guess an ID: take it from platforms.json or a category file.'}
    write(f'{V}/atlas/index.json', api_json(atlas))
    root = {'name': 'Commonworld API', 'description': 'Static, read-only JSON API of Commonworld, a shared world for humans and agents.',
            'version': api_v1.API_VERSION, 'schema_version': api_v1.SCHEMA_VERSION, 'generated_at': gen,
            'modules': {'atlas': {'name': 'Atlas of Agent Platforms', 'url': A(f'{V}/atlas/index.json'), 'count': len(site.cards),
                                  'description': 'Verified catalog of AI-agent platforms: every fact checked against its own source and dated.'}},
            'links': {'self': A(f'{V}/index.json'), 'openapi': A(f'{V}/openapi.json'), 'docs': A(API_DOCS), 'schemas': A(f'{V}/schemas/') + '{name}.schema.json',
                      'changelog': A(f'{V}/changelog.json'), 'llms_txt': A('/llms.txt'), 'llms_full_txt': A('/llms-full.txt'),
                      'license': f'{REPO_URL}/blob/main/LICENSE-DATA.md', 'source': REPO_URL,
                      'github_mirror': RAW_BASE + '/', 'github_mirror_api': RAW_BASE + '/api/v1/'},
            'license': {'data': lic, 'code': 'MIT', 'attribution': 'Credit "Commonworld Atlas" with a link.'},
            'access': 'No key. Static files with CORS open (Access-Control-Allow-Origin: *). Cloudflare and browsers may cache responses for up to a few hours.',
            'stability': api_v1.VERSIONING}
    write(f'{V}/index.json', api_json(root))


def build_api_docs(site):
    b, V, A = site.base, api_v1.API_BASE, site.abs
    crumbs, crumb_ld = breadcrumbs(site, [('Atlas', f'{b}/'), ('API', API_DOCS)])
    lic = site.cfg.get('data_licence') or 'not yet specified'
    ids = [c['slug'] for c in site.cards]
    ex = next((s for s in ('dealwork-ai', 'bountybook') if s in ids), ids[0])
    rows = [('API root: version, modules, links', f'{V}/index.json'),
            ('Atlas module: counts, categories, links', f'{V}/atlas/index.json'),
            ('All published entries', f'{V}/atlas/platforms.json'),
            ('One entry with all claims and sources', f'{V}/atlas/platforms/&lt;id&gt;.json'),
            ('Entries of one category', f'{V}/atlas/categories/&lt;category&gt;.json'),
            ('Where agents get paid (money figures by unit)', f'{V}/atlas/earn.json'),
            ('OpenAPI 3.1 description', f'{V}/openapi.json'),
            ('JSON Schemas (2020-12)', f'{V}/schemas/platform.schema.json'),
            ('Changelog', f'{V}/changelog.json')]
    trs = ''.join(f'<tr><td>{t}</td><td>' + (f'<a href="{u}"><code>{u}</code></a>' if '&lt;' not in u else f'<code>{u}</code>') + '</td></tr>' for t, u in rows)
    cats = ', '.join(f'<code>{k}</code>' for k in site.cats)
    curl = (f'curl -s {A(V + "/index.json")}\n'
            f'curl -s {A(V + "/atlas/platforms.json")} | jq \'.platforms[] | {{id, name, status}}\'\n'
            f'curl -s {A(V + "/atlas/platforms/" + ex + ".json")} | jq \'.claims[] | {{kind, statement, basis, source_url}}\'\n'
            f'curl -s {A(V + "/atlas/categories/work.json")} | jq \'.count\'')
    lead = ('<p>The Commonworld API is a set of static, read-only JSON files: no key, no sign-up, open CORS. '
            'It is one namespace for the whole platform; the Atlas of agent platforms is its first module.</p>')
    body = f"""{crumbs}
{cw.hero('Atlas · API', 'Commonworld API v1', lead, small=True, kicker_href=f'{b}/')}
<div class="prose">
<h2 id="endpoints">What is there</h2>
<div class="table-wrap"><table class="list"><thead><tr><th scope="col">What</th><th scope="col">URL</th></tr></thead><tbody>{trs}</tbody></table></div>
<p>Categories: {cats}. Every data document carries <code>schema_version</code> and a link to its JSON Schema.</p>
<h2 id="ids">IDs</h2>
<p>An entry ID is its permanent URL slug (for example <code>{e(ex)}</code>). Never construct or guess an ID: take it from <a href="{V}/atlas/platforms.json">platforms.json</a> or a category file. An ID that is not listed there does not exist, and the request returns 404.</p>
<h2 id="examples">Examples</h2>
<div class="badge-snippet-head"><span id="api-ex-l">curl + jq</span><button type="button" class="cw-btn badge-copy" data-copy-for="api-ex" data-track="api_use" data-format="examples" aria-describedby="api-ex-l" hidden>Copy</button></div>
<pre><code id="api-ex">{e(curl)}</code></pre>
<p class="copy-status sr" role="status" aria-live="polite"></p>
<h2 id="access">Access, caching and CORS</h2>
<ul><li>Static files served by Cloudflare: no key and no rate limit beyond fair use. Please cache on your side instead of polling.</li>
<li>CORS is open (<code>Access-Control-Allow-Origin: *</code>), so browser apps can read the files directly. JSON files are served as <code>application/json</code> (UTF-8); a wrong ID returns HTTP 404.</li>
<li>Cloudflare and browsers may keep a copy for up to a few hours, so a change can take that long to show. The data itself is rebuilt with every change to the site, including the weekly re-check; <code>generated_at</code> says when.</li>
<li>If commonworld.one cannot be reached, the same data is mirrored on GitHub: <a href="{RAW_BASE}/platforms.json" rel="nofollow noopener">raw.githubusercontent.com/…/atlas/public/</a>, with the API description under <code>atlas/public/api/v1/</code>. The site stays canonical.</li></ul>
<h2 id="stability">Stability promise</h2>
<p>{e(api_v1.VERSIONING)} The older files at <code>{b}/platforms.json</code>, <code>{b}/platforms/&lt;id&gt;.json</code>, <code>{b}/categories/&lt;category&gt;.json</code> and <code>{b}/earn.json</code> carry the same records and keep working. See the <a href="{V}/changelog.json">changelog</a>.</p>
<h2 id="schemas">Schemas</h2>
<p>The <a href="{V}/openapi.json">OpenAPI 3.1 description</a> lists every path; response shapes are JSON Schema 2020-12 files: <a href="{V}/schemas/platform.schema.json">platform</a>, <a href="{V}/schemas/platform-list.schema.json">platform list</a>, <a href="{V}/schemas/category.schema.json">category</a>, <a href="{V}/schemas/earn.schema.json">earn</a> and <a href="{V}/schemas/earn-row.schema.json">earn row</a>. Every published file is validated against them before it ships.</p>
<h2 id="license">License</h2>
<p>Data: {e(lic)}. Please credit “Commonworld Atlas” with a link. Code: MIT. Details in <a href="{REPO_URL}/blob/main/LICENSE-DATA.md" rel="nofollow noopener">LICENSE-DATA.md</a>. How each fact is checked: <a href="{b}/about/">How the Atlas works</a>. For a short map aimed at AI agents, see <a href="/llms.txt">/llms.txt</a>.</p>
</div>"""
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'TechArticle', 'name': 'Commonworld API v1', 'url': A(API_DOCS), 'inLanguage': 'en',
                     'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld Atlas', 'url': A(f'{b}/')}}]
    return page(site, path=API_DOCS, title='Commonworld API v1: static JSON for the Atlas | Commonworld',
                description='Read the Commonworld Atlas as data: static JSON files with open CORS, an OpenAPI 3.1 description and JSON Schemas. No key needed.',
                body=body, active='api', ld=ld,
                og=og_generic(site, 'page-api', 'Commonworld API v1',
                              'Static JSON with open CORS, an OpenAPI 3.1 description and JSON Schemas. No key needed.',
                              [('static JSON', 'olive'), ('OpenAPI 3.1', None), ('CC BY 4.0', None)], kicker='API'))


# ---------------------------------------------------------------- main
PUBLIC_FIELDS = ['id', 'slug', 'name', 'entity_type', 'category', 'census_category', 'status', 'canonical_url', 'description_en', 'claims', 'qa', 'qa_status', 'verdict', 'status_history', 'disclosure']


# Security headers for every page (written into /_headers for Cloudflare Pages).
PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), browsing-topics=(), payment=(), usb=()'
# Strict CSP, no 'unsafe-inline' anywhere:
# - our own inline scripts (the tiny pre-paint boot script) are allowed by their sha256 hash, computed from the
#   written pages (write() collects them; check.py re-hashes every page and fails on any script without a hash);
# - no style="" attributes and no inline <style>: colors, catbar widths and ad sizes are generated CSS classes;
# - JSON-LD / application/json blocks are data, not executed, so CSP does not apply to them;
# - Cloudflare's own scripts load from /cdn-cgi/ on our origin ('self'). Its JavaScript Detections bootstrap is an
#   inline snippet that changes on every response; functions/_middleware.js adds a fresh per-request nonce to
#   script-src and Cloudflare stamps that nonce on the scripts it injects (documented Cloudflare behaviour).
CSP_SCRIPT_HOSTS = "https://www.googletagmanager.com https://*.googletagmanager.com https://static.cloudflareinsights.com"


def csp_hash(src):
    return "'sha256-" + base64.b64encode(hashlib.sha256(src.encode('utf-8')).digest()).decode() + "'"


# executable inline <script> (no src, not a JSON data block) and inline <style>; check.py uses the same patterns
INLINE_SCRIPT_RE = re.compile(r'<script\b(?![^>]*\bsrc=)(?![^>]*\btype="application/(?:ld\+)?json")[^>]*>(.*?)</script>', re.S)
INLINE_STYLE_RE = re.compile(r'<style\b[^>]*>(.*?)</style>', re.S)


def build_csp(script_hashes, style_hashes=()):
    return '; '.join([
        "default-src 'self'",
        ' '.join(["script-src 'self'", *sorted(script_hashes), CSP_SCRIPT_HOSTS]),
        "script-src-attr 'none'",
        ' '.join(["style-src 'self'", *sorted(style_hashes)]),
        "style-src-attr 'none'",
        "img-src 'self' data: https://*.google-analytics.com https://*.googletagmanager.com https://*.analytics.google.com",
        "connect-src 'self' https://*.google-analytics.com https://google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com https://cloudflareinsights.com https://*.cloudflareinsights.com",
        "font-src 'self' data:",
        "frame-src 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
        "upgrade-insecure-requests",
    ])


# Pages Functions run only for HTML pages (the nonce middleware); static assets and JSON skip the Function entirely.
ROUTES = {'version': 1, 'include': ['/*'],
          'exclude': ['/atlas/assets/*', '/atlas/og/*', '/atlas/screens/*', '/atlas/badge/*', '/atlas/data/*',
                      '/atlas/platforms/*.json', '/atlas/categories/*.json', '/atlas/*.json', '/atlas/*.txt', '/atlas/*.xml',
                      '/atlas/decisions/index.md', '/stats.json', '/stats/index.md', '/api/*', '/cdn-cgi/*', '/favicon.ico', '/robots.txt', '/sitemap.xml',
                      '/llms.txt', '/llms-full.txt', '/404.html']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DEFAULT_DATA)
    ap.add_argument('--config', default=os.path.join(HERE, 'site-config.json'))
    ap.add_argument('--out', default=os.path.join(HERE, 'dist'))
    ap.add_argument('--tags', default=TAGS_FILE, help='census tags (descriptive labels, not verified claims)')
    ap.add_argument('--local', action='store_true', help="local preview: cross-product links (site.product_url) point to '/'")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.local:
        cfg['site']['product_url'] = '/'
    data = json.load(open(a.data))
    removed = load_removed()
    gone = {r['slug'] for r in removed}
    if any(c.get('slug') in gone for c in data['platforms']):  # removed.json wins over the data file
        print(f"note: dropping removed entries still in the data: {sorted(c['slug'] for c in data['platforms'] if c.get('slug') in gone)}", file=sys.stderr)
        data['platforms'] = [c for c in data['platforms'] if c.get('slug') not in gone]
        data['count'] = len(data['platforms'])
    site = Site(cfg, data)
    site.removed = removed
    site.safety = load_link_safety()
    bad = [c.get('slug') for c in site.cards if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', str(c.get('slug') or ''))]
    bad += [r.get('slug') for r in removed if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', str(r.get('slug') or ''))]
    if bad:
        raise SystemExit(f'invalid slug(s) in data (allowed: a-z 0-9 -): {bad[:5]}')
    lab_path = os.path.join(HERE, 'claim-labels.json')
    site.claim_labels = {k: v for k, v in json.load(open(lab_path)).items() if not k.startswith('_')} if os.path.exists(lab_path) else {}
    tags = json.load(open(a.tags))['tags'] if a.tags and os.path.exists(a.tags) else {}
    enrich(site, tags)
    site.shot_dir, shots, site.shot_src = screens.load()
    site.shots = {c['slug']: shots[c['slug']] for c in site.cards if c['slug'] in shots}
    try:
        import PIL  # noqa: F401  thumbnails need Pillow; without it the grids reuse the full image
        site.thumbs_ok = bool(site.shots)
    except ImportError:
        site.thumbs_ok = False
    if not site.shots:
        msg = f'no homepage screenshots ({site.shot_src}): pages show placeholders'
        if os.environ.get('CW_SCREENS_REQUIRED') == '1':
            raise SystemExit('screens required (CW_SCREENS_REQUIRED=1) but ' + msg)
        print('WARNING: ' + msg, file=sys.stderr)
    site.earn = earn_rows(site)
    css = open(os.path.join(HERE, 'components', 'cw-components.css')).read() + '\n' + open(os.path.join(HERE, 'static', 'atlas.css')).read()
    css += '\n/* category swatches (generated from CATEGORIES) */\n' + cw.color_classes([(k, col) for k, _, _, col, _ in CATEGORIES]) + '\n'
    # strict CSP: no style="" attributes, so widths and slot sizes are classes too
    css += '/* catbar widths + ad slot sizes (generated) */\n' + cw.flex_classes(len(v) for v in site.by_cat.values()) + cw.ad_slot_classes(cfg) + '\n'
    js = open(os.path.join(HERE, 'components', 'cw-components.js')).read() + '\n' + open(os.path.join(HERE, 'static', 'atlas.js')).read()
    import hashlib
    site.asset_v = hashlib.sha1((css + js).encode()).hexdigest()[:10]
    # logo/favicon images: own version so a new mark reaches cached browsers (assets/* is max-age=7d)
    sdir = os.path.join(HERE, 'static')
    site.img_v = cw.MARK_V = hashlib.sha1(b''.join(open(os.path.join(sdir, f), 'rb').read() for f in sorted(os.listdir(sdir)) if f.endswith(('.svg', '.png', '.ico')))).hexdigest()[:10]

    out, b = a.out, site.base
    if os.path.isdir(out):
        shutil.rmtree(out)
    root = os.path.join(out, b.strip('/'))

    out_root = os.path.realpath(out)
    script_hashes, style_hashes = set(), set()

    def write(rel, content, mode='w'):
        p = os.path.join(out, rel.lstrip('/'))
        # never write outside dist (a crafted slug like '../x' in untrusted data must fail the build)
        if os.path.commonpath([out_root, os.path.realpath(p)]) != out_root:
            raise SystemExit(f'refusing to write outside {out}: {rel!r}')
        if p.endswith('/'):
            p += 'index.html'
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if p.endswith('.html') and isinstance(content, str):
            script_hashes.update(csp_hash(m.group(1)) for m in INLINE_SCRIPT_RE.finditer(content))
            style_hashes.update(csp_hash(m.group(1)) for m in INLINE_STYLE_RE.finditer(content))
        with open(p, mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
            f.write(content)

    write('/', build_landing(site))  # Commonworld landing (main product placeholder)
    write(f'{b}/', build_index(site))
    write(f'{b}/platforms/', build_all(site))
    for c in site.cards:
        write(c['_url'], build_platform(site, c))
    for r in removed:  # slugs are permanent: a removed entry keeps a neutral noindex stub
        write(f"{b}/platforms/{r['slug']}/", build_removed_stub(site, r['slug']))
    write(f'{b}/categories/', build_categories_index(site))
    for k in site.cats:
        write(f'{b}/categories/{k}/', build_category(site, k))
    write(f'{b}/closed/', build_closed(site))
    write(f'{b}/earn/', build_earn(site))
    write(f'{b}/about/', build_about(site))
    write(DECISIONS_PATH, build_decisions(site))
    write(DECISIONS_MD, build_decisions_md(site))
    write(f'{b}/badge/', build_badge_page(site))
    write(API_DOCS, build_api_docs(site))
    n_badges = write_badges(site, write)
    write(CW_ABOUT, build_cw_about(site))  # About Commonworld
    stats_doc = load_stats(site)  # public stats: atlas/data/stats.json (+ Atlas counts derived from the data)
    write(STATS_PATH, build_stats(site, stats_doc))
    write(STATS_MD, build_stats_md(site, stats_doc))
    write(STATS_JSON, json.dumps(stats_doc, ensure_ascii=False, indent=1) + '\n')
    priv_url, terms_url = legal_urls(site)
    write(priv_url, build_privacy(site))
    write(terms_url, build_terms(site))
    old_legal = [(f'{b}/privacy/', priv_url, 'Commonworld Privacy Policy'), (f'{b}/terms/', terms_url, 'Commonworld Terms of Use')]
    for old, new, name in old_legal:
        if old != new:
            write(old, build_legal_redirect(site, old, new, name))
    write('/404.html', build_404(site))

    os.makedirs(os.path.join(root, 'assets'), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, 'static')):
        if f.endswith(('.png', '.ico', '.svg')):
            shutil.copy(os.path.join(HERE, 'static', f), os.path.join(root, 'assets', f))
    shutil.copy(os.path.join(HERE, 'static', 'favicon.ico'), os.path.join(out, 'favicon.ico'))  # browsers request /favicon.ico on their own
    if site.shots:  # homepage screenshots (orphan branch atlas-screens) -> /atlas/screens/, top-band thumbnails -> /atlas/screens/t/
        sdir = os.path.join(root, SHOTS_PATH.strip('/'))
        os.makedirs(os.path.join(sdir, 't'), exist_ok=True)
        sb = tb = 0
        for slug, r in sorted(site.shots.items()):
            shutil.copy(os.path.join(site.shot_dir, r['file']), os.path.join(sdir, r['file']))
            sb += r['bytes']
            if site.thumbs_ok:
                t = screens.thumb(os.path.join(site.shot_dir, r['file']), r['sha256'])
                with open(os.path.join(sdir, 't', r['file']), 'wb') as fh:
                    fh.write(t)
                tb += len(t)
        man = {'note': screens.RIGHTS + ' Site owners can ask for a screenshot to be replaced or removed via the corrections link.',
               'source': f'{REPO_URL}/tree/{screens.BRANCH}', 'count': len(site.shots),
               'screens': {s: {k: r.get(k) for k in ('file', 'sha256', 'source_url', 'captured_at', 'width', 'height', 'bytes')} for s, r in sorted(site.shots.items())}}
        write(f'{b}{SHOTS_PATH}/manifest.json', json.dumps(man, ensure_ascii=False, indent=1) + '\n')
        print(f'screens: {len(site.shots)} of {len(site.cards)} cards from {site.shot_src}; {sb // 1024} KB full + {tb // 1024} KB thumbnails')
    if site.og_enabled:
        import time
        t0 = time.time()
        rendered, cached = ogi.render_all(site.og_jobs, os.path.join(root, 'og'))
        og_bytes = sum(os.path.getsize(os.path.join(root, 'og', f)) for f in os.listdir(os.path.join(root, 'og')))
        print(f'og images: {len(site.og_jobs)} ({rendered} rendered, {cached} from cache) {og_bytes // 1024} KB in {time.time() - t0:.1f}s')
    else:
        print('WARNING: Pillow not installed: all pages use the static og-atlas.png (pip install Pillow for per-page OG images)', file=sys.stderr)
    write(f'{b}/assets/atlas.css', css)
    write(f'{b}/assets/atlas.js', js)

    pub = {'name': 'Commonworld Atlas', 'url': site.abs(f'{b}/'), 'generated_at': data.get('generated_at'),
           'count': len(site.cards), 'license': cfg.get('data_licence') or 'not yet specified', 'fields_note': 'observed_at values are ISO 8601 UTC timestamps.',
           'platforms': [{k: c.get(k) for k in PUBLIC_FIELDS if k in c} | {'url': site.abs(c['_url']), 'link_safety': link_safety_of(site, c)} for c in site.cards]}
    write(f'{b}/data/snapshot.json', json.dumps(pub, ensure_ascii=False, indent=1))
    # search index for the catalog: claim statements + units per slug, fetched lazily by atlas.js
    sidx = {c['slug']: ' '.join(filter(None, [x.get('statement') or '' for x in c.get('claims', [])] + [x.get('unit') or '' for x in c.get('claims', [])]))
            for c in site.cards}
    write(f'{b}/data/search-index.json', json.dumps(sidx, ensure_ascii=False, separators=(',', ':')))

    write(SAFETY_PATH, json.dumps(safety_doc(site), ensure_ascii=False, indent=1) + '\n')  # not mirrored: it changes daily
    write(DECISIONS_JSON, json.dumps(decisions_doc(site), ensure_ascii=False, indent=1) + '\n')
    build_agent_files(site, write)
    build_earn_json(site, write)
    build_api(site, write)

    def sitemap(pages):
        sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for p, lm in pages:
            sm.append(f'<url><loc>{e(site.abs(p))}</loc>' + (f'<lastmod>{lm.strftime("%Y-%m-%d")}</lastmod>' if lm else '') + '</url>')
        sm.append('</urlset>')
        return '\n'.join(sm) + '\n'
    in_atlas = [x for x in site.pages if x[0].startswith(b + '/')]
    site_level = [x for x in site.pages if not x[0].startswith(b + '/')]
    write_github_mirror(out, b)
    write(f'{b}/sitemap.xml', sitemap(in_atlas))
    write('/sitemap.xml', sitemap(site_level))  # Commonworld-wide pages (privacy, terms); the main site may take this file over
    if site.cfg.get('indexnow_key'):  # public IndexNow key file (Bing/Yandex/etc. verify ownership with it)
        write('/' + site.cfg['indexnow_key'] + '.txt', site.cfg['indexnow_key'])
    # RFC 9116 security contact (Cloudflare Security Insights flagged it missing). Expires must stay in the future: refreshed on every build.
    _exp = (datetime.now(timezone.utc) + timedelta(days=365)).strftime('%Y-%m-%dT00:00:00Z')
    write('/.well-known/security.txt', f"Contact: mailto:{site.cfg['contact']['general']}\nExpires: {_exp}\nPreferred-Languages: en\nCanonical: {site.abs('/.well-known/security.txt')}\n")
    write('/robots.txt', f'User-agent: *\nAllow: /\n\nSitemap: {site.abs("/sitemap.xml")}\nSitemap: {site.abs(b + "/sitemap.xml")}\n')
    # Cloudflare Pages redirects: old Atlas-only legal URLs -> site-wide ones
    red_path = os.path.join(HERE, '..', 'data', 'redirects.json')  # moved pages: old path -> new path (check.py growth guard)
    moved = (json.load(open(red_path)).get('redirects') or {}) if os.path.exists(red_path) else {}
    write('/_redirects', ''.join(f'{old} {new} 301\n{old.rstrip("/")} {new} 301\n' for old, new, _ in old_legal if old != new)
          + ''.join(f'{old} {new} 301\n' for old, new in moved.items()))
    write('/_headers', f"""{b}/assets/*
  Cache-Control: public, max-age=604800
{b}/og/*
  Cache-Control: public, max-age=86400
{b}{SHOTS_PATH}/*
  Cache-Control: public, max-age=86400
{b}/badge/*.svg
  Cache-Control: public, max-age=3600
  Access-Control-Allow-Origin: *
  Content-Type: image/svg+xml; charset=utf-8
{b}/platforms.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
{b}/platforms/*.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
{b}/earn.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
{b}/safety.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
{b}/decisions.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
{b}/decisions/index.md
  Access-Control-Allow-Origin: *
  Content-Type: text/markdown; charset=utf-8
/stats.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
/stats/index.md
  Access-Control-Allow-Origin: *
  Content-Type: text/markdown; charset=utf-8
{b}/categories/*.json
  Access-Control-Allow-Origin: *
  Content-Type: application/json; charset=utf-8
/api/*
  Access-Control-Allow-Origin: *
/api/v1/CHANGELOG.md
  Content-Type: text/markdown; charset=utf-8
{b}/llms.txt
  Access-Control-Allow-Origin: *
  Content-Type: text/plain; charset=utf-8
/llms.txt
  Access-Control-Allow-Origin: *
  Content-Type: text/plain; charset=utf-8
/llms-full.txt
  Access-Control-Allow-Origin: *
  Content-Type: text/plain; charset=utf-8
/*
  Strict-Transport-Security: max-age=15552000
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: SAMEORIGIN
  Permissions-Policy: {PERMISSIONS_POLICY}
  Content-Security-Policy: {build_csp(script_hashes, style_hashes)}
""")
    write('/_routes.json', json.dumps(ROUTES, indent=1) + '\n')  # which paths run functions/_middleware.js (HTML only)
    total = sum(1 for _ in site.pages)
    print(f'built {total} indexable pages + 404 into {out} ({len(site.cards)} entries, {len(site.cats)} categories, {n_badges} badges x2)')


if __name__ == '__main__':
    main()
