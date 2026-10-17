/** Domain normalisation and the candidate names a blocklist entry may be written under. */

/** Shared hosting / platform suffixes: a listing of one of THESE as a whole would flag every site on them, so a
 * parent-domain match never climbs to them (a subdomain is matched only by its own exact name). */
export const SHARED_SUFFIXES = new Set([
  'vercel.app', 'netlify.app', 'pages.dev', 'workers.dev', 'github.io', 'gitlab.io', 'web.app', 'firebaseapp.com',
  'herokuapp.com', 'onrender.com', 'fly.dev', 'railway.app', 'replit.app', 'repl.co', 'glitch.me', 'gitbook.io',
  'notion.site', 'webflow.io', 'framer.website', 'framer.app', 'wixsite.com', 'weebly.com', 'weeblysite.com',
  'blogspot.com', 'wordpress.com', 'carrd.co', 'super.site', 'azurewebsites.net', 'cloudfront.net', 'appspot.com',
  'amazonaws.com', 'r2.dev', 'ipfs.io', 'dweb.link', 'fleek.co', 'on-fleek.app', 'surge.sh', 'translate.goog',
  '000webhostapp.com', 'myshopify.com', 'square.site', 'godaddysites.com', 'sites.google.com', 'medium.com', 'substack.com',
  'co.uk', 'com.au', 'co.jp', 'com.br', 'co.in', 'com.cn', 'co.kr', 'com.tr', 'com.mx',
]);

/** 'HTTPS://WWW.Example.com./x' or 'Example.com' -> 'example.com' (lower case, no scheme/path/port, no trailing dot,
 * no leading www.). Returns '' when there is no usable host name. */
export function normalizeDomain(input: string): string {
  let s = String(input || '').trim().toLowerCase();
  if (!s) return '';
  if (s.includes('://')) {
    try { s = new URL(s).hostname; } catch { return ''; }
  } else {
    s = s.split(/[/?#]/)[0].split('@').pop()!.replace(/:\d+$/, '');
  }
  s = s.replace(/\.+$/, '');
  if (s.startsWith('www.')) s = s.slice(4);
  if (!/^[a-z0-9.-]+$/.test(s) || !s.includes('.') || s.startsWith('.') || s.includes('..')) return '';
  return s;
}

/** Names under which a blocklist would list `domain`: the domain itself, its www. form, and each parent domain with at
 * least two labels that is not a shared platform suffix (so `app.evil.example` matches a listing of `evil.example`,
 * but `mysite.vercel.app` never matches a listing of `vercel.app`). */
export function candidates(domain: string): string[] {
  const d = normalizeDomain(domain);
  if (!d) return [];
  const out = [d, 'www.' + d];
  const labels = d.split('.');
  for (let i = 1; i <= labels.length - 2; i++) {
    const parent = labels.slice(i).join('.');
    if (SHARED_SUFFIXES.has(parent)) break;
    out.push(parent);
  }
  return out;
}
