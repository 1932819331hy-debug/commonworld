# AI crawler and agent visit log

Our own small tool (agent-SEO plan, step 4): which AI crawlers and agents read which Commonworld pages, kept as long as we
want (Cloudflare's own dashboards keep about 30 days). $0: one D1 table, no extra Cloudflare product.

## What is counted

A request whose `User-Agent` contains a token from `policy/ai-bots.json` (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot,
Claude-User, Claude-SearchBot, PerplexityBot, Perplexity-User, GoogleOther, Gemini-Deep-Research, Google-Agent,
Google-GeminiNotebook, Applebot, Bytespider, CCBot, Meta-ExternalAgent, Amazonbot, DuckAssistBot, MistralAI-User, KimiBot,
Kimi-User, Kimi-SearchBot, Manus-User, …). After the Worker answers, it adds 1 to the row

| day (UTC) | bot (name from our list) | verified | category | path (no query, ≤ 200 chars) | status | count |

Nothing else: no IP, no full User-Agent, no query string, no cookies, no account. Ordinary visitors (no AI token) are
never written. Google-Extended and Applebot-Extended are robots.txt control tokens only (Google and Apple never send them
as a User-Agent), so they stay in the list with `"match": false` and are not counted.

Names are what the visitor **claims**. Anyone can send `User-Agent: GPTBot`. Since 2026-10-18 every row also keeps
Cloudflare's own verdict for that request (next section), so "said it was GPTBot" and "Cloudflare confirmed a verified
bot" are counted apart.

## Verified or not: Cloudflare's verdict (migration 0018)

Cloudflare checks every request against its list of verified bots and agents (published IP ranges, reverse DNS, Web Bot
Auth signatures; directory: https://radar.cloudflare.com/bots/directory). A Worker reads the result in
`request.cf.verifiedBotCategory` — on **every plan**, Free zone included, $0, no extra service, no API call. We store:

| verified | when | category |
|---|---|---|
| `verified` | `verifiedBotCategory` is a non-empty string | Cloudflare's label, e.g. `AI Crawler`, `AI Assistant`, `AI Search`, `Search Engine Crawler` (≤ 64 chars) |
| `not_verified` | `verifiedBotCategory` is `""`: Cloudflare checked, not a verified bot | `''` |
| `unknown` | no Cloudflare signal: rows written before 2026-10-18, local dev, tests | `''` |

Not used: `request.cf.botManagement.verifiedBot` — only set with Enterprise Bot Management (paid add-on); without it the
field is absent or always false (https://developers.cloudflare.com/workers/runtime-apis/request/#incomingrequestcfproperties).
Also not used (they would need more): the GraphQL Analytics API (`httpRequestsAdaptiveGroups`, needs token permission
Zone → Analytics → Read, which `hark-wrangler-staging` does not have) and a Transform Rule header (needs Zone → Transform
Rules → Edit). The Worker field gives the same verdict per request without either.

How to read `not_verified`: it depends on whether Cloudflare lists that bot at all. `policy/ai-bots.json` has
`cloudflare_radar` per bot = its slug in Cloudflare's directory (checked 2026-10-18 with the Radar API, `GET /radar/bots`),
or `null`:

- listed (19 of 37): OAI-SearchBot, ChatGPT-User, GPTBot, Claude-SearchBot, Claude-User, ClaudeBot, Google-CloudVertexBot,
  GoogleOther, Google-Agent, Applebot, Meta-ExternalFetcher, Meta-ExternalAgent, Amazonbot, DuckAssistBot, MistralAI-User,
  YouBot, KimiBot, Manus-User (Radar "Manus Bot", no UA pattern, so verified by signature), Bravebot. Here
  `not_verified` means the name is probably fake (or the bot used an address Cloudflare does not know).
- not listed (`null`): anthropic-ai, PerplexityBot, Perplexity-User, Gemini-Deep-Research, Google-GeminiNotebook,
  Bytespider, CCBot, cohere-*, AI2Bot, Diffbot, Kimi-SearchBot, Kimi-User, ImagesiftBot, TikTokSpider, Timpibot and the
  robots-only tokens. These always show `not_verified`, even when genuine: Cloudflare has nothing to check them against.

`verified` says Cloudflare confirmed *a* verified bot; it does not by itself name which one. The name is still ours (from
the User-Agent). Old rows (before 0018) stay as `unknown`; nothing is back-filled.

Covers everything the Worker serves: v1 pages, `/v1/*`, robots.txt, sitemaps, llms files and the Atlas pages. Since
2026-10-20 the Worker serves the whole `commonworld.one` domain and the Atlas ships inside it as Workers Static Assets
(`docs/ATLAS-STATIC-ASSETS.md`, `../docs/DEPLOY.md`): Atlas HTML pages and redirects run the Worker and are in this log;
Atlas static files that Cloudflare serves without invoking the Worker (CSS, JS, images, `/atlas/**.json`, `/api/v1/*`,
the files listed as negative `run_worker_first` patterns in `wrangler.toml`) are not.

## Second counter: unnamed agents (heuristic, not verified)

Many agents never say who they are: a script with curl or python-requests, an agent framework with a default HTTP client,
a model's built-in fetch tool. They are counted separately, in `unnamed_agent_visits`, and shown in the admin answer under
`unnamed_agents` with the label **heuristic, not verified**. Rule (`classifyUnnamedAgent` in `src/ai-bots.ts`):

1. Only `GET`/`HEAD`; never `/health`; never a request with an `Authorization` key (registered API callers).
2. Never a named AI bot (those go to the first counter), and never a User-Agent token from `heuristic.not_agents` in
   `policy/ai-bots.json`: classic search engines (Googlebot, Bingbot, YandexBot, Baiduspider, DuckDuckBot, …), link
   previews (facebookexternalhit, Slackbot, Discordbot, …), SEO crawlers (AhrefsBot, SemrushBot, …) and uptime / monitor /
   heartbeat checks (UptimeRobot, Pingdom, Better Stack, our own CommonworldTrust checker, any UA containing `uptime`, `monitor`, `heartbeat`, `healthcheck`).
3. Not a browser: **no `Sec-Fetch-*` header and no `Cookie`**. Every current browser sends `Sec-Fetch-*` on navigation
   and subresource requests, so this is the conservative gate.
4. Then it counts if **one** of these holds:
   - the User-Agent contains a generic HTTP-client token from `heuristic.http_clients` (curl, wget, python-requests,
     python-httpx, aiohttp, python-urllib, node-fetch, `node`, undici, axios, Go-http-client, okhttp, Java-http-client,
     libwww-perl, HTTPie, Postman, Deno, Bun) → class `generic-http-client`, family = that client's name;
   - no `Accept-Language` header → class `unnamed-agent`;
   - a request for `/llms.txt`, `/llms-full.txt`, any `*.md` path, or `Accept: text/markdown` → class `unnamed-agent`.

Row: | day (UTC) | class | family (from our list, `''` if none) | path (no query, ≤ 200 chars) | status | count |.
No IP, no User-Agent, no query string. Same write budget (shared with the first counter) and same 400-day retention.

What it can get wrong: a person's own script or an unknown monitor lands here; an agent that sends full browser headers
does not. Read it as "non-browser traffic, probably programs", never as a list of identities.

Verify by hand: `curl -s -A 'GPTBot/1.2' https://staging.commonworld.one/llms.txt` from any machine shows up as GPTBot
with `not_verified` (Cloudflare knows it is not OpenAI). `curl -s https://staging.commonworld.one/llms.txt` counts as `generic-http-client` / `curl`; the same
request with `-H 'Sec-Fetch-Mode: navigate'` (what a browser sends) does not.

## Cost and guards

- Write after the response (`ctx.waitUntil`), so it never slows a page.
- The verdict costs nothing extra: it is read from `request.cf` in the same request, no API call, same single upsert.
- One D1 upsert per AI-bot or unnamed-agent request (browsers never write); at most 600 writes per minute per Worker isolate (the rest are skipped), so a flood
  of fake bot User-Agents cannot run up D1 writes without limit.
- Rows older than 400 days are deleted by the nightly cron (`17 3 * * *`).

## Read it

    curl -s -H "Authorization: Bearer $ADMIN_KEY" "https://staging.commonworld.one/v1/admin/ai-bots?days=30" | jq

Query: `days` 1–400 (default 30, today included), `bot` = one name from the list, `verified` = `verified` |
`not_verified` | `unknown`, `limit` 1–500 rows of `top_paths` (default 100). Answer: `total_hits`, `verified_hits`,
`not_verified_hits`, `unknown_hits`, `bots` (per bot: operator, purpose, `cloudflare_radar`, hits = claimed visits,
`verified_hits` / `not_verified_hits` / `unknown_hits`, `categories` with Cloudflare's labels, distinct paths), `by_day`
(same split per day and bot), `top_paths` (bot, verified, path, status, hits), and `unnamed_agents` (label, rule, `total_hits`, `classes`, `by_day`, `top_paths`;
not filtered by `bot`). Admin key only.

## Sources for the list

Every entry in `policy/ai-bots.json` has `info` (the source URL) and `evidence`. `operator docs` = the operator publishes
the token. Entries added 2026-10-18:

| Name | Source | Evidence |
|---|---|---|
| Google-Agent, Google-GeminiNotebook | https://developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers | operator docs |
| KimiBot, Kimi-SearchBot, Kimi-User | https://www.kimi.com/policies/kimi-crawlers | operator docs |
| Manus-User | https://manus.im/help/Manus-user (+ Cloudflare Radar "Manus Bot", Matomo Device Detector) | operator page names it; UA token observed |
| ImagesiftBot | https://imagesift.com/about | operator docs |
| Bravebot | https://radar.cloudflare.com/bots/directory/bravebot | Cloudflare verified bot; Brave says it often crawls with a generic UA |
| TikTokSpider | https://udger.com/resources/ua-list/bot-detail?bot=TikTokSpider | observed only (UA names ttspider-feedback@tiktok.com) |
| Timpibot | https://udger.com/resources/ua-list/bot-detail?bot=Timpibot | observed only (UA links timpi.io/crawler, page gone) |

Checked and **not** added (no operator page, no reliable observed token): xAI/Grok (GrokBot, xAI-SearchBot, xAI-Grok
appear only in third-party lists; xAI publishes none), Alibaba/Qwen (QwenBot), DeepSeek (DeepSeekBot), OpenAI "ChatGPT
agent" (signs requests with Web Bot Auth, no own UA token on https://platform.openai.com/docs/bots), `GoogleAgent-*`
(Google publishes only `Google-Agent`). Visits from these, if they look like programs, show up in the second counter.

## Change the list

Edit `policy/ai-bots.json` (put a more specific token before a shorter one it contains), bump `version`, run
`npm test` (`test/ai-bots.test.ts` checks unique names/tokens, no shadowing, real sample User-Agents, and that every AI
agent named in robots.txt is in the list).
