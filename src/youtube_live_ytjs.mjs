import {
  ReadableStream,
  TransformStream,
  WritableStream,
} from 'node:stream/web';

if (!globalThis.ReadableStream) {
  globalThis.ReadableStream = ReadableStream;
}
if (!globalThis.TransformStream) {
  globalThis.TransformStream = TransformStream;
}
if (!globalThis.WritableStream) {
  globalThis.WritableStream = WritableStream;
}

const MAX_CANDIDATES = Number.parseInt(process.env.YTJS_MAX_CANDIDATES ?? '5', 10);
const CONCURRENCY = Number.parseInt(process.env.YTJS_CONCURRENCY ?? '4', 10);
const CHANNEL_TIMEOUT_MS = Number.parseInt(process.env.YTJS_CHANNEL_TIMEOUT_MS ?? '15000', 10);
const PROGRESS = ['1', 'true', 'yes', 'on'].includes(
  (process.env.YTJS_PROGRESS ?? '').trim().toLowerCase()
);

if (!['1', 'true', 'yes', 'on'].includes((process.env.YTJS_SHOW_WARNINGS ?? '').trim().toLowerCase())) {
  console.warn = () => {};
}

function progressLog(message) {
  if (PROGRESS) {
    process.stderr.write(`${message}\n`);
  }
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function channelUrlFromStreamer(streamer) {
  if (streamer.youtube_channel_id) {
    return `https://www.youtube.com/channel/${streamer.youtube_channel_id}`;
  }
  return streamer.youtube_url ?? null;
}

async function resolveChannelId(youtube, streamer) {
  if (streamer.youtube_channel_id) {
    return streamer.youtube_channel_id;
  }

  const url = channelUrlFromStreamer(streamer);
  if (!url) {
    return null;
  }

  const endpoint = await youtube.resolveURL(url);
  return endpoint?.payload?.browseId ?? null;
}

function lockupCandidates(feed) {
  const lockups = feed?.memo?.get('LockupView') ?? [];
  return lockups
    .filter((lockup) => lockup.content_type === 'VIDEO' && lockup.content_id)
    .slice(0, Number.isFinite(MAX_CANDIDATES) && MAX_CANDIDATES > 0 ? MAX_CANDIDATES : 5);
}

function nullableNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function liveViewerCount(info) {
  return nullableNumber(info?.primary_info?.view_count?.original_view_count);
}

function basicViewerCount(info) {
  return nullableNumber(info?.basic_info?.view_count);
}

function withTimeout(promise, timeoutMs, label) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return promise;
  }

  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`${label} exceeded ${timeoutMs}ms`)), timeoutMs);
    }),
  ]);
}

async function fetchStreamer(youtube, streamer) {
  const channel_id = await resolveChannelId(youtube, streamer);
  if (!channel_id) {
    return {
      vtuber_id: streamer.vtuber_id,
      live: null,
      error: 'missing YouTube channel id',
    };
  }

  const channel = await youtube.getChannel(channel_id);
  if (!channel.has_live_streams) {
    return { vtuber_id: streamer.vtuber_id, channel_id, live: null };
  }

  const feed = await channel.getLiveStreams();
  for (const lockup of lockupCandidates(feed)) {
    let basic;
    try {
      const basicInfo = await youtube.getBasicInfo(lockup.content_id, { client: 'WEB' });
      basic = basicInfo.basic_info ?? {};
      if (!basic.is_live) {
        continue;
      }
    } catch (error) {
      continue;
    }

    try {
      const info = await youtube.getInfo(lockup.content_id, { client: 'WEB' });
      const fullBasic = info.basic_info ?? basic;
      if (!fullBasic?.is_live) {
        continue;
      }

      return {
        vtuber_id: streamer.vtuber_id,
        channel_id,
        live: {
          platform_stream_id: lockup.content_id,
          stream_url: `https://www.youtube.com/watch?v=${lockup.content_id}`,
          title: fullBasic.title ?? lockup.metadata?.title?.toString?.() ?? '',
          viewer_count: liveViewerCount(info) ?? basicViewerCount({ basic_info: fullBasic }),
          started_at: fullBasic.live_start_timestamp ?? null,
        },
      };
    } catch (error) {
      return {
        vtuber_id: streamer.vtuber_id,
        channel_id,
        live: {
          platform_stream_id: lockup.content_id,
          stream_url: `https://www.youtube.com/watch?v=${lockup.content_id}`,
          title: basic.title ?? lockup.metadata?.title?.toString?.() ?? '',
          viewer_count: basicViewerCount({ basic_info: basic }),
          started_at: basic.live_start_timestamp ?? null,
        },
      };
    }
  }

  return { vtuber_id: streamer.vtuber_id, channel_id, live: null };
}

async function runPool(items, worker, concurrency) {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(concurrency || 1, 1), items.length || 1);

  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (nextIndex < items.length) {
        const current = nextIndex;
        nextIndex += 1;
        results[current] = await worker(items[current]);
      }
    })
  );

  return results;
}

async function main() {
  const input = await readStdin();
  const streamers = JSON.parse(input || '[]');
  let finished = 0;
  const { Innertube } = await import('youtubei.js');
  const youtube = await Innertube.create({
    lang: 'zh-TW',
    location: 'TW',
    retrieve_player: false,
    generate_session_locally: true,
  });

  const results = await runPool(
    streamers,
    async (streamer) => {
      const label = `${streamer.vtuber_id}${streamer.name ? ` ${streamer.name}` : ''}`;
      progressLog(`[youtube] checking ${label}`);
      try {
        const result = await withTimeout(
          fetchStreamer(youtube, streamer),
          CHANNEL_TIMEOUT_MS,
          label
        );
        finished += 1;
        if (result.error) {
          progressLog(`[youtube] [${finished}/${streamers.length}] ${label} -> ERROR ${result.error}`);
        } else if (result.live) {
          const viewers = result.live.viewer_count ?? 'unknown';
          progressLog(
            `[youtube] [${finished}/${streamers.length}] ${label} -> LIVE ` +
            `${viewers} viewers | ${result.live.title}`
          );
        } else {
          progressLog(`[youtube] [${finished}/${streamers.length}] ${label} -> offline`);
        }
        return result;
      } catch (error) {
        finished += 1;
        progressLog(
          `[youtube] [${finished}/${streamers.length}] ${label} -> ERROR ` +
          `${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`
        );
        return {
          vtuber_id: streamer.vtuber_id,
          live: null,
          error: `${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`,
        };
      }
    },
    Number.isFinite(CONCURRENCY) && CONCURRENCY > 0 ? CONCURRENCY : 4
  );

  process.stdout.write(`${JSON.stringify({ results })}\n`);
  process.exit(0);
}

main().catch((error) => {
  process.stderr.write(`${error?.stack ?? error}\n`);
  process.exit(1);
});
