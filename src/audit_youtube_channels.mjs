import { ReadableStream, TransformStream, WritableStream } from 'node:stream/web';

globalThis.ReadableStream ??= ReadableStream;
globalThis.TransformStream ??= TransformStream;
globalThis.WritableStream ??= WritableStream;

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

async function runPool(items, worker, concurrency) {
  const results = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length || 1) }, async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await worker(items[index]);
    }
  }));
  return results;
}

const input = JSON.parse((await readStdin()) || '[]');
const { Innertube } = await import('youtubei.js');
const youtube = await Innertube.create({
  lang: 'zh-TW',
  location: 'TW',
  retrieve_player: false,
  generate_session_locally: true,
});

const results = await runPool(input, async (item) => {
  try {
    const channel = await youtube.getChannel(item.youtube_channel_id);
    return {
      source_id: item.source_id,
      requested_channel_id: item.youtube_channel_id,
      actual_channel_id: channel.metadata?.external_id ?? item.youtube_channel_id,
      channel_name: channel.metadata?.title ?? null,
      vanity_channel_url: channel.metadata?.vanity_channel_url ?? null,
      error: null,
    };
  } catch (error) {
    return {
      source_id: item.source_id,
      requested_channel_id: item.youtube_channel_id,
      actual_channel_id: null,
      channel_name: null,
      vanity_channel_url: null,
      error: `${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`,
    };
  }
}, 6);

process.stdout.write(`${JSON.stringify({ results })}\n`);
