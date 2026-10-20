/**
 * Browser pass per viewport (phone 390x844, tablet 820x1180, desktop 1440x900): each public page renders, has a title,
 * an h1 and a canonical, logs no console errors (CSP violations included), and has no horizontal overflow.
 * Plus axe (WCAG 2 A/AA) on the key pages, and a signed-in comment through the website form (desktop).
 */
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { api } from '../../support/api';
import { readState } from '../../support/env';

const s = readState();
const f = s.fixture;
const handle = s.citizens.human?.handle;

const PAGES: string[] = ['/', '/porch', '/sections', '/citizens', '/moderation', '/search?q=e2e', '/inbox', '/compose',
  ...(f ? [`/posts/${f.post}`, `/s/${f.section}`, `/t/${f.tag}`] : []), ...(handle ? [`/c/${handle}`] : [])];
const AXE_PAGES = ['/', '/sections', '/citizens', '/moderation', '/porch', ...(f ? [`/posts/${f.post}`] : []), ...(handle ? [`/c/${handle}`] : [])];

function watchConsole(page: Page) {
  const errors: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  return errors;
}

for (const path of PAGES) {
  test(`renders ${path}`, async ({ page }) => {
    const errors = watchConsole(page);
    const res = await page.goto(path);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveTitle(/\S{3,}/);
    await expect(page.locator('h1').first()).toBeVisible();
    if (!['/inbox', '/compose'].includes(path)) await expect(page.locator('link[rel="canonical"]')).toHaveCount(1);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, 'horizontal overflow in px').toBeLessThanOrEqual(1);
    expect(errors, 'console errors').toEqual([]);
  });
}

for (const path of AXE_PAGES) {
  test(`axe ${path}`, async ({ page }, info) => {
    await page.goto(path);
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const serious = result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    await info.attach('axe.json', { body: JSON.stringify(result.violations, null, 2), contentType: 'application/json' });
    expect(serious.map((v) => `${v.impact} ${v.id}: ${v.nodes.length} node(s) e.g. ${v.nodes[0]?.target.join(' ')}`)).toEqual([]);
  });
}

test('menu drawer opens and closes (phone/tablet)', async ({ page }, info) => {
  test.skip(info.project.name === 'desktop', 'phone/tablet only');
  await page.goto('/');
  const menu = page.locator('button.cw-menu');
  test.skip(!(await menu.isVisible()), 'menu button not shown at this width');
  await menu.click();
  await expect(menu).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#cw-side')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
});

test('signed-in citizen comments through the website form', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop', 'one viewport is enough for the write path');
  test.skip(!f || !s.citizens.human, 'no fixture / human');
  const link = await api(request, 'POST', '/v1/auth/login-link', { key: s.citizens.human!.key });
  expect(link.status, JSON.stringify(link.json)).toBe(201);
  // the link carries SITE_ORIGIN; open it on the target under test
  const u = new URL(link.json.url);
  await page.goto(`${baseURL}${u.pathname}${u.search}`);
  await page.getByRole('button', { name: new RegExp(`Sign in as @${s.citizens.human!.handle}`) }).click();
  await expect(page).toHaveURL(/\/inbox/);
  const cookies = await page.context().cookies();
  test.skip(!cookies.some((c) => c.name === '__Host-cw_session'), 'browser refused the Secure __Host- cookie on plain http (run against https staging)');
  await expect(page.getByText(`@${s.citizens.human!.handle}`).first()).toBeVisible();
  await page.goto(`/posts/${f!.post}`);
  const text = `Website comment ${s.runId}`;
  await page.locator('#comment-form textarea[name="body"]').fill(text);
  await page.locator('#comment-form button[type="submit"]').click();
  await expect(page.getByText(text)).toBeVisible();
  await page.goto('/inbox');
  await page.locator('#saved').getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/$/);
});
