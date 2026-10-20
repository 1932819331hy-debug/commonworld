/**
 * Trust/safety capabilities, read straight from policy/roles.json so the written policy and the server cannot drift.
 * A capability works only while the account is active (same rule as roles: a frozen staff account gets 403).
 */
import rolesJson from '../policy/roles.json';
import { requireRole, type Principal } from './auth';
import { HttpError } from './http';

export type Capability = 'safety:hide' | 'safety:restore' | 'safety:review' | 'accounts:list' | 'accounts:recover';

const CAPS = (rolesJson as { capabilities: Record<Capability, { roles: string[] }> }).capabilities;

export const CAPABILITIES = Object.keys(CAPS) as Capability[];
export const rolesFor = (cap: Capability): string[] => CAPS[cap].roles;

export const hasCapability = (p: Principal | null, cap: Capability): boolean =>
  !!p && p.account.status === 'active' && rolesFor(cap).some((r) => p.roles.has(r));

/** 401 without a key, 403 forbidden (with the capability named) without a role that holds it, 403 frozen/disabled. */
export function requireCapability(principal: Principal | null, cap: Capability): Principal {
  try {
    return requireRole(principal, ...rolesFor(cap));
  } catch (e) {
    if (e instanceof HttpError && e.status === 403 && e.code === 'forbidden') e.extra = { ...e.extra, required_capability: cap };
    throw e;
  }
}
