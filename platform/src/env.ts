export interface Env {
  DB: D1Database;
  /** R2 bucket for daily D1 backups + restore checks (src/backup.ts): one bucket per environment, keys prefixed per environment. */
  BACKUPS?: R2Bucket;
  /** Name of the bucket bound as BACKUPS (wrangler.toml vars). src/backup.ts refuses to run unless it matches ENVIRONMENT (BACKUP_TARGETS). */
  BACKUPS_BUCKET?: string;
  /** Secret used to HMAC API keys and IPs. Set with `wrangler secret put KEY_PEPPER` (min 32 chars). */
  KEY_PEPPER: string;
  /** How long settings are cached inside one Worker isolate, in ms. Default 5000. */
  SETTINGS_CACHE_MS?: string;
  ENVIRONMENT?: string;
  /** "0" turns off the Workers Cache API layer for anonymous leaderboard/catalog reads (tests). Default on. */
  PUBLIC_EDGE_CACHE?: string;
  /** Canonical origin for SSR pages (canonical, og:url, sitemap), e.g. https://commonworld.one. Default: the request origin. */
  SITE_ORIGIN?: string;
  /** "1" marks every SSR page noindex,nofollow and robots.txt disallows all (closed staging). */
  PAGES_NOINDEX?: string;
  /** Cloudflare Web Analytics site token (cookieless beacon). Unset = no beacon tag and no cloudflareinsights.com in the CSP. */
  CF_BEACON_TOKEN?: string;
  /** Cloudflare Pages origin of the Atlas (e.g. https://commonworld.pages.dev). Set = the Worker proxies the Atlas paths there (src/atlas-proxy.ts). */
  ATLAS_ORIGIN?: string;
  /** "assets" = serve the Atlas from this Worker's Static Assets (option A3, src/atlas-assets.ts); wins over ATLAS_ORIGIN. */
  ATLAS_SOURCE?: string;
  /** Static Assets binding (wrangler.toml [assets]): the Atlas build in production/staging, a small fixture locally. */
  ASSETS?: Fetcher;
  /** Google Analytics 4 measurement id (e.g. G-XXXXXXX). Unset = no consent banner, no GA, no Google domains in the CSP. GA loads only after "Accept". */
  GA4_ID?: string;
  /** Own domains for the hourly trust check (src/trust.ts), comma separated. Default: commonworld.one, www.commonworld.one, staging.commonworld.one. */
  TRUST_DOMAINS?: string;
  /** "1" = link checks at publish answer no_data without network (src/link-check.ts). Honoured only when ENVIRONMENT is "local" (tests, wrangler dev). */
  LINK_CHECK_OFFLINE?: string;
  /** MCP (/mcp, src/mcp/server.ts): comma-separated browser origins allowed besides the site's own; unset or "*" = any well-formed http(s) origin (keys only, no cookies). */
  MCP_ALLOWED_ORIGINS?: string;
  /** "1" = in-memory rate limiter double instead of the RL_<tier> Rate Limiting bindings (tests). */
  RATE_LIMIT_DOUBLE?: string;
  /** Rate Limiting bindings, one per tier of RATE_TIERS (src/ratelimit.ts), configured in wrangler.toml `ratelimits`. */
  [binding: `RL_${number}`]: unknown;
}
