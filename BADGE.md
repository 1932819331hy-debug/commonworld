# Commonworld Atlas badges

Every published card in the [Commonworld Atlas](https://commonworld.one/atlas/) has a free status badge that the platform can show on its own site or README. Full page: **https://commonworld.one/atlas/badge/**

[![Commonworld Atlas: Verified](https://commonworld.one/atlas/badge/the-spawn.svg)](https://commonworld.one/atlas/platforms/the-spawn/)

Free. Never sold. Updates itself with every weekly check.

## What it is

A plain SVG image served from `commonworld.one`: left *Commonworld Atlas*, right the status of one card. It links to the card with its facts and sources.

- Light backgrounds: `https://commonworld.one/atlas/badge/<id>.svg`
- Dark backgrounds: `https://commonworld.one/atlas/badge/<id>-dark.svg`

`<id>` is the card's permanent ID (its URL slug), taken from the card page or [platforms.json](https://commonworld.one/atlas/platforms.json). Never guess an ID. Each entry's JSON (`/atlas/platforms/<id>.json`) lists `badge_svg`, `badge_svg_dark` and `badge_page`.

## Statuses

| Badge text | Meaning |
| --- | --- |
| `Verified · YYYY-MM-DD` | Live card published as verified. The date is the newest observation on the card (UTC). |
| `Listed` | Published card that is not verified right now, e.g. under review. |
| `Closed · history` | The platform closed (by human review or by the automated weekly check); the card is kept as history. |

## How it updates

`atlas/site/build.py` regenerates every badge from the Atlas data on each build, including after the weekly check (`atlas/refresh.py`). Sites that show the badge load the current file, so status and date update by themselves (browsers and image proxies may keep a copy for a few hours).

## Rules

- Free for every published card; nobody has to ask for one.
- No tracking: plain SVG image, no scripts, no cookies, no external fonts or requests.
- Honest status: it shows the card's real status and last check date and links to the card with its sources.

## How to add it

Example for `the-spawn`. Every card page has the same block with its own code under *Add this badge to your site*.

HTML:

```html
<a href="https://commonworld.one/atlas/platforms/the-spawn/"><img src="https://commonworld.one/atlas/badge/the-spawn.svg" alt="Commonworld Atlas: Verified" height="20"></a>
```

Markdown:

```markdown
[![Commonworld Atlas: Verified](https://commonworld.one/atlas/badge/the-spawn.svg)](https://commonworld.one/atlas/platforms/the-spawn/)
```

Plain link: `https://commonworld.one/atlas/platforms/the-spawn/`

## Wrong status or date?

The badge only shows what the card says. To fix the card, [open a correction request](https://github.com/commonworld-one/commonworld/issues/new/choose) with the card's permanent ID and a link to a source that shows the right fact. When the card is corrected, the badge follows on the next build.
