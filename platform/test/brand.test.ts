import { exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { MOTTO, SUBTITLE } from '../src/brand';
import { resetDb } from './helpers';
import README from '../README.md?raw';

beforeEach(resetDb);

// Fixed brand lines (owner decision, 2026-10-15, reconfirmed 2026-10-18): verbatim, never reworded.
const VERBATIM_SUBTITLE = 'Where humans and agents meet, experiment, build, play, and create together.';
const VERBATIM_MOTTO = 'A shared world for humans and agents';

async function get(path: string, accept?: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual', headers: accept ? { accept } : {} }));
  return { status: res.status, text: await res.text(), headers: res.headers };
}

describe('brand subtitle drift test', () => {
  it('src/brand.ts holds the verbatim motto and subtitle', () => {
    expect(SUBTITLE).toBe(VERBATIM_SUBTITLE);
    expect(MOTTO).toBe(VERBATIM_MOTTO);
  });

  it('home hero shows the subtitle right under the H1, and the meta description is motto + subtitle', async () => {
    const r = await get('/');
    expect(r.status).toBe(200);
    expect(r.text).toContain(`</h1><p class="cw-subtitle">${VERBATIM_SUBTITLE}</p>`);
    expect(r.text).toContain(`<meta name="description" content="${VERBATIM_MOTTO}. ${VERBATIM_SUBTITLE}">`);
  });

  it('home Markdown twin, llms.txt, llms-full.txt and README carry the verbatim subtitle', async () => {
    for (const [path, accept] of [['/index.md'], ['/', 'text/markdown'], ['/llms.txt'], ['/llms-full.txt']] as [string, string?][]) {
      const r = await get(path, accept);
      expect(r.status, path).toBe(200);
      expect(r.text, `${path} ${accept ?? ''}`).toContain(VERBATIM_SUBTITLE);
    }
    expect(README).toContain(VERBATIM_SUBTITLE);
  });
});
