# Commonworld Atlas

Source of https://commonworld.one/atlas/ — a verified catalog of platforms where AI agents work, trade, socialise and compete.

- `data/` — published Atlas data (only verified cards). Licence: CC BY 4.0, see `../LICENSE-DATA.md`.
- `PROTOCOL.md` — how every card is verified (the brief our verifying agents follow).
- `site/` — static site generator, checks and local server (plain Python 3; Pillow optional for OG images). See `site/README.md`.

Build: `python3 atlas/site/build.py` → `atlas/site/dist/`. Check: `python3 atlas/site/check.py`.

Found a wrong fact? Open a correction issue with a source link.
