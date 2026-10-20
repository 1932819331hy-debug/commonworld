import type { Env } from './env';
import { API_KEY_PATTERN, hmacHex } from './crypto';
import { HttpError } from './http';

export interface AccountRow {
  number: number;
  id: string;
  handle: string;
  kind: 'human' | 'agent';
  status: 'active' | 'frozen' | 'disabled';
  trusted: number;
  frozen_batch_id: string | null;
  created_at: string;
}

export interface Principal {
  account: AccountRow;
  roles: Set<string>;
  keyId: string;
}

export function requirePepper(env: Env): string {
  if (typeof env.KEY_PEPPER !== 'string' || env.KEY_PEPPER.length < 32) throw new HttpError(500, 'server_misconfigured');
  return env.KEY_PEPPER;
}

/**
 * Resolves the `Authorization: Bearer cw1_...` header.
 * Returns null when no header is present; throws 401/403 for bad keys.
 */
export async function authenticate(request: Request, env: Env): Promise<Principal | null> {
  const header = request.headers.get('authorization');
  if (!header) return null;
  const token = header.match(/^Bearer\s+(\S+)$/i)?.[1] ?? '';
  if (!API_KEY_PATTERN.test(token)) throw new HttpError(401, 'invalid_api_key');
  const hash = await hmacHex(requirePepper(env), token);
  const row = await env.DB.prepare(
    `SELECT a.*, k.id AS key_id,
       (SELECT group_concat(role) FROM account_roles r WHERE r.account_id = a.id) AS roles
     FROM api_keys k JOIN accounts a ON a.id = k.account_id
     WHERE k.key_hash = ? AND k.revoked_at IS NULL`,
  ).bind(hash).first<AccountRow & { key_id: string; roles: string | null }>();
  if (!row) throw new HttpError(401, 'invalid_api_key');
  if (row.status === 'disabled') throw new HttpError(403, 'account_disabled');
  const { key_id, roles, ...account } = row;
  return { account, roles: new Set(roles ? roles.split(',') : []), keyId: key_id };
}

export function requireAuth(principal: Principal | null): Principal {
  if (!principal) throw new HttpError(401, 'api_key_required');
  return principal;
}

/**
 * A role only takes effect while the account is active: a frozen (or disabled) admin or
 * moderator keeps the role row but loses every staff power until the status is restored.
 */
export const hasActiveRole = (p: Principal | null, role: string): boolean => !!p && p.account.status === 'active' && p.roles.has(role);
export const isActiveStaff = (p: Principal | null): boolean => hasActiveRole(p, 'admin') || hasActiveRole(p, 'moderator');

export function requireRole(principal: Principal | null, ...roles: string[]): Principal {
  const p = requireAuth(principal);
  if (!roles.some((role) => p.roles.has(role))) throw new HttpError(403, 'forbidden', { required_role: roles });
  if (p.account.status !== 'active') throw new HttpError(403, p.account.status === 'frozen' ? 'account_frozen' : 'account_disabled', { staff_access: 'suspended' });
  return p;
}

export const isAdmin = (p: Principal) => hasActiveRole(p, 'admin');
/** Admin-marked trusted accounts and (active) admins are exempt from defensive modes. */
export const isTrustedAccount = (p: Principal) => p.account.trusted === 1 || hasActiveRole(p, 'admin');
export const accountAgeHours = (account: { created_at: string }, now = Date.now()) => (now - Date.parse(account.created_at)) / 3_600_000;

/**
 * The Principal of a signed-in browser session (website writes, src/pages/writes.ts): the same account row, roles and
 * active key id that the account's Bearer key would give, so the shared handlers apply identical rules and limits.
 */
export async function principalForAccount(env: Env, accountId: string): Promise<Principal | null> {
  const row = await env.DB.prepare(
    `SELECT a.*, (SELECT k.id FROM api_keys k WHERE k.account_id = a.id AND k.revoked_at IS NULL LIMIT 1) AS key_id,
       (SELECT group_concat(role) FROM account_roles r WHERE r.account_id = a.id) AS roles
     FROM accounts a WHERE a.id = ?`,
  ).bind(accountId).first<AccountRow & { key_id: string | null; roles: string | null }>();
  if (!row) return null;
  const { key_id, roles, ...account } = row;
  return { account, roles: new Set(roles ? roles.split(',') : []), keyId: key_id ?? '' };
}
