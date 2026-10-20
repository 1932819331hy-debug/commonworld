// Canonical host handling, kept out of src/index.ts: the Worker entry module may only export the Worker default
// (Wrangler treats every named export of the entry module as a handler; `npx wrangler dev` failed on WWW_HOST).
import { SECURITY_HEADERS } from './pages/router';

/** Only this host is redirected (production www Custom Domain); every other host, staging included, is served as is. */
export const WWW_HOST = 'www.commonworld.one';

/** 301 from `www.commonworld.one` to `commonworld.one` (path and query kept); null for every other host. Exported for tests. */
export function canonicalHostRedirect(request: Request): Response | null {
  const url = new URL(request.url);
  if (url.hostname !== WWW_HOST) return null;
  url.hostname = 'commonworld.one';
  return new Response(null, { status: 301, headers: { ...SECURITY_HEADERS, location: url.toString(), 'cache-control': 'public, max-age=86400' } });
}
