#!/usr/bin/env python3
"""Weekly Atlas refresh (Python 3.12, standard library only).

    python3 atlas/refresh.py --dry-run                 # check everything, write nothing, print the summary
    python3 atlas/refresh.py --summary /tmp/pr.md      # apply changes to the snapshot + state, write a PR summary

What it does, per entry of the Atlas snapshot (atlas/data/snapshot-verified-*.json):
  1. Reachability: GET the primary URL (canonical_url, or check_url from atlas/refresh-sources.json), follow redirects,
     timeout 15 s, polite User-Agent, up to 3 attempts. If all attempts fail, a second method is tried (http<->https /
     www toggle) before the week counts as failed. 401/403/405/406/429/451/503 count as reachable-but-blocked
     (JS/Cloudflare shells are never evidence of death, atlas/PROTOCOL.md).
  2. Death rule (no false deaths), state in atlas/data/refresh-state.json:
       1st failed week  -> suspected_down (state only, nothing published)
       2nd consecutive  -> status closed / include_closed_history, with a direct_observation claim + status_history record
       recovered        -> suspected cleared; an entry closed BY THIS SCRIPT that answers again is revived (live + history).
     Entries closed by humans are never revived automatically (a re-registered/parked domain answers 200 too); a
     responding closed entry is only listed in the summary. Pages and slugs are never removed.
  3. Domain moved: final URL on another registrable domain than canonical_url -> flagged for human review, nothing changed.
  4. Numbers: only the explicit mappings in atlas/refresh-sources.json. A changed value is a re-observation (new value
     with observed_at in UTC, the previous value appended to claim.history); past records are never rewritten.
No change at all -> the snapshot and state files are left byte-identical (so the workflow opens no PR).
Exit code 0 always unless the script itself breaks; findings go to the summary.
"""
import argparse, concurrent.futures as cf, copy, glob, json, os, re, socket, ssl, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
UA = 'CommonworldAtlasBot/1.0 (+https://commonworld.one/atlas/about/)'
TIMEOUT = 15
ATTEMPTS = 3
BACKOFF = (2, 5)
BLOCKED = {401, 403, 405, 406, 429, 451, 503, 999}
TOOL = 'atlas/refresh.py'
# hosting suffixes where the first label below them is the "registrable" owner (no PSL in stdlib)
MULTI_SUFFIX = {'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'com.au', 'net.au', 'org.au', 'co.jp', 'co.kr', 'com.br', 'com.cn', 'co.in',
                'co.nz', 'com.mx', 'com.tr', 'co.za', 'com.sg', 'com.hk', 'github.io', 'gitlab.io', 'vercel.app', 'netlify.app',
                'pages.dev', 'workers.dev', 'up.railway.app', 'railway.app', 'onrender.com', 'herokuapp.com', 'fly.dev',
                'replit.app', 'repl.co', 'chatgpt.site', 'web.app', 'firebaseapp.com', 'azurewebsites.net', 'hf.space',
                'streamlit.app', 'vercel.sh', 'deno.dev', 'surge.sh', 'glitch.me', 'notion.site', 'substack.com',
                'medium.com', 'blogspot.com', 'wordpress.com', 'framer.website', 'framer.app', 'webflow.io', 'carrd.co'}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def reg_domain(url):
    host = (urllib.parse.urlsplit(url).hostname or '').lower().rstrip('.')
    if host.startswith('www.'):
        host = host[4:]
    parts = host.split('.')
    for n in (3, 2):
        if len(parts) > n and '.'.join(parts[-n:]) in MULTI_SUFFIX:
            return '.'.join(parts[-(n + 1):])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


def default_snapshot():
    files = sorted(glob.glob(os.path.join(DATA, 'snapshot-verified-*.json')))
    if not files:
        raise SystemExit('no atlas/data/snapshot-verified-*.json')
    return files[-1]


# ------------------------------------------------------------------ HTTP
_CTX = ssl.create_default_context()


def fetch(url, want_body=False, limit=65536):
    """One GET. Returns dict(status, final_url, error, body)."""
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8',
                                               'Accept-Language': 'en'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            body = r.read(limit if not want_body else 20_000_000)
            return {'status': r.status, 'final_url': r.geturl(), 'error': None, 'body': body if want_body else None}
    except urllib.error.HTTPError as ex:
        return {'status': ex.code, 'final_url': ex.geturl() or url, 'error': f'HTTP {ex.code}', 'body': None}
    except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError, OSError, ValueError) as ex:
        reason = getattr(ex, 'reason', ex)
        return {'status': None, 'final_url': url, 'error': f'{type(reason).__name__}: {str(reason)[:160]}', 'body': None}


def classify(res):
    s = res['status']
    if s is None:
        return 'fail'
    if s < 400:
        return 'ok'
    if s in BLOCKED:
        return 'blocked'
    return 'fail'


def alt_urls(url):
    sp = urllib.parse.urlsplit(url)
    host = sp.hostname or ''
    out = []
    other_host = host[4:] if host.startswith('www.') else 'www.' + host
    out.append(sp._replace(netloc=other_host).geturl())
    out.append(sp._replace(scheme='http' if sp.scheme == 'https' else 'https').geturl())
    return out


def check(url, extra=(), sleep=time.sleep):
    """Up to ATTEMPTS GETs of url; if all fail, one try per alternate method (www/scheme toggle, then `extra` URLs:
    the pages that served the entry's supported site_reachable observations). Returns a result dict."""
    tries = []
    for i in range(ATTEMPTS):
        r = fetch(url)
        r['cls'] = classify(r)
        tries.append(r)
        if r['cls'] != 'fail':
            return {'cls': r['cls'], 'status': r['status'], 'final_url': r['final_url'], 'error': r['error'],
                    'attempts': i + 1, 'methods': [f'GET {url} -> {r["status"] or r["error"]}'], 'via': url}
        if i < ATTEMPTS - 1:
            sleep(BACKOFF[min(i, len(BACKOFF) - 1)])
    methods = [f'GET {url} x{ATTEMPTS} -> {tries[-1]["status"] or tries[-1]["error"]}']
    alts = list(dict.fromkeys(alt_urls(url) + [x for x in extra if x and x != url]))
    for a in alts:
        r = fetch(a)
        r['cls'] = classify(r)
        methods.append(f'GET {a} -> {r["status"] or r["error"]}')
        if r['cls'] != 'fail':
            return {'cls': r['cls'], 'status': r['status'], 'final_url': r['final_url'], 'error': r['error'],
                    'attempts': ATTEMPTS + 1, 'methods': methods, 'via': a}
    last = tries[-1]
    return {'cls': 'fail', 'status': last['status'], 'final_url': last['final_url'], 'error': last['error'],
            'attempts': ATTEMPTS + len(alts), 'methods': methods, 'via': url}


# ------------------------------------------------------------------ numbers
def dig(obj, path):
    for k in path.split('.'):
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        else:
            return None
    return obj


def as_number(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and re.fullmatch(r'-?\d+(\.\d+)?', v.strip()):
        f = float(v)
        return int(f) if f.is_integer() and '.' not in v else round(f, 6)
    return None


def get_json(url):
    last = None
    for i in range(ATTEMPTS):
        r = fetch(url, want_body=True)
        if r['status'] == 200 and r['body'] is not None:
            try:
                return json.loads(r['body'].decode('utf-8', 'replace')), None
            except ValueError as ex:
                return None, f'not JSON: {ex}'
        last = r['error'] or f'HTTP {r["status"]}'
        if i < ATTEMPTS - 1:
            time.sleep(BACKOFF[min(i, len(BACKOFF) - 1)])
    return None, last


def read_mapping(m):
    """-> (value, quote, methods, error)"""
    if m.get('agg'):
        ag = m['agg']
        items, url, pages, methods = [], m['url'], 0, []
        while True:
            doc, err = get_json(url)
            if err:
                return None, None, methods, f'{url}: {err}'
            lst = dig(doc, ag['list'])
            if not isinstance(lst, list):
                return None, None, methods, f'{url}: no list at {ag["list"]}'
            items += lst
            pages += 1
            methods.append(f'GET {url}')
            nxt = doc.get('nextOffset') if isinstance(doc, dict) else None
            if m.get('paginate') == 'offset' and doc.get('hasMore') and nxt is not None and pages < 50:
                sp = urllib.parse.urlsplit(m['url'])
                q = dict(urllib.parse.parse_qsl(sp.query))
                q['offset'] = str(nxt)
                url = sp._replace(query=urllib.parse.urlencode(q)).geturl()
                continue
            break

        def ok(x):
            for k, want in (ag.get('where') or {}).items():
                v = dig(x, k)
                if want == '*':
                    if v in (None, '', [], {}):
                        return False
                elif v != want:
                    return False
            return True
        sel = [x for x in items if ok(x)]
        if ag['op'] == 'count':
            val = len(sel)
        else:
            nums = [as_number(dig(x, ag['field'])) for x in sel]
            if any(n is None for n in nums):
                return None, None, methods, f'non-numeric {ag["field"]} in list'
            val = sum(nums)
            val = int(val) if float(val).is_integer() else round(val, 6)
        where = ', '.join(f'{k}={v}' for k, v in (ag.get('where') or {}).items())
        quote = f'{len(items)} items read; {len(sel)} with {where}' + (f'; sum {ag["field"]} = {val}' if ag['op'] == 'sum' else '')
        methods.append(f'{ag["op"]} over {ag["list"]}' + (f' of {ag["field"]}' if ag['op'] == 'sum' else '') + (f' where {where}' if where else ''))
        return val, quote, methods, None
    doc, err = get_json(m['url'])
    if err:
        return None, None, [f'GET {m["url"]}'], f'{m["url"]}: {err}'
    val = as_number(dig(doc, m['path']))
    if val is None:
        return None, None, [f'GET {m["url"]}'], f'no number at {m["path"]}'
    q = ','.join(f'"{f.split(".")[-1]}":{json.dumps(dig(doc, f))}' for f in (m.get('quote_fields') or [m['path']]))
    return val, q[:200], [f'GET {m["url"]}', f'read {m["path"]}'], None


def fmt_value(v):
    if isinstance(v, int):
        return f'{v:,}'
    return f'{v:,.6f}'.rstrip('0').rstrip('.')


def apply_number(entry, m, val, quote, methods, ts):
    """Mutates entry. Returns ('new'|'changed'|'same', old_value)."""
    claims = entry.setdefault('claims', [])
    c = next((x for x in claims if x.get('refresh_id') == m['id']), None)
    if c is None and m.get('match'):
        mt = m['match']
        c = next((x for x in claims if x.get('source_url') == mt.get('source_url') and x.get('unit') == mt.get('unit')
                  and x.get('kind') == m['kind'] and x.get('basis') == m['basis']), None)
    statement = (m.get('statement') or '').replace('{value}', fmt_value(val)) or None
    if c is None:
        claims.append({'kind': m['kind'], 'statement': statement or f'{fmt_value(val)} {m["unit"]}', 'value': val, 'unit': m['unit'],
                       'window': m.get('window'), 'basis': m['basis'], 'source_url': m['url'], 'quote': quote, 'observed_at': ts,
                       'methods': methods, 'outcome': 'supported', 'refresh_id': m['id']})
        return 'new', None
    if c.get('value') == val:
        return 'same', val
    old = {k: c.get(k) for k in ('value', 'unit', 'window', 'statement', 'quote', 'source_url', 'observed_at', 'basis', 'outcome')}
    old['superseded_at'] = ts
    old['reason'] = 'weekly automated re-observation (atlas/refresh.py)'
    c.setdefault('history', []).append(old)
    c.update({'value': val, 'quote': quote, 'observed_at': ts, 'methods': methods, 'outcome': 'supported', 'refresh_id': m['id']})
    if statement:
        c['statement'] = statement
    if m.get('window') and not c.get('window'):
        c['window'] = m['window']
    return 'changed', old['value']


# ------------------------------------------------------------------ main
def closed_by_refresh(e):
    hist = e.get('status_history') or []
    return bool(hist) and hist[-1].get('to') == 'closed' and hist[-1].get('by') == TOOL


def load_json(p, default):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true', help='check everything, write nothing')
    ap.add_argument('--snapshot', default=None)
    ap.add_argument('--sources', default=os.path.join(HERE, 'refresh-sources.json'))
    ap.add_argument('--state', default=os.path.join(DATA, 'refresh-state.json'))
    ap.add_argument('--state-from', default=None, help='start from this state (e.g. the open refresh PR) if it is newer than --state')
    ap.add_argument('--summary', default=None, help='write the markdown PR summary here')
    ap.add_argument('--report', default=None, help='write the full JSON report here')
    ap.add_argument('--only', default=None, help='comma-separated slugs (testing)')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()

    snap_path = a.snapshot or default_snapshot()
    snap_raw = open(snap_path, encoding='utf-8').read()
    snap = json.loads(snap_raw)
    sources = load_json(a.sources, {}).get('sources', {})
    state_raw = open(a.state, encoding='utf-8').read() if os.path.exists(a.state) else None
    state = json.loads(state_raw) if state_raw else {'version': 1, 'entries': {}, 'moved': {}}
    if a.state_from and os.path.exists(a.state_from):
        alt = load_json(a.state_from, None)
        if alt and (alt.get('updated_at') or '') > (state.get('updated_at') or ''):
            print(f'starting from newer state {a.state_from} ({alt.get("updated_at")})')
            state = alt
    state.setdefault('entries', {}); state.setdefault('moved', {})
    state_before = copy.deepcopy(state)
    ts = now_iso()
    today = ts[:10]

    entries = snap['platforms']
    if a.only:
        keep = set(a.only.split(','))
        entries = [e for e in entries if e['slug'] in keep]

    def job(e):
        url = (sources.get(e['slug']) or {}).get('check_url') or e.get('canonical_url')
        if not url:
            return e['slug'], {'cls': 'no_url', 'methods': [], 'via': None, 'status': None, 'final_url': None, 'error': 'no URL'}
        extra = [x.get('source_url') for x in e.get('claims', []) if x.get('kind') == 'site_reachable' and x.get('outcome') == 'supported'
                 and (x.get('source_url') or '').startswith('http') and reg_domain(x['source_url']) == reg_domain(url)]
        return e['slug'], check(url, extra)

    t0 = time.time()
    results = {}
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for slug, r in ex.map(job, entries):
            results[slug] = r
    print(f'checked {len(results)} entries in {time.time() - t0:.0f}s', file=sys.stderr)

    rep = {'run_at': ts, 'dry_run': a.dry_run, 'counts': {}, 'died': [], 'suspected': [], 'recovered': [], 'revived': [],
           'moved': [], 'closed_responding': [], 'numbers': [], 'number_errors': [], 'notes': []}
    from collections import Counter
    rep['counts'] = dict(Counter(r['cls'] for r in results.values()))
    rep['counts_by_status'] = {st: dict(Counter(results[e['slug']]['cls'] for e in entries if e['status'] == st)) for st in ('live', 'closed')}
    changed_slugs = set()

    for e in entries:
        slug, r = e['slug'], results[e['slug']]
        st = state['entries'].get(slug)
        if e['status'] == 'live':
            if r['cls'] == 'fail':
                st = st or {'failed_weeks': 0, 'first_failed_at': ts}
                st['failed_weeks'] += 1
                st['last_error'] = r['error']
                state['entries'][slug] = st
                if st['failed_weeks'] >= 2:
                    rep['died'].append({'slug': slug, 'url': r['via'], 'error': r['error'], 'first_failed_at': st['first_failed_at']})
                    claim = {'kind': 'site_reachable',
                             'statement': f'Automated weekly check could not reach the site in {st["failed_weeks"]} consecutive weeks '
                                          f'({ATTEMPTS} attempts each week plus alternate URLs); last error: {r["error"]}.',
                             'value': None, 'unit': None, 'window': None, 'basis': 'direct_observation', 'source_url': r['via'],
                             'quote': (r['error'] or '')[:200], 'observed_at': ts, 'methods': r['methods'], 'outcome': 'contradicted',
                             'refresh': {'by': TOOL, 'rule': 'closed after 2 consecutive failed weekly checks', 'first_failed_at': st['first_failed_at']}}
                    e['claims'].insert(0, claim)
                    e.setdefault('status_history', []).append({'at': ts, 'from': 'live', 'to': 'closed', 'by': TOOL,
                                                               'reason': f'unreachable in {st["failed_weeks"]} consecutive weekly checks since {st["first_failed_at"][:10]}'})
                    e['status'], e['verdict'] = 'closed', 'include_closed_history'
                    st['closed_at'] = ts
                    changed_slugs.add(slug)
                else:
                    rep['suspected'].append({'slug': slug, 'url': r['via'], 'error': r['error'], 'methods': r['methods']})
            else:
                if st and st.get('failed_weeks'):
                    rep['recovered'].append({'slug': slug, 'was_failed_weeks': st['failed_weeks']})
                    state['entries'].pop(slug, None)
        elif e['status'] == 'closed':
            if r['cls'] == 'ok' and closed_by_refresh(e):
                rep['revived'].append({'slug': slug, 'url': r['via'], 'status': r['status']})
                e['claims'].insert(0, {'kind': 'site_reachable', 'statement': f'Automated weekly check: the site answers again (HTTP {r["status"]}).',
                                       'value': None, 'unit': None, 'window': None, 'basis': 'direct_observation', 'source_url': r['via'],
                                       'quote': f'HTTP {r["status"]} final URL {r["final_url"]}', 'observed_at': ts, 'methods': r['methods'],
                                       'outcome': 'supported', 'refresh': {'by': TOOL, 'rule': 'revived: entry closed by refresh answers again'}})
                e['status_history'].append({'at': ts, 'from': 'closed', 'to': 'live', 'by': TOOL, 'reason': f'site answers again (HTTP {r["status"]})'})
                e['status'], e['verdict'] = 'live', 'include_verified'
                state['entries'].pop(slug, None)
                changed_slugs.add(slug)
            elif r['cls'] == 'ok':
                rep['closed_responding'].append({'slug': slug, 'status': r['status'], 'final_url': r['final_url']})
        # domain moved (only flag; never change data). Closed entries are skipped: their old domains often point elsewhere.
        if e['status'] == 'live' and r.get('final_url') and r['cls'] in ('ok', 'blocked') and e.get('canonical_url'):
            want, got = reg_domain(e['canonical_url']), reg_domain(r['final_url'])
            if want != got:
                prev = state['moved'].get(slug)
                if prev != got:
                    rep['moved'].append({'slug': slug, 'canonical': e['canonical_url'], 'final_url': r['final_url'], 'previous': prev,
                                         'status': e['status']})
                    state['moved'][slug] = got
            elif slug in state['moved']:
                state['moved'].pop(slug)

    # numbers
    for e in entries:
        if e['status'] != 'live' or results[e['slug']]['cls'] == 'fail':
            continue
        for m in (sources.get(e['slug']) or {}).get('numbers', []):
            val, quote, methods, err = read_mapping(m)
            if err:
                rep['number_errors'].append({'slug': e['slug'], 'id': m['id'], 'error': err})
                continue
            what, old = apply_number(e, m, val, quote, methods, ts)
            if what != 'same':
                changed_slugs.add(e['slug'])
                rep['numbers'].append({'slug': e['slug'], 'id': m['id'], 'kind': m['kind'], 'basis': m['basis'], 'unit': m['unit'],
                                       'old': old, 'new': val, 'action': what, 'source': m['url']})
                if m.get('on_change_note'):
                    rep['notes'].append(f'{e["slug"]}: {m["on_change_note"]}')

    data_changed = bool(changed_slugs)
    if data_changed:
        snap['generated_at'] = ts
        snap.setdefault('amendments', []).append({
            'date': today, 'tag': f'refresh-{today}', 'by': TOOL,
            'rule': 'weekly automated refresh: reachability (2 failed weeks -> closed history), explicit numeric mappings from atlas/refresh-sources.json',
            'died': [d['slug'] for d in rep['died']], 'revived': [d['slug'] for d in rep['revived']],
            'number_updates': [f'{n["slug"]}:{n["id"]}' for n in rep['numbers']]})
    state_changed = state != state_before
    if state_changed:
        state['updated_at'] = ts
    rep['data_changed'], rep['state_changed'] = data_changed, state_changed
    rep['changed_slugs'] = sorted(changed_slugs)
    if not data_changed and not state_changed:
        rep['notes'].append('No data or state change: no PR needed.')

    md = summary_md(rep, snap_path)
    if not a.dry_run:
        if data_changed:
            with open(snap_path, 'w', encoding='utf-8') as f:
                f.write(dump(snap))
        if state_changed:
            with open(a.state, 'w', encoding='utf-8') as f:
                f.write(dump(state))
    if a.summary:
        with open(a.summary, 'w', encoding='utf-8') as f:
            f.write(md)
    if a.report:
        with open(a.report, 'w', encoding='utf-8') as f:
            json.dump(rep | {'results': results}, f, ensure_ascii=False, indent=1)
    print(md)
    print(f'changes: data={data_changed} state={state_changed} dry_run={a.dry_run}')


def summary_md(rep, snap_path):
    L = [f'## Atlas weekly refresh {rep["run_at"][:10]}', '',
         f'Run at {rep["run_at"]} (UTC) by `atlas/refresh.py`. Rules: [atlas/PROTOCOL.md](https://github.com/commonworld-one/commonworld/blob/main/atlas/PROTOCOL.md); '
         'a failed week = 3 failed attempts + alternate URLs; 1st failed week = suspected (not published), 2nd = closed history. '
         'Pages and slugs are never removed. **Review before merging; never auto-merged.**', '',
         '| | count |', '|---|---:|']
    c = rep['counts']
    L += [f'| checked | {sum(c.values())} |', f'| reachable (2xx/3xx) | {c.get("ok", 0)} |', f'| blocked / needs browser (401/403/429/503…) | {c.get("blocked", 0)} |',
          f'| failed this week | {c.get("fail", 0)} |',
          f'| **died** (2nd failed week → closed history) | {len(rep["died"])} |', f'| suspected down (1st failed week) | {len(rep["suspected"])} |',
          f'| recovered from suspected | {len(rep["recovered"])} |', f'| **revived** (closed by refresh → live) | {len(rep["revived"])} |',
          f'| domain moved (needs human review) | {len(rep["moved"])} |', f'| number changes | {len(rep["numbers"])} |', '']

    def table(title, rows, cols):
        if not rows:
            return
        L.append(f'### {title}'); L.append('')
        L.append('| ' + ' | '.join(h for h, _ in cols) + ' |'); L.append('|' + '---|' * len(cols))
        for r in rows:
            L.append('| ' + ' | '.join(str(f(r)).replace('|', '\\|').replace('\n', ' ') for _, f in cols) + ' |')
        L.append('')
    pg = lambda s: f'[{s}](https://commonworld.one/atlas/platforms/{s}/)'
    table('Died (status → closed history; page and URL kept)', rep['died'], [('entry', lambda r: pg(r['slug'])), ('url', lambda r: r['url']), ('first failed', lambda r: r['first_failed_at'][:10]), ('last error', lambda r: r['error'])])
    table('Suspected down (first failed week; nothing published)', rep['suspected'], [('entry', lambda r: pg(r['slug'])), ('url', lambda r: r['url']), ('error', lambda r: r['error'])])
    table('Revived', rep['revived'], [('entry', lambda r: pg(r['slug'])), ('url', lambda r: r['url']), ('HTTP', lambda r: r['status'])])
    table('Recovered (was suspected)', rep['recovered'], [('entry', lambda r: pg(r['slug'])), ('failed weeks before', lambda r: r['was_failed_weeks'])])
    table('Redirects to another domain (flag only, data unchanged)', rep['moved'], [('entry', lambda r: pg(r['slug'])), ('status', lambda r: r['status']), ('canonical', lambda r: r['canonical']), ('now ends at', lambda r: r['final_url']), ('previously seen', lambda r: r['previous'] or '—')])
    table('Number changes (re-observations; old value kept in claim history)', rep['numbers'], [('entry', lambda r: pg(r['slug'])), ('claim', lambda r: r['id']), ('basis', lambda r: r['basis']), ('old', lambda r: '—' if r['old'] is None else fmt_value(r['old'])), ('new', lambda r: fmt_value(r['new'])), ('unit', lambda r: r['unit']), ('source', lambda r: r['source'])])
    if rep['notes']:
        L.append('### Needs a human'); L.append(''); L += [f'- {n}' for n in rep['notes']]; L.append('')
    if rep['closed_responding']:
        L.append('<details><summary>Closed entries (closed by a human) that answer HTTP 2xx/3xx — not revived automatically</summary>'); L.append('')
        L += [f'- {pg(r["slug"])}: HTTP {r["status"]} → {r["final_url"]}' for r in rep['closed_responding']]; L += ['', '</details>', '']
    if rep['number_errors']:
        L.append('<details><summary>Number sources that could not be read (no change made)</summary>'); L.append('')
        L += [f'- {r["slug"]} `{r["id"]}`: {r["error"]}' for r in rep['number_errors']]; L += ['', '</details>', '']
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
