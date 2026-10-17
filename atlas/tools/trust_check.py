"""Link-safety decisions (atlas/CURATION.md#link-safety): who may remove or restore an Atlas entry, and the record of each decision.

check(roles, removed_doc, report) -> list of failure strings (empty = fine):
  - atlas/data/trust-roles.json lists actors with unique ids;
  - every decision in atlas/data/removed.json `decisions` has action remove|restore, slug, host, by (an actor id from
    trust-roles.json), on (YYYY-MM-DD), reason and an https evidence link; a restore also has recheck "clean";
  - every entry under `removed` has its latest decision = remove (same slug and host);
  - a slug whose latest decision is restore is not under `removed`, and its host is "clean" in the latest safety report
    (atlas/data/link-safety.json, `hosts` or `removed_hosts`).
"""
import json, os, re

DATA = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def load(name, default=None):
    fp = os.path.join(DATA, name)
    return json.load(open(fp, encoding='utf-8')) if os.path.exists(fp) else default


def check(roles, removed_doc, report):
    fails = []
    if not roles:
        return ['atlas/data/trust-roles.json is missing']
    ids = [a.get('id') for a in roles.get('actors') or []]
    if not ids or any(not i for i in ids): fails.append('trust-roles.json: every actor needs an id')
    if len(set(ids)) != len(ids): fails.append('trust-roles.json: duplicate actor ids')
    actions = set(roles.get('actions') or [])
    if actions != {'remove', 'restore'}: fails.append(f'trust-roles.json: actions {sorted(actions)} != [remove, restore]')
    removed = (removed_doc or {}).get('removed') or []
    decisions = (removed_doc or {}).get('decisions') or []
    latest = {}
    for n, d in enumerate(decisions):
        tag = f"removed.json decisions[{n}] ({d.get('action')} {d.get('slug')})"
        if d.get('action') not in ('remove', 'restore'): fails.append(f'{tag}: action must be remove or restore')
        for k in ('slug', 'host', 'reason'):
            if not str(d.get(k) or '').strip(): fails.append(f'{tag}: {k} is required')
        if d.get('by') not in ids: fails.append(f"{tag}: actor {d.get('by')!r} is not in trust-roles.json")
        if not DATE.match(str(d.get('on') or '')): fails.append(f"{tag}: on {d.get('on')!r} is not YYYY-MM-DD")
        if not str(d.get('evidence') or '').startswith('https://'): fails.append(f'{tag}: evidence must be an https link')
        if d.get('action') == 'restore' and d.get('recheck') != 'clean': fails.append(f'{tag}: a restore needs recheck "clean"')
        if n and str(d.get('on') or '') < str(decisions[n - 1].get('on') or ''): fails.append(f'{tag}: decisions must be in date order')
        latest[d.get('slug')] = d
    gone = {r.get('slug') for r in removed}
    for r in removed:
        d = latest.get(r.get('slug'))
        if not d or d.get('action') != 'remove':
            fails.append(f"removed.json: {r.get('slug')} has no remove decision (who, when, reason, evidence)")
        elif d.get('host') != r.get('host'):
            fails.append(f"removed.json: {r.get('slug')} host {r.get('host')!r} != decision host {d.get('host')!r}")
    hosts = ((report or {}).get('hosts') or {}) | ((report or {}).get('removed_hosts') or {})
    for slug, d in latest.items():
        if d.get('action') != 'restore':
            continue
        if slug in gone: fails.append(f'removed.json: {slug} is restored by its latest decision but still listed under removed')
        st = (hosts.get(d.get('host')) or {}).get('status')
        if st != 'clean': fails.append(f"{slug}: restored host {d.get('host')} is {st or 'not in the latest safety report'}, must be clean")
    return fails


def main():
    return check(load('trust-roles.json'), load('removed.json', {}), load('link-safety.json', {}))


if __name__ == '__main__':
    f = main()
    print('\n'.join(f) or 'trust decisions: ok')
    raise SystemExit(1 if f else 0)
