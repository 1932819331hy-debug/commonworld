#!/usr/bin/env node
/** Commonworld trust engine CLI (Node 22.6+, runs the TypeScript directly; no install needed).
 *
 *   node trust/src/cli.ts example.com other.example            # JSON report to stdout
 *   node trust/src/cli.ts --domains-file hosts.txt --out r.json  # one domain per line
 *   node trust/src/cli.ts --sources google_safe_browsing,scamsniffer example.com
 *   node trust/src/cli.ts --list-sources
 *
 * Exit code: 0 = no domain flagged, 1 = at least one flagged (with --fail-on-flag), 2 = usage error or crash. */
import { readFileSync, writeFileSync } from 'node:fs';
import { checkDomains } from './engine.ts';
import { ALL_SOURCES, DEFAULT_SOURCES } from './sources/index.ts';

function main(argv: string[]): Promise<number> | number {
  const domains: string[] = [];
  let out = '', ids = '', failOnFlag = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--domains-file') domains.push(...readFileSync(argv[++i], 'utf8').split('\n').map((s) => s.trim()).filter((s) => s && !s.startsWith('#')));
    else if (a === '--out') out = argv[++i];
    else if (a === '--sources') ids = argv[++i];
    else if (a === '--fail-on-flag') failOnFlag = true;
    else if (a === '--list-sources') {
      for (const s of ALL_SOURCES) console.log(`${s.id}${DEFAULT_SOURCES.includes(s) ? '' : ' (off by default)'}\n  ${s.name}: ${s.covers}\n  ${s.url}\n  terms: ${s.terms}`);
      return 0;
    } else if (a.startsWith('--')) { console.error(`unknown option ${a}`); return 2; }
    else domains.push(a);
  }
  if (!domains.length) { console.error('no domains given (arguments or --domains-file)'); return 2; }
  let sources = DEFAULT_SOURCES;
  if (ids) {
    const want = ids.split(',').map((s) => s.trim()).filter(Boolean);
    const bad = want.filter((w) => !ALL_SOURCES.some((s) => s.id === w));
    if (bad.length) { console.error(`unknown source(s): ${bad.join(', ')}`); return 2; }
    sources = ALL_SOURCES.filter((s) => want.includes(s.id));
  }
  return checkDomains(domains, { sources }).then((r) => {
    const json = JSON.stringify(r, null, 1) + '\n';
    if (out) writeFileSync(out, json); else process.stdout.write(json);
    const s = r.summary;
    console.error(`trust: ${s.domains} domains, ${s.clean} clean, ${s.flagged} flagged, ${s.no_data} no data, ${s.source_errors} source errors`);
    for (const d of r.flagged) console.error(`FLAGGED ${d}: ${r.results[d].sources.filter((x) => x.verdict === 'flagged').map((x) => `${x.name}${x.detail ? ` (${x.detail})` : ''}`).join('; ')}`);
    return failOnFlag && r.flagged.length ? 1 : 0;
  });
}

Promise.resolve()
  .then(() => main(process.argv.slice(2)))
  .then((code) => { process.exitCode = code; }, (e) => { console.error(e); process.exitCode = 2; });
