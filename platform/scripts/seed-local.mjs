#!/usr/bin/env node
// Cross-platform runner for local sample-data seed (Issue #151).
// Works portably across Windows (cmd.exe / PowerShell), macOS, and Linux without shell-specific mkdir or python3 assumptions.
// 1. Detects an available Python 3.10+ launcher (checks $PYTHON, python3, python, py).
// 2. Safely creates .local directory via fs.mkdirSync(..., { recursive: true }).
// 3. Runs scripts/seed_from_mockups.py, validating exit status before touching .local/seed.sql.
// 4. Executes wrangler d1 execute commonworld-dev --local --file .local/seed.sql.

import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const platformDir = path.resolve(__dirname, '..');
const localDir = path.join(platformDir, '.local');
const seedSqlPath = path.join(localDir, 'seed.sql');
const generatorScript = path.join(platformDir, 'scripts', 'seed_from_mockups.py');

function findPython() {
  const isWindows = process.platform === 'win32';
  const candidates = [
    process.env.PYTHON,
    ...(isWindows ? ['python', 'py', 'python3'] : ['python3', 'python'])
  ].filter(Boolean);

  for (const cmd of candidates) {
    try {
      const check = spawnSync(cmd, ['-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'], {
        stdio: 'ignore',
        shell: isWindows
      });
      if (check.status === 0) {
        return cmd;
      }
    } catch {
      // Ignore and continue checking next candidate
    }
  }
  return null;
}

const pythonBin = findPython();
if (!pythonBin) {
  console.error('Error: No Python 3.10+ interpreter found (tried python3, python, py).');
  console.error('Please ensure Python 3 is installed and added to PATH, or specify its location via the PYTHON environment variable.');
  process.exit(1);
}

// Generate the SQL content
console.log(`[seed:local] Generating seed SQL using ${pythonBin}...`);
const genResult = spawnSync(pythonBin, [generatorScript], {
  cwd: platformDir,
  encoding: 'utf-8',
  maxBuffer: 50 * 1024 * 1024,
  shell: process.platform === 'win32'
});

if (genResult.status !== 0) {
  console.error(`[seed:local] Python generator failed with exit code ${genResult.status}:`);
  if (genResult.stderr) console.error(genResult.stderr);
  process.exit(genResult.status ?? 1);
}

// Write the output file only after successful generation
mkdirSync(localDir, { recursive: true });
writeFileSync(seedSqlPath, genResult.stdout, 'utf-8');
console.log(`[seed:local] Written ${genResult.stdout.length} bytes to ${path.relative(platformDir, seedSqlPath)}`);

// Execute Wrangler
console.log('[seed:local] Executing SQL via Wrangler D1...');
const wranglerCmd = process.platform === 'win32' ? 'wrangler.cmd' : 'wrangler';
const wranglerArgs = ['d1', 'execute', 'commonworld-dev', '--local', '--file', seedSqlPath];

let wranglerResult = spawnSync(wranglerCmd, wranglerArgs, {
  cwd: platformDir,
  stdio: 'inherit',
  shell: process.platform === 'win32'
});

// Fallback to npx --yes wrangler if wrangler binary is not directly in PATH
if (wranglerResult.error && wranglerResult.error.code === 'ENOENT') {
  const npxCmd = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  wranglerResult = spawnSync(npxCmd, ['--yes', 'wrangler', ...wranglerArgs], {
    cwd: platformDir,
    stdio: 'inherit',
    shell: process.platform === 'win32'
  });
}

process.exit(wranglerResult.status ?? 0);
