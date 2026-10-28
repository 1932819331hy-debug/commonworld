// Excerpts never cut an emoji, flag or accented letter in half (reported privately by Tiny Logic Lab, 2026-10-28):
// the old UTF-16 slice(0, max - 1) left a lone surrogate at max 160 (meta descriptions), 110 (JSON-LD headline) and
// the default 220 (cards, comments).
import { describe, expect, it } from 'vitest';
import { cutExcerpt, excerpt, leadingGraphemes } from '../src/pages/html';
import { excerptText } from '../src/pages/layout';
import { around } from '../src/pages/misc';

/** An unpaired high or low surrogate anywhere in the string. */
const LONE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const graphemeCount = (s: string) => Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(s)).length;

/** The implementations before the fix, as the reference for ASCII (unchanged behavior) and for the bug itself. */
function oldExcerptText(body: string, max = 220): string {
  const t = String(body ?? '').replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  const sp = cut.lastIndexOf(' ');
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut) + '…';
}
function oldExcerpt(text: string, max: number): string {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  const sp = cut.lastIndexOf(' ');
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:–-]+$/, '') + '…';
}

describe('excerpt truncation is Unicode-safe', () => {
  it('runs with Intl.Segmenter in the Workers runtime (grapheme clusters, not only code points)', () => {
    expect(typeof Intl.Segmenter).toBe('function');
    expect(leadingGraphemes('👨‍👩‍👧‍👦🇱🇻é', 5)).toEqual(['👨‍👩‍👧‍👦', '🇱🇻', 'é']);
  });

  for (const max of [160, 110, 220]) {
    it(`emoji right at the boundary, max ${max}: no lone surrogate, length and ellipsis kept`, () => {
      // the emoji's high surrogate sits at index max-2, the last unit the old slice kept
      const text = 'a'.repeat(max - 2) + '😀' + 'b'.repeat(50);
      expect(oldExcerptText(text, max)).toMatch(LONE); // the reported bug
      for (const out of [excerptText(text, max), excerpt(text, max)]) {
        expect(out).not.toMatch(LONE);
        expect(out.endsWith('…')).toBe(true);
        expect(graphemeCount(out)).toBeLessThanOrEqual(max);
        expect(out).toBe('a'.repeat(max - 2) + '😀…');
      }
    });

    it(`emoji at every offset around the boundary, max ${max}, with and without spaces`, () => {
      for (let pad = max - 6; pad <= max + 2; pad++) {
        for (const text of ['x'.repeat(pad) + '🦆🦆🦆' + 'y'.repeat(40), ('word '.repeat(60)).slice(0, pad) + '🦆 tail '.repeat(20)]) {
          for (const out of [excerptText(text, max), excerpt(text, max)]) {
            expect(out, `pad ${pad}`).not.toMatch(LONE);
            expect(graphemeCount(out)).toBeLessThanOrEqual(max);
          }
        }
      }
    });
  }

  it('ZWJ family emoji, flags and combining accents are kept whole or dropped whole', () => {
    const family = '👨‍👩‍👧‍👦', flag = '🇱🇻', accent = 'e\u0301';
    for (const unit of [family, flag, accent, '👍🏽']) {
      for (const max of [110, 160, 220]) {
        for (let pad = max - 4; pad <= max; pad++) {
          const text = 'z'.repeat(pad) + unit.repeat(10);
          const out = excerptText(text, max);
          expect(out).not.toMatch(LONE);
          expect(graphemeCount(out)).toBeLessThanOrEqual(max);
          // whatever follows the z run is only whole units, then the ellipsis
          const tail = out.slice(out.lastIndexOf('z') + 1, -1);
          expect(tail.split(unit).every((x) => x === ''), `${JSON.stringify(unit)} pad ${pad}: ${JSON.stringify(tail)}`).toBe(true);
        }
      }
    }
  });

  it('counts user-perceived characters: 300 flags at max 160 give 159 flags and the ellipsis', () => {
    const out = excerptText('🇱🇻'.repeat(300), 160);
    expect(out).toBe('🇱🇻'.repeat(159) + '…');
    expect(excerptText('🇱🇻'.repeat(160), 160)).toBe('🇱🇻'.repeat(160)); // fits in graphemes: unchanged
  });

  it('ASCII output is byte-for-byte what it was before (word boundary, 60% rule, punctuation trim)', () => {
    const words = ['alpha', 'be', 'gamma,', 'delta.', 'epsilon', 'zeta;', 'eta', 'theta-', 'iota:'];
    let seed = 7;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31;
    for (let n = 0; n < 300; n++) {
      const text = Array.from({ length: 1 + Math.floor(rnd() * 80) }, () => rnd() < 0.1 ? 'x'.repeat(Math.floor(rnd() * 150)) : words[Math.floor(rnd() * words.length)]).join(rnd() < 0.2 ? '  \n ' : ' ');
      for (const max of [1, 2, 10, 70, 110, 150, 160, 200, 220, 400]) {
        expect(excerptText(text, max)).toBe(oldExcerptText(text, max));
        expect(excerpt(text, max)).toBe(oldExcerpt(text, max));
      }
    }
    expect(excerptText('short text', 220)).toBe('short text');
    expect(cutExcerpt('', 5)).toBe('');
  });

  it('search excerpt around a match never starts inside a surrogate pair', () => {
    for (let pad = 0; pad < 6; pad++) {
      const text = 'p'.repeat(pad) + '😀'.repeat(40) + ' needle ' + 'q '.repeat(200);
      const out = around(text, 'needle');
      expect(out, `pad ${pad}`).not.toMatch(LONE);
      expect(out).toContain('needle');
    }
  });
});
