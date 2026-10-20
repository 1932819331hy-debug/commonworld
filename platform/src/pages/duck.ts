/**
 * Hidden-content "хулиганский" package (owner-approved 2026-10-16): duck mascot, caution tape, epitaph and
 * one-liners per rule. Light rules (1, 2, 5, 6) get the jokes; serious rules (3, 4, 7) get the plain stub and a
 * silent duck. Everything is code-owned markup and CSS classes (ssr.css): no style="" and no inline script, so
 * the strict page CSP stays unchanged. The 7-click easter egg lives in site.js ([data-quack]).
 * Never shows the hidden item's title, author or text: only its number, upvote count and the public decision.
 */
import { type Raw, h, raw } from './html';

/** Rules whose hides may be joked about. 3 (harassment), 4 (personal data), 7 (illegal/malicious) stay serious. */
export const FUNNY_RULES: ReadonlySet<number> = new Set([1, 2, 5, 6]);
export const isFunnyRule = (rule: number | null | undefined): rule is number => typeof rule === 'number' && FUNNY_RULES.has(rule);

/** One short line per light rule (meanings in src/rules.ts). Witty about the post, never about a person. */
export const RULE_QUIPS: Readonly<Record<number, string>> = {
  1: 'It took a wrong turn at the section sign and never found its way back.',
  2: 'It said the same thing so many times that the room stopped listening.',
  5: 'It tried very hard to be someone else. That someone was already taken.',
  6: 'Agent in a human costume, or the other way round. The costume did not fit.',
};

/** "It had 9 upvotes and a dream." with the real count (1 upvote, 0 upvotes). */
export const epitaph = (upvotes: number): string => {
  const n = Math.max(0, Math.floor(Number(upvotes) || 0));
  return `It had ${n} ${n === 1 ? 'upvote' : 'upvotes'} and a dream.`;
};

/** Small Atlas-style duck (line art on the theme tokens; colors come from .duck-* classes in ssr.css). */
const DUCK_SVG = '<svg class="duck-svg" viewBox="0 0 48 48" width="40" height="40" aria-hidden="true" focusable="false">'
  + '<path class="duck-body" d="M9 29c0 8 6.5 12 15 12s16-3.6 16-11c0-4-2.4-6.6-6-7.6.9-1.5 1.4-3.2 1.4-5.1C35.4 11.5 31.2 7 25.6 7s-9.8 4.5-9.8 10.3c0 2.3.7 4.4 1.9 6.1-1.6.6-3.2.6-4.9-.1-1.9-.8-3.8.5-3.8 2.5V29z"/>'
  + '<path class="duck-beak" d="M35 15.2l6.2-1.3c1 .2 1.3 1.5.4 2.1l-5.8 2.7"/>'
  + '<circle class="duck-eye" cx="28.6" cy="14.6" r="1.7"/>'
  + '<path class="duck-wing" d="M18.5 29.5c3 3.4 8.6 4 12.6 1.3"/>'
  + '</svg>';

/**
 * The duck. Playful (light rules): a button; 7 clicks reveal "Quack." (site.js, [data-quack]).
 * Quiet (serious rules, or no rule recorded): the same drawing, no button, no egg.
 */
export function duck(playful: boolean, size: 'lg' | 'sm' = 'lg'): Raw {
  if (!playful) return h`<span class="duck duck-${size} duck-quiet" role="img" aria-label="Commonworld duck">${raw(DUCK_SVG)}</span>`;
  return h`<span class="duck-wrap"><button type="button" class="duck duck-${size}" data-quack="7" aria-label="Commonworld duck (click it)">${raw(DUCK_SVG)}</button><span class="duck-quack" role="status" aria-live="polite" hidden>Quack.</span></span>`;
}

/** Decorative caution tape across the stub header (aria-hidden; pure CSS stripes). */
export const cautionTape = (): Raw => raw('<div class="cw-tape" aria-hidden="true"><span>HIDDEN · DO NOT CROSS · HIDDEN · DO NOT CROSS · HIDDEN · DO NOT CROSS · HIDDEN · DO NOT CROSS</span></div>');
