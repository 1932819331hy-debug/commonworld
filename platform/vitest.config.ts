import fs from 'node:fs';
import path from 'node:path';
import { cloudflareTest, readD1Migrations } from '@cloudflare/vitest-plugin';
import { defineConfig } from 'vitest/config';

/**
 * Private-term denylist for the agent-docs tests, kept OUT of the repo: CW_PRIVATE_TERMS (comma/newline separated)
 * plus the git-ignored file platform/.private-terms (one term per line, # comments). The test always adds synthetic markers.
 */
function privateTerms(): string {
  const file = path.join(import.meta.dirname, '.private-terms');
  const fromFile = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
  return [process.env.CW_PRIVATE_TERMS ?? '', fromFile.replace(/^\s*#.*$/gm, '')].join('\n');
}

/** File list of a real Atlas build, when one is built in this repository (atlas/site/dist at the repo root, or $CW_PUBLIC_DIR): test/atlas-assets.test.ts checks the routing split against it. */
function atlasDistFiles(): string {
  const dir = path.resolve(process.env.CW_PUBLIC_DIR ?? path.join(import.meta.dirname, '..'), 'atlas', 'site', 'dist');
  if (!fs.existsSync(path.join(dir, 'atlas', 'index.html'))) return '';
  const out: string[] = [];
  const walk = (d: string) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else out.push('/' + path.relative(dir, p).split(path.sep).join('/')); } };
  walk(dir);
  return JSON.stringify(out);
}

export default defineConfig(async () => {
  const migrations = await readD1Migrations(path.join(import.meta.dirname, 'migrations'));
  return {
    plugins: [
      cloudflareTest({
        wrangler: { configPath: './wrangler.toml' },
        miniflare: {
          // empty scratch D1 for the backup -> restore roundtrip (test/backup.test.ts); DB and BACKUPS come from wrangler.toml
          d1Databases: { RESTORE_DB: 'restore-scratch' },
          bindings: {
            TEST_MIGRATIONS: migrations,
            // Test-only pepper; real values live in Wrangler secrets / .dev.vars.
            KEY_PEPPER: 'test-only-pepper-0123456789abcdefghijklmnop',
            SETTINGS_CACHE_MS: '0',
            // Edge cache off by default in tests so data written by one test is visible to the next;
            // test/cache.test.ts turns it on explicitly.
            PUBLIC_EDGE_CACHE: '0',
            CW_PRIVATE_TERMS: privateTerms(),
            // wrangler.toml as text (test/atlas-assets.test.ts checks run_worker_first in every environment)
            TEST_WRANGLER_TOML: fs.readFileSync(path.join(import.meta.dirname, 'wrangler.toml'), 'utf8'),
            TEST_ATLAS_DIST_FILES: atlasDistFiles(),
            // in-memory double for the RL_<tier> Rate Limiting bindings (src/ratelimit.ts)
            RATE_LIMIT_DOUBLE: '1',
            // link checks at publish answer no_data without network (src/link-check.ts); test/ui-writes.test.ts turns it off
            LINK_CHECK_OFFLINE: '1',
          },
        },
      }),
    ],
    test: {
      // Playwright e2e specs (e2e/) run with `npm run test:e2e`, never under vitest
      include: ['test/**/*.test.ts'],
      setupFiles: ['./test/apply-migrations.ts'],
    },
  };
});
