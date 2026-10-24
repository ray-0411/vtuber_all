import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const DEFAULT_COOKIE_FILE = fileURLToPath(
  new URL('../../other/local/cookie/www.youtube.com_cookies.txt', import.meta.url),
);

function parseNetscapeCookies(text) {
  const now = Math.floor(Date.now() / 1000);
  const cookies = [];

  for (const originalLine of text.split(/\r?\n/)) {
    let line = originalLine.trim();
    if (!line || (line.startsWith('#') && !line.startsWith('#HttpOnly_'))) continue;
    if (line.startsWith('#HttpOnly_')) line = line.slice('#HttpOnly_'.length);

    const fields = line.split('\t');
    if (fields.length < 7) continue;
    const [domain, , , , expiresText, name, ...valueParts] = fields;
    if (!/(^|\.)youtube\.com$/i.test(domain.replace(/^\./, ''))) continue;

    const expires = Number.parseInt(expiresText, 10);
    if (Number.isFinite(expires) && expires > 0 && expires <= now) continue;
    if (name) cookies.push(`${name}=${valueParts.join('\t')}`);
  }

  return cookies.join('; ');
}

function parseJsonCookies(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return '';
  }
  if (!Array.isArray(parsed)) return '';

  const now = Date.now() / 1000;
  return parsed
    .filter((item) => item && typeof item.name === 'string')
    .filter((item) => !item.domain || /(^|\.)youtube\.com$/i.test(item.domain.replace(/^\./, '')))
    .filter((item) => !item.expirationDate || item.expirationDate > now)
    .map((item) => `${item.name}=${item.value ?? ''}`)
    .join('; ');
}

function parseCookieFile(text) {
  const trimmed = text.trim();
  if (!trimmed) return '';

  const jsonCookie = parseJsonCookies(trimmed);
  if (jsonCookie) return jsonCookie;

  const netscapeCookie = parseNetscapeCookies(trimmed);
  if (netscapeCookie) return netscapeCookie;

  const header = trimmed.replace(/^cookie\s*:\s*/i, '').replace(/\r?\n/g, '').trim();
  return header.includes('=') ? header : '';
}

export async function loadYoutubeCookie() {
  const configuredCookieFile = (process.env.YOUTUBE_COOKIES_FILE ?? '').trim();
  const cookieFile = configuredCookieFile || DEFAULT_COOKIE_FILE;
  if (cookieFile) {
    let contents;
    try {
      contents = await readFile(cookieFile, 'utf8');
    } catch (error) {
      if (!configuredCookieFile && error?.code === 'ENOENT') {
        const cookie = (process.env.YOUTUBE_COOKIE ?? '').trim();
        return { cookie, source: cookie ? 'environment' : 'anonymous' };
      }
      throw new Error(`Cannot read YouTube cookie file: ${cookieFile}`, { cause: error });
    }
    const cookie = parseCookieFile(contents);
    if (!cookie) throw new Error(`No usable YouTube cookies found in: ${cookieFile}`);
    return { cookie, source: configuredCookieFile ? 'file' : 'default-file' };
  }
}
