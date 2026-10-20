import { env } from 'cloudflare:workers';
import { describe, expect, it } from 'vitest';
import { canonicalHostRedirect } from '../src/index';

describe('www -> apex redirect (launch cutover 2026-10-20)', () => {
  it('sends www to the apex with path and query, 301', () => {
    const r = canonicalHostRedirect(new Request('https://www.commonworld.one/atlas/platforms/1f916/?ref=x'))!;
    expect(r.status).toBe(301);
    expect(r.headers.get('location')).toBe('https://commonworld.one/atlas/platforms/1f916/?ref=x');
  });
  it('leaves the apex and staging alone', () => {
    expect(canonicalHostRedirect(new Request('https://commonworld.one/'))).toBeNull();
    expect(canonicalHostRedirect(new Request('https://staging.commonworld.one/health'))).toBeNull();
  });
  it('leaves any other www host alone (only the production www domain is redirected)', () => {
    expect(canonicalHostRedirect(new Request('https://www.example.com/x?y=1'))).toBeNull();
    expect(canonicalHostRedirect(new Request('https://www.staging.commonworld.one/'))).toBeNull();
  });
  it('production routes the apex and www as custom domains', () => {
    const toml: string = (env as any).TEST_WRANGLER_TOML;
    const prod = toml.slice(toml.indexOf('[env.production]'));
    expect(prod).toContain('{ pattern = "commonworld.one", custom_domain = true }');
    expect(prod).toContain('{ pattern = "www.commonworld.one", custom_domain = true }');
  });
});
