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
const CHANNEL_TIMEOUT_MS = Number.parseInt(process.env.YTJS_CHANNEL_TIMEOUT_MS ?? '10000', 10);
const REQUEST_DELAY_MIN_MS = Number.parseInt(process.env.YTJS_REQUEST_DELAY_MIN_MS ?? '200', 10);
const REQUEST_DELAY_MAX_MS = Number.parseInt(process.env.YTJS_REQUEST_DELAY_MAX_MS ?? '600', 10);
const PROGRESS = ['1', 'true', 'yes', 'on'].includes(
  (process.env.YTJS_PROGRESS ?? '').trim().toLowerCase()
);
const DEBUG_CANDIDATES = ['1', 'true', 'yes', 'on'].includes(
  (process.env.YTJS_DEBUG_CANDIDATES ?? '').trim().toLowerCase()
);

if (!['1', 'true', 'yes', 'on'].includes((process.env.YTJS_SHOW_WARNINGS ?? '').trim().toLowerCase())) {
  console.warn = () => {};
}

function progressLog(message) {
  if (PROGRESS) {
    process.stderr.write(`${message}\n`);
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function randomRequestDelayMs() {
  const minimum = Number.isFinite(REQUEST_DELAY_MIN_MS)
    ? Math.max(REQUEST_DELAY_MIN_MS, 0)
    : 200;
  const maximum = Number.isFinite(REQUEST_DELAY_MAX_MS)
    ? Math.max(REQUEST_DELAY_MAX_MS, minimum)
    : Math.max(600, minimum);
  return Math.floor(Math.random() * (maximum - minimum + 1)) + minimum;
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

function lockupPresentation(lockup) {
  const thumbnailBadges = (lockup?.content_image?.overlays ?? [])
    .flatMap((overlay) => overlay?.badges ?? [])
    .map((badge) => ({
      text: badge?.text ?? '',
      style: badge?.badge_style ?? '',
      icon: badge?.icon_name ?? '',
    }));
  const metadataRows = (lockup?.metadata?.metadata?.metadata_rows ?? []).map((row) => ({
    text: (row?.metadata_parts ?? [])
      .map((part) => part?.text?.toString?.() ?? '')
      .filter(Boolean),
    badges: (row?.badges ?? []).map((badge) => badge?.text?.toString?.() ?? ''),
  }));
  return { thumbnailBadges, metadataRows };
}

function lockupLooksLive(lockup) {
  const presentation = lockupPresentation(lockup);
  const badgeText = presentation.thumbnailBadges
    .map((badge) => `${badge.text} ${badge.style} ${badge.icon}`)
    .join(' ');
  const metadataText = presentation.metadataRows
    .flatMap((row) => [...row.text, ...row.badges])
    .join(' ');
  const isUpcoming = /即將直播|正在等候|預定發布|upcoming|waiting|premiere/i.test(
    `${badgeText} ${metadataText}`
  );
  if (isUpcoming) {
    return false;
  }
  return (
    /正在觀看|視聴中|watching now/i.test(metadataText) ||
    /直播中|配信中|\blive\b|BADGE_STYLE_LIVE|ICON.*LIVE/i.test(badgeText)
  );
}

function hasParsedNodeType(feed, nodeType) {
  return feed?.memo?.has?.(nodeType) ?? false;
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
    if (streamer.was_live) {
      return {
        vtuber_id: streamer.vtuber_id,
        channel_id,
        live: null,
        error: 'previously live but the channel live tab disappeared; unable to confirm offline status',
      };
    }
    return { vtuber_id: streamer.vtuber_id, channel_id, live: null };
  }

  const feed = await channel.getLiveStreams();
  const candidates = lockupCandidates(feed);
  if (DEBUG_CANDIDATES) {
    for (const lockup of candidates) {
      progressLog(
        `[youtube] candidate ${streamer.vtuber_id} ${lockup.content_id} ` +
        `${JSON.stringify(lockupPresentation(lockup))}`
      );
    }
  }
  if (candidates.length === 0) {
    if (hasParsedNodeType(feed, 'ChannelOwnerEmptyState')) {
      return { vtuber_id: streamer.vtuber_id, channel_id, live: null };
    }
    const parsedNodeTypes = Array.from(feed?.memo?.keys?.() ?? []).slice(0, 20).join(', ');
    return {
      vtuber_id: streamer.vtuber_id,
      channel_id,
      live: null,
      error:
        'live tab exists but no video candidates were parsed' +
        `${parsedNodeTypes ? ` (node types: ${parsedNodeTypes})` : ''}`,
    };
  }

  const candidateErrors = [];
  for (const lockup of candidates) {
    let basic;
    try {
      const basicInfo = await youtube.getBasicInfo(lockup.content_id, { client: 'WEB' });
      basic = basicInfo.basic_info ?? {};
      const playabilityStatus = basicInfo.playability_status?.status ?? null;
      const playabilityReason = basicInfo.playability_status?.reason ?? null;
      if (playabilityStatus === 'LOGIN_REQUIRED' || basic.is_live == null) {
        throw new Error(
          `indeterminate live state; playability=${playabilityStatus ?? 'unknown'}` +
          `${playabilityReason ? `; reason=${playabilityReason}` : ''}`
        );
      }
      if (!basic.is_live) {
        continue;
      }
    } catch (error) {
      const message = error?.message ?? String(error);
      if (
        message.includes('indeterminate live state') &&
        !lockupLooksLive(lockup)
      ) {
        continue;
      }
      candidateErrors.push(
        `${lockup.content_id}: ${error?.name ?? 'Error'}: ${message}`
      );
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

  if (candidateErrors.length > 0) {
    const details = candidateErrors.slice(0, 3).join(' | ');
    const omitted = candidateErrors.length > 3
      ? ` | ${candidateErrors.length - 3} more`
      : '';
    return {
      vtuber_id: streamer.vtuber_id,
      channel_id,
      live: null,
      error:
        `unable to confirm offline status: ${candidateErrors.length}/${candidates.length} ` +
        `candidate checks failed (${details}${omitted})`,
    };
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
        const delayMs = randomRequestDelayMs();
        if (delayMs > 0) {
          await sleep(delayMs);
        }
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
  const cookie = (process.env.YOUTUBE_COOKIE ?? '').trim();
  progressLog(
    `[youtube] authentication=${cookie ? 'cookie' : 'anonymous'}`
  );
  progressLog(
    `[youtube] concurrency=${CONCURRENCY} request_delay=${REQUEST_DELAY_MIN_MS}-${REQUEST_DELAY_MAX_MS}ms`
  );
  const youtube = await Innertube.create({
    lang: 'zh-TW',
    location: 'TW',
    retrieve_player: false,
    generate_session_locally: !cookie,
    ...(cookie ? { cookie } : {}),
  });

  const results = await runPool(
    streamers,
    async (streamer) => {
      const label = `${streamer.vtuber_id}${streamer.name ? ` ${streamer.name}` : ''}`;
      progressLog(`[youtube] checking ${label}`);
      try {
        let result;
        try {
          result = await withTimeout(
            fetchStreamer(youtube, streamer),
            CHANNEL_TIMEOUT_MS,
            label
          );
        } catch (firstError) {
          const message = firstError?.message ?? String(firstError);
          if (!message.toLowerCase().includes('fetch failed')) {
            throw firstError;
          }
          const retryDelayMs = 800 + Math.floor(Math.random() * 801);
          progressLog(
            `[youtube] ${label} transient fetch failure; retrying in ${retryDelayMs}ms`
          );
          await sleep(retryDelayMs);
          result = await withTimeout(
            fetchStreamer(youtube, streamer),
            CHANNEL_TIMEOUT_MS,
            `${label} retry`
          );
        }
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
