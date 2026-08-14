import crypto from 'node:crypto';

/**
 * 単語レベルのタイムスタンプ
 */
export interface WordMark {
  word: string;
  /** 秒 */
  start: number;
  /** 秒 */
  end: number;
}

/**
 * 音素レベルのタイムスタンプ 単語より細かい
 */
export interface PhonemeMark {
  phone: string;
  start: number;
  end: number;
}

/**
 * WebSocket 経路の合成結果
 */
export interface TtsWebSocketResult {
  audio: Buffer;
  text: string;
  duration: number | null;
  words: WordMark[];
  phonemes: PhonemeMark[];
}

export interface TtsWebSocketOptions {
  text: string;
  speaker: string;
  tokenUrl: string;
  wsUrl: string;
  appId: string;
  appVersion: string;
  platformId: string;
  signVersion: string;
  sampleRate: number;
  userAgent: string;
  origin: string;
  /** 音素まで返すか 単語だけで足りるなら false */
  includePhonemes?: boolean;
  timeoutMs?: number;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/**
 * token endpoint 用の署名を作る
 *
 * 実測でこの経路だけ path 末尾 7 文字を使う
 * 編集 API 側 (4 文字) と混ぜると ret=1014 で弾かれる
 */
const createTokenSignature = (
  tokenUrl: string,
  platformId: string,
  appVersion: string
) => {
  const url = new URL(tokenUrl);
  const deviceTime = Math.floor(Date.now() / 1000).toString();
  const raw = `9e2c|${url.pathname.slice(-7)}|${platformId}|${appVersion}|${deviceTime}||11ac`;

  return {
    sign: crypto.createHash('md5').update(raw).digest('hex').toLowerCase(),
    deviceTime,
  };
};

/**
 * SAMI 用の短命トークンを取る
 * Cookie もログインも要らないので、セッションと独立に動く
 */
export const fetchTtsToken = async (options: {
  tokenUrl: string;
  appVersion: string;
  platformId: string;
  signVersion: string;
  userAgent: string;
  origin: string;
}): Promise<{ token: string; appKey: string }> => {
  const signature = createTokenSignature(
    options.tokenUrl,
    options.platformId,
    options.appVersion
  );

  const response = await fetch(options.tokenUrl, {
    method: 'POST',
    headers: {
      Appvr: options.appVersion,
      'Device-Time': signature.deviceTime,
      Origin: options.origin,
      Pf: options.platformId,
      Sign: signature.sign,
      'Sign-Ver': options.signVersion,
      'User-Agent': options.userAgent,
    },
  });

  const payload = (await response.json()) as {
    ret?: string;
    errmsg?: string;
    data?: { token?: string; app_key?: string };
  };

  if (!payload?.data?.token || !payload.data.app_key) {
    throw new Error(
      `CapCut TTS token request failed: ${payload?.ret ?? '?'} ${payload?.errmsg ?? ''}`
    );
  }

  return { token: payload.data.token, appKey: payload.data.app_key };
};

/**
 * ランタイム差を吸収した WebSocket 接続
 *
 * Cloudflare Workers は new WebSocket() で外へ繋げないため
 * fetch の Upgrade を使う Node 22 は標準の WebSocket を持っている
 */
const connect = async (wsUrl: string): Promise<WebSocket> => {
  const response = await fetch(wsUrl.replace(/^ws/, 'http'), {
    headers: { Upgrade: 'websocket' },
  }).catch(() => null);

  const socket = (response as unknown as { webSocket?: WebSocket } | null)
    ?.webSocket;

  if (socket) {
    (socket as unknown as { accept(): void }).accept();
    return socket;
  }

  if (typeof globalThis.WebSocket === 'undefined') {
    throw new Error('No WebSocket implementation available in this runtime');
  }

  const native = new globalThis.WebSocket(wsUrl);
  native.binaryType = 'arraybuffer';

  await new Promise<void>((resolve, reject) => {
    native.addEventListener('open', () => resolve(), { once: true });
    native.addEventListener('error', () => reject(new Error('WebSocket connect failed')), {
      once: true,
    });
  });

  return native;
};

const parseMarks = (payload: unknown, includePhonemes: boolean) => {
  const alignment =
    isRecord(payload) && isRecord(payload.alignment) ? payload.alignment : null;

  const words: WordMark[] = [];
  const phonemes: PhonemeMark[] = [];

  if (alignment && Array.isArray(alignment.words)) {
    for (const raw of alignment.words) {
      if (!isRecord(raw)) continue;
      const start = asNumber(raw.start_time);
      const end = asNumber(raw.end_time);
      const word = typeof raw.word === 'string' ? raw.word : '';

      if (word && start !== null && end !== null) {
        words.push({ word, start, end });
      }
    }
  }

  if (includePhonemes && alignment && Array.isArray(alignment.phonemes)) {
    for (const raw of alignment.phonemes) {
      if (!isRecord(raw)) continue;
      const start = asNumber(raw.start_time);
      const end = asNumber(raw.end_time);
      const phone = typeof raw.phone === 'string' ? raw.phone : '';

      if (phone && start !== null && end !== null) {
        phonemes.push({ phone, start, end });
      }
    }
  }

  return { words, phonemes };
};

/**
 * WebSocket 経路で合成し、単語タイムスタンプまで受け取る
 *
 * REST 経路は caption を返さない (draft_info.subtitle_list が常に null) が
 * こちらは合成エンジンが出した alignment をそのまま返してくる
 * enable_text_seg と internal を送らないと alignment が空になる
 */
export const synthesizeWithTimestamps = async (
  options: TtsWebSocketOptions
): Promise<TtsWebSocketResult> => {
  const { token, appKey } = await fetchTtsToken(options);
  const socket = await connect(options.wsUrl);

  return new Promise<TtsWebSocketResult>((resolve, reject) => {
    const chunks: Buffer[] = [];
    let text = options.text;
    let duration: number | null = null;
    let words: WordMark[] = [];
    let phonemes: PhonemeMark[] = [];
    let settled = false;

    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        socket.close();
      } catch {
        // 閉じられなくても結果には影響しない
      }

      if (error) {
        reject(error);
        return;
      }

      const audio = Buffer.concat(chunks);

      // 空のまま 200 を返さない 話者が非対応だと無音で完了してしまう
      if (audio.byteLength === 0) {
        reject(
          new Error(
            'CapCut TTS WebSocket returned no audio. The speaker is likely not supported on this path'
          )
        );
        return;
      }

      resolve({ audio, text, duration, words, phonemes });
    };

    const timer = setTimeout(
      () => finish(new Error('CapCut TTS WebSocket timed out')),
      options.timeoutMs ?? 30_000
    );

    socket.addEventListener('message', (event: MessageEvent) => {
      const data = event.data;

      if (typeof data === 'string') {
        let frame: Record<string, unknown>;
        try {
          frame = JSON.parse(data) as Record<string, unknown>;
        } catch {
          return;
        }

        if (frame.event === 'TTSResponse' && typeof frame.payload === 'string') {
          try {
            const payload = JSON.parse(frame.payload) as Record<string, unknown>;
            duration = asNumber(payload.duration) ?? duration;
            if (typeof payload.text === 'string' && payload.text) {
              text = payload.text;
            }
            const marks = parseMarks(payload, options.includePhonemes ?? false);
            if (marks.words.length) words = marks.words;
            if (marks.phonemes.length) phonemes = marks.phonemes;
          } catch {
            // alignment が壊れていても音声は返す
          }
          return;
        }

        if (frame.event === 'TaskFinished') {
          finish();
          return;
        }

        if (frame.event === 'TaskFailed') {
          finish(
            new Error(
              `CapCut TTS WebSocket task failed: ${String(frame.status_text ?? '')}`
            )
          );
        }

        return;
      }

      chunks.push(
        Buffer.from(
          data instanceof ArrayBuffer ? new Uint8Array(data) : (data as Uint8Array)
        )
      );
    });

    socket.addEventListener('error', () =>
      finish(new Error('CapCut TTS WebSocket error'))
    );
    socket.addEventListener('close', () => finish());

    socket.send(
      JSON.stringify({
        token,
        appkey: appKey,
        namespace: 'TTS',
        event: 'StartTask',
        payload: JSON.stringify({
          text: options.text,
          speaker: options.speaker,
          audio_config: {
            enable_timestamp: true,
            format: 'mp3',
            sample_rate: options.sampleRate,
          },
          // この 2 つを落とすと alignment が空で返る 実測で確認済み
          enable_text_seg: true,
          internal: { phoneme_size: 40, max_paragraph_phoneme_size: 200 },
          appid: options.appId,
        }),
      })
    );
  });
};
