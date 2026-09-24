import {
  ReadableStream,
  TransformStream,
  WritableStream,
} from 'node:stream/web';
import { loadYoutubeCookie } from './youtube_cookie.mjs';

if (!globalThis.ReadableStream) globalThis.ReadableStream = ReadableStream;
if (!globalThis.TransformStream) globalThis.TransformStream = TransformStream;
if (!globalThis.WritableStream) globalThis.WritableStream = WritableStream;

const CONCURRENCY = Number.parseInt(process.env.YTJS_AVATAR_CONCURRENCY ?? '2', 10);
const DELAY_MIN_MS = Number.parseInt(process.env.YTJS_REQUEST_DELAY_MIN_MS ?? '200', 10);
const DELAY_MAX_MS = Number.parseInt(process.env.YTJS_REQUEST_DELAY_MAX_MS ?? '600', 10);

if (!['1', 'true', 'yes', 'on'].includes((process.env.YTJS_SHOW_WARNINGS ?? '').toLowerCase())) {
  console.warn = () => {};
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function randomDelay() {
  const minimum = Number.isFinite(DELAY_MIN_MS) ? Math.max(DELAY_MIN_MS, 0) : 200;
  const maximum = Number.isFinite(DELAY_MAX_MS) ? Math.max(DELAY_MAX_MS, minimum) : 600;
  return Math.floor(Math.random() * (maximum - minimum + 1)) + minimum;
}

function bestImage(images) {
  if (!Array.isArray(images) || images.length === 0) return null;
  return [...images]
    .filter((image) => image?.url)
    .sort((left, right) => (right.width ?? 0) - (left.width ?? 0))[0] ?? null;
}

function avatarImage(channel) {
  const candidates = [
    channel?.header?.content?.image?.avatar?.image,
    channel?.header?.content?.image?.image,
    channel?.header?.author?.thumbnails,
    channel?.metadata?.avatar,
  ];
  for (const images of candidates) {
    const image = bestImage(images);
    if (image) return image;
  }
  return null;
}

async function fetchOne(youtube, item) {
  let channelId = item.youtube_channel_id ?? null;
  if (!channelId && item.youtube_url) {
    const endpoint = await youtube.resolveURL(item.youtube_url);
    channelId = endpoint?.payload?.browseId ?? null;
  }
  if (!channelId) throw new Error('missing YouTube channel ID and resolvable URL');

  const channel = await youtube.getChannel(channelId);
  const image = avatarImage(channel);
  if (!image?.url) throw new Error('channel avatar URL was not found');
  return {
    vtuber_id: item.vtuber_id,
    youtube_channel_id: channelId,
    youtube_avatar_url: image.url,
    youtube_avatar_width: image.width ?? null,
    youtube_avatar_height: image.height ?? null,
  };
}

async function runPool(items, worker, concurrency) {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(concurrency || 1, 1), items.length || 1);
  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (nextIndex < items.length) {
      const current = nextIndex++;
      await sleep(randomDelay());
      try {
        results[current] = await worker(items[current]);
      } catch (error) {
        results[current] = {
          vtuber_id: items[current].vtuber_id,
          error: `${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`,
        };
      }
    }
  }));
  return results;
}

async function main() {
  const items = JSON.parse((await readStdin()) || '[]');
  const { Innertube } = await import('youtubei.js');
  const { cookie } = await loadYoutubeCookie();
  const youtube = await Innertube.create({
    lang: 'zh-TW',
    location: 'TW',
    retrieve_player: false,
    generate_session_locally: !cookie,
    ...(cookie ? { cookie } : {}),
  });
  const results = await runPool(
    items,
    (item) => fetchOne(youtube, item),
    Number.isFinite(CONCURRENCY) ? CONCURRENCY : 2
  );
  process.stdout.write(`${JSON.stringify({ results })}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error?.stack ?? error}\n`);
  process.exit(1);
});
