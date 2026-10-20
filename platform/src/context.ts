import type { Env } from './env';
import type { Principal } from './auth';

export interface Ctx {
  request: Request;
  env: Env;
  exec: ExecutionContext;
  url: URL;
  params: string[];
  principal: Principal | null;
}
export type Handler = (c: Ctx) => Promise<Response>;
/** The read-only part of a request context: what the shared data functions (API + SSR pages) need. */
export type ReadCtx = Pick<Ctx, 'env' | 'url' | 'params' | 'principal'>;
