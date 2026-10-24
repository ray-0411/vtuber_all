import {
  ReadableStream,
  TransformStream,
  WritableStream,
} from 'node:stream/web';
import { loadYoutubeCookie } from './youtube_cookie.mjs';

if (!globalThis.ReadableStream) globalThis.ReadableStream = ReadableStream;
if (!globalThis.TransformStream) globalThis.TransformStream = TransformStream;
if (!globalThis.WritableStream) globalThis.WritableStream = WritableStream;

const CONCURRENCY = Number.parseInt(process.env.YTJS_AUDIENCE_CONCURRENCY ?? '2', 10);
const DELAY_MIN_MS = Number.parseInt(process.env.YTJS_REQUEST_DELAY_MIN_MS ?? '200', 10);
const DELAY_MAX_MS = Number.parseInt(process.env.YTJS_REQUEST_DELAY_MAX_MS ?? '600', 10);
const DEBUG = ['1', 'true', 'yes', 'on'].includes(
  (process.env.YTJS_AUDIENCE_DEBUG ?? '').trim().toLowerCase()
);

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

function textValue(value) {
  if (value == null) return null;
  const text = value?.toString?.() ?? String(value);
  return text && text !== '[object Object]' ? text.trim() : null;
}

function subscriberText(channel, about) {
  const direct = [
    channel?.header?.subscribers,
    channel?.header?.subscriber_count,
    about?.subscriber_count,
  ];
  for (const value of direct) {
    const text = textValue(value);
    if (text) return text;
  }

  const pageHeaderMetadata = channel?.header?.content?.metadata?.metadata_rows ?? [];
  for (const row of pageHeaderMetadata) {
    for (const part of row?.metadata_parts ?? []) {
      const text = textValue(part?.text);
      if (text && /訂閱者|subscribers?|チャンネル登録者/i.test(text)) {
        return text;
      }
    }
  }

  for (const type of ['C4TabbedHeader', 'Channel', 'AboutChannelView']) {
    for (const node of channel?.memo?.get?.(type) ?? []) {
      const text = textValue(node?.subscribers ?? node?.subscriber_count);
      if (text) return text;
    }
  }
  return null;
}

function parseSubscriberCount(text) {
  if (!text) return null;
  const normalized = text.replaceAll(',', '').replaceAll('，', '').trim();
  const match = normalized.match(/([0-9]+(?:\.[0-9]+)?)\s*([KMB萬万億亿]?)/i);
  if (!match) return null;
  const multipliers = {
    '': 1,
    K: 1_000,
    M: 1_000_000,
    B: 1_000_000_000,
    '萬': 10_000,
    '万': 10_000,
    '億': 100_000_000,
    '亿': 100_000_000,
  };
  const suffix = /^[kmb]$/i.test(match[2]) ? match[2].toUpperCase() : match[2];
  return Math.round(Number(match[1]) * (multipliers[suffix] ?? 1));
}

async function fetchOne(youtube, item) {
  const endpoint = await youtube.resolveURL(item.youtube_url);
  const channelId = endpoint?.payload?.browseId ?? null;
  if (!channelId) throw new Error('unable to resolve YouTube channel ID');
  const channel = await youtube.getChannel(channelId);
  let about = null;
  try {
    about = await channel.getAbout();
  } catch {
    // Header data is often enough; an unavailable About tab is not fatal.
  }
  const subscriberCountText = subscriberText(channel, about);
  if (DEBUG) {
    process.stderr.write(
      `${item.vtuber_id} header=${JSON.stringify(channel?.header ?? null)} ` +
      `about=${JSON.stringify(about ?? null)}\n`
    );
  }
  const subscriberCount = parseSubscriberCount(subscriberCountText);
  if (subscriberCount == null) {
    throw new Error(
      subscriberCountText
        ? `unable to parse subscriber count: ${subscriberCountText}`
        : 'subscriber count is unavailable or hidden'
    );
  }
  return {
    vtuber_id: item.vtuber_id,
    youtube_channel_id: channelId,
    youtube_subscribers: subscriberCount,
    youtube_subscriber_text: subscriberCountText,
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
