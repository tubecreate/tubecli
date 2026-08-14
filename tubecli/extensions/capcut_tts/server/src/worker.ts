import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { setEnvSource } from '@/configs/env';
import { ApiError, apiError, ErrorCode } from '@/lib/apiError';
import { CapCutApiError } from '@/lib/capcut/responseUtils';
import { R2BlobStorage, setBlobStorage } from '@/lib/storage';
import { D1SessionStore, setSessionStore } from '@/lib/storage/sessionStore';
import type { D1Like } from '@/lib/storage/sessionStore';
import type { R2BucketLike } from '@/lib/storage';
import { SynthesizeBodySchema, SynthesizeQuerySchema } from '@/schemas/synthesize';
import { capCutService, getCapCutService } from '@/services/CapCutService';
import { extractRequestCredentials } from '@/lib/capcut/requestCredentials';
import { capCutLegacySpeakers } from '@/models/capcutLegacySpeakers';
import { toMarkedResponse } from '@/lib/audioResponse';
import { createAdminRoutes } from '@/lib/admin/adminRoutes';

/**
 * wrangler.toml で宣言する bindings
 */
export interface WorkerBindings extends Record<string, unknown> {
  /** プレビュー音声の置き場 */
  CAPCUT_BUCKET: R2BucketLike;
  /** セッションを 1 行で共有する 全 isolate で 1 セッションにするため */
  CAPCUT_DB?: D1Like;
  /** 管理 UI のアクセストークン 無ければ管理 UI は動かない */
  ADMIN_TOKEN?: string;
  /** 資格情報の暗号化キー */
  ADMIN_ENC_KEY?: string;
}

/** 管理 API から参照する現在の bindings */
let currentBindings: WorkerBindings | null = null;

let bootstrapped = false;

/**
 * 環境変数と保存先を Workers の bindings から一度だけ組み立てる
 *
 * isolate は使い回されるので二度目以降は何もしない
 */
const bootstrap = (bindings: WorkerBindings) => {
  if (bootstrapped) {
    return;
  }

  setEnvSource(bindings as Record<string, unknown>);
  setBlobStorage(new R2BlobStorage(bindings.CAPCUT_BUCKET));
  setSessionStore(bindings.CAPCUT_DB ? new D1SessionStore(bindings.CAPCUT_DB) : null);
  bootstrapped = true;
};

/**
 * リクエスト由来の資格情報があればそのアカウント用サービスを返す
 */
const serviceFor = (
  c: {
    req: { header: (k: string) => string | undefined };
    set?: (k: 'capcutService', v: unknown) => void;
  },
  body?: Record<string, unknown>
) => {
  const service = getCapCutService(
    extractRequestCredentials({
      headers: {
        'x-capcut-email': c.req.header('x-capcut-email'),
        'x-capcut-password': c.req.header('x-capcut-password'),
      },
      body,
    })
  );
  c.set?.('capcutService', service);

  return service;
};

type Vars = { capcutService?: ReturnType<typeof getCapCutService> };

const app = new Hono<{ Bindings: WorkerBindings; Variables: Vars }>();

app.use('*', async (c, next) => {
  bootstrap(c.env);
  currentBindings = c.env;
  await next();

  // レスポンス後に未完了の promise は打ち切られるので waitUntil に載せる
  // セッション保存はここ 1 回だけ 各サブリクエストごとには書かない
  // このリクエストが実際に使ったインスタンスを保存する
  // 既定インスタンス固定だとアカウント別のセッションが保存されない
  const used = c.get('capcutService') ?? capCutService;
  c.executionCtx?.waitUntil(used.flushSession());
});

app.use('*', cors());

/**
 * 音声レスポンスを組み立てる
 */
const audioResponse = (
  buffer: Buffer,
  contentType: string,
  fileName?: string
) => {
  const headers: Record<string, string> = {
    'Content-Type': contentType,
    'Content-Length': String(buffer.byteLength),
  };

  if (fileName) {
    headers['Content-Disposition'] = `inline; filename="${fileName}"`;
  }

  return new Response(
    buffer.buffer.slice(
      buffer.byteOffset,
      buffer.byteOffset + buffer.byteLength
    ) as ArrayBuffer,
    { status: 200, headers }
  );
};

app.route(
  '/admin',
  createAdminRoutes(() => ({
    db: currentBindings?.CAPCUT_DB,
    adminToken: currentBindings?.ADMIN_TOKEN,
    encKey: currentBindings?.ADMIN_ENC_KEY,
    sessionBasePath: String(currentBindings?.CAPCUT_SESSION_STORE_PATH ?? 'capcut-session.json'),
    bucket: currentBindings?.CAPCUT_BUCKET,
    // 実際に 1 回合成してみて、その資格情報が使えるか確かめる
    listVoices: async (email, password, language) =>
      getCapCutService({ email, password }).listSpeakers(
        language ? { language } : {}
      ),
    synthesize: async (email, password, opts) => {
      const service = getCapCutService({ email, password });
      const base = {
        text: opts.text,
        speaker: opts.speaker,
        type: 0,
        pitch: 10,
        speed: opts.speed,
        volume: opts.volume,
      };

      if (opts.timestamps) {
        const marked = await service.synthesizeWithMarks(base);

        return {
          audio: marked.audio.toString('base64'),
          contentType: 'audio/mpeg',
          words: marked.words,
          duration: marked.duration,
        };
      }

      const audio = await service.synthesizeBuffer(base);

      return {
        audio: audio.buffer.toString('base64'),
        contentType: audio.contentType,
      };
    },
    probe: async (email, password) => {
      try {
        const service = getCapCutService({ email, password });
        // listSpeakers はログイン失敗を握り潰して fallback を返すため
        // 疎通確認には使えない 認証そのものを見る
        await service.ensureAuthenticated();
        const speakers = await service.listSpeakers({ language: 'vi' });

        return {
          ok: true,
          detail: `Đăng nhập OK · ${speakers.length} giọng tiếng Việt`,
        };
      } catch (error) {
        return {
          ok: false,
          detail: error instanceof Error ? error.message : 'Unknown error',
        };
      }
    },
  }))
);

app.get('/v2/speakers', async (c) => {
  const language = c.req.query('language') ?? c.req.query('country');
  const category = c.req.query('category');

  return c.json(await serviceFor(c).listSpeakers({ language, category }));
});

app.get('/v2/languages', async (c) =>
  c.json(await serviceFor(c).listSpeakerLanguages())
);

app.get('/v2/speakers/:speakerId/preview', async (c) => {
  const speakerId = c.req.param('speakerId')?.trim();

  if (!speakerId) {
    throw apiError(ErrorCode.NOT_FOUND, 'Speaker');
  }

  const audio = await serviceFor(c).getSpeakerPreviewAudio(speakerId);
  return audioResponse(audio.buffer, audio.contentType, audio.fileName);
});

app.get('/v2/synthesize', async (c) => {
  const parsed = SynthesizeQuerySchema.safeParse(
    Object.fromEntries(new URL(c.req.url).searchParams)
  );

  if (!parsed.success) {
    throw apiError(ErrorCode.VALIDATION_ERROR, parsed.error.issues);
  }

  if (parsed.data.timestamps) {
    const marked = await serviceFor(c).synthesizeWithMarks(parsed.data);
    return c.json(toMarkedResponse(marked, parsed.data.phonemes ?? false));
  }

  const audio = await serviceFor(c).synthesizeBuffer(parsed.data);
  return audioResponse(audio.buffer, audio.contentType, audio.fileName);
});

app.post('/v2/synthesize', async (c) => {
  const body = await c.req.json().catch(() => ({}));
  const parsed = SynthesizeBodySchema.safeParse(body);

  if (!parsed.success) {
    throw apiError(ErrorCode.VALIDATION_ERROR, parsed.error.issues);
  }

  const service = serviceFor(c, body as Record<string, unknown>);

  if (parsed.data.timestamps) {
    const marked = await service.synthesizeWithMarks(parsed.data);
    return c.json(toMarkedResponse(marked, parsed.data.phonemes ?? false));
  }

  const audio = await service.synthesizeBuffer(parsed.data);
  return audioResponse(audio.buffer, audio.contentType, audio.fileName);
});

app.get('/v1/models', (c) =>
  c.json(
    capCutLegacySpeakers.map((model) => ({
      id: model.id,
      name: model.title,
      description: model.description,
      language: model.language,
      type: model.type,
    }))
  )
);

// /v1/synthesize は ws による WebSocket 実装に依存しており Workers では動かないため出さない
app.all('/v1/synthesize', () => {
  throw apiError(
    ErrorCode.SERVICE_UNAVAILABLE,
    'Legacy synthesize is not available on the Workers deployment. Use /v2/synthesize'
  );
});

app.notFound(() => {
  throw apiError(ErrorCode.FORBIDDEN);
});

app.onError((error, c) => {
  if (error instanceof ApiError) {
    return c.json(error.toResponse(), error.statusCode as 400);
  }

  // 呼び出し側の入力が原因のものは理由をそのまま返す
  if (error instanceof CapCutApiError && error.statusCode === 400) {
    return c.json({ code: ErrorCode.VALIDATION_ERROR, message: error.message }, 400);
  }

  // 設定漏れを 500 に埋もれさせない どの変数が足りないかまで返す
  // 変数名自体は秘密ではないので、そのまま出して復旧を早くする
  if (
    error instanceof Error &&
    error.message.startsWith('Invalid environment variables:')
  ) {
    console.error('Worker is not configured', error);

    return c.json(
      { code: ErrorCode.SERVICE_UNAVAILABLE, message: error.message },
      503
    );
  }

  console.error('Unexpected worker error', error);

  return c.json(
    { code: ErrorCode.INTERNAL_SERVER_ERROR, message: 'Internal server error' },
    500
  );
});

export default app;
