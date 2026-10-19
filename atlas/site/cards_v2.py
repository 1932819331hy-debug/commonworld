"""Atlas cards v2 (stdlib only): evidence ladder, keys and books, first task.

The rules here are the contract described in atlas/CURATION.md ("Cards v2"). build.py adds the results to every card page, its
Markdown twin, its JSON record and the API; check.py recomputes them from the published claims and fails on any drift;
tests/test_cards_v2.py pins the rules with examples.

1. Evidence ladder. Every money or activity claim (kind economic_flow, metric, recent_activity) gets a level from its source URL:
   3 public transactions  the source is a concrete public record with a checkable identifier on a block explorer (a transaction
                          hash, an address or account page, a block): records anyone can open and check independently;
                          explorer stats, charts and other aggregate pages are level 2;
   2 public dashboard     the source is a public stats page, dashboard or API (machine-readable endpoint) anyone can open;
   1 operator says        any other page: the platform's own words (site text, docs, posts) and other text pages.
   Where a URL could be read two ways, the rule takes the lower level. A card's level is the highest level reached by its
   supported money/activity claims; a card without one shows "not recorded yet".
   Curator review: atlas/data/evidence-levels.json sets the level of a card's claims with one source URL by hand after a curator
   opened that source (evidence_level + a short evidence_note + reviewed_on). It is used only where the URL rule reads the source
   wrongly (a JSON log on a plain path, a dated report on a dashboard host, an endpoint that showed no figures); an entry must
   change the level, and the note is published on the claim.
2. Keys and books. Three questions per card: who holds the keys (custody of funds or accounts), whether the books are open (its money
   figures, such as payouts, balances or volume, publicly checkable), which organization is behind it (a company, team or project
   from ORG_NAMES in keys-and-books.json; never an individual person). Custody resting on the operator's own words is shown as an
   attributed claim ("The operator says ..."); only a smart contract recorded with a public explorer link (basis onchain_verified,
   contract_url at ladder level 3) is stated plainly. A value is filled only from a supported claim already on
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
EVIDENCE_FILE = os.path.join(DATA_DIR, 'evidence-levels.json')

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
# Concrete public record pages (on an explorer host, or a host that calls itself a scanner or explorer): a transaction hash, an
# address or account, a token contract or a block, each with its identifier in the path (/tx/<hash>, /address/<addr>,
# /api/v2/addresses/<addr>, /block/<number>). Explorer pages without such an identifier (home, /stats, /charts, /api/v2/stats)
# are aggregate views: level 2.
TX_PATH = re.compile(r'/(tx|txs|transactions?|address(?:es)?|accounts?|tokens?|blocks?)/'
                     r'(0x[0-9a-fA-F]{8,}|[0-9a-fA-F]{64}|[1-9A-HJ-NP-Za-km-z]{32,}|\d+)(/|$)', re.I)
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
    explorer = _host_in(host, EXPLORER_HOSTS)
    if (explorer or 'scan' in host.split('.')[0] or 'explorer' in host) and TX_PATH.search(path):
        return 3
    if explorer:  # explorer stats, charts and other aggregate views
        return 2
    if _host_in(host, DASHBOARD_HOSTS) or host.startswith(('api.', 'stats.')) or STATS_SEGMENT.search(path) \
            or VERSIONED_API.search(path) or path.lower().endswith('.json'):
        return 2
    return 1


def load_evidence_overrides(path=EVIDENCE_FILE):
    """{slug: [{source_url, evidence_level, evidence_note, reviewed_on}]} from the curated review file ({} when absent)."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return json.load(fh).get('overrides') or {}


def _override(x, ov):
    """The curator entry for this claim (same source URL, money/activity kind) from a card's override list, or None."""
    if not ov or x.get('kind') not in EVIDENCE_KINDS:
        return None
    return next((o for o in ov if o.get('source_url') == x.get('source_url')), None)


def card_overrides(card, overrides):
    return (overrides or {}).get(card.get('slug') or card.get('id')) or []


def claim_level(x, ov=None):
    """Level of a money/activity claim: the curator's level when the card's override list `ov` has its source URL, otherwise the
    URL rule. None for other kinds or a claim without a source."""
    if x.get('kind') not in EVIDENCE_KINDS:
        return None
    o = _override(x, ov)
    if o:
        return o['evidence_level']
    return source_level(x.get('source_url'))


def claim_note(x, ov=None):
    """The curator's evidence_note for this claim, or None when its level comes from the URL rule."""
    o = _override(x, ov)
    return o.get('evidence_note') if o else None


NOTE_MAX = 200


def validate_evidence_overrides(overrides, cards_by_slug):
    """Errors in the curated evidence-levels file: unknown slug, a source URL that is no money/activity claim on the card, a level
    outside 1-3 or equal to the URL rule (an entry must change something), a note that is empty, long or negative, a bad date,
    or the same source twice on one card."""
    errs = []
    for slug, ov in overrides.items():
        w = f'evidence-levels: {slug}'
        c = cards_by_slug.get(slug)
        if c is None:
            errs.append(f'{w} is not a published card'); continue
        if not isinstance(ov, list) or not ov:
            errs.append(f'{w}: needs a non-empty list'); continue
        seen = set()
        for o in ov:
            u = o.get('source_url')
            extra = set(o) - {'source_url', 'evidence_level', 'evidence_note', 'reviewed_on'}
            if extra:
                errs.append(f'{w}: unexpected keys {sorted(extra)}')
            if u in seen:
                errs.append(f'{w}: {u} listed twice')
            seen.add(u)
            claims = [x for x in c.get('claims', []) if x.get('kind') in EVIDENCE_KINDS and x.get('source_url') == u]
            if not claims:
                errs.append(f'{w}: {u} is not the source of a money/activity claim on the card'); continue
            lv = o.get('evidence_level')
            if lv not in LEVELS or isinstance(lv, bool):
                errs.append(f'{w}: {u} evidence_level {lv!r} not in 1, 2, 3')
            elif lv == source_level(u):
                errs.append(f'{w}: {u} evidence_level {lv} equals the URL rule (drop the entry)')
            note = (o.get('evidence_note') or '').strip()
            if not note or len(note) > NOTE_MAX:
                errs.append(f'{w}: {u} evidence_note must be 1-{NOTE_MAX} characters')
            for word in negative_hits(note):
                errs.append(f'{w}: {u} evidence_note uses negative wording {word!r}')
            if not DATE.match(str(o.get('reviewed_on') or '')):
                errs.append(f'{w}: {u} reviewed_on must be YYYY-MM-DD')
    return errs


def level_record(level):
    if level is None:
        return {'level': None, 'id': None, 'label': NOT_RECORDED}
    lid, label, _ = LEVELS[level]
    return {'level': level, 'id': lid, 'label': label}


def card_evidence(card, overrides=None):
    """Card-level summary: the highest level of its supported money/activity claims (curator levels applied)."""
    ov = card_overrides(card, overrides)
    levels = [claim_level(x, ov) for x in card.get('claims', []) if x.get('outcome') == 'supported']
    levels = [lv for lv in levels if lv]
    rec = level_record(max(levels) if levels else None)
    rec['claims_counted'] = len(levels)
    return rec


def annotate_claim(x, ov=None):
    """Copy of a claim with evidence_level / evidence_label on money/activity claims, plus evidence_note where a curator set the
    level (others unchanged)."""
    lv = claim_level(x, ov)
    if lv is None:
        return dict(x)
    out = dict(x) | {'evidence_level': lv, 'evidence_label': LEVELS[lv][1]}
    note = claim_note(x, ov)
    if note:
        out['evidence_note'] = note
    return out


# ---------------------------------------------------------------- 2. keys and books
KEYS_VALUES = {'operator': 'The operator holds the funds',
               'user_wallet': "Users hold their own wallet or keys",
               'smart_contract': 'A smart contract holds the funds'}
# Custody basis: operator_says (default: the claim is the operator's own text) or onchain_verified (smart_contract only, with a
# contract_url on a public explorer, ladder level 3). The label of an operator_says value is an attributed claim.
KEYS_BASES = ('operator_says', 'onchain_verified')
KEYS_SAID = {'operator': 'The operator says it holds the funds',
             'user_wallet': 'The operator says users hold their own wallet or keys',
             'smart_contract': 'The operator says a smart contract holds the funds'}
KEYS_ONCHAIN = {'smart_contract': 'A smart contract holds the funds (contract on a public block explorer)'}
BOOKS_VALUES = {'public_transactions': 'Open: its money figures are on public transactions',
                'public_dashboard': 'Open: its money figures are on a public dashboard or API'}
PEOPLE_VALUES = {'named': 'Named'}  # an organization (company, team, project), never an individual person: ORG_NAMES
KB_FIELDS = {'keys': ('Who holds the keys', KEYS_VALUES), 'books': ('Open books', BOOKS_VALUES), 'people': ('People behind it', PEOPLE_VALUES)}
BOOKS_BY_LEVEL = {3: 'public_transactions', 2: 'public_dashboard'}


def _norm(s):
    return re.sub(r'\s+', ' ', s or '').strip().lower()


def load_keys_books(path=KEYS_BOOKS_FILE):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return json.load(fh).get('entries') or {}


def load_org_names(path=KEYS_BOOKS_FILE):
    """Curated allowlist of organization names (companies, teams, projects) allowed in people.names."""
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        return json.load(fh).get('org_names') or []


def org_name_ok(names, orgs):
    """people.names is one allowlisted organization, optionally followed by a short note in brackets: 'Meta (acquired ...)'."""
    n = (names or '').strip()
    return any(n == o or n.startswith(o + ' (') for o in orgs or [])


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


def validate_keys_books(entries, cards_by_slug, orgs=None):
    """Errors in the curated keys-and-books file: unknown slug or field, value outside its list, a source/quote that is not a
    supported claim already on the card, a people.names that is no allowlisted organization (the Atlas lists places, never
    individual people), or a custody basis onchain_verified without a public explorer record (contract_url at ladder level 3)."""
    orgs = load_org_names() if orgs is None else orgs
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
            elif f == 'people' and not org_name_ok(v.get('names'), orgs):
                errs.append(f'keys-and-books: {slug}.people names {v.get("names")!r} is no organization in org_names (no individual people)')
            if f != 'keys' and ({'basis', 'contract_url'} & set(v)):
                errs.append(f'keys-and-books: {slug}.{f}: basis/contract_url belong to keys only')
            if f == 'keys':
                basis = v.get('basis', 'operator_says')
                if basis not in KEYS_BASES:
                    errs.append(f'keys-and-books: {slug}.keys basis {basis!r} not in {KEYS_BASES}')
                elif basis == 'onchain_verified' and (v.get('value') not in KEYS_ONCHAIN or source_level(v.get('contract_url')) != 3):
                    errs.append(f'keys-and-books: {slug}.keys onchain_verified needs value smart_contract and a contract_url on a public explorer (level 3)')
                elif basis == 'operator_says' and v.get('contract_url'):
                    errs.append(f'keys-and-books: {slug}.keys has a contract_url: set basis onchain_verified')
            if not _supporting_claim(c, v.get('source_url'), v.get('quote')):
                errs.append(f'keys-and-books: {slug}.{f} source/quote is not a supported claim on the card')
    return errs


def _item(field, value, source_url, quote, names=None):
    label = KB_FIELDS[field][1][value]
    if names:
        label = f'{label}: {names}'
    return {'state': 'recorded', 'value': value, 'label': label, 'source_url': source_url, 'quote': quote}


def _keys_item(v):
    """Custody: an attributed claim ("The operator says ...") unless a curator recorded the contract on a public explorer."""
    basis = v.get('basis', 'operator_says')
    it = _item('keys', v['value'], v['source_url'], v['quote'])
    if basis == 'onchain_verified':
        return it | {'label': KEYS_ONCHAIN[v['value']], 'basis': basis, 'contract_url': v['contract_url']}
    return it | {'label': KEYS_SAID[v['value']], 'basis': 'operator_says'}


def _empty():
    return {'state': 'not_recorded', 'value': None, 'label': NOT_RECORDED, 'source_url': None, 'quote': None}


def keys_and_books(card, curated, overrides=None):
    """{keys, books, people} for one card. Curated values first; open books otherwise derived from the highest-level supported
    money-flow claim at ladder level 2 or 3 (curator levels applied). Everything else: not recorded yet."""
    ent = curated.get(card.get('slug') or card.get('id')) or {}
    ov = card_overrides(card, overrides)
    out = {}
    for f in KB_FIELDS:
        v = ent.get(f)
        if v and _supporting_claim(card, v.get('source_url'), v.get('quote')):
            out[f] = _keys_item(v) if f == 'keys' else _item(f, v['value'], v['source_url'], v['quote'], v.get('names'))
        else:
            out[f] = _empty()
    if out['books']['state'] == 'not_recorded':
        best = None
        for x in card.get('claims', []):
            lv = claim_level(x, ov)
            if x.get('kind') == 'economic_flow' and x.get('outcome') == 'supported' and lv in BOOKS_BY_LEVEL and (best is None or lv > best[0]):
                best = (lv, x)
        if best:
            x = best[1]
            out['books'] = _item('books', BOOKS_BY_LEVEL[best[0]], x['source_url'], (x.get('quote') or x.get('statement') or '')[:240])
    return out


# ---------------------------------------------------------------- 3. first task
TASK_FIELDS = ('title', 'steps', 'done_when', 'contributed_by', 'contributed_via', 'source_url', 'verified_by', 'verified_on', 'verification')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


# A step that fetches a file from the web, a step that runs code, and the hash check that must sit between them.
DOWNLOAD_STEP = re.compile(r'\b(download|curl|wget|fetch)\b.*https?://', re.I)
RUN_STEP = re.compile(r'`\s*(python3?|bash|sh|node|deno|bun|ruby|perl|php|\./)[^`]*`', re.I)
HASH_STEP = re.compile(r'\b([0-9a-f]{64})\b.*\bsha256sum -c\b|\bsha256sum -c\b.*\b([0-9a-f]{64})\b', re.I)


def code_safety_errors(steps, verification=''):
    """A task that downloads code and runs it needs a SHA-256 check step (`echo "<sha256>  <file>" | sha256sum -c -`) after the
    download and before the first run, with the hash the curator recorded in `verification`."""
    steps = [s for s in steps if isinstance(s, str)]
    dl = next((i for i, s in enumerate(steps) if DOWNLOAD_STEP.search(s)), None)
    if dl is None:
        return []
    run = next((i for i, s in enumerate(steps) if i >= dl and RUN_STEP.search(s) and not HASH_STEP.search(s)), None)
    if run is None:
        return []
    chk = [(i, m) for i, s in enumerate(steps) if (m := HASH_STEP.search(s)) and dl <= i < run]
    if not chk:
        return [f'step {run + 1} runs downloaded code: add a SHA-256 check step (sha256sum -c) between the download and the run']
    sha = (chk[0][1].group(1) or chk[0][1].group(2)).lower()
    if sha not in (verification or '').lower():
        return [f'the SHA-256 in the check step is not the hash recorded in verification']
    return []


def validate_first_tasks(tasks, slugs):
    errs = []
    for slug, t in tasks.items():
        w = f'first-tasks: {slug}'
        if slug not in slugs:
            errs.append(f'{w} is not a published card'); continue
        extra = set(t) - set(TASK_FIELDS) - {'no_code'}
        if extra:
            errs.append(f'{w}: unexpected keys {sorted(extra)}')
        if 'no_code' in t and not (isinstance(t['no_code'], str) and t['no_code'].strip()):
            errs.append(f'{w}: no_code must be a non-empty string')
        miss = [k for k in TASK_FIELDS if not t.get(k)]
        if miss:
            errs.append(f'{w} missing {", ".join(miss)}')
        if not isinstance(t.get('steps'), list) or not all(isinstance(s, str) and s.strip() for s in t.get('steps') or []):
            errs.append(f'{w}: steps must be a list of non-empty strings')
        if not str(t.get('source_url') or '').startswith('https://'):
            errs.append(f'{w}: source_url must be https')
        if not DATE.match(str(t.get('verified_on') or '')):
            errs.append(f'{w}: verified_on must be YYYY-MM-DD')
        errs += [f'{w}: {x}' for x in code_safety_errors(t.get('steps') or [], t.get('verification'))]
    return errs


def first_task(card, tasks):
    t = tasks.get(card.get('slug') or card.get('id'))
    if not t:
        return None
    out = {k: t[k] for k in TASK_FIELDS} | {'credit': f"Contributed by {t['contributed_by']}"}
    if t.get('no_code'):
        out['no_code'] = t['no_code']  # optional: a way to finish the task without running code
    return out


# ---------------------------------------------------------------- public wording guard
# Site-authored v2 wording says what a thing IS; these words must not appear in the v2 blocks we write.
NEGATIVE_WORDS = re.compile(r"\b(unknown|unverified|doesn't|does not|don't|fails?|failed|missing|none|no data|not verified)\b", re.I)


def negative_hits(text):
    return sorted(set(m.group(0).lower() for m in NEGATIVE_WORDS.finditer(text or '')))
