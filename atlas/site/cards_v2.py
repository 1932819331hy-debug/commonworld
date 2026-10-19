"""Atlas cards v2 (stdlib only): evidence ladder, keys and books, first task.

The rules here are the contract described in atlas/CURATION.md ("Cards v2"). build.py adds the results to every card page, its
Markdown twin, its JSON record and the API; check.py recomputes them from the published claims and fails on any drift;
tests/test_cards_v2.py pins the rules with examples.

1. Evidence ladder. Every money or activity claim (kind economic_flow, metric, recent_activity) gets a level from its source URL:
   3 public transactions  the source is a public block explorer (or a tx/address page on an explorer host): records anyone can
                          open and check independently;
   2 public dashboard     the source is a public stats page, dashboard or API (machine-readable endpoint) anyone can open;
   1 operator says        any other page: the platform's own words (site text, docs, posts) and other text pages.
   Where a URL could be read two ways, the rule takes the lower level. A card's level is the highest level reached by its
   supported money/activity claims; a card without one shows "not recorded yet".
2. Keys and books. Three questions per card: who holds the keys (custody of funds or accounts), whether the books are open (its money
   figures, such as payouts, balances or volume, publicly checkable), whether the people behind it are named. A value is filled only from a supported claim already on
   the card (curated in atlas/data/keys-and-books.json with the claim's source URL and a quote from that claim; open books are also
   derived from a supported money-flow claim at ladder level 2 or 3). Every other answer is "not recorded yet".
3. First task. One simple first step for a newcomer, from atlas/data/first-tasks.json. Only tasks a curator ran and verified are
   published, with credit to the contributor. Cards without one show no first-task block.
"""
import json
import os
import re
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, '..', 'data'))
KEYS_BOOKS_FILE = os.path.join(DATA_DIR, 'keys-and-books.json')
FIRST_TASKS_FILE = os.path.join(DATA_DIR, 'first-tasks.json')

NOT_RECORDED = 'not recorded yet'

# ---------------------------------------------------------------- 1. evidence ladder
EVIDENCE_KINDS = ('economic_flow', 'metric', 'recent_activity')
LEVELS = {
    1: ('operator_says', 'operator says', "The platform's own words: site text, docs or posts (and other text pages)."),
    2: ('public_dashboard', 'public dashboard', 'A public stats page, dashboard or API that anyone can open.'),
    3: ('public_transactions', 'public transactions', 'On-chain or other public records that anyone can open and check independently.'),
}
# Public block explorers: their pages are views of public chain records (a host matches itself and its subdomains).
EXPLORER_HOSTS = (
    'etherscan.io', 'basescan.org', 'arbiscan.io', 'polygonscan.com', 'bscscan.com', 'celoscan.io', 'lineascan.build', 'scrollscan.com',
    'snowtrace.io', 'ftmscan.com', 'solscan.io', 'explorer.solana.com', 'solana.fm', 'blockscout.com', 'mempool.space', 'blockstream.info',
    'blockchair.com', 'explorer.hiro.so', 'tronscan.org', 'tonviewer.com', 'tonscan.org', 'suiscan.xyz', 'explorer.aptoslabs.com',
    'oklink.com', 'kitescan.ai',  # kitescan.ai: the Blockscout explorer of the Kite chain
)
# Explorer-style record pages on other hosts that call themselves scanners or explorers: /tx/<hash>, /address/<addr>, ...
TX_PATH = re.compile(r'/(tx|txs|transaction|address|token|block)/(0x[0-9a-fA-F]{8,}|[1-9A-HJ-NP-Za-km-z]{32,}|\d+)(/|$)')
# Public dashboards run by independent trackers (whole site is a dashboard).
DASHBOARD_HOSTS = ('dune.com', 'chainward.ai', 'defillama.com', 'tokenterminal.com', 'x402scan.com')
# Path segments of stats pages, dashboards and APIs.
STATS_SEGMENT = re.compile(r'(^|/)(api|stats|statistics|analytics|dashboard|metrics|leaderboard|status)(/|$|\.|-)', re.I)
VERSIONED_API = re.compile(r'(^|/)v\d+(/|$)')
TEXT_ONLY_HOSTS = ('web.archive.org',)  # archived copies are read as text pages, whatever URL they wrap


def _host_in(host, hosts):
    return any(host == h or host.endswith('.' + h) for h in hosts)


def source_level(url):
    """Ladder level (1, 2 or 3) of one source URL, or None when there is no URL. Deterministic; ties go to the lower level."""
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return None
    u = urlparse(url)
    host = (u.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = u.path or '/'
    if _host_in(host, TEXT_ONLY_HOSTS):
        return 1
    if _host_in(host, EXPLORER_HOSTS):
        return 3
    if ('scan' in host.split('.')[0] or 'explorer' in host) and TX_PATH.search(path):
        return 3
    if _host_in(host, DASHBOARD_HOSTS) or host.startswith(('api.', 'stats.')) or STATS_SEGMENT.search(path) \
            or VERSIONED_API.search(path) or path.lower().endswith('.json'):
        return 2
    return 1


def claim_level(x):
    """Level of a money/activity claim (from its source URL), None for other kinds or a claim without a source."""
    if x.get('kind') not in EVIDENCE_KINDS:
        return None
    return source_level(x.get('source_url'))


def level_record(level):
    if level is None:
        return {'level': None, 'id': None, 'label': NOT_RECORDED}
    lid, label, _ = LEVELS[level]
    return {'level': level, 'id': lid, 'label': label}


def card_evidence(card):
    """Card-level summary: the highest level of its supported money/activity claims."""
    levels = [claim_level(x) for x in card.get('claims', []) if x.get('outcome') == 'supported']
    levels = [lv for lv in levels if lv]
    rec = level_record(max(levels) if levels else None)
    rec['claims_counted'] = len(levels)
    return rec


def annotate_claim(x):
    """Copy of a claim with evidence_level / evidence_label on money/activity claims (others unchanged)."""
    lv = claim_level(x)
    if lv is None:
        return dict(x)
    return dict(x) | {'evidence_level': lv, 'evidence_label': LEVELS[lv][1]}


# ---------------------------------------------------------------- 2. keys and books
KEYS_VALUES = {'operator': 'The operator holds the funds',
               'user_wallet': "Users hold their own wallet or keys",
               'smart_contract': 'A smart contract holds the funds'}
BOOKS_VALUES = {'public_transactions': 'Open: its money figures are on public transactions',
                'public_dashboard': 'Open: its money figures are on a public dashboard or API'}
PEOPLE_VALUES = {'named': 'Named'}
KB_FIELDS = {'keys': ('Who holds the keys', KEYS_VALUES), 'books': ('Open books', BOOKS_VALUES), 'people': ('People behind it', PEOPLE_VALUES)}
BOOKS_BY_LEVEL = {3: 'public_transactions', 2: 'public_dashboard'}


def _norm(s):
    return re.sub(r'\s+', ' ', s or '').strip().lower()


def load_keys_books(path=KEYS_BOOKS_FILE):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return json.load(fh).get('entries') or {}


def load_first_tasks(path=FIRST_TASKS_FILE):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return json.load(fh).get('tasks') or {}


def _supporting_claim(card, source_url, quote):
    """The supported claim on the card with this source URL whose quote or statement contains the quote, or None."""
    q = _norm(quote)
    for x in card.get('claims', []):
        if x.get('outcome') == 'supported' and x.get('source_url') == source_url and q and \
                (q in _norm(x.get('quote')) or q in _norm(x.get('statement'))):
            return x
    return None


def validate_keys_books(entries, cards_by_slug):
    """Errors in the curated keys-and-books file: unknown slug or field, value outside its list, or a source/quote that is not a
    supported claim already on the card."""
    errs = []
    for slug, ent in entries.items():
        c = cards_by_slug.get(slug)
        if c is None:
            errs.append(f'keys-and-books: {slug} is not a published card'); continue
        for f, v in ent.items():
            if f not in KB_FIELDS:
                errs.append(f'keys-and-books: {slug}.{f} is not one of {", ".join(KB_FIELDS)}'); continue
            vals = KB_FIELDS[f][1]
            if v.get('value') not in vals:
                errs.append(f'keys-and-books: {slug}.{f} value {v.get("value")!r} not in {sorted(vals)}')
            if f == 'people' and not (v.get('names') or '').strip():
                errs.append(f'keys-and-books: {slug}.people needs names')
            if not _supporting_claim(c, v.get('source_url'), v.get('quote')):
                errs.append(f'keys-and-books: {slug}.{f} source/quote is not a supported claim on the card')
    return errs


def _item(field, value, source_url, quote, names=None):
    label = KB_FIELDS[field][1][value]
    if names:
        label = f'{label}: {names}'
    return {'state': 'recorded', 'value': value, 'label': label, 'source_url': source_url, 'quote': quote}


def _empty():
    return {'state': 'not_recorded', 'value': None, 'label': NOT_RECORDED, 'source_url': None, 'quote': None}


def keys_and_books(card, curated):
    """{keys, books, people} for one card. Curated values first; open books otherwise derived from the highest-level supported
    money-flow claim at ladder level 2 or 3. Everything else: not recorded yet."""
    ent = curated.get(card.get('slug') or card.get('id')) or {}
    out = {}
    for f in KB_FIELDS:
        v = ent.get(f)
        if v and _supporting_claim(card, v.get('source_url'), v.get('quote')):
            out[f] = _item(f, v['value'], v['source_url'], v['quote'], v.get('names'))
        else:
            out[f] = _empty()
    if out['books']['state'] == 'not_recorded':
        best = None
        for x in card.get('claims', []):
            lv = claim_level(x)
            if x.get('kind') == 'economic_flow' and x.get('outcome') == 'supported' and lv in BOOKS_BY_LEVEL and (best is None or lv > best[0]):
                best = (lv, x)
        if best:
            x = best[1]
            out['books'] = _item('books', BOOKS_BY_LEVEL[best[0]], x['source_url'], (x.get('quote') or x.get('statement') or '')[:240])
    return out


# ---------------------------------------------------------------- 3. first task
TASK_FIELDS = ('title', 'steps', 'done_when', 'contributed_by', 'contributed_via', 'source_url', 'verified_by', 'verified_on', 'verification')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def validate_first_tasks(tasks, slugs):
    errs = []
    for slug, t in tasks.items():
        w = f'first-tasks: {slug}'
        if slug not in slugs:
            errs.append(f'{w} is not a published card'); continue
        miss = [k for k in TASK_FIELDS if not t.get(k)]
        if miss:
            errs.append(f'{w} missing {", ".join(miss)}')
        if not isinstance(t.get('steps'), list) or not all(isinstance(s, str) and s.strip() for s in t.get('steps') or []):
            errs.append(f'{w}: steps must be a list of non-empty strings')
        if not str(t.get('source_url') or '').startswith('https://'):
            errs.append(f'{w}: source_url must be https')
        if not DATE.match(str(t.get('verified_on') or '')):
            errs.append(f'{w}: verified_on must be YYYY-MM-DD')
    return errs


def first_task(card, tasks):
    t = tasks.get(card.get('slug') or card.get('id'))
    if not t:
        return None
    return {k: t[k] for k in TASK_FIELDS} | {'credit': f"Contributed by {t['contributed_by']}"}


# ---------------------------------------------------------------- public wording guard
# Site-authored v2 wording says what a thing IS; these words must not appear in the v2 blocks we write.
NEGATIVE_WORDS = re.compile(r"\b(unknown|unverified|doesn't|does not|don't|fails?|failed|missing|none|no data|not verified)\b", re.I)


def negative_hits(text):
    return sorted(set(m.group(0).lower() for m in NEGATIVE_WORDS.finditer(text or '')))
