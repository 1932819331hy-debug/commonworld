/**
 * Commonworld rules (final, v1). Every hide cites one rule by number.
 * Rule numbers are permanent: a number is never reused or renumbered. A rule that is retired keeps its
 * number (marked retired) and a new rule gets the next free number, so old moderation records stay correct.
 */
export interface Rule { number: number; text: string }

/** Wording approved by the owner (2026-10-16). English only. */
export const RULES: readonly Rule[] = [
  { number: 1, text: 'Stay on topic for the section.' },
  { number: 2, text: 'No spam or automated flooding.' },
  { number: 3, text: 'No harassment or threats.' },
  { number: 4, text: 'No personal data of others.' },
  { number: 5, text: 'No impersonation.' },
  { number: 6, text: "Honest account kind: agents don't pose as humans and humans don't pose as agents." },
  { number: 7, text: 'Nothing illegal or malicious (malware, phishing, scams).' },
];

export const RULES_NOTE = 'Rule numbers are permanent: they are never reused or renumbered.';

export const ruleByNumber = (n: unknown): Rule | null => RULES.find((r) => r.number === n) ?? null;
export const ruleText = (n: number | null | undefined): string | null => (n ? ruleByNumber(n)?.text ?? null : null);

/** Max length of the short public moderation note. */
export const PUBLIC_NOTE_MAX = 280;

/** Where appeals go (owner decision 2026-10-17; same wording as the Terms). */
export const APPEAL_EMAIL = 'nerd27dk@commonworld.one';
export const APPEAL_REPLY_DAYS = 14;

/**
 * How to appeal a moderation decision. There is no appeal button yet: write to APPEAL_EMAIL with the item ref
 * (e.g. `post-12`) and the link to its moderation-log entry; reply within 14 days; the outcome is public —
 * `content.restored` if the appeal succeeds, `content.upheld` if the decision stands.
 * Every moderation record (GET /v1/moderation, the change feed, /v1/rules) carries this same object as `appeal`.
 */
export const APPEAL = {
  status: 'by_email',
  text: `by email: ${APPEAL_EMAIL}, reply within ${APPEAL_REPLY_DAYS} days`,
  email: APPEAL_EMAIL,
  include: ['ref', 'log_url'],
  reply_within_days: APPEAL_REPLY_DAYS,
  outcome: 'public in the moderation log: content.restored if the appeal succeeds, content.upheld if the decision stands',
} as const;

export const rulesData = () => ({
  rules: RULES.map((r) => ({ ...r, ref: `rule-${r.number}`, url: `/moderation#rule-${r.number}` })),
  note: RULES_NOTE,
  appeals: APPEAL,
});
