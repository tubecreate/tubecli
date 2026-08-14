"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const hono_1 = require("hono");
const cors_1 = require("hono/cors");
const env_1 = require("./configs/env");
const apiError_1 = require("./lib/apiError");
const responseUtils_1 = require("./lib/capcut/responseUtils");
const storage_1 = require("./lib/storage");
const sessionStore_1 = require("./lib/storage/sessionStore");
const synthesize_1 = require("./schemas/synthesize");
const CapCutService_1 = require("./services/CapCutService");
const requestCredentials_1 = require("./lib/capcut/requestCredentials");
const capcutLegacySpeakers_1 = require("./models/capcutLegacySpeakers");
const audioResponse_1 = require("./lib/audioResponse");
const adminRoutes_1 = require("./lib/admin/adminRoutes");
/** 管理 API から参照する現在の bindings */
let currentBindings = null;
let bootstrapped = false;
/**
 * 環境変数と保存先を Workers の bindings から一度だけ組み立てる
 *
 * isolate は使い回されるので二度目以降は何もしない
 */
const bootstrap = (bindings) => {
    if (bootstrapped) {
        return;
    }
    (0, env_1.setEnvSource)(bindings);
    (0, storage_1.setBlobStorage)(new storage_1.R2BlobStorage(bindings.CAPCUT_BUCKET));
    (0, sessionStore_1.setSessionStore)(bindings.CAPCUT_DB ? new sessionStore_1.D1SessionStore(bindings.CAPCUT_DB) : null);
    bootstrapped = true;
};
/**
 * リクエスト由来の資格情報があればそのアカウント用サービスを返す
 */
const serviceFor = (c, body) => {
    const service = (0, CapCutService_1.getCapCutService)((0, requestCredentials_1.extractRequestCredentials)({
        headers: {
            'x-capcut-email': c.req.header('x-capcut-email'),
            'x-capcut-password': c.req.header('x-capcut-password'),
        },
        body,
    }));
    c.set?.('capcutService', service);
    return service;
};
const app = new hono_1.Hono();
app.use('*', async (c, next) => {
    bootstrap(c.env);
    currentBindings = c.env;
    await next();
    // レスポンス後に未完了の promise は打ち切られるので waitUntil に載せる
    // セッション保存はここ 1 回だけ 各サブリクエストごとには書かない
    // このリクエストが実際に使ったインスタンスを保存する
    // 既定インスタンス固定だとアカウント別のセッションが保存されない
    const used = c.get('capcutService') ?? CapCutService_1.capCutService;
    c.executionCtx?.waitUntil(used.flushSession());
});
app.use('*', (0, cors_1.cors)());
/**
 * 音声レスポンスを組み立てる
 */
const audioResponse = (buffer, contentType, fileName) => {
    const headers = {
        'Content-Type': contentType,
        'Content-Length': String(buffer.byteLength),
    };
    if (fileName) {
        headers['Content-Disposition'] = `inline; filename="${fileName}"`;
    }
    return new Response(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength), { status: 200, headers });
};
app.route('/admin', (0, adminRoutes_1.createAdminRoutes)(() => ({
    db: currentBindings?.CAPCUT_DB,
    adminToken: currentBindings?.ADMIN_TOKEN,
    encKey: currentBindings?.ADMIN_ENC_KEY,
    sessionBasePath: String(currentBindings?.CAPCUT_SESSION_STORE_PATH ?? 'capcut-session.json'),
    bucket: currentBindings?.CAPCUT_BUCKET,
    // 実際に 1 回合成してみて、その資格情報が使えるか確かめる
    listVoices: async (email, password, language) => (0, CapCutService_1.getCapCutService)({ email, password }).listSpeakers(language ? { language } : {}),
    synthesize: async (email, password, opts) => {
        const service = (0, CapCutService_1.getCapCutService)({ email, password });
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
            const service = (0, CapCutService_1.getCapCutService)({ email, password });
            // listSpeakers はログイン失敗を握り潰して fallback を返すため
            // 疎通確認には使えない 認証そのものを見る
            await service.ensureAuthenticated();
            const speakers = await service.listSpeakers({ language: 'vi' });
            return {
                ok: true,
                detail: `Đăng nhập OK · ${speakers.length} giọng tiếng Việt`,
            };
        }
        catch (error) {
            return {
                ok: false,
                detail: error instanceof Error ? error.message : 'Unknown error',
            };
        }
    },
})));
app.get('/v2/speakers', async (c) => {
    const language = c.req.query('language') ?? c.req.query('country');
    const category = c.req.query('category');
    return c.json(await serviceFor(c).listSpeakers({ language, category }));
});
app.get('/v2/languages', async (c) => c.json(await serviceFor(c).listSpeakerLanguages()));
app.get('/v2/speakers/:speakerId/preview', async (c) => {
    const speakerId = c.req.param('speakerId')?.trim();
    if (!speakerId) {
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.NOT_FOUND, 'Speaker');
    }
    const audio = await serviceFor(c).getSpeakerPreviewAudio(speakerId);
    return audioResponse(audio.buffer, audio.contentType, audio.fileName);
});
app.get('/v2/synthesize', async (c) => {
    const parsed = synthesize_1.SynthesizeQuerySchema.safeParse(Object.fromEntries(new URL(c.req.url).searchParams));
    if (!parsed.success) {
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.VALIDATION_ERROR, parsed.error.issues);
    }
    if (parsed.data.timestamps) {
        const marked = await serviceFor(c).synthesizeWithMarks(parsed.data);
        return c.json((0, audioResponse_1.toMarkedResponse)(marked, parsed.data.phonemes ?? false));
    }
    const audio = await serviceFor(c).synthesizeBuffer(parsed.data);
    return audioResponse(audio.buffer, audio.contentType, audio.fileName);
});
app.post('/v2/synthesize', async (c) => {
    const body = await c.req.json().catch(() => ({}));
    const parsed = synthesize_1.SynthesizeBodySchema.safeParse(body);
    if (!parsed.success) {
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.VALIDATION_ERROR, parsed.error.issues);
    }
    const service = serviceFor(c, body);
    if (parsed.data.timestamps) {
        const marked = await service.synthesizeWithMarks(parsed.data);
        return c.json((0, audioResponse_1.toMarkedResponse)(marked, parsed.data.phonemes ?? false));
    }
    const audio = await service.synthesizeBuffer(parsed.data);
    return audioResponse(audio.buffer, audio.contentType, audio.fileName);
});
app.get('/v1/models', (c) => c.json(capcutLegacySpeakers_1.capCutLegacySpeakers.map((model) => ({
    id: model.id,
    name: model.title,
    description: model.description,
    language: model.language,
    type: model.type,
}))));
// /v1/synthesize は ws による WebSocket 実装に依存しており Workers では動かないため出さない
app.all('/v1/synthesize', () => {
    throw (0, apiError_1.apiError)(apiError_1.ErrorCode.SERVICE_UNAVAILABLE, 'Legacy synthesize is not available on the Workers deployment. Use /v2/synthesize');
});
app.notFound(() => {
    throw (0, apiError_1.apiError)(apiError_1.ErrorCode.FORBIDDEN);
});
app.onError((error, c) => {
    if (error instanceof apiError_1.ApiError) {
        return c.json(error.toResponse(), error.statusCode);
    }
    // 呼び出し側の入力が原因のものは理由をそのまま返す
    if (error instanceof responseUtils_1.CapCutApiError && error.statusCode === 400) {
        return c.json({ code: apiError_1.ErrorCode.VALIDATION_ERROR, message: error.message }, 400);
    }
    // 設定漏れを 500 に埋もれさせない どの変数が足りないかまで返す
    // 変数名自体は秘密ではないので、そのまま出して復旧を早くする
    if (error instanceof Error &&
        error.message.startsWith('Invalid environment variables:')) {
        console.error('Worker is not configured', error);
        return c.json({ code: apiError_1.ErrorCode.SERVICE_UNAVAILABLE, message: error.message }, 503);
    }
    console.error('Unexpected worker error', error);
    return c.json({ code: apiError_1.ErrorCode.INTERNAL_SERVER_ERROR, message: 'Internal server error' }, 500);
});
exports.default = app;
//# sourceMappingURL=worker.js.map