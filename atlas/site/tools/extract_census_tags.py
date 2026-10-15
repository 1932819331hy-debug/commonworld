#!/usr/bin/env python3
"""Map the census tags (the ones shown in research/atlas/catalog_en.html) onto the published Atlas entries.

    python3 atlas/site/tools/extract_census_tags.py   # writes atlas/data/census-tags-2026-10-15.json

Tags are DESCRIPTIVE LABELS from the 2026-10-15 census, not verified claims. Cleaning rules:
  * lowercase, trimmed
  * drop internal / status / evaluation tags (DROP below and anything ending in "-listed")
  * merge obvious duplicates (MERGE below)
  * keep only tags used by >= 2 published entries
Matching: census `id` == snapshot `id` (the snapshot kept census ids), confirmed by a normalised-name or
canonical-host match; anything that fails both is reported and gets no tags.
"""
import json, os, re, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', '..', 'data'))
CENSUS = os.path.join(DATA, 'census-2026-10-15.json')
SNAP = os.path.join(DATA, 'snapshot-verified-2026-10-15.json')
OUT = os.path.join(DATA, 'census-tags-2026-10-15.json')

# status / census-process / evaluative tags: they describe the census state or a judgement, not what the entry is
DROP = {
    'dead', 'dormant', 'quiet', 'unverified', 'not-deep-dived', 'closed', 'ended', 'paused', 'pivoted', 'inactive',
    'frozen', 'collapsed', 'rebranded', 'moved', 'stale', 'stale-banner', 'stale-counters', 'empty', 'flaky', 'new',
    'unreachable', 'declining', 'graveyard', 'flop', 'demo-only', 'one-off', 'pilot', 'waitlist', 'closed-beta',
    'self-reported', 'unverified-numbers', 'unverified-claims', 'inflated', 'inflated-counts', 'fake', 'fake-activity',
    'fake-stats', 'grandiose-claims', 'avoid', 'name-collision', 'meta', 'small', 'wash', 'wash-filter', 'farming',
    'sybil-risk', 'spam', 'pr-spam', 'crypto-spam', 'memecoin-spam', 'bot-farms', 'weak-moderation', 'review-bottleneck',
    'concentrated', 'concentrated-demand', 'unfunded', 'subsidised', 'supply-only', 'failed-payouts', 'unlawful-demand',
    'honeypot-repos', 'pennies', 'whale', 'marketing', 'vendor-driven', 'breach', 'prompt-injection', 'memory-injection',
    'owner-self-review', 'walled-garden', 'broad-buyers', 'ai',
}
MERGE = {
    'oss': 'open-source', 'games': 'game', 'tokens': 'token', 'wallets': 'wallet', 'no-accounts': 'no-account',
    'no-registration': 'no-account', 'monitors': 'monitor', 'directories': 'directory', 'evaluators': 'evaluator',
    'challenges': 'challenge', 'attestations': 'attestation', 'dms': 'dm', 'competitions': 'competition',
    'small-board': 'board', 'agent-to-agent': 'a2a', 'llm-router': 'inference-router', 'social-network': 'social',
    'signed-messages': 'signed-receipts', 'ai-review': 'peer-review', 'predictions': 'forecasting',
    'prediction-markets': 'forecasting', 'stablecoin': 'stablecoins', 'usdt': 'stablecoins',
}
MIN_USES = 2

norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())


def host(u):
    m = re.match(r'https?://(?:www\.)?([^/]+)', u or '')
    return m[1].lower() if m else None


def clean(tags):
    out = []
    for t in tags:
        t = t.strip().lower()
        if not t or t in DROP or t.endswith('-listed'):
            continue
        t = MERGE.get(t, t)
        if t not in out:
            out.append(t)
    return out


def main():
    census = {c['id']: c for c in json.load(open(CENSUS))}
    snap = json.load(open(SNAP))['platforms']
    mapped, unmatched = {}, []
    for s in snap:
        c = census.get(s['id'])
        ok = c and (norm(c['name']) in norm(s['name']) or norm(s['name']) in norm(c['name'])
                    or host(s.get('canonical_url')) in {host(u) for u in [c.get('url')] + (c.get('also_urls') or []) if u})
        if not ok:
            unmatched.append(s['slug'])
            continue
        mapped[s['slug']] = clean(c.get('tags') or [])
    uses = Counter(t for ts in mapped.values() for t in ts)
    keep = {t for t, n in uses.items() if n >= MIN_USES}
    result = {slug: [t for t in ts if t in keep] for slug, ts in mapped.items()}
    result = {k: v for k, v in sorted(result.items()) if v}
    doc = {'_help': 'Descriptive labels from the 2026-10-15 census (research/atlas/catalog_en.html), cleaned by '
                    'atlas/site/tools/extract_census_tags.py. They are NOT verified claims. slug -> [tags].',
           'tags': result}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    final = Counter(t for ts in result.values() for t in ts)
    print(f'{len(result)} of {len(snap)} entries tagged, {len(final)} distinct tags (>= {MIN_USES} uses); unmatched: {unmatched or "none"}')
    print(', '.join(f'{t} {n}' for t, n in final.most_common()))


if __name__ == '__main__':
    sys.exit(main())
