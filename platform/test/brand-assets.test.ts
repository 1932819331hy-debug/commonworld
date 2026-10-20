/** CW mark vector logo (2026-10-18): SVG favicon + PNG fallbacks, dark variant, caching and CSP of the assets. */
import { exports } from 'cloudflare:workers';
import { describe, expect, it } from 'vitest';
import { ASSETS } from '../src/pages/assets.gen';

const get = async (path: string) => {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`));
  return { status: res.status, headers: res.headers, body: new Uint8Array(await res.arrayBuffer()) };
};

describe('brand assets', () => {
  it('pages link the SVG favicon, the ICO and PNG fallbacks, the apple-touch icon and both theme marks', async () => {
    const html = new TextDecoder().decode((await get('/sections')).body);
    for (const name of ['favicon.svg', 'favicon.ico', 'favicon-32.png', 'apple-touch-icon.png', 'cw-mark-light.svg', 'cw-mark-dark.svg']) {
      expect(html, name).toContain(`/assets/${name}?v=${ASSETS[name].hash}`);
    }
    expect(html).toContain('type="image/svg+xml"');
    expect(html).toContain('class="cw-mark cw-mark-d"');
  });

  it('SVGs: image/svg+xml, immutable when versioned, locked-down CSP, no script; favicon follows the OS dark mode', async () => {
    for (const name of ['favicon.svg', 'cw-mark-light.svg', 'cw-mark-dark.svg']) {
      const r = await get(`/assets/${name}?v=${ASSETS[name].hash}`);
      expect(r.status).toBe(200);
      expect(r.headers.get('content-type')).toBe('image/svg+xml');
      expect(r.headers.get('cache-control')).toBe('public, max-age=31536000, immutable');
      expect(r.headers.get('content-security-policy')).toContain("default-src 'none'");
      const text = new TextDecoder().decode(r.body);
      expect(text).not.toMatch(/<script|on[a-z]+=|href=/i);
      expect(text).toContain('#cb7756');
    }
    expect(atob(ASSETS['favicon.svg'].base64!)).toContain('prefers-color-scheme:dark');
  });

  it('PNG fallbacks have the right sizes; /favicon.ico serves the new icon', async () => {
    const size = (b: Uint8Array) => [new DataView(b.buffer).getUint32(16), new DataView(b.buffer).getUint32(20)];
    expect(size((await get('/assets/apple-touch-icon.png')).body)).toEqual([180, 180]);
    expect(size((await get('/assets/cw-mark-512.png')).body)).toEqual([512, 512]);
    expect(size((await get('/assets/cw-mark-light.png')).body)).toEqual([256, 256]);
    const ico = await get('/favicon.ico');
    expect(ico.headers.get('content-type')).toBe('image/x-icon');
    expect(ico.headers.get('etag')).toBe(`"${ASSETS['favicon.ico'].hash}"`);
  });
});
