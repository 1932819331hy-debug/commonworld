"""Atlas cards v2 (stdlib only): evidence ladder, keys and books, first task.

The rules here are the contract described in atlas/CURATION.md ("Cards v2"). build.py adds the results to every card page, its
Markdown twin, its JSON record and the API; check.py recomputes them from the published claims and fails on any drift;
tests/test_cards_v2.py pins the rules with examples.

1. Evidence ladder. Every money or activity claim (kind economic_flow, metric, recent_activity) gets a level from its source URL:
   3 public transactions  the source is a concrete public record with a checkable identifier on a block explorer (a transaction
                          hash, an address or account page, a block): the whole path is one of that explorer's
                          own record routes with an identifier of its network (RECORD_ROUTES): records anyone can open and check independently;
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
   from org_names in keys-and-books.json, matched exactly; never an individual person; an optional `role` from ORG_ROLES says how
   the organization relates to it, such as "acquired it"). Custody resting on the operator's own words is shown as an
   attributed claim ("The operator says ..."); only a smart contract recorded with a public explorer link (basis onchain_verified,
   contract_url = an explorer page of one address or token, ladder level 3) is stated plainly. A value is filled only from a supported claim already on
   the card (curated in atlas/data/keys-and-books.json with the claim's source URL and a quote from that claim; open books are also
   derived from a supported money-flow claim at ladder level 2 or 3). Every other answer is "not recorded yet".
3. First task. One simple first step for a newcomer, from atlas/data/first-tasks.json. Only tasks a curator ran and verified are
   published, with credit to the contributor. Cards without one show no first-task block. A task that downloads code carries a
   structured `code` block (sandbox, url, filename, sha256, run); its steps are generated from it in the order sandbox ->
   download -> verify (`echo "<sha256>  <filename>" | sha256sum -c -`) -> run. Any free-text step that downloads or installs
   code outside that block fails validation (fail closed).
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
# Public block explorers: their pages are views of public chain records. An EXACT allowlist: the host (after a leading `www.`)
# must equal one entry; subdomains are not included (list each one, such as optimistic.etherscan.io), and a host that merely
# contains "scan" or "explorer" is no explorer. Level 3 (and a custody contract_url) also needs https. Documented in CURATION.md.
EXPLORER_HOSTS = (
    'etherscan.io', 'optimistic.etherscan.io', 'sepolia.etherscan.io', 'basescan.org', 'sepolia.basescan.org', 'arbiscan.io',
    'nova.arbiscan.io', 'polygonscan.com', 'zkevm.polygonscan.com', 'bscscan.com', 'celoscan.io', 'lineascan.build', 'scrollscan.com',
    'snowtrace.io', 'ftmscan.com', 'gnosisscan.io', 'era.zksync.network', 'blastscan.io', 'solscan.io', 'explorer.solana.com',
    'solana.fm', 'blockscout.com', 'eth.blockscout.com', 'base.blockscout.com', 'optimism.blockscout.com', 'gnosis.blockscout.com', 'mempool.space',
    'blockstream.info', 'blockchair.com', 'explorer.hiro.so', 'tronscan.org', 'tonviewer.com', 'tonscan.org', 'suiscan.xyz',
    'explorer.aptoslabs.com', 'oklink.com',
    'kitescan.ai',  # kitescan.ai: the Blockscout explorer of the Kite chain (used by the Kite AI card)
)
# Level 3 (round 8, fixed table instead of a shared identifier union): a URL is a concrete public record only when its host is
# in RECORD_ROUTES and its WHOLE path (an optional trailing slash aside, no other segments) is one of that explorer's own record
# routes with an identifier in that explorer's network format. Route names are matched case-sensitively in lowercase.
# Explorer hosts outside the table (multi-chain explorers such as blockscout.com, blockchair.com, oklink.com, and explorers whose
# records live in the URL fragment, such as tronscan.org) and every other page on a listed explorer are level 2. There is no
# guessing: an identifier of another network (a base58 string on an EVM explorer), a prefix before the route
# (/unrelated/tx/<hash>), an API path or a sub-page (/address/<addr>/tokens) is level 2. Documented in CURATION.md.
_B58 = '[1-9A-HJ-NP-Za-km-z]'
_HEX64 = '[0-9a-fA-F]{64}'
_EVM_TX, _EVM_ADDR, _HEX32_ID = f'0x{_HEX64}', '0x[0-9a-fA-F]{40}', f'0x{_HEX64}'
_DEC = '0|[1-9][0-9]{0,11}'                                       # a block number or version: no leading zero, at most 12 digits
_SOL_SIG, _SOL_ADDR = f'{_B58}{{86,88}}', f'{_B58}{{32,44}}'
_BTC_ADDR = f'[13]{_B58}{{25,34}}|bc1[02-9ac-hj-np-z]{{11,71}}'
_TON_ADDR = '[EUk0]Q[A-Za-z0-9_-]{46}|(?:0|-1):[0-9a-fA-F]{64}'
# network -> {record kind: [(route prefix, identifier)]}
NETWORK_ROUTES = {
    'evm': {'tx': [('/tx/', _EVM_TX)], 'address': [('/address/', _EVM_ADDR)], 'token': [('/token/', _EVM_ADDR)],
            'block': [('/block/', f'{_DEC}|{_EVM_TX}')]},
    'solscan': {'tx': [('/tx/', _SOL_SIG)], 'address': [('/account/', _SOL_ADDR)], 'token': [('/token/', _SOL_ADDR)],
                'block': [('/block/', _DEC)]},
    'solana': {'tx': [('/tx/', _SOL_SIG)], 'address': [('/address/', _SOL_ADDR)], 'block': [('/block/', _DEC)]},
    'bitcoin': {'tx': [('/tx/', _HEX64)], 'address': [('/address/', _BTC_ADDR)], 'block': [('/block/', f'{_HEX64}|{_DEC}')]},
    'tonviewer': {'tx': [('/transaction/', _HEX64)], 'address': [('/', _TON_ADDR)]},
    'tonscan': {'tx': [('/tx/', _HEX64)], 'address': [('/address/', _TON_ADDR)]},
    'sui': {'tx': [('/mainnet/tx/', f'{_B58}{{43,44}}')], 'address': [('/mainnet/account/', _HEX32_ID)]},
    'aptos': {'tx': [('/txn/', f'{_HEX32_ID}|{_DEC}')], 'address': [('/account/', _HEX32_ID)]},
}
_EVM_HOSTS = ('etherscan.io', 'optimistic.etherscan.io', 'sepolia.etherscan.io', 'basescan.org', 'sepolia.basescan.org', 'arbiscan.io',
              'nova.arbiscan.io', 'polygonscan.com', 'zkevm.polygonscan.com', 'bscscan.com', 'celoscan.io', 'lineascan.build',
              'scrollscan.com', 'snowtrace.io', 'ftmscan.com', 'gnosisscan.io', 'era.zksync.network', 'blastscan.io',
              'eth.blockscout.com', 'base.blockscout.com', 'optimism.blockscout.com', 'gnosis.blockscout.com', 'kitescan.ai')
# explorer host -> network (the explorer -> network map; every host here is also in EXPLORER_HOSTS)
RECORD_ROUTES = {**{h: 'evm' for h in _EVM_HOSTS}, 'solscan.io': 'solscan', 'explorer.solana.com': 'solana', 'solana.fm': 'solana',
                 'mempool.space': 'bitcoin', 'blockstream.info': 'bitcoin', 'tonviewer.com': 'tonviewer', 'tonscan.org': 'tonscan',
                 'suiscan.xyz': 'sui', 'explorer.aptoslabs.com': 'aptos'}
_ROUTE_RX = {net: {kind: re.compile('^(?:' + '|'.join(f'{re.escape(pre)}(?:{ident})' for pre, ident in rs) + ')/?$')
                   for kind, rs in kinds.items()} for net, kinds in NETWORK_ROUTES.items()}
# Public dashboards run by independent trackers (whole site is a dashboard).
DASHBOARD_HOSTS = ('dune.com', 'chainward.ai', 'defillama.com', 'tokenterminal.com', 'x402scan.com')
# Path segments of stats pages, dashboards and APIs.
STATS_SEGMENT = re.compile(r'(^|/)(api|stats|statistics|analytics|dashboard|metrics|leaderboard|status)(/|$|\.|-)', re.I)
VERSIONED_API = re.compile(r'(^|/)v\d+(/|$)')
TEXT_ONLY_HOSTS = ('web.archive.org',)  # archived copies are read as text pages, whatever URL they wrap


def _host_in(host, hosts):
    return any(host == h or host.endswith('.' + h) for h in hosts)


def _bare_host(u):
    host = (u.hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def _plain_netloc(u):
    """The network location is a bare host name: no userinfo (`user:pass@`, so `https://evil.com@basescan.org/` is not an
    explorer page) and no explicit port (`:443` included)."""
    netloc = u.netloc or ''
    return bool(netloc) and '@' not in netloc and ':' not in netloc and u.username is None and u.password is None


def explorer_host(url):
    """True when the URL's host (after a leading `www.`) is exactly one of EXPLORER_HOSTS, with no userinfo and no port."""
    if not isinstance(url, str):
        return False
    u = urlparse(url)
    return _plain_netloc(u) and _bare_host(u) in EXPLORER_HOSTS


def record_kind(url):
    """'tx', 'address', 'token' or 'block' when the URL is a concrete record page under RECORD_ROUTES: https, a host in the
    explorer -> network map (after a leading `www.`), no userinfo or port, no query or fragment, and the whole path is one of that
    network's routes with an identifier in its format. None otherwise."""
    if not isinstance(url, str) or not url.startswith('https://') or '?' in url or '#' in url:
        return None
    u = urlparse(url)
    net = RECORD_ROUTES.get(_bare_host(u)) if _plain_netloc(u) else None
    if not net:
        return None
    return next((kind for kind, rx in _ROUTE_RX[net].items() if rx.match(u.path or '')), None)


def source_level(url):
    """Ladder level (1, 2 or 3) of one source URL, or None when there is no URL. Deterministic; ties go to the lower level."""
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return None
    u = urlparse(url)
    host = _bare_host(u)
    path = u.path or '/'
    if _host_in(host, TEXT_ONLY_HOSTS):
        return 1
    explorer = host in EXPLORER_HOSTS and _plain_netloc(u)  # exact allowlist, no subdomains, no userinfo or port, no "scan" guess
    if explorer and record_kind(url):
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
PEOPLE_VALUES = {'named': 'Named'}  # an organization (company, team, project), never an individual person: org_names
# Optional people.role: how the named organization relates to the platform. A fixed list, so no free text sits next to the name.
ORG_ROLES = {'acquired': 'acquired it', 'announced': 'announced it'}
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
    """people.names is exactly one allowlisted organization name (no notes or brackets after it: free text next to a name could
    carry an individual person's name). How the organization relates to the platform goes in people.role (ORG_ROLES)."""
    return isinstance(names, str) and names in (orgs or [])


# A smart contract's page on a public explorer: the WHOLE path is one address or token, `/<kind>/<id>` with at most one trailing
# slash, nothing before or after it. Transactions and blocks are records too (ladder level 3), but they do not name the contract
# that holds the funds; `/tx/<hash>/address/<addr>` or a query/fragment is rejected so the page shown is exactly that contract.
# Segment names are lowercase and matched case-sensitively (/ADDRESS/ is rejected).
def contract_url_ok(url):
    """contract_url is a level-3 explorer page of one address or token (record_kind 'address' or 'token': not a transaction,
    block or stats page): printable ASCII only, https, a host in the explorer -> network map, no userinfo, no port, no query or
    fragment, and the whole path is that explorer's address or token route with an identifier of its network."""
    if not isinstance(url, str) or not ASCII_PRINTABLE.match(url):
        return False
    return record_kind(url) in ('address', 'token')


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
    supported claim already on the card, a people.names that is not exactly one allowlisted organization (the Atlas lists places,
    never individual people) or a people.role outside ORG_ROLES, or a custody basis onchain_verified without a public explorer
    page of the contract's address or token (contract_url_ok)."""
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
                errs.append(f'keys-and-books: {slug}.people names {v.get("names")!r} is not exactly one organization in org_names (no individual people, no notes)')
            if f == 'people' and 'role' in v and v['role'] not in ORG_ROLES:
                errs.append(f'keys-and-books: {slug}.people role {v["role"]!r} not in {sorted(ORG_ROLES)}')
            if f != 'people' and ({'names', 'role'} & set(v)):
                errs.append(f'keys-and-books: {slug}.{f}: names/role belong to people only')
            if f != 'keys' and ({'basis', 'contract_url'} & set(v)):
                errs.append(f'keys-and-books: {slug}.{f}: basis/contract_url belong to keys only')
            if f == 'keys':
                basis = v.get('basis', 'operator_says')
                if basis not in KEYS_BASES:
                    errs.append(f'keys-and-books: {slug}.keys basis {basis!r} not in {KEYS_BASES}')
                elif basis == 'onchain_verified' and (v.get('value') not in KEYS_ONCHAIN or not contract_url_ok(v.get('contract_url'))):
                    errs.append(f'keys-and-books: {slug}.keys onchain_verified needs value smart_contract and a contract_url that is a public '
                                f'explorer page of one address or token (level 3; not a transaction or block)')
                elif basis == 'operator_says' and v.get('contract_url'):
                    errs.append(f'keys-and-books: {slug}.keys has a contract_url: set basis onchain_verified')
            if not _supporting_claim(c, v.get('source_url'), v.get('quote')):
                errs.append(f'keys-and-books: {slug}.{f} source/quote is not a supported claim on the card')
    return errs


def _item(field, value, source_url, quote, names=None, role=None):
    label = KB_FIELDS[field][1][value]
    if names:
        label = f'{label}: {names}' + (f' ({ORG_ROLES[role]})' if role in ORG_ROLES else '')
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
            out[f] = _keys_item(v) if f == 'keys' else _item(f, v['value'], v['source_url'], v['quote'], v.get('names'), v.get('role'))
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
SHA256 = re.compile(r'^[0-9a-f]{64}$')
HEX64 = re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])')
CODE_FIELDS = ('sandbox', 'url', 'filename', 'sha256', 'run')
# Control characters (newline, carriage return, tab, NUL, any other below 0x20, and DEL) could hide a second command or a second line.
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
# run.cmd, code.filename, code.url (and a custody contract_url): printable ASCII only (0x20-0x7e), so no Unicode line or
# paragraph separator (U+2028/U+2029), NEL (U+0085), fullwidth punctuation (U+FF1B ；) or zero-width character can hide in them.
ASCII_PRINTABLE = re.compile(r'^[\x20-\x7e]*$')
# Free text (title, steps, sandbox, then, done_when, no_code, verification, contributor and verifier fields): no Unicode line
# breaks (U+2028, U+2029, U+0085), zero-width characters
# (U+200B-U+200D, U+2060, U+FEFF) or bidi controls (U+202A-U+202E, U+2066-U+2069): they can hide or reorder text.
HIDDEN_UNICODE = re.compile('[\u2028\u2029\u0085\u200b-\u200d\u2060\ufeff\u202a-\u202e\u2066-\u2069]')
# Shell syntax a run command may not contain: links, chaining, pipes, redirects, command substitution, variables.
RUN_FORBIDDEN = re.compile(r'https?://|[`|;&$<>]|\$\(|&&|\|\|')
FILENAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')
# A run command starts the downloaded file by name: `python3 tool.py ...`, `bash tool.sh`, `node tool.js`, `./tool`. Runners that fetch
# more code on their own (uv run, deno run, npx) are left out: what they fetch is not covered by the hash check.
RUN_PREFIXES = ('python3 ', 'python ', 'bash ', 'sh ', 'node ', 'ruby ', 'perl ', './')

# Inline code execution, fail closed, with NO option parsing: a human-text field is rejected when it names an interpreter or shell
# ANYWHERE and has an inline-code flag ANYWHERE in the same field, whatever stands between them or in what order
# (`python -W ignore -c`, `node --input-type module -e`, `powershell -ExecutionPolicy Bypass -Command` all fail). Prose that
# names an interpreter and such a flag in one field fails too; reword it or split it.
# Interpreter token: one of INTERPRETERS as a whole word, case-insensitive, also with a path (`/usr/bin/python3`,
# `C:\Python312\python.exe`), behind `env`, with a version suffix (`python3.12`, `php8.2`) and `.exe`; `python.org` or `node.js`
# (a dot and more letters) is no token.
# Inline-code flag (case-insensitive, a separate word: after the start, whitespace, a quote, a backtick, `(`, `[`, `=` or `,`):
#   - any one-dash option with `c` or `e` among its first four letters: -c, -e, -E, -lc, -ce, -ic, -enc, -ec, -Command,
#     -EncodedCommand, -ExecutionPolicy, also with the code attached (`-cprint(1)`);
#   - -p and -r (print / run code: node -p, perl -p, php -r);
#   - --eval, --print, --command, --exec / --execute (also with `=`);
#   - /c and /k (cmd.exe);
#   - a heredoc `<<` (code fed on standard input).
# `-m` (run an installed module) is not inline code; installs through it are caught by the install pattern below.
# Code on standard input (round 8): an interpreter token together with a pipe `|` or an input redirect `<` ANYWHERE in the same
# field also fails (`printf 'puts 1' | ruby`, `perl < x`), for every interpreter in INTERPRETERS, as does an interpreter token
# together with the word `exec` in any form.
# Interpreter-free forms are matched on their own: the word `eval` in ANY form (`eval "..."`, `eval("...")`, `eval(`), `exec(`
# with an argument, PowerShell `iex` / `Invoke-Expression`. Prose that uses the word "eval" fails too; write "evaluate".
INTERPRETERS = ('python', 'py', 'pypy', 'bash', 'sh', 'zsh', 'dash', 'ksh', 'fish', 'pwsh', 'powershell', 'cmd', 'node', 'nodejs',
                'deno', 'bun', 'perl', 'ruby', 'php', 'lua', 'osascript', 'rscript', 'tclsh')
INTERPRETER_TOKEN = re.compile(
    r'(?<![\w.-])(?:' + '|'.join(INTERPRETERS) + r')(?:\d+(?:\.\d+)*)?(?:\.exe)?(?![\w-]|\.\w)', re.I)
INLINE_FLAG = re.compile(
    r'(?:^|(?<=[\s"\'`(\[=,]))(?:'
    r'-[a-z]{0,3}[ce]'                                  # one-dash option with c or e among its first four letters
    r'|-[pr](?![a-z])'                                  # -p, -r
    r'|--(?:eval|print|command|exec|execute)(?![\w-])'  # long forms
    r'|/[ck](?![\w/.-])'                                # cmd.exe /c, /k
    r')|<<', re.I)
STDIN_OR_EXEC = re.compile(r'[|<]|\bexec\b', re.I)          # with an interpreter token: code on stdin, or exec in any form
INLINE_OTHER = re.compile(r'\beval\b|\bexec\s*\(\s*[^\s)]|\biex\b|\binvoke-expression\b', re.I)


def inline_exec(text):
    """True when one text field runs inline code: an interpreter token anywhere together with an inline-code flag, a pipe, an
    input redirect or the word exec anywhere; or an interpreter-free form (eval in any form, exec(...), iex, Invoke-Expression)."""
    text = text or ''
    return bool((INTERPRETER_TOKEN.search(text) and (INLINE_FLAG.search(text) or STDIN_OR_EXEC.search(text)))
                or INLINE_OTHER.search(text))


# Fail closed: free text in a first task may not fetch, install or pipe code. Code reaches a newcomer only through the structured
# `code` block, whose download, hash check and run steps are generated below.
DOWNLOAD_PATTERNS = (
    ('a link to a script or binary', re.compile(
        r'https?://[^\s`"\'<>)]+\.(py|pyz|sh|bash|zsh|ps1|bat|cmd|js|mjs|cjs|ts|exe|msi|dmg|pkg|deb|rpm|apk|appimage|jar|whl|bin|run)'
        r'(?=$|[\s`"\'<>)?#.,;:])', re.I)),
    ('a raw GitHub or gist link', re.compile(r'\b(raw\.githubusercontent\.com|gist\.github(usercontent)?\.com)\b', re.I)),
    ('a download command with a link', re.compile(r'\b(download|curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^\n]*https?://', re.I)),
    ('a pipe into a shell', re.compile(r'\|\s*(sudo\s+)?(sh|bash|zsh|python3?|node|iex|invoke-expression)\b', re.I)),
    ('a package install or remote run', re.compile(
        r'\b(pip3?\s+install|python3?\s+-m\s+pip\s+install|pipx\s+(install|run)|uvx|uv\s+(pip\s+install|tool\s+(install|run)|run|add)|'
        r'npm\s+(install|i|exec)|npx|pnpm\s+(add|install|dlx)|yarn\s+(add|dlx)|bunx|bun\s+(add|install|x)|gem\s+install|'
        r'cargo\s+install|go\s+(install|run)\s+\S*(@|\.go\b|/)|brew\s+install|apt(-get)?\s+install)\b', re.I)),
    ('inline code execution', inline_exec),
)


def download_hits(text):
    """Why a free-text step looks like it downloads, installs or pipes code ([] when it does not)."""
    return [why for why, rx in DOWNLOAD_PATTERNS if (rx(text or '') if callable(rx) else rx.search(text or ''))]


def code_steps(code):
    """Steps generated from a structured `code` block, in the fixed order sandbox -> download -> verify -> run."""
    fn, sha = code['filename'], code['sha256']
    steps = [code['sandbox'].strip(),
             f"Download the script: `curl -fsSLO {code['url']}`",
             f'Check the file against the hash we verified, before running it: `echo "{sha}  {fn}" | sha256sum -c -`. Go on only when it '
             f'prints `{fn}: OK`; any other output means the file changed, so stop here and leave it unrun.']
    for r in code['run']:
        then = r.get('then') if isinstance(r.get('then'), str) else ''
        steps.append(f"Run `{r['cmd']}`." + (f" {then.strip()}" if then.strip() else ''))
    return steps


def task_steps(t):
    """The published steps of a task: the generated code steps first (when it downloads code), then its own free-text steps."""
    own = [s for s in (t.get('steps') or []) if isinstance(s, str)]
    return (code_steps(t['code']) if isinstance(t.get('code'), dict) else []) + own


def code_block_errors(code, verification=''):
    """Errors in a structured `code` block: url (https, its file name = filename), filename, sha256 (64 lowercase hex, the one and
    only hash in `verification`), a sandbox step, and run commands that each start `filename` by name and fetch nothing."""
    if not isinstance(code, dict):
        return ['code must be an object with ' + ', '.join(CODE_FIELDS)]
    errs = []
    extra, miss = set(code) - set(CODE_FIELDS), [k for k in CODE_FIELDS if not code.get(k)]
    if extra:
        errs.append(f'code: unexpected keys {sorted(extra)}')
    if miss:
        return errs + [f'code missing {", ".join(miss)}']
    for k in ('sandbox', 'url', 'filename', 'sha256'):
        if not isinstance(code[k], str):
            errs.append(f'code.{k} must be a string, not {type(code[k]).__name__}')
        elif CONTROL.search(code[k]):
            errs.append(f'code.{k} must not contain control characters (newline, tab, NUL)')
        elif k in ('url', 'filename') and not ASCII_PRINTABLE.match(code[k]):
            errs.append(f'code.{k} must be printable ASCII only (no Unicode separators, zero-width or fullwidth characters)')
    if not isinstance(verification, str):
        errs.append('verification must be a string')
        verification = ''
    url, fn, sha = code['url'], code['filename'], code['sha256']
    if not (isinstance(fn, str) and FILENAME.match(fn)):
        errs.append(f'code.filename {fn!r} must be a plain file name')
    if not (isinstance(url, str) and url.startswith('https://') and not re.search(r'[\s`"\'|;&$<>]', url)):
        errs.append('code.url must be one https URL')
    elif os.path.basename(urlparse(url).path) != fn:
        errs.append(f'code.url saves as {os.path.basename(urlparse(url).path)!r} (curl -O), not code.filename {fn!r}')
    if not (isinstance(sha, str) and SHA256.match(sha)):
        errs.append('code.sha256 must be 64 lowercase hex characters')
    elif {h.lower() for h in HEX64.findall(verification or '')} != {sha}:
        errs.append('code.sha256 is not the one hash recorded in verification')
    if not isinstance(code['sandbox'], str) or 'sandbox' not in code['sandbox'].lower():
        errs.append('code.sandbox must be a step that says to work in a sandbox without secrets')
    runs = code['run']
    if not isinstance(runs, list) or not runs or not all(isinstance(r, dict) and isinstance(r.get('cmd'), str) for r in runs):
        return errs + ['code.run must be a non-empty list of {cmd, then}']
    for i, r in enumerate(runs, 1):
        if set(r) - {'cmd', 'then'}:
            errs.append(f'code.run {i}: unexpected keys {sorted(set(r) - {"cmd", "then"})}')
        if 'then' in r and not isinstance(r['then'], str):
            errs.append(f'code.run {i}: then must be a string, not {type(r["then"]).__name__}')
        elif CONTROL.search(r.get('then') or ''):
            errs.append(f'code.run {i}: then must not contain control characters (newline, tab, NUL)')
        if CONTROL.search(r['cmd']):
            errs.append(f'code.run {i}: {r["cmd"]!r} must be one line without control characters (newline, tab, NUL)')
            continue
        if not ASCII_PRINTABLE.match(r['cmd']):
            errs.append(f'code.run {i}: {r["cmd"]!r} must be printable ASCII only (no Unicode separators, zero-width or fullwidth characters)')
            continue
        cmd = r['cmd'].strip()
        target = next(((cmd[len(p):] if p != './' else cmd).split(' ')[0] for p in RUN_PREFIXES if cmd.startswith(p)), None)
        if not isinstance(fn, str) or target not in (fn, './' + fn):
            errs.append(f'code.run {i}: `{cmd}` must start the downloaded file {fn!r} (for example `python3 {fn}`)')
        if RUN_FORBIDDEN.search(cmd):
            errs.append(f'code.run {i}: `{cmd}` must be one plain command without links, pipes or chaining')
    return errs


# Every human-text field of a task (all others are links, dates or a hash): the step texts, code.sandbox and each run's `then`
# (collected in code_safety_errors), plus these. All of them reject hidden Unicode and inline code execution; the record fields
# (who contributed and verified it, and how) may name a link or a download as provenance, so the download/install patterns skip them.
TEXT_FIELDS = ('title', 'done_when', 'no_code', 'verification', 'contributed_by', 'contributed_via', 'verified_by')
RECORD_FIELDS = ('verification', 'contributed_by', 'contributed_via', 'verified_by')


def code_safety_errors(t):
    """Fail closed: a task that downloads code carries a structured `code` block (validated by code_block_errors), and none of its
    human-text parts (title, steps, sandbox, the text after each run command, done_when, no_code, verification and the contributor
    and verifier fields) runs inline code (inline_exec: an interpreter token and an inline-code flag anywhere in the field, `eval`, `exec(...)`,
    `iex` ...) or hides text with Unicode separators, zero-width or bidi characters; the task texts also may not download, install
    or pipe code."""
    errs = []
    code = t.get('code')
    if code is not None:
        errs += code_block_errors(code, t.get('verification'))
    steps = t.get('steps') if isinstance(t.get('steps'), list) else []
    texts = [('step', s) for s in steps if isinstance(s, str)]
    if isinstance(code, dict):
        runs = code.get('run') if isinstance(code.get('run'), list) else []
        texts += [('code.sandbox', code.get('sandbox'))] + [('code.run then', r.get('then')) for r in runs if isinstance(r, dict)]
    texts += [(k, t.get(k)) for k in TEXT_FIELDS]
    for where, text in texts:
        if not isinstance(text, str):
            continue  # a wrong type is reported by the type checks (code_block_errors / validate_first_tasks)
        if CONTROL.search(text) and where != 'step':
            errs.append(f'{where} {text[:60]!r} must not contain control characters (newline, tab, NUL)')
        if HIDDEN_UNICODE.search(text):
            errs.append(f'{where} {text[:60]!r} must not contain Unicode line separators, zero-width characters or bidi controls')
        hits = download_hits(text) if where not in RECORD_FIELDS else (['inline code execution'] if inline_exec(text) else [])
        for why in hits:
            errs.append(f'{where} {text[:60]!r} has {why}: code is allowed only through the structured `code` block '
                        f'(url, filename, sha256, run), with steps generated from it')
    return errs


def validate_first_tasks(tasks, slugs):
    errs = []
    for slug, t in tasks.items():
        w = f'first-tasks: {slug}'
        if slug not in slugs:
            errs.append(f'{w} is not a published card'); continue
        if not isinstance(t, dict):
            errs.append(f'{w} must be an object'); continue
        for k in TASK_FIELDS:
            if k != 'steps' and k in t and not isinstance(t[k], str):
                errs.append(f'{w}: {k} must be a string, not {type(t[k]).__name__}')
        if 'code' in t and not isinstance(t['code'], dict):
            errs.append(f'{w}: code must be an object, not {type(t["code"]).__name__}')
        extra = set(t) - set(TASK_FIELDS) - {'no_code', 'code'}
        if extra:
            errs.append(f'{w}: unexpected keys {sorted(extra)}')
        if 'no_code' in t and not (isinstance(t['no_code'], str) and t['no_code'].strip()):
            errs.append(f'{w}: no_code must be a non-empty string')
        # A task with a code block may leave `steps` out: its steps are generated from the block.
        miss = [k for k in TASK_FIELDS if not t.get(k) and not (k == 'steps' and 'code' in t)]
        if miss:
            errs.append(f'{w} missing {", ".join(miss)}')
        if not isinstance(t.get('steps', []), list) or not all(isinstance(s, str) and s.strip() for s in t.get('steps') or []):
            errs.append(f'{w}: steps must be a list of non-empty strings')
        if not str(t.get('source_url') or '').startswith('https://'):
            errs.append(f'{w}: source_url must be https')
        if not DATE.match(str(t.get('verified_on') or '')):
            errs.append(f'{w}: verified_on must be YYYY-MM-DD')
        errs += [f'{w}: {x}' for x in code_safety_errors(t)]
    return errs


def curation_event_gaps(overrides, curated, tasks, events, start):
    """The curation files change published cards outside the snapshot's `amendments`, so each record carries its own date
    and needs its event in atlas/data/events.jsonl (atlas/CURATION.md#events-log) from `start` (the log's first day) on:
    an evidence-level review (reviewed_on) a `relabelled` event, a keys-and-books value (reviewed_on, required on every
    value) and a first task (verified_on) a `corrected` event, same day and slug. Changing a record means a new date, and
    with it a new event. -> list of gaps."""
    have = {(e.get('date'), e.get('slug'), e.get('type')) for e in events}
    gaps = []

    def need(date, slug, typ, what):
        if not DATE.match(str(date or '')):
            gaps.append(f'{what}: needs a YYYY-MM-DD date'); return
        if date >= start and (date, slug, typ) not in have:
            gaps.append(f'{what} ({date}) has no "{typ}" event for {slug} on {date} in atlas/data/events.jsonl')

    for slug, rows in (overrides or {}).items():
        for o in rows or []:
            if isinstance(o, dict):
                need(o.get('reviewed_on'), slug, 'relabelled', f'evidence-levels: {slug} {o.get("source_url")}')
    for slug, ent in (curated or {}).items():
        for f, v in (ent or {}).items():
            if isinstance(v, dict):
                need(v.get('reviewed_on'), slug, 'corrected', f'keys-and-books: {slug}.{f} reviewed_on')
    for slug, t in (tasks or {}).items():
        if isinstance(t, dict):
            need(t.get('verified_on'), slug, 'corrected', f'first-tasks: {slug} verified_on')
    return gaps


def first_task(card, tasks):
    t = tasks.get(card.get('slug') or card.get('id'))
    if not t or not isinstance(t, dict):
        return None
    out = {k: t[k] for k in TASK_FIELDS if k != 'steps'} | {'steps': task_steps(t), 'credit': f"Contributed by {t['contributed_by']}"}
    out = {k: out[k] for k in TASK_FIELDS} | {'credit': out['credit']}  # same key order as before
    if isinstance(t.get('code'), dict):
        c = t['code']
        out['code'] = {'url': c['url'], 'filename': c['filename'], 'sha256': c['sha256'], 'run': [r['cmd'] for r in c['run']]}
    if t.get('no_code'):
        out['no_code'] = t['no_code']  # optional: a way to finish the task without running code
    return out


# ---------------------------------------------------------------- public wording guard
# Site-authored v2 wording says what a thing IS; these words must not appear in the v2 blocks we write.
NEGATIVE_WORDS = re.compile(r"\b(unknown|unverified|doesn't|does not|don't|fails?|failed|missing|none|no data|not verified)\b", re.I)


def negative_hits(text):
    return sorted(set(m.group(0).lower() for m in NEGATIVE_WORDS.finditer(text or '')))
