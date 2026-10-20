/**
 * Browser sign-in by one-time link, and cookie sessions for the SSR pages.
 *
 *   POST /v1/auth/login-link (Bearer key) -> { url: <origin>/login?t=cwl_…, expires_at }
 *   GET  /login?t=…   confirm page ("Sign in as @handle?"); does NOT use the link (previewers and agents prefetch GETs)
 *   POST /login       uses the link once -> new session, Set-Cookie __Host-cw_session, 303 to /inbox
 *   POST /logout      deletes the current session, clears the cookie, 303 to /
 *
 * Link tokens and session values are stored only as HMAC-SHA256(KEY_PEPPER, value).
 * Sessions slide: they end after SESSION_DAYS without a visit. A visit renews expires_at (and the cookie Max-Age) at most
 * once per SESSION_TOUCH_MS, so most page views do no D1 write. No absolute cap (owner decision 2026-10-17).
 * Sessions are deleted on sign-out, key rotation (POST /v1/keys/rotate) and when the account is frozen or disabled;
 * a session whose account is not active is also refused (and deleted) on lookup.
 *
 * The cookie only signs in the SSR pages. The /v1 API ignores it and keeps Bearer keys only. The website write forms
 * (src/pages/writes.ts) are the only cookie-authenticated writes: each needs same-origin (assertSameOrigin) AND the
 * per-session CSRF token (csrfToken), on top of SameSite=Lax.
 */
import type { Env } from './env';
import type { AccountRow } from './auth';
import { requirePepper } from './auth';
import { hmacHex } from './crypto';
import { HttpError, readTextCapped } from './http';

/** `__Host-` prefix: browsers accept it only with Secure, Path=/ and no Domain, so no subdomain can set or shadow it. */
export const SESSION_COOKIE = '__Host-cw_session';
export const LINK_TTL_MS = 10 * 60_000;
export const SESSION_DAYS = 30;
export const SESSION_TTL_MS = SESSION_DAYS * 86_400_000;
/** A session is renewed (expires_at, last_seen_at, cookie) at most once per day. */
export const SESSION_TOUCH_MS = 86_400_000;
/** Login links one account may create per hour. */
export const LINKS_PER_HOUR = 10;

export const LINK_PATTERN = /^cwl_[A-Za-z0-9_-]{43}$/;
export const SESSION_PATTERN = /^cws_[A-Za-z0-9_-]{43}$/;

function random43(): string {
  let binary = '';
  for (const byte of crypto.getRandomValues(new Uint8Array(32))) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export const newLinkToken = (): string => `cwl_${random43()}`;
export const newSessionValue = (): string => `cws_${random43()}`;

const hash = (env: Env, value: string) => hmacHex(requirePepper(env), value);

// ---------------------------------------------------------------- links

export async function createLoginLink(env: Env, accountId: string, now = Date.now()): Promise<{ token: string; expires_at: string }> {
  const token = newLinkToken();
  const expiresAt = new Date(now + LINK_TTL_MS).toISOString();
  await env.DB.prepare('INSERT INTO login_links (token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)')
    .bind(await hash(env, token), accountId, new Date(now).toISOString(), expiresAt).run();
  return { token, expires_at: expiresAt };
}

export type LinkState =
  | { ok: true; account: AccountRow; expires_at: string }
  | { ok: false; reason: 'invalid' | 'expired' | 'used' | 'account_inactive' };

/** Read-only check for the GET confirm page: never marks the link used. */
export async function peekLoginLink(env: Env, token: string, now = Date.now()): Promise<LinkState> {
  if (!LINK_PATTERN.test(token)) return { ok: false, reason: 'invalid' };
  const row = await env.DB.prepare(
    `SELECT l.expires_at AS link_expires_at, l.used_at, a.* FROM login_links l JOIN accounts a ON a.id = l.account_id WHERE l.token_hash = ?`,
  ).bind(await hash(env, token)).first<AccountRow & { link_expires_at: string; used_at: string | null }>();
  if (!row) return { ok: false, reason: 'invalid' };
  if (row.used_at) return { ok: false, reason: 'used' };
  if (Date.parse(row.link_expires_at) <= now) return { ok: false, reason: 'expired' };
  const { link_expires_at, used_at: _used, ...account } = row;
  if (account.status !== 'active') return { ok: false, reason: 'account_inactive' };
  return { ok: true, account, expires_at: link_expires_at };
}

/**
 * Uses the link (atomic: one UPDATE … WHERE used_at IS NULL AND not expired) and opens a session.
 * Returns the plain session value for the cookie, or why it failed.
 */
export async function consumeLoginLink(env: Env, token: string, now = Date.now()):
  Promise<{ ok: true; account: AccountRow; session: string } | { ok: false; reason: 'invalid' | 'expired' | 'used' | 'account_inactive' }> {
  const state = await peekLoginLink(env, token, now);
  if (!state.ok) return state;
  const used = await env.DB.prepare('UPDATE login_links SET used_at = ? WHERE token_hash = ? AND used_at IS NULL AND expires_at > ? RETURNING account_id')
    .bind(new Date(now).toISOString(), await hash(env, token), new Date(now).toISOString()).first<{ account_id: string }>();
  if (!used) return { ok: false, reason: 'used' }; // lost a race with another POST
  const session = newSessionValue();
  const at = new Date(now).toISOString();
  await env.DB.prepare('INSERT INTO sessions (id, session_hash, account_id, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(`sess_${crypto.randomUUID()}`, await hash(env, session), used.account_id, at, at, new Date(now + SESSION_TTL_MS).toISOString()).run();
  return { ok: true, account: state.account, session };
}

// ---------------------------------------------------------------- sessions

export function readCookie(request: Request, name = SESSION_COOKIE): string | null {
  const header = request.headers.get('cookie');
  if (!header) return null;
  for (const part of header.split(';')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    if (part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

export const hasSessionCookie = (request: Request): boolean => readCookie(request) !== null;

export const sessionCookie = (value: string): string =>
  `${SESSION_COOKIE}=${value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${SESSION_DAYS * 86_400}`;
export const clearSessionCookie = (): string => `${SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`;

export interface Viewer { account: AccountRow; sessionId: string }

/**
 * Resolves the __Host-cw_session cookie. `setCookie` is set when the response must (re)send the cookie:
 * a renewed sliding session, or a clearing cookie for an unknown/expired/inactive session.
 */
export async function resolveSession(env: Env, request: Request, now = Date.now()): Promise<{ viewer: Viewer | null; setCookie: string | null }> {
  const value = readCookie(request);
  if (value === null) return { viewer: null, setCookie: null };
  if (!SESSION_PATTERN.test(value)) return { viewer: null, setCookie: clearSessionCookie() };
  const row = await env.DB.prepare(
    `SELECT s.id AS session_id, s.last_seen_at, s.expires_at AS session_expires_at, a.* FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.session_hash = ?`,
  ).bind(await hash(env, value)).first<AccountRow & { session_id: string; last_seen_at: string; session_expires_at: string }>();
  if (!row) return { viewer: null, setCookie: clearSessionCookie() };
  const { session_id, last_seen_at, session_expires_at, ...account } = row;
  if (Date.parse(session_expires_at) <= now || account.status !== 'active') {
    await env.DB.prepare('DELETE FROM sessions WHERE id = ?').bind(session_id).run();
    return { viewer: null, setCookie: clearSessionCookie() };
  }
  let setCookie: string | null = null;
  if (now - Date.parse(last_seen_at) >= SESSION_TOUCH_MS) {
    await env.DB.prepare('UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?')
      .bind(new Date(now).toISOString(), new Date(now + SESSION_TTL_MS).toISOString(), session_id).run();
    setCookie = sessionCookie(value);
  }
  return { viewer: { account, sessionId: session_id }, setCookie };
}

export async function revokeSession(env: Env, sessionId: string): Promise<void> {
  await env.DB.prepare('DELETE FROM sessions WHERE id = ?').bind(sessionId).run();
}

/** Statement for batches: deletes every session of one account (key rotation, freeze, disable). */
export const deleteAccountSessions = (db: D1Database, accountId: string): D1PreparedStatement =>
  db.prepare('DELETE FROM sessions WHERE account_id = ?').bind(accountId);

// ---------------------------------------------------------------- CSRF

/**
 * Cookie-authenticated POSTs (/login, /logout) must come from our own pages: Sec-Fetch-Site, when sent, must be
 * same-origin, and Origin, when sent, must equal the request origin (or SITE_ORIGIN). At least one of the two must be
 * present (every current browser sends Origin on a form POST); otherwise 403 csrf_rejected. `Origin: null` (sent by
 * Chrome from a no-referrer page) counts as absent only together with Sec-Fetch-Site: same-origin.
 */
export function assertSameOrigin(request: Request, env: Env): void {
  const url = new URL(request.url);
  const allowed = new Set([url.origin, (env.SITE_ORIGIN ?? '').replace(/\/+$/, '')].filter(Boolean));
  const site = request.headers.get('sec-fetch-site');
  let origin = request.headers.get('origin');
  // Chrome sends `Origin: null` on a form POST from a page with Referrer-Policy: no-referrer (our /login page).
  // Treat it as absent only when the browser itself vouches same-origin; otherwise a null Origin is rejected.
  if (origin === 'null') {
    if (site !== 'same-origin') throw new HttpError(403, 'csrf_rejected');
    origin = null;
  }
  if (site !== null && site !== 'same-origin') throw new HttpError(403, 'csrf_rejected');
  if (origin !== null && !allowed.has(origin)) throw new HttpError(403, 'csrf_rejected');
  if (site === null && origin === null) throw new HttpError(403, 'csrf_rejected');
}

/** Urlencoded form body, capped at `maxBytes` (default 4 KB: /login, /logout). */
export async function readForm(request: Request, maxBytes = 4096): Promise<URLSearchParams> {
  // Streams and counts bytes: 413 as soon as the body passes the cap, also without Content-Length (chunked).
  return new URLSearchParams(await readTextCapped(request, maxBytes));
}

/**
 * Per-session CSRF token for the website write forms (src/pages/writes.ts): HMAC-SHA256(KEY_PEPPER, "csrf:" + session
 * id). Stateless (nothing stored), different for every session, unknown to other sites, and it dies with the session.
 * Rendered as a hidden `_csrf` field only on signed-in (private, no-store) pages. Checked together with
 * assertSameOrigin and the SameSite=Lax cookie.
 */
export const csrfToken = (env: Env, sessionId: string): Promise<string> => hash(env, `csrf:${sessionId}`);

export async function csrfValid(env: Env, sessionId: string, given: string | null): Promise<boolean> {
  if (!given || !/^[0-9a-f]{64}$/.test(given)) return false;
  const want = await csrfToken(env, sessionId);
  let diff = 0;
  for (let i = 0; i < 64; i++) diff |= want.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}
