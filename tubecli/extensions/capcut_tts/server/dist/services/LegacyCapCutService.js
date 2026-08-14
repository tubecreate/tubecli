"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.startLegacyTokenTask = exports.legacyCapCutService = void 0;
const node_stream_1 = require("node:stream");
const ws_1 = require("ws");
const env_1 = __importDefault(require("../configs/env"));
const capcutLegacySpeakers_1 = require("../models/capcutLegacySpeakers");
const logger_1 = __importDefault(require("../services/logger"));
const LEGACY_CAPCUT_APP_ID = '348188';
const LEGACY_CAPCUT_APP_VERSION = '5.8.0';
const LEGACY_CAPCUT_SAMPLE_RATE = 24000;
const LEGACY_DEFAULT_SPEAKER = 'BV016_streaming';
const LEGACY_PLATFORM = '7';
const LEGACY_SIGN_VERSION = '1';
const LEGACY_TOKEN_REQUEST_TIMEOUT_MS = 10_000;
const LEGACY_TOKEN_RETRY_DELAY_MS = 60_000;
class LegacyCapCutService {
    tokenState = {
        token: '',
        appKey: '',
        refreshedAt: 0,
    };
    refreshPromise = null;
    refreshTimer = null;
    /**
     * 旧 token + websocket フローに必要な環境変数が揃っているか
     */
    isConfigured() {
        return Boolean(env_1.default.LEGACY_DEVICE_TIME && env_1.default.LEGACY_SIGN);
    }
    /**
     * 起動時の事前ウォームアップ
     */
    async warmup() {
        if (!this.isConfigured()) {
            return;
        }
        await this.refreshToken();
    }
    /**
     * 旧 websocket フローで音声をバッファとして取得する
     */
    async synthesizeBuffer(options) {
        const tokenState = await this.getTokenState();
        const buffer = await this.getAudioBuffer(tokenState, options);
        return {
            buffer,
            contentType: 'audio/wav',
            contentLength: String(buffer.byteLength),
        };
    }
    /**
     * 旧 websocket フローで音声をストリームとして取得する
     */
    async synthesizeStream(options) {
        const tokenState = await this.getTokenState();
        return {
            stream: this.createAudioStream(tokenState, options),
            contentType: 'audio/wav',
            contentLength: undefined,
            fileName: undefined,
        };
    }
    /**
     * 現在有効な token を返す
     */
    async getTokenState() {
        this.assertConfigured();
        if (this.isTokenReady()) {
            return this.tokenState;
        }
        return this.refreshToken();
    }
    /**
     * token を取得し、以降の更新も予約する
     */
    async refreshToken() {
        this.assertConfigured();
        if (this.refreshPromise) {
            return this.refreshPromise;
        }
        this.refreshPromise = (async () => {
            try {
                const tokenResponse = await this.fetchToken();
                this.tokenState.token = tokenResponse.data.token;
                this.tokenState.appKey = tokenResponse.data.app_key;
                this.tokenState.refreshedAt = Date.now();
                logger_1.default.info('Legacy CapCut token refreshed');
                this.scheduleRefresh(env_1.default.LEGACY_TOKEN_INTERVAL * 60 * 60 * 1000);
                return this.tokenState;
            }
            catch (error) {
                this.scheduleRefresh(LEGACY_TOKEN_RETRY_DELAY_MS);
                if (this.isTokenReady()) {
                    logger_1.default.warn('Legacy token refresh failed. Using the previous token until the next retry', { error });
                    return this.tokenState;
                }
                logger_1.default.error('Legacy token refresh failed', error);
                throw error;
            }
        })().finally(() => {
            this.refreshPromise = null;
        });
        return this.refreshPromise;
    }
    /**
     * 起動中のバックグラウンド更新を開始する
     */
    async startRefreshTask() {
        if (!this.isConfigured()) {
            logger_1.default.info('Legacy CapCut endpoint is disabled because LEGACY_DEVICE_TIME / LEGACY_SIGN are not configured');
            return;
        }
        try {
            await this.warmup();
        }
        catch (error) {
            logger_1.default.warn('Initial legacy token fetch failed. The service will retry in the background', { error });
        }
    }
    /**
     * 旧 token API を叩く
     */
    async fetchToken() {
        const response = await fetch(`${env_1.default.LEGACY_CAPCUT_API_URL}/common/tts/token`, {
            method: 'POST',
            headers: new Headers({
                Appvr: LEGACY_CAPCUT_APP_VERSION,
                'Device-Time': env_1.default.LEGACY_DEVICE_TIME ?? '',
                Origin: env_1.default.CAPCUT_WEB_URL,
                Pf: LEGACY_PLATFORM,
                Sign: env_1.default.LEGACY_SIGN ?? '',
                'Sign-Ver': LEGACY_SIGN_VERSION,
                'User-Agent': env_1.default.USER_AGENT,
            }),
            signal: AbortSignal.timeout(LEGACY_TOKEN_REQUEST_TIMEOUT_MS),
        });
        if (!response.ok) {
            throw new Error(`Legacy token request failed: ${response.status} ${response.statusText}`);
        }
        const payload = (await response.json());
        if (!payload?.data?.token || !payload?.data?.app_key) {
            throw new Error('Legacy token response did not contain token metadata');
        }
        return payload;
    }
    /**
     * バッファ用 websocket フロー
     */
    async getAudioBuffer(tokenState, options) {
        return new Promise((resolve, reject) => {
            let audioBuffer = Buffer.alloc(0);
            let settled = false;
            const startedAt = Date.now();
            const ws = new ws_1.WebSocket(this.getWebSocketUrl());
            const resolveOnce = (buffer) => {
                if (settled) {
                    return;
                }
                settled = true;
                resolve(buffer);
            };
            const rejectOnce = (error) => {
                if (settled) {
                    return;
                }
                settled = true;
                reject(error);
            };
            ws.on('open', () => {
                logger_1.default.debug('Connected to legacy CapCut websocket');
                ws.send(this.buildTaskMessage(tokenState, options));
            });
            ws.on('message', (data) => {
                const taskStatus = parseLegacyTaskStatus(data);
                if (!taskStatus) {
                    audioBuffer = Buffer.concat([audioBuffer, rawDataToBuffer(data)]);
                    return;
                }
                if (taskStatus.event === 'TaskStarted') {
                    logger_1.default.debug(`Legacy task started: ${taskStatus.task_id}`);
                    return;
                }
                if (taskStatus.event === 'TaskFinished') {
                    logger_1.default.debug(`Legacy task finished: ${taskStatus.task_id} / Audio Buffer Size: ${audioBuffer.byteLength} bytes / Tasking Time: ${Date.now() - startedAt}ms`);
                    ws.close();
                    resolveOnce(audioBuffer);
                    return;
                }
                if (taskStatus.event === 'TaskFailed' ||
                    taskStatus.status_code >= 400) {
                    ws.close();
                    rejectOnce(new Error(`Legacy task failed: ${taskStatus.status_code} ${taskStatus.status_text}`));
                }
            });
            ws.on('error', (error) => {
                logger_1.default.error('WebSocket error while buffering legacy audio', error);
                rejectOnce(error instanceof Error
                    ? error
                    : new Error('Legacy CapCut websocket error'));
            });
            ws.on('close', () => {
                if (!settled) {
                    rejectOnce(new Error('Legacy CapCut websocket closed before the task finished'));
                }
            });
        });
    }
    /**
     * ストリーム用 websocket フロー
     */
    createAudioStream(tokenState, options) {
        const audioStream = new node_stream_1.Readable({
            read() { },
        });
        const startedAt = Date.now();
        const ws = new ws_1.WebSocket(this.getWebSocketUrl());
        let taskFinished = false;
        ws.on('open', () => {
            logger_1.default.debug('Connected to legacy CapCut websocket');
            ws.send(this.buildTaskMessage(tokenState, options));
        });
        ws.on('message', (data) => {
            const taskStatus = parseLegacyTaskStatus(data);
            if (!taskStatus) {
                audioStream.push(rawDataToBuffer(data));
                return;
            }
            if (taskStatus.event === 'TaskStarted') {
                logger_1.default.debug(`Legacy task started: ${taskStatus.task_id}`);
                return;
            }
            if (taskStatus.event === 'TaskFinished') {
                taskFinished = true;
                logger_1.default.debug(`Legacy task finished: ${taskStatus.task_id} / Tasking Time: ${Date.now() - startedAt}ms`);
                ws.close();
                audioStream.push(null);
                return;
            }
            if (taskStatus.event === 'TaskFailed' || taskStatus.status_code >= 400) {
                audioStream.destroy(new Error(`Legacy task failed: ${taskStatus.status_code} ${taskStatus.status_text}`));
            }
        });
        ws.on('error', (error) => {
            logger_1.default.error('WebSocket error while streaming legacy audio', error);
            audioStream.destroy(error instanceof Error
                ? error
                : new Error('Legacy CapCut websocket error'));
        });
        ws.on('close', () => {
            if (!taskFinished &&
                !audioStream.destroyed &&
                !audioStream.readableEnded) {
                audioStream.destroy(new Error('Legacy CapCut websocket closed before the task finished'));
            }
        });
        audioStream.on('close', () => {
            if (ws.readyState === ws_1.WebSocket.CONNECTING ||
                ws.readyState === ws_1.WebSocket.OPEN) {
                ws.close();
            }
        });
        return audioStream;
    }
    /**
     * websocket に送る StartTask メッセージを作る
     */
    buildTaskMessage(tokenState, options) {
        const payload = {
            text: options.text,
            speaker: resolveLegacySpeaker(options.type),
            pitch: options.pitch,
            speed: options.speed,
            volume: options.volume,
            rate: LEGACY_CAPCUT_SAMPLE_RATE,
            appid: LEGACY_CAPCUT_APP_ID,
        };
        const taskMessage = {
            token: tokenState.token,
            appkey: tokenState.appKey,
            namespace: 'TTS',
            event: 'StartTask',
            payload: JSON.stringify(payload),
        };
        return JSON.stringify(taskMessage);
    }
    /**
     * websocket の接続先 URL を返す
     */
    getWebSocketUrl() {
        return `${env_1.default.LEGACY_BYTEINTL_API_URL}/ws`;
    }
    /**
     * token 更新予約を入れ直す
     */
    scheduleRefresh(delayMs) {
        if (this.refreshTimer) {
            clearTimeout(this.refreshTimer);
        }
        this.refreshTimer = setTimeout(() => {
            void this.refreshToken();
        }, delayMs);
        this.refreshTimer.unref?.();
    }
    /**
     * token キャッシュが埋まっているか
     */
    isTokenReady() {
        return Boolean(this.tokenState.token && this.tokenState.appKey);
    }
    /**
     * 旧ルートが利用可能かをチェックする
     */
    assertConfigured() {
        if (this.isConfigured()) {
            return;
        }
        throw new Error('Legacy CapCut endpoint is not configured. Set LEGACY_DEVICE_TIME and LEGACY_SIGN');
    }
}
const resolveLegacySpeaker = (type) => capcutLegacySpeakers_1.legacySpeakers[type] ?? LEGACY_DEFAULT_SPEAKER;
const rawDataToBuffer = (data) => {
    if (Buffer.isBuffer(data)) {
        return data;
    }
    if (Array.isArray(data)) {
        return Buffer.concat(data.map((chunk) => Buffer.from(chunk)));
    }
    return Buffer.from(data);
};
const parseLegacyTaskStatus = (data) => {
    try {
        return JSON.parse(rawDataToBuffer(data).toString());
    }
    catch {
        return null;
    }
};
exports.legacyCapCutService = new LegacyCapCutService();
const startLegacyTokenTask = async () => {
    await exports.legacyCapCutService.startRefreshTask();
};
exports.startLegacyTokenTask = startLegacyTokenTask;
exports.default = exports.legacyCapCutService;
//# sourceMappingURL=LegacyCapCutService.js.map