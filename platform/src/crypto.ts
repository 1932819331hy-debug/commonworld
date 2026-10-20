const encoder = new TextEncoder();
const KEY_PREFIX = 'cw1_';
export const API_KEY_PATTERN = /^cw1_[A-Za-z0-9_-]{43}$/;

function base64url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

const hex = (buffer: ArrayBuffer): string => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('');

/** 32 random bytes -> `cw1_` + 43 base64url chars. */
export function newApiKey(): string {
  return KEY_PREFIX + base64url(crypto.getRandomValues(new Uint8Array(32)));
}

export const keyPrefix = (key: string): string => key.slice(0, 12);

let cachedPepper: string | null = null;
let cachedKey: CryptoKey | null = null;

async function hmacKey(pepper: string): Promise<CryptoKey> {
  if (cachedKey && cachedPepper === pepper) return cachedKey;
  cachedKey = await crypto.subtle.importKey('raw', encoder.encode(pepper), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  cachedPepper = pepper;
  return cachedKey;
}

/** HMAC-SHA256(pepper, value) as hex. Used for API keys and client IPs. */
export async function hmacHex(pepper: string, value: string): Promise<string> {
  const key = await hmacKey(pepper);
  return hex(await crypto.subtle.sign('HMAC', key, encoder.encode(value)));
}

export async function sha256Hex(value: string): Promise<string> {
  return hex(await crypto.subtle.digest('SHA-256', encoder.encode(value)));
}
