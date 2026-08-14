import { Hono } from 'hono';
import { AccountStore } from '@/lib/admin/accountStore';
import { safeEqual } from '@/lib/admin/secretBox';
import { adminPage } from '@/lib/admin/adminPage';
import type { D1Like } from '@/lib/storage/sessionStore';
import type { R2BucketLike } from '@/lib/storage';

export interface AdminDeps {
  db?: D1Like;
  adminToken?: string;
  encKey?: string;
  sessionBasePath: string;
  /** 試聴した音声を貯めておくバケット */
  bucket?: R2BucketLike;
  /** 合成を 1 回試して疎通を見る */
  probe: (
    email: string,
    password: string
  ) => Promise<{ ok: boolean; detail: string }>;
  /** 管理画面の試聴用 話者一覧 */
  listVoices: (
    email: string,
    password: string,
    language?: string
  ) => Promise<unknown[]>;
  /** 管理画面の試聴用 合成 資格情報はサーバー側だけで扱う */
  synthesize: (
    email: string,
    password: string,
    options: {
      text: string;
      speaker: string;
      speed: number;
      volume: number;
      timestamps: boolean;
    }
  ) => Promise<{
    audio: string;
    contentType: string;
    words?: Array<{ word: string; start: number; end: number }>;
    duration?: number | null;
  }>;
}

/** 試聴音声の置き場 セッションや preview キャッシュと混ぜない */
const SAVED_PREFIX = 'admin-preview/';

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });

/**
 * 管理 UI と管理 API
 *
 * 公開 URL に置く以上、トークン無しでは何も返さない
 * トークンは Authorization: Bearer か admin_token クッキーで受ける
 */
export const createAdminRoutes = (getDeps: () => AdminDeps) => {
  const admin = new Hono();

  const readToken = (request: Request): string => {
    const header = request.headers.get('authorization') ?? '';

    if (header.toLowerCase().startsWith('bearer ')) {
      return header.slice(7).trim();
    }

    const cookie = request.headers.get('cookie') ?? '';
    const match = cookie.match(/(?:^|;\s*)admin_token=([^;]+)/);

    return match ? decodeURIComponent(match[1]) : '';
  };

  // ログイン画面だけは素通し それ以外は必ずトークンを見る
  admin.use('*', async (c, next) => {
    const deps = getDeps();

    if (!deps.adminToken || !deps.encKey || !deps.db) {
      return json(
        {
          code: 'SERVICE_UNAVAILABLE',
          message:
            'Admin UI needs ADMIN_TOKEN, ADMIN_ENC_KEY secrets and the CAPCUT_DB binding',
        },
        503
      );
    }

    if (c.req.path === '/admin' || c.req.path === '/admin/') {
      return next();
    }

    if (!safeEqual(readToken(c.req.raw), deps.adminToken)) {
      return json({ code: 'FORBIDDEN', message: 'Invalid admin token' }, 401);
    }

    return next();
  });

  admin.get('/', () => new Response(adminPage, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  }));

  const storeOf = (deps: AdminDeps) =>
    new AccountStore(deps.db as D1Like, deps.encKey as string, deps.sessionBasePath);

  admin.get('/api/accounts', async () => {
    const deps = getDeps();
    return json(await storeOf(deps).list());
  });

  admin.post('/api/accounts', async (c) => {
    const deps = getDeps();
    const body = (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
    const email = typeof body.email === 'string' ? body.email.trim() : '';
    const password = typeof body.password === 'string' ? body.password : '';
    const label = typeof body.label === 'string' ? body.label.trim() : '';

    if (!email || !password) {
      return json(
        { code: 'VALIDATION_ERROR', message: 'email and password are required' },
        400
      );
    }

    await storeOf(deps).add(email, password, label);
    return json({ ok: true });
  });

  admin.delete('/api/accounts/:email', async (c) => {
    const deps = getDeps();
    await storeOf(deps).remove(decodeURIComponent(c.req.param('email')));
    return json({ ok: true });
  });

  admin.post('/api/accounts/:email/:action', async (c) => {
    const deps = getDeps();
    const store = storeOf(deps);
    const email = decodeURIComponent(c.req.param('email'));
    const action = c.req.param('action');

    if (action === 'enable' || action === 'disable') {
      await store.setEnabled(email, action === 'enable');
      return json({ ok: true });
    }

    if (action === 'reset') {
      await store.resetSession(email);
      return json({ ok: true });
    }

    if (action === 'clear-backoff') {
      await store.clearBackoff(email);
      return json({ ok: true });
    }

    if (action === 'test') {
      const credentials = await store.credentialsFor(email);

      if (!credentials) {
        return json(
          { code: 'NOT_FOUND', message: 'Account not found or disabled' },
          404
        );
      }

      const result = await deps.probe(credentials.email, credentials.password);
      await store.recordUsage(email, result.ok ? '' : result.detail);

      return json(result);
    }

    return json({ code: 'NOT_FOUND', message: 'Unknown action' }, 404);
  });

  /**
   * 試聴用の話者一覧
   * 資格情報はサーバー側で引くのでブラウザへは渡さない
   */
  admin.get('/api/tts/voices', async (c) => {
    const deps = getDeps();
    const account = c.req.query('account') ?? '';
    const language = c.req.query('language') ?? '';
    const credentials = await storeOf(deps).credentialsFor(account);

    if (!credentials) {
      return json(
        { code: 'NOT_FOUND', message: 'Account not found or disabled' },
        404
      );
    }

    try {
      return json(
        await deps.listVoices(
          credentials.email,
          credentials.password,
          language || undefined
        )
      );
    } catch (error) {
      return json(
        {
          code: 'BAD_GATEWAY',
          message: error instanceof Error ? error.message : 'Unknown error',
        },
        502
      );
    }
  });

  admin.post('/api/tts/preview', async (c) => {
    const deps = getDeps();
    const body = (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
    const account = typeof body.account === 'string' ? body.account : '';
    const text = typeof body.text === 'string' ? body.text.trim() : '';
    const speaker = typeof body.speaker === 'string' ? body.speaker : '';

    if (!text || !speaker) {
      return json(
        { code: 'VALIDATION_ERROR', message: 'text and speaker are required' },
        400
      );
    }

    const credentials = await storeOf(deps).credentialsFor(account);

    if (!credentials) {
      return json(
        { code: 'NOT_FOUND', message: 'Account not found or disabled' },
        404
      );
    }

    try {
      const result = await deps.synthesize(
        credentials.email,
        credentials.password,
        {
          text,
          speaker,
          speed: Number(body.speed) || 10,
          volume: Number(body.volume) || 10,
          timestamps: body.timestamps === true,
        }
      );
      await storeOf(deps).recordUsage(account, '');

      let savedKey: string | null = null;

      if (body.save === true && deps.bucket) {
        // 時刻を先頭に置くと、そのまま並べれば新しい順になる
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        savedKey = `${SAVED_PREFIX}${stamp}_${speaker}.mp3`;
        const bytes = Uint8Array.from(atob(result.audio), (ch) => ch.charCodeAt(0));

        await deps.bucket.put(savedKey, bytes.buffer as ArrayBuffer, {
          httpMetadata: { contentType: 'audio/mpeg' },
          customMetadata: {
            speaker,
            account,
            text: text.slice(0, 200),
          },
        });
      }

      return json({ ...result, savedKey });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      await storeOf(deps).recordUsage(account, message);

      return json({ code: 'BAD_GATEWAY', message }, 502);
    }
  });

  /**
   * 保存済みの試聴音声を新しい順に返す
   */
  admin.get('/api/files', async () => {
    const deps = getDeps();

    if (!deps.bucket?.list) {
      return json({ code: 'SERVICE_UNAVAILABLE', message: 'No bucket bound' }, 503);
    }

    const listed = await deps.bucket.list({ prefix: SAVED_PREFIX, limit: 200 });
    const files = listed.objects
      .map((object) => ({
        key: object.key,
        size: object.size,
        uploadedAt: object.uploaded ? object.uploaded.getTime() : 0,
        speaker: object.customMetadata?.speaker ?? '',
        account: object.customMetadata?.account ?? '',
        text: object.customMetadata?.text ?? '',
      }))
      .sort((left, right) => right.uploadedAt - left.uploadedAt);

    return json(files);
  });

  /**
   * 音声そのものを返す トークンが要るので直リンクは配れない
   */
  admin.get('/api/files/*', async (c) => {
    const deps = getDeps();
    const key = decodeURIComponent(new URL(c.req.url).pathname.replace('/admin/api/files/', ''));

    if (!key.startsWith(SAVED_PREFIX) || !deps.bucket) {
      return json({ code: 'NOT_FOUND', message: 'Unknown file' }, 404);
    }

    const object = await deps.bucket.get(key);

    if (!object) {
      return json({ code: 'NOT_FOUND', message: 'Unknown file' }, 404);
    }

    return new Response(await object.arrayBuffer(), {
      headers: {
        'Content-Type': object.httpMetadata?.contentType ?? 'audio/mpeg',
        'Content-Disposition': `inline; filename="${key.split('/').pop()}"`,
      },
    });
  });

  admin.delete('/api/files/*', async (c) => {
    const deps = getDeps();
    const key = decodeURIComponent(new URL(c.req.url).pathname.replace('/admin/api/files/', ''));

    if (!key.startsWith(SAVED_PREFIX) || !deps.bucket?.delete) {
      return json({ code: 'NOT_FOUND', message: 'Unknown file' }, 404);
    }

    await deps.bucket.delete(key);
    return json({ ok: true });
  });

  return admin;
};
