/**
 * Hidden-content package (owner-approved 2026-10-16): duck mascot with a 7-click easter egg, caution tape,
 * epitaph with the real upvote count and one-liners for light rules (1, 2, 5, 6); serious rules (3, 4, 7) keep
 * the plain stub with a silent duck. No title/author/text leaks, no inline style/script, CSP unchanged.
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { ASSETS, BOOT_SCRIPT } from '../src/pages/assets.gen';
import { FUNNY_RULES, RULE_QUIPS, epitaph } from '../src/pages/duck';
import { contentSecurityPolicy } from '../src/pages/router';
import { RULES } from '../src/rules';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(async () => {
  await resetDb();
  await setSetting('limits.daily.post', 100);
  await setSetting('limits.daily.comment', 100);
});

async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}

const TITLE = 'Zebra quokka title marker';
const BODY = 'Xylophone body marker text';

/** A post with `ups` upvotes, hidden under `rule`. */
async function hiddenPost(rule: number, ups: number) {
  const admin = await makeAdmin();
  const author = await register('stubauthor', 'agent', 24 * 10);
  const p = (await post(author.key, TITLE, { body: BODY })).body;
  for (let i = 0; i < ups; i++) {
    const v = await register('voter', i % 2 ? 'human' : 'agent', 24 * 10);
    expect((await api(`/v1/posts/${p.number}/upvote`, { key: v.key, method: 'POST' })).status).toBeLessThan(300);
  }
  const hide = await api(`/v1/admin/content/post/${p.number}/hide`, { key: admin.key, body: { rule, note: `Public note for rule ${rule}.`, ...(rule === 7 ? { reason: 'flagged by a safety source', evidence_url: 'https://example.org/report/7' } : {}) } });
  expect(hide.status).toBe(200);
  return { admin, author, p, hide, r: await page(`/posts/${p.number}`) };
}

const noLeaks = (html: string, author: string) => {
  expect(html).not.toContain(TITLE);
  expect(html).not.toContain(BODY);
  expect(html).not.toContain(author);
};

describe('hidden post: light rules get the joke', () => {
  it('epitaph wording: plural, singular, zero', () => {
    expect(epitaph(9)).toBe('It had 9 upvotes and a dream.');
    expect(epitaph(1)).toBe('It had 1 upvote and a dream.');
    expect(epitaph(0)).toBe('It had 0 upvotes and a dream.');
  });

  it('only rules 1, 2, 5, 6 have one-liners, and every rule number exists', () => {
    expect([...FUNNY_RULES].sort()).toEqual([1, 2, 5, 6]);
    expect(Object.keys(RULE_QUIPS).map(Number).sort()).toEqual([1, 2, 5, 6]);
    for (const n of FUNNY_RULES) expect(RULES.some((r) => r.number === n)).toBe(true);
  });

  for (const [rule, ups, line] of [[1, 9, 'It had 9 upvotes and a dream.'], [2, 1, 'It had 1 upvote and a dream.'], [5, 0, 'It had 0 upvotes and a dream.'], [6, 2, 'It had 2 upvotes and a dream.']] as const) {
    it(`rule ${rule}: tape, playful duck, one-liner, epitaph with the real count (${ups}), all public facts kept`, async () => {
      const { r, admin, author, hide, p } = await hiddenPost(rule, ups);
      expect(r.status).toBe(200);
      expect(r.headers.get('x-commonworld-status')).toBe('hidden');
      expect(r.html).toContain('<meta name="robots" content="noindex,follow">');
      expect(r.html).toContain('hidden-stub-funny');
      expect(r.html).toContain('<div class="cw-tape" aria-hidden="true">');
      expect(r.html).toContain('data-quack="7" aria-label="Commonworld duck (click it)"');
      expect(r.html).toContain('<span class="duck-quack" role="status" aria-live="polite" hidden>Quack.</span>');
      expect(r.html).toContain(`<p class="stub-quip">${RULE_QUIPS[rule].replace(/'/g, '&#39;')}</p>`);
      expect(r.html).toContain(`<p class="stub-epitaph">${line}</p>`);
      // existing facts
      expect(r.html).toContain('This post is hidden');
      expect(r.html).toContain(`<span class="chip">post-${p.number}</span>`);
      expect(r.html).toContain(`rule ${rule}</a> ${RULES.find((x) => x.number === rule)!.text.replace(/'/g, '&#39;')}`);
      expect(r.html).toContain(`Public note for rule ${rule}.`);
      expect(r.html).toContain(`<a href="/c/${admin.handle}">@${admin.handle}</a>`);
      expect(hide.body.log_url).toMatch(/^\/moderation(\?[^#]*)?#mod-\d+$/);
      expect(r.html).toContain(`href="${hide.body.log_url}"`);
      expect(r.html).toContain('<dt>Appeal</dt><dd>by email: <a href="mailto:nerd27dk@commonworld.one">nerd27dk@commonworld.one</a>, reply within 14 days</dd>');
      noLeaks(r.html, author.handle);
    });
  }
});

describe('hidden post: serious rules stay serious', () => {
  for (const rule of [3, 4, 7]) {
    it(`rule ${rule}: no tape, no joke, no epitaph, silent duck; facts kept`, async () => {
      const { r, admin, author, hide } = await hiddenPost(rule, 4);
      expect(r.headers.get('x-commonworld-status')).toBe('hidden');
      expect(r.html).toContain('hidden-stub-serious');
      expect(r.html).not.toContain('cw-tape');
      expect(r.html).not.toContain('data-quack');
      expect(r.html).not.toContain('duck-quack');
      expect(r.html).not.toContain('stub-quip');
      expect(r.html).not.toContain('stub-epitaph');
      expect(r.html).not.toContain('and a dream');
      for (const q of Object.values(RULE_QUIPS)) expect(r.html).not.toContain(q.replace(/'/g, '&#39;'));
      expect(r.html).toContain('<span class="duck duck-lg duck-quiet" role="img" aria-label="Commonworld duck">');
      expect(r.html).toContain(`rule ${rule}</a>`);
      expect(r.html).toContain(`<a href="/c/${admin.handle}">@${admin.handle}</a>`);
      expect(r.html).toContain(`href="${hide.body.log_url}"`);
      expect(r.html).toContain('<dt>Appeal</dt><dd>by email: <a href="mailto:nerd27dk@commonworld.one">nerd27dk@commonworld.one</a>, reply within 14 days</dd>');
      noLeaks(r.html, author.handle);
    });
  }

  it('a hide with no rule recorded is treated as serious', async () => {
    const a = await register('old', 'agent');
    const p = (await post(a.key, TITLE, { body: BODY })).body;
    await env.DB.prepare("UPDATE posts SET status = 'hidden' WHERE number = ?").bind(p.number).run();
    await env.DB.prepare("INSERT INTO events (type, object_type, object_number, created_at) VALUES ('content.hidden', 'post', ?, ?)").bind(p.number, new Date().toISOString()).run();
    const r = await page(`/posts/${p.number}`);
    expect(r.html).toContain('hidden-stub-serious');
    expect(r.html).not.toContain('cw-tape');
    noLeaks(r.html, a.handle);
  });
});

describe('hidden comment notice: lighter version', () => {
  it('light rule: small silent duck + one-liner, no tape/epitaph; serious rule: plain', async () => {
    const admin = await makeAdmin();
    const a = await register('cm', 'agent', 24 * 10);
    const p = (await post(a.key, 'Visible post')).body;
    const c1 = (await api(`/v1/posts/${p.number}/comments`, { key: a.key, body: { body: 'Spammy comment marker' } })).body;
    const c2 = (await api(`/v1/posts/${p.number}/comments`, { key: a.key, body: { body: 'Threat comment marker' } })).body;
    await api(`/v1/admin/content/comment/${c1.number}/hide`, { key: admin.key, body: { rule: 2, note: 'Flood.' } });
    await api(`/v1/admin/content/comment/${c2.number}/hide`, { key: admin.key, body: { rule: 3, note: 'Threat.' } });
    const r = await page(`/posts/${p.number}`);
    expect(r.headers.get('x-commonworld-status')).toBeNull();
    const stub = (n: number) => { const i = r.html.indexOf(`id="comment-${n}"`); return r.html.slice(i, r.html.indexOf('</dl>', i)); };
    expect(r.html).toContain(`<div class="cmt cmt-hidden cmt-hidden-funny" id="comment-${c1.number}">`);
    expect(r.html).toContain(`<div class="cmt cmt-hidden" id="comment-${c2.number}">`);
    expect(stub(c1.number)).toContain('duck duck-sm duck-quiet');
    expect(stub(c1.number)).toContain(RULE_QUIPS[2]);
    expect(stub(c2.number)).not.toContain('duck');
    expect(stub(c2.number)).not.toContain('stub-quip');
    expect(r.html).not.toContain('cw-tape');
    expect(r.html).not.toContain('and a dream');
    expect(r.html).not.toContain('data-quack');
    expect(r.html).not.toContain('Spammy comment marker');
    expect(r.html).not.toContain('Threat comment marker');
  });
});

describe('strict CSP holds', () => {
  it('no inline style or script on the hidden pages; same CSP as any page; egg lives in site.js', async () => {
    const { r } = await hiddenPost(1, 3);
    const serious = await hiddenPost(7, 0);
    for (const html of [r.html, serious.r.html]) {
      expect(html).not.toMatch(/\sstyle=/i);
      expect(html).not.toMatch(/<style[\s>]/i);
      expect(html).not.toMatch(/\son[a-z]+=/i);
      const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)(?![^>]*application\/ld\+json)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
      expect(inline).toEqual([BOOT_SCRIPT]);
    }
    const csp = r.headers.get('content-security-policy')!;
    const noNonce = (x: string) => x.replace(/'nonce-[^']+'/, "'nonce-*'");
    expect(noNonce(csp)).toBe(noNonce(contentSecurityPolicy(env as any)));
    expect(csp).toContain("style-src 'self'");
    expect(csp).not.toContain('unsafe-inline');
    expect(noNonce(csp)).toBe(noNonce((await page('/')).headers.get('content-security-policy')!));
    expect(ASSETS['site.js'].text).toContain("document.querySelectorAll('[data-quack]')");
    expect(ASSETS['ssr.css'].text).toContain('.cw-tape');
  });
});
