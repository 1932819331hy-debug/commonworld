#!/usr/bin/env python3
"""Link safety check for the Atlas (stdlib only).

Extracts every outbound host linked from the published Atlas data (canonical URLs, claim and QA source URLs, any
other http(s) URL inside an entry, including URLs embedded in prose such as claim statements), asks Google Safe Browsing about each one through the public Transparency Report
endpoint, and writes a JSON report. The site build reads the report: it is published as /atlas/safety.json and each
entry in the JSON exports carries `link_safety` {status, checked_at} for its own host.

    python3 atlas/tools/safebrowsing_check.py                       # writes atlas/data/link-safety.json
    python3 atlas/tools/safebrowsing_check.py --out /tmp/r.json --limit 20

Statuses: clean (Safe Browsing found no unsafe content), flagged (any unsafe-content flag), no_data (Safe Browsing has
no data for the host, or the query failed after retries and there was no earlier result to keep).
Superseded for the daily run by atlas/tools/link_safety.py (trust engine, all sources); kept for its helpers and as a single-source fallback.
Hosts of entries removed by the link-safety rule (atlas/data/removed.json) are re-checked too and reported under
`removed_hosts`, so the curator can see when a flag has cleared; they are never published on the site.

Polite by design: at most 4 requests at a time, a timeout per request, retries with backoff on errors, rate limits and
HTML answers. Exit code 1 when a published host is flagged (the flagged hosts are printed), 0 otherwise.
The check never edits Atlas data: removing an entry is a curator decision (atlas/CURATION.md#link-safety).
"""
import argparse, json, os, random, re, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', 'data'))
ENDPOINT = 'https://transparencyreport.google.com/transparencyreport/api/v3/safebrowsing/status?site='
SOURCE = 'Google Safe Browsing'
SOURCE_URL = 'https://transparencyreport.google.com/safe-browsing/search'
OWN_HOSTS = {'commonworld.one', 'www.commonworld.one'}
UA = 'CommonworldAtlas-LinkSafety/1.0 (+https://github.com/commonworld-one/commonworld)'
FLAG_NAMES = {2: 'malware', 3: 'unwanted_software', 4: 'social_engineering', 5: 'flag_5', 6: 'flag_6'}  # positions in the sb.ssr row


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def snapshot_path():
    names = sorted(n for n in os.listdir(DATA) if n.startswith('snapshot-verified-') and n.endswith('.json'))
    if not names:
        raise SystemExit(f'no snapshot-verified-*.json in {DATA}')
    return os.path.join(DATA, names[-1])


def norm_host(url):
    try:
        h = (urllib.parse.urlsplit(url.strip()).hostname or '').lower().rstrip('.')
    except ValueError:
        return ''
    return h[4:] if h.startswith('www.') else h


URL_IN_TEXT = re.compile(r'https?://[^\s"\'<>()\[\]`]+')  # also used by link_safety.py for the curation files


def urls_in(obj):
    """Every URL in an entry: a whole-string URL value, and every URL embedded in prose (claim statements, notes)."""
    if isinstance(obj, str):
        if obj.startswith(('http://', 'https://')) and not any(ch.isspace() for ch in obj):
            yield obj
        else:
            for u in URL_IN_TEXT.findall(obj):
                yield u.rstrip('.,;:!?')
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from urls_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from urls_in(v)


def hosts_of_entry(c):
    return {h for h in (norm_host(u) for u in urls_in(c)) if h and '.' in h and h not in OWN_HOSTS}


def extract_hosts(snapshot):
    """host -> sorted list of entry slugs that link to it."""
    out = {}
    for c in snapshot.get('platforms') or []:
        for h in hosts_of_entry(c):
            out.setdefault(h, set()).add(c['slug'])
    return {h: sorted(s) for h, s in sorted(out.items())}


def parse_answer(raw):
    """Transparency Report answer -> (status, code, threats, google_updated_at). Raises ValueError on an unexpected body."""
    body = raw.lstrip()
    if body.startswith(")]}'"):
        body = body[4:]
    row = json.loads(body)[0]
    if not isinstance(row, list) or row[0] != 'sb.ssr':
        raise ValueError('unexpected answer')
    code = row[1]
    threats = [FLAG_NAMES.get(i, f'flag_{i}') for i in range(2, 7) if i < len(row) and row[i] is True]
    upd = None
    if len(row) > 7 and isinstance(row[7], (int, float)) and row[7] > 0:
        upd = datetime.fromtimestamp(row[7] / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    if threats or code in (2, 3):
        status = 'flagged'
    elif code in (1, 4):  # 1: no unsafe content found; 4: large site, no site-wide verdict and no flag
        status = 'clean'
    else:                 # 6: no available data (and anything unknown)
        status = 'no_data'
    return status, code, threats, upd


def query(host, timeout, retries):
    """One host, with retries on network errors, rate limits (429/5xx) and HTML answers. Returns a result dict."""
    delay = 2.0
    last = ''
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(ENDPOINT + urllib.parse.quote(host, safe=''), headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(65536).decode('utf-8', 'replace')
            if raw.lstrip().startswith('<'):
                raise ValueError('HTML answer (rate limit or consent page)')
            status, code, threats, upd = parse_answer(raw)
            return {'status': status, 'code': code, 'threats': threats, 'google_updated_at': upd, 'checked_at': utc_now()}
        except urllib.error.HTTPError as ex:
            last = f'HTTP {ex.code}'
            if ex.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ValueError, IndexError, json.JSONDecodeError, OSError) as ex:
            last = f'{ex.__class__.__name__}: {ex}'[:160]
        if attempt < retries:
            time.sleep(delay + random.random())
            delay *= 2
    return {'status': None, 'error': last or 'query failed'}


def run(hosts, prev, workers, timeout, retries):
    def one(h):
        r = query(h, timeout, retries)
        if r.get('status') is None:  # failed: keep the earlier result (with its own checked_at) rather than inventing one
            old = prev.get(h)
            if old and old.get('status'):
                return h, dict(old, stale=True, error=r['error'])
            return h, {'status': 'no_data', 'code': None, 'threats': [], 'google_updated_at': None, 'checked_at': None, 'error': r['error']}
        return h, r
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as ex:  # never more than 4 at a time
        return dict(ex.map(one, hosts))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--data', default=None, help='snapshot-verified-*.json (default: newest in atlas/data/)')
    ap.add_argument('--removed', default=os.path.join(DATA, 'removed.json'))
    ap.add_argument('--out', default=os.path.join(DATA, 'link-safety.json'))
    ap.add_argument('--concurrency', type=int, default=4)
    ap.add_argument('--timeout', type=float, default=20)
    ap.add_argument('--retries', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0, help='check only the first N hosts (testing)')
    a = ap.parse_args()

    snap = json.load(open(a.data or snapshot_path(), encoding='utf-8'))
    linked = extract_hosts(snap)
    removed = json.load(open(a.removed)).get('removed') if os.path.exists(a.removed) else []
    removed_hosts = sorted({norm_host('https://' + r['host']) for r in removed or [] if r.get('host')} - set(linked))
    prev = {}
    if os.path.exists(a.out):
        try:
            p = json.load(open(a.out, encoding='utf-8'))
            prev = (p.get('hosts') or {}) | (p.get('removed_hosts') or {})
        except (ValueError, OSError):
            prev = {}
    hosts = list(linked)[:a.limit] if a.limit else list(linked)
    started = utc_now()
    t0 = time.time()
    res = run(hosts + removed_hosts, prev, a.concurrency, a.timeout, a.retries)
    pub = {h: res[h] | {'entries': linked[h]} for h in hosts}
    rem = {h: res[h] for h in removed_hosts}
    count = lambda st: sum(1 for r in pub.values() if r['status'] == st)
    flagged = sorted(h for h, r in pub.items() if r['status'] == 'flagged')
    report = {
        'name': 'Commonworld Atlas link safety report',
        'source': SOURCE, 'source_url': SOURCE_URL,
        'method': 'Every outbound host linked from the published Atlas data is looked up in Google Safe Browsing (Transparency Report site status). '
                  'clean = no unsafe content found; flagged = an unsafe-content flag (e.g. social engineering); no_data = Safe Browsing has no data for the host. '
                  'A flagged host leads to removal of its entry (see CURATION.md, Link safety).',
        'run_started_at': started, 'run_at': utc_now(),
        'summary': {'hosts': len(pub), 'clean': count('clean'), 'flagged': count('flagged'), 'no_data': count('no_data'),
                    'query_errors': sum(1 for r in pub.values() if r.get('error'))},
        'flagged': flagged,
        'hosts': pub,
        'removed_hosts': rem,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    s = report['summary']
    print(f"link safety: {s['hosts']} hosts in {time.time() - t0:.0f}s: {s['clean']} clean, {s['flagged']} flagged, {s['no_data']} no data, "
          f"{s['query_errors']} query errors -> {a.out}")
    for h, r in rem.items():
        print(f"removed entry host {h}: {r['status']}" + (' (flag cleared: entry may return after a curator re-check)' if r['status'] == 'clean' else ''))
    if flagged:
        print('FLAGGED hosts (remove their entries, see atlas/CURATION.md#link-safety):')
        for h in flagged:
            print(f"  - {h}: {', '.join(pub[h]['threats']) or 'code ' + str(pub[h]['code'])}; linked from {', '.join(pub[h]['entries'])}")
        sys.exit(1)


if __name__ == '__main__':
    main()
