#!/usr/bin/env python3
"""Refresh the "How fast we respond" block of atlas/data/stats.json from public GitHub issues (stdlib only).

    python3 atlas/tools/github_response_stats.py            # update atlas/data/stats.json in place
    python3 atlas/tools/github_response_stats.py --dry-run  # print the new section, write nothing

Reads https://api.github.com/repos/commonworld-one/commonworld/issues (public, no key; GITHUB_TOKEN is used when set,
only to raise the rate limit). Window: issues opened in the last 90 days (pull requests are excluded).

Definitions (also written into the page notes):
- maintainer = author_association OWNER, MEMBER or COLLABORATOR, human account (not a [bot]);
- outside issue = opened by anyone who is not a maintainer and not a bot;
- time to first maintainer response = from an outside issue's creation to the first maintainer comment, or to its close by a
  maintainer if that came first; median over outside issues opened in the window (no value until there is one);
- time to close = from creation to close, median over all issues opened in the window and closed by now.
"""
import json, os, statistics, sys, urllib.request
from datetime import datetime, timedelta, timezone

REPO = 'commonworld-one/commonworld'
API = f'https://api.github.com/repos/{REPO}'
HERE = os.path.dirname(os.path.abspath(__file__))
STATS = os.path.normpath(os.path.join(HERE, '..', 'data', 'stats.json'))
WINDOW_DAYS = 90
MAINT = {'OWNER', 'MEMBER', 'COLLABORATOR'}
SOURCE = {'name': 'GitHub issues (public API)', 'url': f'https://github.com/{REPO}/issues?q=is%3Aissue'}


def get(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'commonworld-stats'})
    if os.environ.get('GITHUB_TOKEN'):
        req.add_header('Authorization', 'Bearer ' + os.environ['GITHUB_TOKEN'])
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ts(v):
    """GitHub ISO 8601 UTC ('2026-10-17T12:26:01Z'). Also accepts 'Sat 2026-10-17 12:26 PM UTC (UTC+00:00)', the form some
    sandboxed proxies rewrite timestamps into (minute precision)."""
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        parts = v.split()
        off = v[v.index('(UTC') + 4:v.index(')')] if '(UTC' in v else '+00:00'
        dt = datetime.strptime(f'{parts[1]} {parts[2]} {parts[3]}', '%Y-%m-%d %I:%M %p')
        sign = 1 if off[0] == '+' else -1
        h, m = (int(x) for x in off[1:].split(':'))
        return (dt - sign * timedelta(hours=h, minutes=m)).replace(tzinfo=timezone.utc)


def human(u):
    return not (u or {}).get('login', '').endswith('[bot]') and (u or {}).get('type') != 'Bot'


def minutes(a, b):
    return round((b - a).total_seconds() / 60)


def collect(now):
    since = now - timedelta(days=WINDOW_DAYS)
    issues, page = [], 1
    while True:
        batch = get(f'{API}/issues?state=all&per_page=100&page={page}&sort=created&direction=desc')
        issues += [i for i in batch if 'pull_request' not in i]
        if len(batch) < 100 or (batch and ts(batch[-1]['created_at']) < since):
            break
        page += 1
    win = [i for i in issues if ts(i['created_at']) >= since]
    by = {'outside': 0, 'maintainers': 0, 'bots': 0}
    resp, close = [], []
    for i in win:
        created = ts(i['created_at'])
        if not human(i['user']):
            by['bots'] += 1
        elif i.get('author_association') in MAINT:
            by['maintainers'] += 1
        else:
            by['outside'] += 1
            if i['state'] == 'closed':
                i = get(i['url']) | {'comments_url': i['comments_url']}  # closed_by is only on the single-issue API
            firsts = [ts(c['created_at']) for c in (get(i['comments_url']) if i.get('comments') else [])
                      if c.get('author_association') in MAINT and human(c.get('user'))]
            if i.get('closed_at') and human(i.get('closed_by')) and (i.get('closed_by') or {}).get('login'):
                firsts.append(ts(i['closed_at']))  # closing the issue is an answer too
            if firsts:
                resp.append(minutes(created, min(firsts)))
        if i['state'] == 'closed' and i.get('closed_at'):
            close.append(minutes(created, ts(i['closed_at'])))
    return win, by, resp, close


def section(now):
    win, by, resp, close = collect(now)
    as_of = now.strftime('%Y-%m-%d')
    frm = (now - timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%d')
    period = {'from': frm, 'to': as_of, 'label': f'last {WINDOW_DAYS} days'}
    n_open = sum(1 for i in win if i['state'] == 'open')
    m = lambda id_, label, unit, value, note=None, status='ok': {k: v for k, v in {
        'id': id_, 'label': label, 'unit': unit, 'value': value, 'status': status, 'period': period, 'source': SOURCE,
        'as_of': as_of, 'note': note}.items() if v is not None or k == 'value'}
    mix = f"{by['outside']} from people outside the team, {by['maintainers']} from maintainers, {by['bots']} from our own automated checks"
    return {
        'id': 'response', 'title': 'How fast we respond', 'kind': 'support',
        'intro': f'Public GitHub issues of {REPO}: corrections, suggestions and problem reports, opened in the last {WINDOW_DAYS} days. Pull requests are not counted.',
        'metrics': [
            m('gh_issues_open', 'Open issues', 'issues', n_open, f'Of {len(win)} issues opened in this period: {mix}.'),
            m('gh_issues_closed', 'Closed issues', 'issues', len(win) - n_open),
            m('gh_issues_outside', 'Issues from people outside the team', 'issues', by['outside']),
            m('gh_first_response_median', 'Median time to first maintainer response', 'minutes',
              round(statistics.median(resp)) if resp else None,
              f'Over {len(resp)} issue(s) opened by people outside the team.' if resp else
              'No issue from outside the team yet, so there is nothing to measure. The first one starts this number.',
              'ok' if resp else 'none_yet'),
            m('gh_close_median', 'Median time to close', 'minutes', round(statistics.median(close)) if close else None,
              f'Over {len(close)} closed issue(s), all authors.' + (' All of them were opened by maintainers.' if close and not by['outside'] else '')
              if close else 'No closed issue in this period yet.', 'ok' if close else 'none_yet'),
        ]}


def main():
    now = datetime.now(timezone.utc)
    sec = section(now)
    if '--dry-run' in sys.argv:
        print(json.dumps(sec, indent=1)); return
    doc = json.load(open(STATS, encoding='utf-8'))
    secs = doc['sections']
    idx = next((k for k, s in enumerate(secs) if s.get('id') == 'response'), None)
    if idx is None:
        at = next((k for k, s in enumerate(secs) if s.get('id') == 'agents'), len(secs))
        secs.insert(at, sec)
    else:
        secs[idx] = sec
    doc['updated_at'] = now.strftime('%Y-%m-%d')
    with open(STATS, 'w', encoding='utf-8') as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
    print(f"stats.json: response block updated ({len(sec['metrics'])} metrics, as_of {sec['metrics'][0]['as_of']})")


if __name__ == '__main__':
    main()
