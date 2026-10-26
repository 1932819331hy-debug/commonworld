#!/usr/bin/env node
// Cross-platform runner for local sample-data seed (Issue #151).
// Works portably across Windows (cmd.exe / PowerShell), macOS, and Linux without shell-specific mkdir or python3 assumptions.
// 1. Detects an available Python 3.10+ interpreter (checks $PYTHON, then python3/python, or python/py -3/python3 on Windows).
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

// Python is spawned WITHOUT a shell on every platform: python.exe and py.exe are real executables, and with
// `shell: true` Node joins the arguments unquoted, so cmd.exe would split the `-c` program and read `>=` as a
// redirect (every candidate would fail the version check). No shell also keeps a $PYTHON path with spaces intact.
// Each candidate is [command, ...leading args]; `py -3` asks the Windows launcher for a Python 3.
const VERSION_CHECK = 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)';

function findPython() {
  const isWindows = process.platform === 'win32';
  const candidates = [
    ...(process.env.PYTHON ? [[process.env.PYTHON]] : []),
    ...(isWindows ? [['python'], ['py', '-3'], ['python3']] : [['python3'], ['python']])
  ];

  for (const [cmd, ...args] of candidates) {
    const check = spawnSync(cmd, [...args, '-c', VERSION_CHECK], { stdio: 'ignore' });
    if (!check.error && check.status === 0) {
      return { cmd, args };
    }
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error('Error: No Python 3.10+ interpreter found (tried $PYTHON, python3, python, py -3).');
  console.error('Please ensure Python 3 is installed and added to PATH, or specify its location via the PYTHON environment variable.');
  process.exit(1);
}
const pythonLabel = [python.cmd, ...python.args].join(' ');

// Generate the SQL content. Paths are relative to platform/ (the cwd), exactly as in the old npm script.
// PYTHONIOENCODING=utf-8: the SQL contains non-ASCII text, and Python on Windows would otherwise encode a piped
// stdout in the ANSI code page. stdout is kept as raw bytes and written unchanged.
console.log(`[seed:local] Generating seed SQL using ${pythonLabel}...`);
const genResult = spawnSync(python.cmd, [...python.args, 'scripts/seed_from_mockups.py'], {
  cwd: platformDir,
  env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  stdio: ['ignore', 'pipe', 'inherit'],
  maxBuffer: 64 * 1024 * 1024
});

if (genResult.error || genResult.status !== 0) {
  const why = genResult.error ? genResult.error.message : genResult.signal ? `signal ${genResult.signal}` : `exit code ${genResult.status}`;
  console.error(`[seed:local] Python generator failed (${why}); .local/seed.sql was not written.`);
  process.exit(genResult.status || 1);
}

// Write the output file only after successful generation
mkdirSync(localDir, { recursive: true });
writeFileSync(seedSqlPath, genResult.stdout);
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
