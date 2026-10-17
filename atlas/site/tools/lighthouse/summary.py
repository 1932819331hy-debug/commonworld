#!/usr/bin/env python3
"""Markdown table of Lighthouse CI scores (representative run per URL) from an lhci filesystem upload dir.

    python3 atlas/site/tools/lighthouse/summary.py atlas/site/screenshots/lighthouse/mobile mobile
"""
import json, os, sys

d, form = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else '')
cats = ('performance', 'accessibility', 'best-practices', 'seo')
try:
    runs = json.load(open(os.path.join(d, 'manifest.json')))
except OSError:
    print(f'### Lighthouse {form}: no results'); sys.exit(0)
print(f'### Lighthouse {form} (median run, budget >= 95)\n')
print('| page | ' + ' | '.join(cats) + ' |')
print('|---|' + '---|' * len(cats))
for r in runs:
    if r.get('isRepresentativeRun'):
        s = r.get('summary') or {}
        path = '/' + r['url'].split('/', 3)[3] if r['url'].count('/') >= 3 else r['url']
        print(f'| {path} | ' + ' | '.join(str(round(100 * s[c])) if s.get(c) is not None else '-' for c in cats) + ' |')
