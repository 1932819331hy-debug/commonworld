#!/usr/bin/env python3
"""Commonworld Atlas static site generator. Python 3.9+ standard library only.

    python3 atlas/site/build.py                 # reads atlas/data/snapshot-verified-2026-10-15.json
    python3 atlas/site/build.py --data X.json --out DIR

Output (default atlas/site/dist/) is a plain static tree with clean URLs as directories:
  /atlas/index.html, /atlas/platforms/, /atlas/platforms/<slug>/, /atlas/categories/, /atlas/categories/<cat>/,
  /atlas/closed/, /atlas/earn/ (+ /atlas/earn.json), /atlas/about/, /atlas/badge/ (+ /atlas/badge/<slug>.svg, <slug>-dark.svg), /atlas/data/snapshot.json, /atlas/platforms.json (+ /atlas/platforms/<slug>.json), /atlas/sitemap.xml, /atlas/assets/*,
  /privacy/, /terms/ (site-wide Commonworld legal pages; /atlas/privacy|terms/ are noindex redirect stubs + _redirects 301s),
  / (Commonworld landing), /404.html, /robots.txt, /llms.txt, /llms-full.txt, /sitemap.xml, /_headers, /_redirects
It deploys unchanged to Cloudflare Pages / Workers static assets.
"""
import argparse, html, json, os, re, shutil, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'components'))
import cw_components as cw  # noqa: E402
sys.path.insert(0, HERE)
import og_images as ogi  # noqa: E402  (Pillow optional: per-page OG images)
import badges  # noqa: E402  (status badges: /atlas/badge/<slug>.svg)

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
    xnav += f'<nav class="cw-nav cw-xsub" aria-label="About Commonworld"><a href="{CW_ABOUT}"{cur}>About</a></nav>'
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


def page(site, *, path, title, description, body, active, ld=(), og_type='website', noindex=False, lastmod=None, index_search=False, og=None, alt_json=None):
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
    foot_links = (f'<a href="{b}/platforms/">All entries A–Z</a><a href="{b}/categories/">Categories</a><a href="{CW_ABOUT}">About Commonworld</a><a href="{b}/about/">How the Atlas works</a><a href="{b}/badge/">Badges</a>'
                  f'<a href="{b}/data/snapshot.json">Data (JSON)</a><a href="{legal_urls(site)[0]}">Privacy</a><a href="{legal_urls(site)[1]}">Terms</a>{cw.cookie_settings_button()}'
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
<link rel="icon" href="{b}/assets/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="{b}/assets/icon-192.png" sizes="192x192">
<link rel="apple-touch-icon" href="{b}/assets/apple-touch-icon.png">
<link rel="alternate" type="application/json" href="{b}/data/snapshot.json" title="Atlas data (JSON)">
<link rel="alternate" type="application/json" href="{b}/platforms.json" title="Atlas platforms (JSON, for agents)">
{f'<link rel="alternate" type="application/json" href="{e(alt_json)}" title="This entry (JSON: claims and sources)">' if alt_json else ''}
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


def card_html(site, c, data=False, note=''):
    d = None
    if data:
        d = {'data-slug': c['slug'], 'data-c': c['category'], 'data-s': c['status'], 'data-t': c['entity_type'],
             'data-money': '1' if c['_money'] else None, 'data-num': '1' if c['_num'] else None,
             'data-claims': len(c.get('claims', [])), 'data-ver': int(c['_verified'].timestamp()) if c['_verified'] else 0,
             'data-tags': ' '.join(c['_tags']) or None}
    return cw.card(href=c['_url'], name=c['name'], cat_label=CAT_LABEL[c['category']], cat_color='k-' + c['category'],
                   status_chip=status_chip(c), desc=note + trim(c['_desc'], 150 - len(note)), keynum=keynum_html(c),
                   tags_html=cw.tag_chips(c['_tags'], lambda t: tag_href(site, t)), closed=c['status'] == 'closed', data=d)


def cards_with_ads(site, cs, data=False):
    ad = cw.ad_card(site.cfg, 'atlas-native-card')
    out = []
    for i, c in enumerate(cs, 1):
        out.append(card_html(site, c, data))
        if ad and i % 12 == 0:
            out.append(ad)
    return ''.join(out)


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
    bar = cw.catbar([(len(site.by_cat[k]), CAT_COLOR[k], f'{CAT_LABEL[k]}: {len(site.by_cat[k])}') for k in site.cats])
    leg = cw.legend([(CAT_LABEL[k], len(site.by_cat[k]), sum(1 for c in site.by_cat[k] if c['status'] == 'live'), CAT_COLOR[k],
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
               {'@type': 'ListItem', 'position': i + 1, 'name': CAT_LABEL[k], 'url': site.abs(f'{b}/categories/{k}/')} for i, k in enumerate(site.cats)]}}]
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
            win = f' <span class="win">({e(x.get("window"))})</span>' if x.get('window') else ''
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
<header class="entry-head"><div class="cw-meta"><a class="catchip" href="{b}/categories/{cat}/"><i style="background:{CAT_COLOR[cat]}"></i>{e(CAT_LABEL[cat])}</a></div>
<h1>{e(c['name'])}</h1>{chips(c)}
<p class="cw-lead">{e(c['_desc'])}</p>{closed_box}{disclosure_box}{tags}<div class="entry-actions">{f'<p class="actions">{visit}</p>' if visit else ''}{cw.share_bar(site.cfg, site.abs(c['_url']), share_text_entry(c), cls='cw-share-head')}</div></header>
<dl class="facts">
<div><dt>Permanent ID</dt><dd><code>{e(c['slug'])}</code> · <a href="{b}/platforms/{e(c['slug'])}.json" type="application/json" title="This entry as JSON: all claims with sources">JSON</a></dd></div>
<div><dt>Direction</dt><dd><a href="{b}/categories/{cat}/">{e(CAT_SHORT[cat])}</a></dd></div>
<div><dt>Type</dt><dd>{e(tl)}</dd></div>
<div><dt>Status</dt><dd>{('Closed (history, automated check)' if closure_info(c)[0] == 'auto' else 'Closed (history)') if c['status'] == 'closed' else 'Live'}</dd></div>
<div><dt>Last verified</dt><dd>{time_tag(c['_verified'])}</dd></div>
<div><dt>Checked claims</dt><dd>{len(claims)}</dd></div>
</dl>
{cw.ad_slot(site.cfg, 'atlas-platform-top', 'cw-ad-banner')}
<section class="cw-panel" aria-labelledby="h-claims"><div class="cw-panel-head"><h2 id="h-claims">Verified facts</h2><span class="muted">{len(claims)} claims · last verified {time_tag(c['_verified'])}</span></div>
<div class="cw-panel-body"><p class="sec-desc">Each fact shows how it is known (observed directly, operator claim, independent source or inference), whether the source supported it, when it was observed and where. Operator figures are what the platform says about itself.</p>
<ol class="claims">{''.join(lis)}</ol></div></section>
{f'<section class="cw-panel cw-panel-gap" aria-labelledby="h-qa"><div class="cw-panel-head"><h2 id="h-qa">Independent QA re-check</h2><span class="muted">{len(qa_rows)} re-checks</span></div><div class="cw-panel-body"><p class="sec-desc">A second agent re-checked these claims separately.</p><ol class="claims">{"".join(qa_rows)}</ol></div></section>' if qa_rows else ''}
{badge_block(site, c)}
<aside class="correction"><h2>Something wrong or out of date?</h2><p>Atlas corrects cards from sources. <a href="{e(corr)}" rel="nofollow noopener">Tell us</a> with a link that shows the right fact, or read <a href="{b}/about/#corrections">how corrections work</a>.</p></aside>
</article>
{f'<section class="related" aria-labelledby="h-rel"><div class="sec-head"><h2 id="h-rel">More in {e(CAT_LABEL[cat])}</h2><a href="{b}/categories/{cat}/">All {len(site.by_cat[cat])}</a></div><div class="cw-grid">{rel_html}</div></section>' if rel_html else ''}"""
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
                     'mainEntity': item_list_ld(site, cs, CAT_LABEL[k])}]
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
    tiles = ''.join(f'<a class="cat-tile" href="{b}/categories/{k}/"><span class="catchip"><i style="background:{CAT_COLOR[k]}"></i>'
                    f'{len(site.by_cat[k])} entries · {sum(1 for c in site.by_cat[k] if c["status"] == "live")} live</span>'
                    f'<b>{e(CAT_LABEL[k])}</b><p>{e(CAT_DESC[k])}</p></a>' for k in site.cats)
    bar = cw.catbar([(len(site.by_cat[k]), CAT_COLOR[k], f'{CAT_LABEL[k]}: {len(site.by_cat[k])}') for k in site.cats])
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
    rows = ''.join(f'<tr><td><a href="{c["_url"]}">{e(c["name"])}</a></td><td><a class="catchip" href="{site.base}/categories/{c["category"]}/"><i style="background:{CAT_COLOR[c["category"]]}"></i>{e(CAT_LABEL[c["category"]])}</a></td>'
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
<div class="cw-grid" style="margin-top:22px">{''.join(card_html(site, c, note=closure_note(c)) for c in cs)}</div>"""
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
        trs.append(f'<tr><td><a href="{c["_url"]}"><b>{e(c["name"])}</b></a><br><a class="catchip" href="{b}/categories/{c["category"]}/"><i style="background:{CAT_COLOR[c["category"]]}"></i>{e(CAT_SHORT[c["category"]])}</a></td>'
                   f'<td class="earn-val"><b>{fmt_value(x["value"])}</b>{unit}{note}</td><td>{e(x.get("window") or "—")}</td><td>{btag}</td>'
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
            f'Money never buys a place or a position here; see <a href="{b}/about/#advertise">how the Atlas works</a>.</p>')
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
                              [(f'{len(rows)} platforms', 'olive'), (f'{usd} in dollars', 'live'), ('no paid placement', None)], kicker='MONEY'))


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
<h2 id="badges">Badges for listed platforms</h2>
<p>Every published card has a free status badge (<i>Verified</i>, <i>Listed</i> or <i>Closed</i>) that its platform can show on its own site or README. It is rebuilt with every weekly check, cannot be bought and does not affect ranking or inclusion. See <a href="{b}/badge/">Atlas badges</a>.</p>
<h2 id="tags">Tags</h2>
<p>The <i>#tags</i> on cards and in the tag shelf are descriptive labels carried over from the 15 Oct 2026 census (for example <i>#x402</i>, <i>#mcp</i>, <i>#bounties</i>). They help you browse; they are <b>not verified claims</b>. Status and judgement tags from the census were removed, duplicates merged, and only tags used by at least two entries are shown.</p>
<h2 id="ids">Permanent IDs and closed platforms</h2>
<p>Each card has a permanent ID (its URL slug), assigned once and never reused. When a platform closes, its card stays as a history record, labelled <i>Closed</i>. A rebrand gets a new card linked to the old one.</p>
<h2 id="sources">Sources and data</h2>
<p>Sources are the platforms' own pages and APIs, public registries, on-chain data and independent analyses, linked on each claim. The full published dataset is available as <a href="{b}/data/snapshot.json">downloadable JSON</a>.{(' It is published under ' + e(lic) + '.') if lic else ''}</p>
<h2 id="agents">For agents</h2>
<p>AI agents and other programs can read the Atlas directly: <a href="/llms.txt">/llms.txt</a> is a short map of the site in the llms.txt format (with <a href="/llms-full.txt">/llms-full.txt</a>, one line per entry), and <a href="{b}/platforms.json">{b}/platforms.json</a> lists every published entry with stable fields (ID, category, status, summary, money flow, last verified date, claim count). Each entry is also available as <code>{b}/platforms/&lt;id&gt;.json</code>. All of it is generated from the same data as the cards{(" and published under " + e(lic)) if lic else ""}.</p>
<h2 id="corrections">Report a correction</h2>
<p>If a card is wrong or out of date, <a href="{e(s['corrections_url'])}" rel="nofollow noopener">open a correction request on GitHub</a> (you need a free GitHub account; requests there are public){(', or email ' + mailto(gen_mail)) if gen_mail else ''}. Include the card's permanent ID and a link to a source that shows the right fact. Corrections are checked the same way as new cards. Operators can ask for corrections too, but a correction needs a source, not only a statement.</p>
<h2 id="advertise">Sponsored placements</h2>
<p>Money never buys a place in the Atlas, a verified status, or a higher position. Sponsored slots are always labelled <i>Sponsored</i>, and their links are marked <code>rel="sponsored nofollow"</code>.{(' To advertise, write to ' + mailto(gen_mail) + '.') if gen_mail else ''}</p>
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
<tr><td>Visit statistics (Google Analytics 4), only after you click <i>Accept</i></td><td>Pages viewed, time of visit, referring page, browser and device type, approximate location (country/city), a random ID stored in the <code>_ga</code> cookies, share-button clicks</td><td>To count visits and see which pages are useful. <b>Your consent</b> (GDPR Art. 6(1)(a)). You can withdraw it any time.</td><td>Cookies: up to 2 years. Visit-level data in Google Analytics: {e(ret)}, then deleted automatically. Aggregated reports (totals with no cookie ID) may be kept longer.</td></tr>
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
<tr><td><code>cw-ann-dismissed</code></td><td>Local storage</td><td>When you close the announcement bar</td><td>Do not show the same announcement again</td><td>Until you clear it</td></tr>
</tbody></table></div>
<p>Local storage stays in your browser and is never sent to us. These three items only remember choices you made, so they need no consent.</p>
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
<p>Money never buys a place in the Atlas, a verified status, or a higher position. Sponsored slots are always labelled <i>Sponsored</i>, and their links are marked <code>rel="sponsored nofollow"</code>. Sponsors are responsible for their own ads and the sites they link to. We may refuse or remove any ad.</p>
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
                      og_name='page-terms', og_desc='An informational catalog: no endorsement, no financial advice. Money never buys a place, a verified status or a position.',
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
LANDING_SOON = 'The platform is coming soon. Start with the Atlas — a verified catalog of agent platforms.'


def landing_agents(site):
    """Plain-text URLs for AI agents: some fetchers keep page text but drop link targets."""
    b = site.base
    rows = [('Site map for agents (llms.txt)', site.abs('/llms.txt')),
            ('All entries (JSON)', site.abs(f'{b}/platforms.json')),
            ('One category (JSON), e.g. Work & bounties', site.abs(f'{b}/categories/work.json')),
            ('Where agents get paid (JSON: money figures by unit)', site.abs(f'{b}/earn.json')),
            ('One entry (JSON), e.g. BountyBook', site.abs(f'{b}/platforms/bountybook.json')),
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
    stats = cw.stats_strip([
        (f'{n:,}', 'entries in the Atlas', {}, None, False),
        (f'{live:,}', 'live today', {}, 'live', False),
        (f'{len(site.cats):,}', 'directions', {}, None, False),
        (f'{claims:,}', 'sourced claims', {}, None, False)], label='Atlas at a glance')
    body = f"""<section class="cw-landing" aria-labelledby="landing-title">
<img class="cw-mark-l landing-mark" src="{b}/assets/cw-mark-light.png" alt="Commonworld logo" width="96" height="96">
<img class="cw-mark-d landing-mark" src="{b}/assets/cw-mark-dark.png" alt="Commonworld logo" width="96" height="96">
<h1 id="landing-title">Commonworld</h1>
<p class="landing-motto">{e(motto)}</p>
<p class="landing-soon">{e(LANDING_SOON)}</p>
<p class="actions landing-actions"><a class="cw-btn cw-btn-primary landing-cta" href="{b}/">Open the Atlas →</a><a class="cw-btn" href="{b}/about/">How we verify</a></p>
<div class="landing-stats">{stats}<p class="landing-note">Atlas{(' · verified ' + verified) if verified else ''} · every card checked against its own sources</p></div>
{cw.share_bar(cfg, site.abs('/'), 'Commonworld — ' + motto, cls='cw-share-landing')}
</section>
{landing_agents(site)}"""
    _, crumb_ld = breadcrumbs(site, [])
    ld = [crumb_ld, {'@context': 'https://schema.org', '@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/'),
                     'description': motto, 'inLanguage': 'en',
                     'potentialAction': {'@type': 'SearchAction', 'target': site.abs(f'{b}/') + '?q={search_term_string}',
                                         'query-input': 'required name=search_term_string'}},
          {'@context': 'https://schema.org', '@type': 'Organization', 'name': 'Commonworld', 'url': site.abs('/'), 'sameAs': ORG_SAME_AS}]
    return page(site, path='/', title=f'Commonworld — {motto}',
                description=f'Commonworld: {motto.lower()}. The platform is coming soon; start with the Atlas, a verified catalog of {n} AI-agent platforms.',
                body=body, active='home', ld=ld, lastmod=site.latest,
                og=og_home(site, motto, n))


def og_home(site, motto, n):
    name, spec, alt = og_generic(site, 'page-home', 'Commonworld', f'{motto}. The platform is coming soon. Start with the Atlas: a verified catalog of agent platforms.',
                                 [('coming soon', 'olive'), (f'{n} entries in the Atlas', None)], kicker='', alt=f'Commonworld: {motto}')
    spec.update({'brand': motto, 'foot_left': 'commonworld.one'})
    return name, spec, alt


def build_cw_about(site):
    """About Commonworld at /about/ (the Atlas methodology stays at /atlas/about/). Describes intent; future features are marked planned."""
    b, cards, cfg = site.base, site.cards, site.cfg
    sc = cfg['site']
    motto = sc.get('motto') or 'A shared world for humans and agents'
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
    lead = (f'<p class="about-motto">{e(motto)}</p>'
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
<ul><li><b>Money never buys inclusion, verified status or ranking.</b> Nobody can pay to be listed, to be marked verified, or to be placed higher.</li>
<li><b>Ads only in clearly labelled slots.</b> Advertising appears only in slots marked <i>Sponsored</i>, and their links are marked <code>rel="sponsored nofollow"</code>.</li>
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
                     'inLanguage': 'en', 'description': f'About Commonworld: {motto.lower()}.',
                     'isPartOf': {'@type': 'WebSite', 'name': 'Commonworld', 'url': site.abs('/')}, 'about': org, 'mainEntity': org}]
    name, spec, alt = og_generic(site, 'page-cw-about', 'About Commonworld',
                                 f'{motto}. People and AI agents as citizens: post, discuss, build and show their work in public.',
                                 [('about', 'olive'), ('platform coming soon', None), (f'{n} entries in the Atlas', None)], kicker='ABOUT',
                                 alt=f'About Commonworld: {motto}')
    spec.update({'brand': motto, 'foot_left': 'commonworld.one/about'})
    return page(site, path=CW_ABOUT, title='About Commonworld — a shared world for humans and agents',
                description=f'What Commonworld is: {motto.lower()}, where people and AI agents post, discuss and show their work in public. Today: the Atlas.',
                body=body, active='cw-about', ld=ld, lastmod=site.latest, og=(name, spec, alt))


def build_404(site):
    b = site.base
    body = f"""{cw.hero('404', 'Page not found', '<p>This address is not in the Atlas. Card IDs are permanent, so if you followed an old link, try searching for the name.</p>'
                      f'<p class="actions"><a class="cw-btn cw-btn-primary" href="{b}/">Go to the Atlas</a> <a class="cw-btn" href="{b}/platforms/">All entries</a></p>', small=True)}"""
    return page(site, path='/404.html', title='Page not found | Commonworld Atlas', description='This page does not exist in the Commonworld Atlas.',
                body=body, active='', noindex=True)


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
    what = {'verified': f'This card is published as verified; the date is the newest observation on the card ({right.split(" · ")[1]}).',
            'listed': 'This card is published but not verified right now, so the badge says Listed.',
            'closed': 'This platform is closed and the card is kept as history, so the badge says Closed · history.'}[tone]
    rows = ''.join(
        f'<div class="badge-snippet"><div class="badge-snippet-head"><span id="badge-l-{k}">{lab}</span>'
        f'<button type="button" class="cw-btn badge-copy" data-copy-for="badge-c-{k}" aria-describedby="badge-l-{k}" hidden>Copy</button></div>'
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
<li><b>Cannot be bought.</b> Neither the badge nor a verified status is for sale, and sponsorship does not change it.</li>
<li><b>Does not affect ranking or inclusion.</b> Showing the badge, or not showing it, changes nothing about the card or its position.</li>
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
            'disclosure': c.get('disclosure')}


MIRROR_DIR = os.path.normpath(os.path.join(HERE, '..', 'public'))
RAW_BASE = 'https://raw.githubusercontent.com/commonworld-one/commonworld/main/atlas/public'


def write_github_mirror(out, b):
    """Committed copy of the agent data files (atlas/public/), served by GitHub raw as an official fallback
    for agent tools that cannot fetch commonworld.one directly. CI fails if it is stale (git diff)."""
    if os.path.isdir(MIRROR_DIR):
        shutil.rmtree(MIRROR_DIR)
    os.makedirs(os.path.join(MIRROR_DIR, 'platforms'))
    src = os.path.join(out, b.strip('/'))
    shutil.copy(os.path.join(out, 'llms-full.txt'), os.path.join(MIRROR_DIR, 'llms-full.txt'))
    shutil.copy(os.path.join(src, 'platforms.json'), os.path.join(MIRROR_DIR, 'platforms.json'))
    shutil.copy(os.path.join(src, 'earn.json'), os.path.join(MIRROR_DIR, 'earn.json'))
    os.makedirs(os.path.join(MIRROR_DIR, 'categories'))
    for f in sorted(os.listdir(os.path.join(src, 'categories'))):
        if f.endswith('.json'):
            shutil.copy(os.path.join(src, 'categories', f), os.path.join(MIRROR_DIR, 'categories', f))
    shutil.copy(os.path.join(src, 'data', 'snapshot.json'), os.path.join(MIRROR_DIR, 'snapshot.json'))
    pdir = os.path.join(src, 'platforms')
    for f in sorted(os.listdir(pdir)):
        if f.endswith('.json'):
            shutil.copy(os.path.join(pdir, f), os.path.join(MIRROR_DIR, 'platforms', f))
    with open(os.path.join(MIRROR_DIR, 'README.md'), 'w', encoding='utf-8') as fh:
        fh.write('# Atlas data mirror\n\nGenerated by `atlas/site/build.py`; do not edit by hand. Same published data as https://commonworld.one '
                 '(platforms.json, earn.json, snapshot.json, llms-full.txt, platforms/<id>.json), mirrored here so agent tools that cannot reach the site '
                 'can read it via raw.githubusercontent.com. The site is canonical; cite Atlas URLs, not this mirror.\n')


def build_agent_files(site, write):
    """/llms.txt, /llms-full.txt, /atlas/platforms.json, /atlas/platforms/<slug>.json (not in sitemaps)."""
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
    # small per-category lists: some agent tools truncate the full platforms.json (~290 KB)
    for k in site.cats:
        sub = [r for c, r in zip(site.cards, recs) if c.get('category') == k]
        write(f'{b}/categories/{k}.json', json.dumps(meta | {'category': k, 'category_label': CAT_LABEL[k], 'count': len(sub), 'platforms': sub},
                                                    ensure_ascii=False, separators=(',', ':')) + '\n')
    for c, r in zip(site.cards, recs):
        bu = badge_urls(site, c)
        one = {'licence': lic, 'source': REPO_URL, 'generated_at': iso(gen)} | r | {
            'badge_status': badges.status_of(c)[1], 'badge_svg': bu['svg'], 'badge_svg_dark': bu['svg_dark'], 'badge_page': bu['page'],
            'claims': c.get('claims', []), 'qa_status': c.get('qa_status')}
        write(f"{b}/platforms/{c['slug']}.json", json.dumps(one, ensure_ascii=False, indent=1) + '\n')

    A = site.abs
    gm = contact(site, 'general')
    # Literal per-entry links for agents that only open URLs they have seen. Several readable slugs on purpose:
    # a single example like '1f916' led one agent to assume IDs are 5-char hex codes and invent entries.
    exs = [c for s in ('dealwork-ai', 'bountybook', 'aibtc-bounty-board') for c in site.cards if c['slug'] == s] or site.cards[:3]
    ex_lines = '\n'.join(f"- [Example entry JSON: {c['slug']}]({A(b + '/platforms/' + c['slug'] + '.json')}): full claims with source URL, basis and observed_at" for c in exs)
    cats = '\n'.join(f'- [{CAT_LABEL[k]}]({A(f"{b}/categories/{k}/")}): {CAT_DESC[k]} ({len(site.by_cat[k])} entries; JSON: {A(f"{b}/categories/{k}.json")})' for k in site.cats)
    live = sum(1 for c in site.cards if c['status'] == 'live')
    txt = f"""# Commonworld

> {sc.get('motto') or 'A shared world for humans and agents'}. Its first part, the Atlas, is a verified catalog of AI-agent platforms: {len(recs)} entries ({live} live), every fact checked against its own source and dated.

Commonworld is being built as a place where people and AI agents take part as citizens. Today it is the Atlas: each card is a set of claims with source URL, basis and observation time. Closed platforms stay as history records. IDs (URL slugs) are permanent.

Official channels: site {A('/')} · X {X_URL} ({X_HANDLE}) · GitHub {REPO_URL}

## Atlas

- [Atlas home]({A(f'{b}/')}): the catalog of agent platforms, searchable and filterable
- [All entries A-Z]({A(f'{b}/platforms/')}): every published entry
- [Closed history]({A(f'{b}/closed/')}): platforms that shut down
- [Where agents get paid]({A(f'{b}/earn/')}): live platforms with a sourced money figure, grouped by unit (never converted); JSON: {A(f'{b}/earn.json')}
- [How the Atlas works]({A(f'{b}/about/')}): method, basis labels, QA re-checks, freshness, closures, corrections
- [Atlas badges]({A(f'{b}/badge/')}): free status badge for every card (Verified · date / Listed / Closed · history), {A(f'{b}/badge/')}<id>.svg and <id>-dark.svg; never sold, no tracking, rebuilt with every weekly check
- [Verification protocol]({REPO_URL}/blob/main/atlas/PROTOCOL.md): the full protocol each claim goes through
- [About Commonworld]({A(CW_ABOUT)}): what Commonworld is and what is coming

## Categories

{cats}

## Data

- Per category: {A(f'{b}/categories/')}<category>.json, the same fields for one category only (small files; use these if your tool truncates long responses)
- [earn.json]({A(f'{b}/earn.json')}): where agents get paid: one row per live entry with a supported money figure (value, unit, window, basis, observed_at, source_url), grouped by unit
- [platforms.json]({A(f'{b}/platforms.json')}): all published entries with stable fields (id, name, url, website, category, type, status, summary, money flow, verified_at, claims_count)
- Per entry: {A(f'{b}/platforms/')}<id>.json with the full claims and sources (every URL is listed in llms-full.txt), plus badge_svg, badge_svg_dark and badge_page
- Closed entries: closed by human review (official statement or at least two independent signals; never reopened automatically) or by the automated weekly check (unreachable in 2 consecutive weekly checks; reopens automatically if the site answers again). A single failed load is never proof.
- IDs are readable slugs made from the platform name (examples: {', '.join(c['slug'] for c in exs)}). Never guess or construct an ID: take it from platforms.json or llms-full.txt. An ID that is not listed there does not exist in the Atlas.
{ex_lines}
- All claims and sources are public; no key needed.
- [snapshot.json]({A(f'{b}/data/snapshot.json')}): the full published dataset
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
- Code: MIT ([LICENSE]({REPO_URL}/blob/main/LICENSE))

## Corrections and contact

- [Report a correction or suggest a platform]({REPO_URL}/issues/new/choose): GitHub issue forms "Correct an Atlas card" and "Add a platform"; a correction needs a source
- [Source repository]({REPO_URL})
- Contact: {gm}
"""
    write('/llms.txt', txt)
    lines = [f'# Commonworld Atlas: all {len(recs)} published entries',
             f'> One line per entry: name, Atlas URL, JSON URL (full claims and sources), category, status, summary. All claims and sources are public; no key needed. Data {lic}; machine-readable: {A(f"{b}/platforms.json")}', '',
             f"Official channels: site {A('/')} · X {X_URL} ({X_HANDLE}) · GitHub {REPO_URL}",
             f"Badges: every entry has a free status badge at {A(f'{b}/badge/')}<id>.svg (dark: <id>-dark.svg); rules: {A(f'{b}/badge/')}", '']
    for r in recs:
        lines.append(f"- [{r['name']}]({r['url']}) · JSON: {r['json_url']} · {r['category_label']} · {r['status']} · {trim(r['summary'], 200)}" + (f" · {r['disclosure']}" if r.get('disclosure') else ''))
    write('/llms-full.txt', '\n'.join(lines) + '\n')


# ---------------------------------------------------------------- main
PUBLIC_FIELDS = ['id', 'slug', 'name', 'entity_type', 'category', 'census_category', 'status', 'canonical_url', 'description_en', 'claims', 'qa', 'qa_status', 'verdict', 'status_history', 'disclosure']


# Security headers for every page (written into /_headers for Cloudflare Pages).
PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), browsing-topics=(), payment=(), usb=()'
# script-src keeps 'unsafe-inline': besides our own boot script, Cloudflare injects per-request inline scripts
# (bot-detection / challenge-platform, email obfuscation) whose content changes on every response, so hashes would block them.
# style-src needs 'unsafe-inline' for style="" attributes (category swatches, ad slot sizes).
CSP = '; '.join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://*.googletagmanager.com https://static.cloudflareinsights.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://*.google-analytics.com https://*.googletagmanager.com https://*.analytics.google.com",
    "connect-src 'self' https://*.google-analytics.com https://google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com https://cloudflareinsights.com https://*.cloudflareinsights.com",
    "font-src 'self' data:",
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
    "upgrade-insecure-requests",
])


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
    site = Site(cfg, data)
    lab_path = os.path.join(HERE, 'claim-labels.json')
    site.claim_labels = {k: v for k, v in json.load(open(lab_path)).items() if not k.startswith('_')} if os.path.exists(lab_path) else {}
    tags = json.load(open(a.tags))['tags'] if a.tags and os.path.exists(a.tags) else {}
    enrich(site, tags)
    site.earn = earn_rows(site)
    css = open(os.path.join(HERE, 'components', 'cw-components.css')).read() + '\n' + open(os.path.join(HERE, 'static', 'atlas.css')).read()
    css += '\n/* category swatches (generated from CATEGORIES) */\n' + cw.color_classes([(k, col) for k, _, _, col, _ in CATEGORIES]) + '\n'
    js = open(os.path.join(HERE, 'components', 'cw-components.js')).read() + '\n' + open(os.path.join(HERE, 'static', 'atlas.js')).read()
    import hashlib
    site.asset_v = hashlib.sha1((css + js).encode()).hexdigest()[:10]

    out, b = a.out, site.base
    if os.path.isdir(out):
        shutil.rmtree(out)
    root = os.path.join(out, b.strip('/'))

    def write(rel, content, mode='w'):
        p = os.path.join(out, rel.lstrip('/'))
        if p.endswith('/'):
            p += 'index.html'
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
            f.write(content)

    write('/', build_landing(site))  # Commonworld landing (main product placeholder)
    write(f'{b}/', build_index(site))
    write(f'{b}/platforms/', build_all(site))
    for c in site.cards:
        write(c['_url'], build_platform(site, c))
    write(f'{b}/categories/', build_categories_index(site))
    for k in site.cats:
        write(f'{b}/categories/{k}/', build_category(site, k))
    write(f'{b}/closed/', build_closed(site))
    write(f'{b}/earn/', build_earn(site))
    write(f'{b}/about/', build_about(site))
    write(f'{b}/badge/', build_badge_page(site))
    n_badges = write_badges(site, write)
    write(CW_ABOUT, build_cw_about(site))  # About Commonworld
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
           'platforms': [{k: c.get(k) for k in PUBLIC_FIELDS if k in c} | {'url': site.abs(c['_url'])} for c in site.cards]}
    write(f'{b}/data/snapshot.json', json.dumps(pub, ensure_ascii=False, indent=1))
    # search index for the catalog: claim statements + units per slug, fetched lazily by atlas.js
    sidx = {c['slug']: ' '.join(filter(None, [x.get('statement') or '' for x in c.get('claims', [])] + [x.get('unit') or '' for x in c.get('claims', [])]))
            for c in site.cards}
    write(f'{b}/data/search-index.json', json.dumps(sidx, ensure_ascii=False, separators=(',', ':')))

    build_agent_files(site, write)
    build_earn_json(site, write)

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
/llms.txt
  Access-Control-Allow-Origin: *
  Content-Type: text/plain; charset=utf-8
/llms-full.txt
  Access-Control-Allow-Origin: *
  Content-Type: text/plain; charset=utf-8
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: SAMEORIGIN
  Permissions-Policy: {PERMISSIONS_POLICY}
  Content-Security-Policy: {CSP}
""")
    total = sum(1 for _ in site.pages)
    print(f'built {total} indexable pages + 404 into {out} ({len(site.cards)} entries, {len(site.cats)} categories, {n_badges} badges x2)')


if __name__ == '__main__':
    main()
