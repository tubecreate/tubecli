"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.startCapCutSessionTask = exports.capCutService = exports.getCapCutService = void 0;
const node_crypto_1 = __importDefault(require("node:crypto"));
const node_stream_1 = require("node:stream");
const checkEmailRegistered_1 = require("../api/capcut-login/api/checkEmailRegistered");
const emailLogin_1 = require("../api/capcut-login/api/emailLogin");
const resolveRegion_1 = require("../api/capcut-login/api/resolveRegion");
const userLogin_1 = require("../api/capcut-login/api/userLogin");
const apiClient_1 = require("../api/capcut-edit/apiClient");
const createMultiPlatformTts_1 = require("../api/capcut-edit/api/createMultiPlatformTts");
const createTtsTask_1 = require("../api/capcut-edit/api/createTtsTask");
const getUserWorkspaces_1 = require("../api/capcut-edit/api/getUserWorkspaces");
const getVoiceModels_1 = require("../api/capcut-edit/api/getVoiceModels");
const getVoicePanelInfo_1 = require("../api/capcut-edit/api/getVoicePanelInfo");
const queryTtsTask_1 = require("../api/capcut-edit/api/queryTtsTask");
const downloadAudio_1 = require("../api/capcut-media/api/downloadAudio");
const getAccountInfo_1 = require("../api/capcut-web/api/getAccountInfo");
const getLoginPage_1 = require("../api/capcut-web/api/getLoginPage");
const env_1 = __importDefault(require("../configs/env"));
const cookieJar_1 = require("../lib/capcut/cookieJar");
const storage_1 = require("../lib/storage");
const sessionStore_1 = require("../lib/storage/sessionStore");
const constants_1 = require("../lib/capcut/constants");
const responseUtils_1 = require("../lib/capcut/responseUtils");
const string_1 = require("../lib/string");
const ttsWebSocket_1 = require("../lib/capcut/ttsWebSocket");
const voiceUtils_1 = require("../lib/capcut/voiceUtils");
const capcutVoiceCategories_1 = require("../models/capcutVoiceCategories");
const capcutSpeakers_1 = require("../models/capcutSpeakers");
const capcutVoiceQuality_1 = require("../models/capcutVoiceQuality");
const CapCutBundleService_1 = __importDefault(require("../services/CapCutBundleService"));
const logger_1 = __importDefault(require("../services/logger"));
const capcutUtils_1 = require("../utils/capcutUtils");
const httpUtils_1 = require("../utils/httpUtils");
const { appId, editorAppVersion, loginSdkVersion, platformId, sessionValidateMs, sessionLifetimeMs, loginLockMs, loginWaitAttempts, loginWaitIntervalMs, loginFailureBackoffMs, loginAttemptLimitBackoffMs, signVersion, ttsMaxPollAttempts, ttsPlatform, ttsPlatformIds, ttsPollIntervalMs, ttsScene, ttsSmartToolType, ttsTokenPath, ttsWebSocketUrl, ttsSampleRate, voiceCacheMs, voiceCategoryCacheMs, voiceFallbackRetryMs, voiceListMaxPages, voiceListPageSize, voicePanel, voicePanelInfoPath, voicePanelSource, webAppVersion, } = constants_1.capCutConstants;
class CapCutService {
    cookieJar = new cookieJar_1.CookieJar();
    credentials;
    constructor(credentials = null) {
        this.credentials = credentials;
    }
    get accountEmail() {
        return this.credentials?.email ?? env_1.default.CAPCUT_EMAIL;
    }
    get accountPassword() {
        return this.credentials?.password ?? env_1.default.CAPCUT_PASSWORD;
    }
    /**
     * セッション JSON の保存キー
     * Node ではファイルパス、Workers では R2 のオブジェクトキーになる
     *
     * アカウントごとにセッションが混ざらないよう、既定以外の資格情報では
     * メールアドレスのハッシュを鍵へ混ぜる
     */
    get sessionStoreKey() {
        const base = env_1.default.CAPCUT_SESSION_STORE_PATH;
        if (!this.credentials) {
            return base;
        }
        const suffix = node_crypto_1.default
            .createHash('sha256')
            .update(this.credentials.email.trim().toLowerCase())
            .digest('hex')
            .slice(0, 16);
        return base.replace(/(\.json)?$/i, `.${suffix}$1`);
    }
    restorePromise = null;
    // 以下 3 つは env に依存するため、フィールド初期化ではなく初回参照時に解決する
    // Workers では bindings が届く前にモジュールが評価されるため
    /**
     * アカウント固有の派生シード
     *
     * env で固定した device fingerprint を全アカウントで共有すると、
     * 別アカウントのログイン失敗が本体アカウントまで巻き込んで
     * CapCut 側のログイン試行制限に引っかかる 実際に発生させたので分離する
     */
    get accountSeed() {
        if (!this.credentials) {
            return null;
        }
        return node_crypto_1.default
            .createHash('sha256')
            .update(this.credentials.email.trim().toLowerCase())
            .digest('hex');
    }
    deviceIdValue = null;
    get deviceId() {
        if (!this.deviceIdValue) {
            const seed = this.accountSeed;
            this.deviceIdValue = seed
                ? `7${BigInt('0x' + seed.slice(0, 15)).toString().padStart(18, '0').slice(0, 18)}`
                : (env_1.default.CAPCUT_DEVICE_ID ?? (0, capcutUtils_1.createDeviceId)());
        }
        return this.deviceIdValue;
    }
    set deviceId(value) {
        this.deviceIdValue = value;
    }
    tdidValue = null;
    get tdid() {
        if (!this.tdidValue) {
            const seed = this.accountSeed;
            this.tdidValue = seed
                ? BigInt('0x' + seed.slice(15, 29)).toString().padStart(17, '0').slice(0, 17)
                : (env_1.default.CAPCUT_TDID ?? (0, capcutUtils_1.createTrackingId)());
        }
        return this.tdidValue;
    }
    set tdid(value) {
        this.tdidValue = value;
    }
    session = null;
    sessionPromise = null;
    speakers = null;
    speakersLoadedAt = 0;
    /** 生きた音声カタログを引けず fallback で凌いでいる状態か */
    speakersDegraded = false;
    liveVoiceCategoryIds = null;
    liveVoiceCategoryIdsLoadedAt = 0;
    verifyFpValue = null;
    get verifyFp() {
        if (!this.verifyFpValue) {
            this.verifyFpValue = this.accountSeed
                ? (0, capcutUtils_1.createVerifyFp)()
                : (env_1.default.CAPCUT_VERIFY_FP ?? (0, capcutUtils_1.createVerifyFp)());
        }
        return this.verifyFpValue;
    }
    set verifyFp(value) {
        this.verifyFpValue = value;
    }
    runtimeLoginBundleConfig = {};
    runtimeEditorBundleConfig = {
        sourceUrls: [],
    };
    /**
     * 永続化済みセッションの復元を一度だけ走らせる
     *
     * コンストラクタで起動すると Workers では bindings 到着前に走ってしまうため
     * 最初に必要になった時点まで遅らせる
     */
    ensureRestored() {
        if (!this.restorePromise) {
            this.restorePromise = this.restorePersistedSession();
        }
        return this.restorePromise;
    }
    /**
     * 音声をバッファとして取得する
     */
    async synthesizeBuffer(options) {
        const chunkedTexts = (0, string_1.splitTtsText)(options.text, env_1.default.CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH, env_1.default.CAPCUT_TTS_TEXT_CHUNK_BOUNDARY_SEARCH_RATIO);
        if (chunkedTexts.length === 1) {
            const response = await this.createAudioResponse(options);
            const buffer = Buffer.from(await response.arrayBuffer());
            return {
                buffer,
                contentType: response.headers.get('content-type') ?? 'audio/mpeg',
                contentLength: response.headers.get('content-length') ?? undefined,
                fileName: this.extractFileName(response),
            };
        }
        const chunkedResults = await this.synthesizeChunkedBuffers(options, chunkedTexts);
        const buffer = Buffer.concat(chunkedResults.map((chunkResult) => chunkResult.buffer));
        return {
            buffer,
            contentType: chunkedResults[0]?.contentType ?? 'audio/mpeg',
            contentLength: String(buffer.byteLength),
            fileName: chunkedResults[0]?.fileName,
        };
    }
    /**
     * 音声をストリームとして取得する
     */
    async synthesizeStream(options) {
        const chunkedTexts = (0, string_1.splitTtsText)(options.text, env_1.default.CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH, env_1.default.CAPCUT_TTS_TEXT_CHUNK_BOUNDARY_SEARCH_RATIO);
        if (chunkedTexts.length === 1) {
            const response = await this.createAudioResponse(options);
            if (!response.body) {
                throw new Error('CapCut audio response did not contain a body');
            }
            return {
                stream: node_stream_1.Readable.fromWeb(response.body),
                contentType: response.headers.get('content-type') ?? 'audio/mpeg',
                contentLength: response.headers.get('content-length') ?? undefined,
                fileName: this.extractFileName(response),
            };
        }
        const audioResult = await this.synthesizeBuffer(options);
        return {
            stream: node_stream_1.Readable.from([audioResult.buffer]),
            contentType: audioResult.contentType,
            contentLength: audioResult.contentLength,
            fileName: audioResult.fileName,
        };
    }
    /**
     * 単語タイムスタンプ付きで合成する
     *
     * REST 経路は caption を返さないため、SAMI の WebSocket 経路を使う
     * こちらは合成エンジンが出した alignment をそのまま受け取れる
     */
    async synthesizeWithMarks(options) {
        const speakers = await this.loadSpeakers();
        const resolvedSpeaker = (0, voiceUtils_1.resolveSpeaker)(options.type, speakers, options.speaker, options.platform);
        // WebSocket 経路は SAMI 専用 11labs の話者を渡すと
        // 音声 0 バイト alignment 空のまま 200 で返ってくるので先に弾く
        const speakerPlatform = resolvedSpeaker.platform?.trim().toLowerCase();
        if (speakerPlatform && speakerPlatform !== 'sami') {
            throw new responseUtils_1.CapCutApiError(`Word timestamps are only available for sami voices. Speaker "${resolvedSpeaker.speaker}" runs on ${resolvedSpeaker.platform}`, 
            // 呼び出し側の入力が原因なので 400 として扱わせる
            { statusCode: 400 });
        }
        return (0, ttsWebSocket_1.synthesizeWithTimestamps)({
            text: options.text,
            speaker: resolvedSpeaker.speaker,
            tokenUrl: new URL(ttsTokenPath, env_1.default.CAPCUT_EDIT_API_URL).toString(),
            wsUrl: ttsWebSocketUrl,
            appId: appId,
            appVersion: this.getResolvedEditorAppVersion(),
            platformId: this.getResolvedPlatformId(),
            signVersion: this.getResolvedSignVersion(),
            sampleRate: ttsSampleRate,
            userAgent: env_1.default.USER_AGENT,
            origin: env_1.default.CAPCUT_WEB_URL,
            includePhonemes: options.phonemes ?? false,
        });
    }
    /**
     * 利用可能な話者一覧を返す
     *
     * @param filter - 言語 国 カテゴリでの絞り込み条件
     */
    async listSpeakers(filter = {}) {
        const speakers = (0, voiceUtils_1.toSpeakerInfoList)(await this.loadSpeakers());
        if (!filter.language && !filter.category) {
            return speakers;
        }
        return (0, voiceUtils_1.filterSpeakerInfoList)(speakers, filter);
    }
    /**
     * 話者が持つ言語コード一覧を返す
     */
    async listSpeakerLanguages() {
        const speakers = (0, voiceUtils_1.toSpeakerInfoList)(await this.loadSpeakers());
        const counts = new Map();
        for (const speaker of speakers) {
            const language = (0, voiceUtils_1.normalizeLanguageCode)(speaker.language);
            counts.set(language, (counts.get(language) ?? 0) + 1);
        }
        return Array.from(counts, ([language, speakerCount]) => ({
            language,
            countries: capcutVoiceCategories_1.capCutLanguageCountries[language] ?? [],
            speakerCount,
        })).sort((a, b) => b.speakerCount - a.speakerCount);
    }
    /**
     * 話者プレビュー音声をキャッシュ付きで返す
     */
    async getSpeakerPreviewAudio(speakerId) {
        const buffer = await this.ensureSpeakerPreviewAudio(speakerId);
        return {
            buffer,
            contentType: 'audio/mpeg',
            contentLength: String(buffer.byteLength),
            fileName: `${speakerId}.mp3`,
        };
    }
    /**
     * 話者プレビュー音声を必要に応じて生成または再生成する
     *
     * 保存先は BlobStorage 経由なので、Node ではローカルディレクトリ、
     * Workers では R2 バケットがそのまま置き場になる
     */
    async ensureSpeakerPreviewAudio(speakerId) {
        const speakers = await this.loadSpeakers();
        const resolvedSpeaker = (0, voiceUtils_1.resolveSpeaker)(speakerId, speakers, speakerId);
        const previewKey = `${env_1.default.CAPCUT_SPEAKER_PREVIEW_TEMP_DIR.replace(/\/+$/, '')}/${resolvedSpeaker.speaker}.mp3`;
        const storage = (0, storage_1.getBlobStorage)();
        const maxAgeMs = env_1.default.CAPCUT_SPEAKER_PREVIEW_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
        const cached = await storage.readBlob(previewKey);
        if (cached && Date.now() - cached.uploadedAt < maxAgeMs) {
            return Buffer.from(cached.body);
        }
        const previewAudio = await this.synthesizeBuffer({
            text: env_1.default.CAPCUT_SPEAKER_PREVIEW_TEXT,
            speaker: resolvedSpeaker.speaker,
            type: 0,
            pitch: 10,
            speed: 10,
            volume: 10,
        });
        await storage.writeBlob(previewKey, new Uint8Array(previewAudio.buffer), 'audio/mpeg');
        return previewAudio.buffer;
    }
    /**
     * 起動時の事前ウォームアップ
     */
    async warmup() {
        await this.refreshLoginBundleConfig();
        await this.ensureEditorBundleConfig();
        await this.ensureAuthenticated();
        await this.loadSpeakers();
        void this.refreshEditorBundleConfig();
    }
    /**
     * セッションを確保する
     * 既存セッションが生きていれば再利用し、失効時だけ再ログインする
     */
    async ensureAuthenticated(force = false) {
        await this.ensureRestored();
        if (!force && this.session) {
            const sessionAge = Date.now() - this.session.verifiedAt;
            if (sessionAge < sessionValidateMs) {
                return this.session;
            }
        }
        if (this.sessionPromise) {
            return this.sessionPromise;
        }
        this.sessionPromise = (async () => {
            if (!force && this.session) {
                try {
                    await this.fetchPrimaryWorkspace();
                    this.session.verifiedAt = Date.now();
                    await this.persistSession();
                    return this.session;
                }
                catch (error) {
                    logger_1.default.info('CapCut session validation failed. Re-authenticating', {
                        error,
                    });
                }
            }
            return this.loginWithGlobalLock();
        })().finally(() => {
            this.sessionPromise = null;
        });
        return this.sessionPromise;
    }
    /**
     * login bundle 由来の設定を更新する
     */
    async refreshLoginBundleConfig() {
        this.runtimeLoginBundleConfig =
            await CapCutBundleService_1.default.resolveLoginBundleConfig();
    }
    /**
     * editor bundle 由来の設定を更新する
     */
    async refreshEditorBundleConfig() {
        this.runtimeEditorBundleConfig =
            await CapCutBundleService_1.default.resolveEditorBundleConfig(this.fetchWithCookies.bind(this));
    }
    /**
     * workspace / TTS 実行に足りる editor bundle 設定かを判定する
     */
    hasUsableEditorBundleConfig() {
        return this.runtimeEditorBundleConfig.sourceUrls.length > 0;
    }
    /**
     * 必要なら live bundle から editor 設定を再取得する
     */
    async ensureEditorBundleConfig(forceRefresh = false) {
        if (!forceRefresh && this.hasUsableEditorBundleConfig()) {
            return;
        }
        this.runtimeEditorBundleConfig =
            await CapCutBundleService_1.default.resolveEditorBundleConfig(this.fetchWithCookies.bind(this), true);
    }
    /**
     * bundle 由来 login sdk version を返す
     */
    getResolvedLoginSdkVersion() {
        return isSemverLike(this.runtimeLoginBundleConfig.sdkVersion)
            ? this.runtimeLoginBundleConfig.sdkVersion
            : loginSdkVersion;
    }
    /**
     * bundle 由来 login email path を返す
     */
    getResolvedEmailLoginPath() {
        return (this.runtimeLoginBundleConfig.emailLoginPath ??
            '/passport/web/email/login/');
    }
    /**
     * bundle 由来 login user path を返す
     */
    getResolvedUserLoginPath() {
        return (this.runtimeLoginBundleConfig.userLoginPath ?? '/passport/web/user/login/');
    }
    /**
     * bundle 由来 region path を返す
     */
    getResolvedRegionPath() {
        return this.runtimeLoginBundleConfig.regionPath ?? '/passport/web/region/';
    }
    /**
     * bundle 由来 account info path を返す
     */
    getResolvedAccountInfoPath() {
        return (this.runtimeLoginBundleConfig.accountInfoPath ??
            '/passport/web/account/info/');
    }
    /**
     * bundle 由来 editor app version を返す
     */
    getResolvedEditorAppVersion() {
        return isSemverLike(this.runtimeEditorBundleConfig.editorAppVersion)
            ? this.runtimeEditorBundleConfig.editorAppVersion
            : editorAppVersion;
    }
    /**
     * bundle 由来 web app version を返す
     */
    getResolvedWebAppVersion() {
        return isSemverLike(this.runtimeEditorBundleConfig.webAppVersion)
            ? this.runtimeEditorBundleConfig.webAppVersion
            : webAppVersion;
    }
    /**
     * bundle 由来 version_name を返す
     */
    getResolvedVersionName() {
        return isSemverLike(this.runtimeEditorBundleConfig.versionName)
            ? this.runtimeEditorBundleConfig.versionName
            : '11.0.0';
    }
    /**
     * bundle 由来 version_code を返す
     */
    getResolvedVersionCode() {
        return isSemverLike(this.runtimeEditorBundleConfig.versionCode)
            ? this.runtimeEditorBundleConfig.versionCode
            : '11.0.0';
    }
    /**
     * bundle 由来 sdk_version を返す
     */
    getResolvedSdkVersion() {
        return isSemverLike(this.runtimeEditorBundleConfig.sdkVersion)
            ? this.runtimeEditorBundleConfig.sdkVersion
            : '19.3.0';
    }
    /**
     * bundle 由来 effect_sdk_version を返す
     */
    getResolvedEffectSdkVersion() {
        return isSemverLike(this.runtimeEditorBundleConfig.effectSdkVersion)
            ? this.runtimeEditorBundleConfig.effectSdkVersion
            : '19.3.0';
    }
    /**
     * bundle 由来 voice panel を返す
     */
    getResolvedVoicePanel() {
        return this.runtimeEditorBundleConfig.voicePanel ?? voicePanel;
    }
    /**
     * bundle 由来 voice panel source を返す
     */
    getResolvedVoicePanelSource() {
        return this.runtimeEditorBundleConfig.voicePanelSource ?? voicePanelSource;
    }
    /**
     * 設定由来の voice category ids を返す
     * CapCut 側で ID が入れ替わるため、実行時取得できなかったときの保険として使う
     */
    getFallbackVoiceCategoryIds() {
        return this.runtimeEditorBundleConfig.voiceCategoryIds?.length
            ? this.runtimeEditorBundleConfig.voiceCategoryIds
            : [...capcutVoiceCategories_1.capCutVoiceCategoryIds];
    }
    /**
     * bundle 由来 voice list path を返す
     */
    getResolvedVoiceListPath() {
        return (this.runtimeEditorBundleConfig.voiceListPath ??
            '/artist/v1/effect/get_resources_by_category_id');
    }
    /**
     * bundle 由来 workspace path を返す
     */
    getResolvedWorkspacePath() {
        return (this.runtimeEditorBundleConfig.workspacePath ??
            '/cc/v1/workspace/get_user_workspaces');
    }
    /**
     * bundle 由来 multi_platform path を返す
     */
    getResolvedMultiPlatformPath() {
        const extractedPath = this.runtimeEditorBundleConfig.multiPlatformPath;
        if (!extractedPath) {
            return '/storyboard/v1/tts/multi_platform';
        }
        return extractedPath.startsWith('/storyboard/')
            ? extractedPath
            : '/storyboard/v1/tts/multi_platform';
    }
    /**
     * bundle 由来 create task path を返す
     */
    getResolvedCreateTaskPath() {
        const extractedPath = this.runtimeEditorBundleConfig.createTaskPath;
        if (!extractedPath) {
            return '/lv/v2/intelligence/create';
        }
        return extractedPath.startsWith('/lv/')
            ? extractedPath
            : `/lv/v2${extractedPath}`;
    }
    /**
     * bundle 由来 query task path を返す
     */
    getResolvedQueryTaskPath() {
        const extractedPath = this.runtimeEditorBundleConfig.queryTaskPath;
        if (!extractedPath) {
            return '/lv/v2/intelligence/query';
        }
        return extractedPath.startsWith('/lv/')
            ? extractedPath
            : `/lv/v2${extractedPath}`;
    }
    /**
     * bundle 由来 sign recipe を返す
     */
    getResolvedSignRecipe() {
        const signRecipe = this.runtimeEditorBundleConfig.signRecipe;
        return {
            ...signRecipe,
            // 古い bundle 断片だと 4 が取れることがあるが、実 API 検証では 7 以上でないと workspace が通らない
            pathTailLength: Math.max(signRecipe?.pathTailLength ?? 7, 7),
        };
    }
    /**
     * bundle 由来 platform id を返す
     */
    getResolvedPlatformId() {
        return this.runtimeEditorBundleConfig.signRecipe?.platformId ?? platformId;
    }
    /**
     * bundle 由来 sign version を返す
     */
    getResolvedSignVersion() {
        return (this.runtimeEditorBundleConfig.signRecipe?.signVersion ?? signVersion);
    }
    /**
     * 永続化済みセッションを復元する
     */
    async restorePersistedSession() {
        // deviceId と verifyFp が env で固定されていても、ここで打ち切ってはいけない
        // Cookie とセッションの復元まで飛ばしてしまい、起動のたびに再ログインが走る
        // env 側の値を優先する処理は下の各分岐が既に担当している
        try {
            const raw = await this.readSessionPayload();
            if (!raw) {
                return;
            }
            const parsed = JSON.parse(raw);
            if (!parsed ||
                !Array.isArray(parsed.cookies) ||
                typeof parsed.verifyFp !== 'string' ||
                typeof parsed.deviceId !== 'string') {
                return;
            }
            if (!env_1.default.CAPCUT_DEVICE_ID) {
                this.deviceId = parsed.deviceId;
            }
            if (!env_1.default.CAPCUT_VERIFY_FP) {
                this.verifyFp = parsed.verifyFp;
            }
            if (!env_1.default.CAPCUT_TDID && typeof parsed.tdid === 'string' && parsed.tdid) {
                this.tdid = parsed.tdid;
            }
            this.cookieJar.hydrate(parsed.cookies);
            this.syncDeviceIdFromCookies();
            this.session = parsed.session ?? null;
        }
        catch (error) {
            logger_1.default.warn('Failed to restore persisted CapCut session', { error });
        }
    }
    /**
     * セッションをディスクへ保存する
     */
    /** Cookie などが変わったが、まだ保存していない状態か */
    sessionDirty = false;
    /** D1 の楽観ロック用 読み出したときの version */
    sessionVersion = null;
    /**
     * 変更があれば保存する
     *
     * Workers ではレスポンス返却後に未完了の promise が打ち切られるため
     * 呼び出し側で ctx.waitUntil に載せて使う
     */
    async flushSession() {
        if (!this.sessionDirty) {
            return;
        }
        // 読み込んでいないものを上書きしない
        // 復元が走っていない状態で保存すると、保存済みセッションを空の jar で潰す
        if (!this.restorePromise) {
            logger_1.default.warn('Skipped session flush before restore');
            this.sessionDirty = false;
            return;
        }
        await this.persistSession();
    }
    async persistSession() {
        // ログインが確立していない状態で保存しない
        //
        // 失敗した試行の中途半端な Cookie jar を書くと、次の isolate が
        // それを復元して壊れたセッションを掴み、また再ログインを始めてしまう
        if (!this.session) {
            this.sessionDirty = false;
            return;
        }
        try {
            const payload = {
                session: this.session,
                cookies: this.cookieJar.serialize(),
                verifyFp: this.verifyFp,
                deviceId: this.deviceId,
                tdid: this.tdid,
            };
            await this.writeSessionPayload(JSON.stringify(payload, null, 2));
            this.sessionDirty = false;
        }
        catch (error) {
            logger_1.default.warn('Failed to persist CapCut session', { error });
        }
    }
    /**
     * セッション JSON を読む D1 があればそちら優先
     */
    async readSessionPayload() {
        const store = (0, sessionStore_1.getSessionStore)();
        if (store) {
            const record = await store.read(this.sessionStoreKey);
            this.sessionVersion = record?.version ?? null;
            return record?.payload ? record.payload : null;
        }
        return (0, storage_1.getBlobStorage)().readText(this.sessionStoreKey);
    }
    /**
     * セッション JSON を書く
     *
     * D1 では version が一致したときだけ書く 負けた側は書かない
     * 先に他 isolate が更新していれば、そちらの方が新しいので上書きしない
     */
    async writeSessionPayload(payload) {
        const store = (0, sessionStore_1.getSessionStore)();
        if (!store) {
            await (0, storage_1.getBlobStorage)().writeText(this.sessionStoreKey, payload);
            return;
        }
        const expiresAt = Date.now() + sessionLifetimeMs;
        const written = await store.write(this.sessionStoreKey, payload, expiresAt, this.sessionVersion);
        if (written) {
            this.sessionVersion =
                this.sessionVersion === null ? 1 : this.sessionVersion + 1;
            return;
        }
        // 競り負けた 相手の方が新しいので読み直しておく
        const latest = await store.read(this.sessionStoreKey);
        this.sessionVersion = latest?.version ?? null;
        logger_1.default.debug('Session write skipped, another writer was ahead');
    }
    /**
     * passport 系 API 用の CSRF Cookie を事前に投入する
     */
    seedPassportCookies() {
        const csrf = node_crypto_1.default.randomBytes(16).toString('hex');
        const domains = [
            new URL(env_1.default.CAPCUT_WEB_URL).hostname,
            new URL(env_1.default.CAPCUT_LOGIN_HOST).hostname,
            new URL(env_1.default.CAPCUT_FALLBACK_LOGIN_HOST).hostname,
        ];
        for (const domain of domains) {
            this.cookieJar.set('passport_csrf_token', csrf, domain);
            this.cookieJar.set('passport_csrf_token_default', csrf, domain);
        }
    }
    /**
     * login host を切り替える前に Cookie 状態を初期化する
     */
    async resetLoginAttemptState() {
        this.cookieJar.clear();
        this.seedPassportCookies();
        await this.primeCookies();
    }
    /**
     * ログインを全 isolate で 1 回だけにする
     *
     * sessionPromise の重複排除は isolate 内でしか効かない
     * Workers は isolate が多数動くため、実測で同時 6 リクエストが
     * 5 回のログインを起こし、CapCut から複数デバイス扱いされていた
     *
     * ロックを取れなかった側はログインせず、勝った側が書いたセッションを待つ
     */
    async loginWithGlobalLock() {
        const store = (0, sessionStore_1.getSessionStore)();
        if (!store) {
            return this.login();
        }
        const key = this.sessionStoreKey;
        const existing = await store.read(key);
        // 直前のログインが失敗している間は誰も試さない
        // ここで殺到させると CapCut のログイン試行上限を一瞬で使い切る
        if (existing && existing.failUntil > Date.now()) {
            const waitSeconds = Math.ceil((existing.failUntil - Date.now()) / 1000);
            throw new responseUtils_1.CapCutApiError(`CapCut login is backing off after a recent failure. Retry in ${waitSeconds}s`);
        }
        if (await store.acquireLock(key, loginLockMs)) {
            try {
                const session = await this.login();
                await store.releaseLock(key).catch(() => undefined);
                return session;
            }
            catch (error) {
                // 失敗を全 isolate へ伝える 次の試行はこの後まで止まる
                // 試行上限に当たった場合は長めに待つ 短く刻むと解除前に使い切る
                const backoffMs = (0, capcutUtils_1.isLoginAttemptLimitError)(error)
                    ? loginAttemptLimitBackoffMs
                    : loginFailureBackoffMs;
                await store.markLoginFailure(key, backoffMs).catch(() => undefined);
                logger_1.default.warn('CapCut login failed. Backing off', {
                    minutes: Math.round(backoffMs / 60000),
                });
                throw error;
            }
        }
        logger_1.default.info('Another worker is logging in. Waiting for its session');
        for (let attempt = 0; attempt < loginWaitAttempts; attempt += 1) {
            await new Promise((resolve) => setTimeout(resolve, loginWaitIntervalMs));
            const record = await store.read(key);
            if (record?.payload && record.lockUntil < Date.now()) {
                this.sessionVersion = record.version;
                this.restorePromise = null;
                await this.ensureRestored();
                if (this.session) {
                    return this.session;
                }
            }
            if (record && record.failUntil > Date.now()) {
                throw new responseUtils_1.CapCutApiError('CapCut login failed on another worker. Backing off');
            }
        }
        // ここで自分もログインしに行くと、障害時に全 isolate が殺到してしまう
        // 呼び出し側にはエラーを返し、次のリクエストへ委ねる
        throw new responseUtils_1.CapCutApiError('Timed out waiting for the shared CapCut session. Try again shortly');
    }
    /**
     * CapCut へログインしてワークスペースまで確定させる
     */
    async login() {
        logger_1.default.info('CapCut login flow started');
        this.verifyFp = env_1.default.CAPCUT_VERIFY_FP ?? (0, capcutUtils_1.createVerifyFp)();
        await this.refreshLoginBundleConfig();
        await this.resetLoginAttemptState();
        const resolvedRegion = await this.resolveLoginRegion().catch((error) => {
            logger_1.default.info('CapCut region bootstrap failed. Falling back to defaults', {
                error,
            });
            return null;
        });
        const loginHosts = [
            resolvedRegion?.domain,
            env_1.default.CAPCUT_LOGIN_HOST,
            env_1.default.CAPCUT_FALLBACK_LOGIN_HOST,
        ].filter((value, index, values) => Boolean(value) && values.indexOf(value) === index);
        let lastError;
        for (const [index, loginHost] of loginHosts.entries()) {
            try {
                if (index > 0) {
                    // 前回 host の session cookie を持ち越すと account/info が失効扱いになりやすい
                    await this.resetLoginAttemptState();
                }
                await this.primeLoginState(loginHost);
                const loginData = await this.loginWithHost(loginHost);
                const accountInfo = await this.fetchAccountInfo().catch((error) => {
                    logger_1.default.info(`CapCut account info lookup failed after login via ${loginHost}`, { error });
                    return null;
                });
                await this.ensureEditorBundleConfig(true);
                const workspace = await this.fetchPrimaryWorkspace();
                const session = {
                    userId: normalizeStringId(accountInfo?.user_id) ??
                        normalizeStringId(loginData.user_id_str) ??
                        normalizeStringId(loginData.user_id) ??
                        '',
                    screenName: normalizeString(accountInfo?.screen_name) ??
                        normalizeString(loginData.screen_name) ??
                        '',
                    workspaceId: workspace.workspace_id,
                    loginHost,
                    verifyFp: this.verifyFp,
                    deviceId: this.deviceId,
                    loggedInAt: Date.now(),
                    verifiedAt: Date.now(),
                };
                if (!session.userId || !session.workspaceId) {
                    throw new Error('CapCut login did not expose user or workspace info');
                }
                this.session = session;
                await this.persistSession();
                void this.refreshEditorBundleConfig();
                logger_1.default.info('CapCut session established', {
                    userId: session.userId,
                    workspaceId: session.workspaceId,
                    loginHost,
                });
                return session;
            }
            catch (error) {
                lastError = error;
                logger_1.default.warn(`CapCut login via ${loginHost} failed`, { error });
                // 試行回数の上限に当たったら、別 host を試しても無意味で
                // 残り試行を減らすだけなので、ここで打ち切る
                if ((0, capcutUtils_1.isLoginAttemptLimitError)(error)) {
                    logger_1.default.warn('CapCut reported the login attempt limit. Stopping without trying other hosts');
                    break;
                }
                if (!shouldTryOtherLoginHost(error)) {
                    break;
                }
            }
        }
        this.session = null;
        await this.persistSession();
        throw lastError instanceof Error
            ? lastError
            : new Error('CapCut login failed');
    }
    /**
     * login ページ取得で Cookie 群を初期化する
     */
    async primeCookies() {
        const response = await (0, getLoginPage_1.getLoginPage)({
            requester: this.fetchWithCookies.bind(this),
            path: `/${env_1.default.CAPCUT_PAGE_LOCALE}/login`,
            headers: {
                Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': env_1.default.CAPCUT_LOCALE,
                'User-Agent': env_1.default.USER_AGENT,
            },
        });
        this.syncDeviceIdFromCookies();
        if (!response.ok) {
            const body = await response.text();
            throw new Error(`CapCut login page bootstrap failed: ${response.status} ${response.statusText} ${(0, httpUtils_1.getResponseBodySnippet)(body)}`);
        }
    }
    /**
     * login 前に check_email_registered を叩いて SDK の前提状態を近づける
     */
    async primeLoginState(loginHost) {
        try {
            await (0, checkEmailRegistered_1.checkEmailRegistered)({
                requester: this.fetchWithCookies.bind(this),
                host: loginHost,
                searchParams: {
                    aid: appId,
                    account_sdk_source: 'web',
                    sdk_version: this.getResolvedLoginSdkVersion(),
                    language: env_1.default.CAPCUT_LOCALE,
                    verifyFp: this.verifyFp,
                },
                headers: {
                    Accept: 'application/json, text/javascript',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'User-Agent': env_1.default.USER_AGENT,
                    appid: appId,
                    did: this.deviceId,
                    Origin: env_1.default.CAPCUT_WEB_URL,
                    Referer: `${env_1.default.CAPCUT_WEB_URL}/${env_1.default.CAPCUT_PAGE_LOCALE}/login`,
                    'store-country-code': env_1.default.CAPCUT_STORE_COUNTRY_CODE,
                    'store-country-code-src': 'uid',
                    'x-tt-passport-csrf-token': this.getPassportCsrfToken(loginHost) ?? '',
                },
                body: (0, capcutUtils_1.buildSensitiveFormBody)({
                    email: this.accountEmail,
                }, ['email']),
            });
        }
        catch (error) {
            logger_1.default.debug('CapCut login preflight failed', { error, loginHost });
        }
    }
    /**
     * メールアドレスに応じた login host を問い合わせる
     */
    async resolveLoginRegion() {
        const response = await (0, resolveRegion_1.resolveRegion)({
            requester: this.fetchWithCookies.bind(this),
            host: env_1.default.CAPCUT_LOGIN_HOST,
            path: this.getResolvedRegionPath(),
            searchParams: {
                aid: appId,
                account_sdk_source: 'web',
                sdk_version: this.getResolvedLoginSdkVersion(),
                language: env_1.default.CAPCUT_LOCALE,
                verifyFp: this.verifyFp,
                mix_mode: '1',
            },
            headers: {
                Accept: 'application/json, text/javascript',
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': env_1.default.USER_AGENT,
                appid: appId,
                did: this.deviceId,
                Origin: env_1.default.CAPCUT_WEB_URL,
                Referer: `${env_1.default.CAPCUT_WEB_URL}/`,
                'store-country-code': env_1.default.CAPCUT_STORE_COUNTRY_CODE,
                'store-country-code-src': 'cdn',
                'x-tt-passport-csrf-token': '',
            },
            body: new URLSearchParams({
                type: '2',
                hashed_id: (0, capcutUtils_1.createEmailRegionHashWithSalt)(this.accountEmail, this.runtimeLoginBundleConfig.emailHashSalt),
            }).toString(),
        });
        return (0, responseUtils_1.unwrapJsonResponse)(response, 'CapCut region bootstrap');
    }
    /**
     * email/password ログインを実行する
     * まず email/login を試し、endpoint 不整合らしい場合だけ user/login へフォールバックする
     */
    async loginWithHost(loginHost) {
        const searchParams = {
            aid: appId,
            account_sdk_source: 'web',
            sdk_version: this.getResolvedLoginSdkVersion(),
            language: env_1.default.CAPCUT_LOCALE,
            verifyFp: this.verifyFp,
        };
        const headers = {
            Accept: 'application/json, text/javascript',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': env_1.default.USER_AGENT,
            appid: appId,
            did: this.deviceId,
            Origin: env_1.default.CAPCUT_WEB_URL,
            Referer: `${env_1.default.CAPCUT_WEB_URL}/${env_1.default.CAPCUT_PAGE_LOCALE}/login`,
            'store-country-code': env_1.default.CAPCUT_STORE_COUNTRY_CODE,
            'store-country-code-src': 'uid',
            'x-tt-passport-csrf-token': this.getPassportCsrfToken(loginHost) ?? '',
        };
        const body = (0, capcutUtils_1.buildSensitiveFormBody)({
            email: this.accountEmail,
            password: this.accountPassword,
        }, ['email', 'password']);
        try {
            return await (0, responseUtils_1.unwrapJsonResponse)(await (0, emailLogin_1.emailLogin)({
                requester: this.fetchWithCookies.bind(this),
                host: loginHost,
                path: this.getResolvedEmailLoginPath(),
                searchParams,
                headers,
                body,
            }), 'CapCut passport /passport/web/email/login/');
        }
        catch (error) {
            if (!shouldFallbackToUserLogin(error)) {
                throw error;
            }
            logger_1.default.info('CapCut email/login fallback to user/login', { error });
            return (0, responseUtils_1.unwrapJsonResponse)(await (0, userLogin_1.userLogin)({
                requester: this.fetchWithCookies.bind(this),
                host: loginHost,
                path: this.getResolvedUserLoginPath(),
                searchParams,
                headers,
                body,
            }), 'CapCut passport /passport/web/user/login/');
        }
    }
    /**
     * アカウント情報を取得する
     */
    async fetchAccountInfo() {
        return (0, responseUtils_1.unwrapJsonResponse)(await (0, getAccountInfo_1.getAccountInfo)({
            requester: this.fetchWithCookies.bind(this),
            path: this.getResolvedAccountInfoPath(),
            searchParams: {
                aid: appId,
                account_sdk_source: 'web',
                sdk_version: this.getResolvedLoginSdkVersion(),
                language: env_1.default.CAPCUT_LOCALE,
                verifyFp: this.verifyFp,
            },
            headers: {
                Accept: 'application/json, text/javascript',
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': env_1.default.USER_AGENT,
                appid: appId,
                did: this.deviceId,
                Referer: `${env_1.default.CAPCUT_WEB_URL}/${env_1.default.CAPCUT_PAGE_LOCALE}/login`,
                'store-country-code': env_1.default.CAPCUT_STORE_COUNTRY_CODE,
                'store-country-code-src': 'uid',
                'x-tt-passport-csrf-token': this.getPassportCsrfToken(env_1.default.CAPCUT_WEB_URL) ?? '',
            },
        }), 'CapCut account info');
    }
    /**
     * デフォルトのワークスペースを取得する
     */
    async fetchPrimaryWorkspace() {
        const data = await this.requestSignedEditJson({
            path: this.getResolvedWorkspacePath(),
            appVersion: this.getResolvedEditorAppVersion(),
            extraHeaders: {
                lan: env_1.default.CAPCUT_LOCALE,
                loc: env_1.default.CAPCUT_REGION,
            },
            body: {
                cursor: '0',
                count: 100,
                need_convert_workspace: true,
            },
            request: ({ headers, body }) => (0, getUserWorkspaces_1.getUserWorkspaces)({
                requester: this.fetchWithCookies.bind(this),
                path: this.getResolvedWorkspacePath(),
                headers,
                body,
            }),
            context: 'CapCut workspace list',
        });
        const workspaces = Array.isArray(data.workspace_infos)
            ? data.workspace_infos
            : [];
        const workspace = workspaces.find((item) => item.role === 'owner') ?? workspaces[0];
        if (!workspace?.workspace_id) {
            throw new Error('CapCut workspace list was empty');
        }
        return workspace;
    }
    /**
     * 音声一覧をロードする
     *
     * 生カタログを引けなかったときは fallback で応答を保つが
     * 縮退していることを error で明示し、次の再取得も早める
     */
    async loadSpeakers() {
        const cacheAge = Date.now() - this.speakersLoadedAt;
        const cacheTtl = this.speakersDegraded ? voiceFallbackRetryMs : voiceCacheMs;
        if (this.speakers && cacheAge < cacheTtl) {
            return this.speakers;
        }
        try {
            const speakers = this.excludeBrokenVoices(await this.requestSpeakerList());
            if (speakers.length === 0) {
                throw new Error('CapCut voice catalog returned no usable speaker');
            }
            if (this.speakersDegraded) {
                logger_1.default.info('CapCut voice catalog recovered', {
                    speakerCount: speakers.length,
                });
            }
            this.speakers = speakers;
            this.speakersDegraded = false;
            this.speakersLoadedAt = Date.now();
            return this.speakers;
        }
        catch (error) {
            logger_1.default.error(`CapCut voice catalog unavailable. Serving ${capcutSpeakers_1.fallbackSpeakers.length} built-in fallback voices instead of the live catalog. Retrying in ${Math.round(voiceFallbackRetryMs / 1000)}s`, { error });
            this.speakers = capcutSpeakers_1.fallbackSpeakers;
            this.speakersDegraded = true;
            this.speakersLoadedAt = Date.now();
            return this.speakers;
        }
    }
    /**
     * 実測で読み上げが破綻している話者をカタログから外す
     *
     * 例 ベトナム語 x 11labs はベトナム語テキストを別言語として読むため
     * 一覧にも合成にも出さない CAPCUT_EXCLUDE_BROKEN_VOICES=false で無効化できる
     */
    excludeBrokenVoices(speakers) {
        if (!env_1.default.CAPCUT_EXCLUDE_BROKEN_VOICES) {
            return speakers;
        }
        const dropped = [];
        const kept = speakers.filter((speaker) => {
            const broken = (0, capcutVoiceQuality_1.isBrokenVoice)(speaker.language, speaker.platform);
            if (broken) {
                dropped.push(speaker.speaker);
                return false;
            }
            return true;
        });
        if (dropped.length > 0) {
            logger_1.default.info('Excluded known-broken CapCut voices', {
                count: dropped.length,
                combos: capcutVoiceQuality_1.brokenVoiceCombos.map((combo) => `${combo.language}/${combo.platform}`),
            });
        }
        return kept;
    }
    /**
     * artist API 共通の search params
     */
    buildArtistSearchParams() {
        return {
            aid: appId,
            version_name: this.getResolvedVersionName(),
            version_code: this.getResolvedVersionCode(),
            sdk_version: this.getResolvedSdkVersion(),
            effect_sdk_version: this.getResolvedEffectSdkVersion(),
            device_platform: 'web',
            region: env_1.default.CAPCUT_REGION,
            language: env_1.default.CAPCUT_LOCALE,
            device_type: 'web',
            channel: 'online',
        };
    }
    /**
     * artist API 共通のヘッダ
     * この系統は sign を要求しないので Cookie と did だけで通る
     */
    buildArtistHeaders() {
        return {
            Accept: 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            Origin: env_1.default.CAPCUT_WEB_URL,
            Referer: `${env_1.default.CAPCUT_WEB_URL}/`,
            'User-Agent': env_1.default.USER_AGENT,
            appid: appId,
            did: this.deviceId,
            'store-country-code': env_1.default.CAPCUT_STORE_COUNTRY_CODE,
            'store-country-code-src': 'uid',
        };
    }
    /**
     * 音声カテゴリ一覧を実行時に取得する
     *
     * CapCut 側でカテゴリ ID は入れ替わるため固定値に頼らない
     * 取得に失敗したときだけ設定値へフォールバックする
     */
    async loadVoiceCategories() {
        const cacheAge = Date.now() - this.liveVoiceCategoryIdsLoadedAt;
        if (this.liveVoiceCategoryIds && cacheAge < voiceCategoryCacheMs) {
            return this.liveVoiceCategoryIds.map((id) => ({ id, key: String(id) }));
        }
        try {
            const payload = await (0, responseUtils_1.unwrapJsonResponse)(await (0, getVoicePanelInfo_1.getVoicePanelInfo)({
                requester: this.fetchWithCookies.bind(this),
                path: voicePanelInfoPath,
                searchParams: this.buildArtistSearchParams(),
                headers: this.buildArtistHeaders(),
                body: JSON.stringify({
                    panel: this.getResolvedVoicePanel(),
                    panel_source: this.getResolvedVoicePanelSource(),
                }),
            }), 'CapCut voice panel info');
            const categories = (payload.categories ?? [])
                .map((category) => ({
                id: Number(category.category_id),
                key: category.category_key ?? String(category.category_id),
            }))
                .filter((category) => Number.isFinite(category.id) && category.id > 0);
            if (categories.length === 0) {
                throw new Error('CapCut voice panel info returned no category');
            }
            this.liveVoiceCategoryIds = categories.map((category) => category.id);
            this.liveVoiceCategoryIdsLoadedAt = Date.now();
            logger_1.default.info('CapCut voice categories resolved', {
                count: categories.length,
                categories: categories.map((category) => category.key),
            });
            return categories;
        }
        catch (error) {
            const fallbackIds = this.getFallbackVoiceCategoryIds();
            logger_1.default.warn('Failed to resolve live CapCut voice categories. Falling back to configured ids', { error, fallbackIds });
            return fallbackIds.map((id) => ({ id, key: String(id) }));
        }
    }
    /**
     * 単一カテゴリの音声を has_more に従って全ページ取得する
     */
    async requestVoiceCategoryItems(category) {
        const items = [];
        let offset = 0;
        for (let page = 0; page < voiceListMaxPages; page += 1) {
            const payload = await (0, responseUtils_1.unwrapJsonResponse)(await (0, getVoiceModels_1.getVoiceModels)({
                requester: this.fetchWithCookies.bind(this),
                path: this.getResolvedVoiceListPath(),
                searchParams: this.buildArtistSearchParams(),
                headers: this.buildArtistHeaders(),
                body: JSON.stringify({
                    panel: this.getResolvedVoicePanel(),
                    category_id: category.id,
                    category_key: category.key,
                    panel_source: this.getResolvedVoicePanelSource(),
                    pack_optional: {
                        need_tag: true,
                        need_thumb: true,
                        thumb_opt: '{"is_support_webp":1}',
                        image_pack_param: {
                            icon_limit: {
                                static_format: 'webp',
                                dynamic_format: 'awebp',
                                width: 100,
                                height: 100,
                            },
                        },
                    },
                    offset,
                    count: voiceListPageSize,
                }),
            }), `CapCut voice catalog category ${category.key}`);
            const pageItems = Array.isArray(payload.effect_item_list)
                ? payload.effect_item_list
                : [];
            items.push(...pageItems);
            const nextOffset = Number(payload.next_offset);
            const hasUsableNextOffset = Number.isFinite(nextOffset) && nextOffset > offset;
            if (!payload.has_more || pageItems.length === 0) {
                break;
            }
            if (page === voiceListMaxPages - 1) {
                logger_1.default.warn('CapCut voice category page limit reached. Truncating', {
                    category: category.key,
                    collected: items.length,
                    maxPages: voiceListMaxPages,
                });
                break;
            }
            offset = hasUsableNextOffset ? nextOffset : offset + pageItems.length;
        }
        return items;
    }
    /**
     * CapCut の音声モデル一覧 API を叩く
     * カテゴリは実行時解決し、各カテゴリはページングして取り切る
     */
    async requestSpeakerList() {
        // カタログはアカウントごとに中身が違う 未ログインだと CapCut は
        // 既定のカタログを返すため、取得前に必ずログイン状態にしておく
        // これが無いと別アカウントの資格情報を渡しても既定カタログが返る
        await this.ensureAuthenticated();
        const categories = await this.loadVoiceCategories();
        const voiceResponses = await Promise.allSettled(categories.map(async (category) => ({
            category,
            items: await this.requestVoiceCategoryItems(category),
        })));
        const speakerMap = new Map();
        const failedCategories = [];
        for (const result of voiceResponses) {
            if (result.status !== 'fulfilled') {
                failedCategories.push(String(result.reason?.message ?? result.reason));
                continue;
            }
            const { category, items } = result.value;
            for (const item of items) {
                const resolvedSpeaker = (0, voiceUtils_1.parseSpeaker)(item, category.key);
                if (!resolvedSpeaker) {
                    continue;
                }
                const existing = speakerMap.get(resolvedSpeaker.resourceId);
                if (!existing) {
                    speakerMap.set(resolvedSpeaker.resourceId, resolvedSpeaker);
                    continue;
                }
                // 同じ話者が複数カテゴリに出るのでカテゴリだけ束ねる
                for (const key of resolvedSpeaker.categories ?? []) {
                    if (!existing.categories?.includes(key)) {
                        existing.categories = [...(existing.categories ?? []), key];
                    }
                }
            }
        }
        if (failedCategories.length > 0) {
            logger_1.default.warn('Some CapCut voice categories failed', {
                failedCount: failedCategories.length,
                totalCount: categories.length,
                errors: failedCategories,
            });
        }
        return Array.from(speakerMap.values());
    }
    /**
     * 実際の音声レスポンスを組み立てる
     * まず multi_platform を使い、失敗時だけ editor の create/query に退避する
     */
    async createAudioResponse(options) {
        return this.createAudioResponseWithRetry(options, true);
    }
    /**
     * 分割したテキストを並列で音声化する
     */
    async synthesizeChunkedBuffers(options, chunkedTexts) {
        const chunkResults = await Promise.all(chunkedTexts.map(async (chunkText) => {
            const response = await this.createAudioResponse({
                ...options,
                text: chunkText,
            });
            const buffer = Buffer.from(await response.arrayBuffer());
            return {
                buffer,
                contentType: response.headers.get('content-type') ?? 'audio/mpeg',
                contentLength: response.headers.get('content-length') ?? undefined,
                fileName: this.extractFileName(response),
            };
        }));
        return chunkResults;
    }
    /**
     * セッション切れだけ 1 回だけ再ログインして再試行する
     */
    async createAudioResponseWithRetry(options, allowRetry) {
        try {
            const speakers = await this.loadSpeakers();
            const resolvedSpeaker = (0, voiceUtils_1.resolveSpeaker)(options.type, speakers, options.speaker, options.platform);
            await this.ensureAuthenticated();
            try {
                return await this.createAudioViaMultiPlatform(resolvedSpeaker, options);
            }
            catch (error) {
                logger_1.default.info('CapCut multi_platform TTS failed. Falling back to editor intelligence flow', { error });
            }
            const session = await this.ensureAuthenticated();
            const taskId = await this.createTtsTask(session.workspaceId, resolvedSpeaker, options);
            const taskDetail = await this.waitForTtsTask(session.workspaceId, taskId);
            if (taskDetail.url) {
                return this.fetchDirectAudio(taskDetail.url);
            }
            const fallbackUrl = taskDetail.transcode_audio_info?.[0]?.url;
            if (fallbackUrl) {
                return this.fetchDirectAudio(fallbackUrl);
            }
            throw new Error('CapCut TTS task completed without an audio URL');
        }
        catch (error) {
            if (allowRetry && (0, capcutUtils_1.isSessionExpiredError)(error)) {
                logger_1.default.info('CapCut session appears expired. Re-authenticating once', {
                    error,
                });
                await this.ensureAuthenticated(true);
                return this.createAudioResponseWithRetry(options, false);
            }
            throw error;
        }
    }
    /**
     * 直接音声 URL を返す multi_platform フロー
     */
    async createAudioViaMultiPlatform(resolvedSpeaker, options) {
        const ttsData = await this.requestSignedEditJson({
            path: this.getResolvedMultiPlatformPath(),
            appVersion: this.getResolvedEditorAppVersion(),
            tdid: this.tdid,
            // lan を送らないと engine が読み上げ言語を取り違える
            // ベトナム語のテキストをマレー語として読む事例を確認している
            extraHeaders: {
                lan: env_1.default.CAPCUT_LOCALE,
                loc: env_1.default.CAPCUT_REGION,
            },
            body: {
                texts: [options.text],
                tts_conf: {
                    speaker: resolvedSpeaker.speaker,
                    rate: (0, capcutUtils_1.toPlaybackRate)(options.speed),
                    volume: (0, capcutUtils_1.toVolumeLevel)(options.volume),
                    name: resolvedSpeaker.title,
                    platform: resolvedSpeaker.platform ?? 'sami',
                    effect_id: resolvedSpeaker.effectId,
                    resource_id: resolvedSpeaker.resourceId,
                    is_clone: false,
                },
                need_url: true,
            },
            request: ({ headers, body }) => (0, createMultiPlatformTts_1.createMultiPlatformTts)({
                requester: this.fetchWithCookies.bind(this),
                path: this.getResolvedMultiPlatformPath(),
                headers,
                body,
            }),
            context: 'CapCut multi_platform TTS',
        });
        const audioUrl = ttsData.tts_materials?.[0]?.meta_data?.url;
        if (!audioUrl) {
            throw new Error('CapCut multi_platform TTS did not return an audio URL');
        }
        return this.fetchDirectAudio(audioUrl);
    }
    /**
     * 話者が属する TTS エンジンの platform 番号を返す
     *
     * 11labs の話者へ既定値を送ると別エンジンで読み上げられ
     * ベトナム語などが正しく発音されないため必ず話者側の指定に従う
     */
    resolveTtsPlatformId(resolvedSpeaker) {
        const platformKey = resolvedSpeaker.platform?.trim().toLowerCase();
        if (!platformKey) {
            return ttsPlatform;
        }
        const platformId = ttsPlatformIds[platformKey];
        if (!platformId) {
            logger_1.default.warn('Unknown CapCut TTS platform. Falling back to default', {
                platform: resolvedSpeaker.platform,
                speaker: resolvedSpeaker.speaker,
            });
            return ttsPlatform;
        }
        return platformId;
    }
    /**
     * editor intelligence タスクを作成する
     */
    async createTtsTask(workspaceId, resolvedSpeaker, options) {
        const data = await this.requestSignedEditJson({
            path: this.getResolvedCreateTaskPath(),
            appVersion: this.getResolvedEditorAppVersion(),
            extraHeaders: {
                lan: env_1.default.CAPCUT_LOCALE,
            },
            searchParams: {
                aid: appId,
                device_platform: 'web',
                region: env_1.default.CAPCUT_REGION,
                web_id: this.deviceId,
            },
            body: {
                workspace_id: workspaceId,
                smart_tool_type: ttsSmartToolType,
                scene: ttsScene,
                params: JSON.stringify({
                    text: options.text,
                    platform: this.resolveTtsPlatformId(resolvedSpeaker),
                }),
                req_json: JSON.stringify({
                    speaker: resolvedSpeaker.speaker,
                    audio_config: {},
                    disable_caption: true,
                    commerce: {
                        resource_type: 'material_artist',
                        benefit_type: 'resource_export',
                        resource_id: resolvedSpeaker.resourceId,
                    },
                }),
            },
            request: ({ searchParams, headers, body }) => (0, createTtsTask_1.createTtsTask)({
                requester: this.fetchWithCookies.bind(this),
                path: this.getResolvedCreateTaskPath(),
                searchParams,
                headers,
                body,
            }),
            context: 'CapCut TTS create',
        });
        if (!data.task_id) {
            throw new Error('CapCut TTS create did not return task_id');
        }
        return data.task_id;
    }
    /**
     * editor intelligence タスクの完了を待つ
     */
    async waitForTtsTask(workspaceId, taskId) {
        for (let attempt = 0; attempt < ttsMaxPollAttempts; attempt += 1) {
            const data = await this.requestSignedEditJson({
                path: this.getResolvedQueryTaskPath(),
                appVersion: this.getResolvedEditorAppVersion(),
                extraHeaders: {
                    lan: env_1.default.CAPCUT_LOCALE,
                },
                searchParams: {
                    aid: appId,
                    device_platform: 'web',
                    region: env_1.default.CAPCUT_REGION,
                    web_id: this.deviceId,
                },
                body: {
                    task_id: taskId,
                    workspace_id: workspaceId,
                    smart_tool_type: ttsSmartToolType,
                },
                request: ({ searchParams, headers, body }) => (0, queryTtsTask_1.queryTtsTask)({
                    requester: this.fetchWithCookies.bind(this),
                    path: this.getResolvedQueryTaskPath(),
                    searchParams,
                    headers,
                    body,
                }),
                context: 'CapCut TTS query',
            });
            const status = Number(data.status ?? 0);
            if (status === 2 && data.task_detail?.[0]) {
                return data.task_detail[0];
            }
            if (status !== 1) {
                throw new Error(`CapCut TTS query failed with status ${status}`);
            }
            await new Promise((resolve) => setTimeout(resolve, ttsPollIntervalMs));
        }
        throw new Error('CapCut TTS query timed out');
    }
    /**
     * 直接音声 URL を取得する
     */
    async fetchDirectAudio(url) {
        const response = await (0, downloadAudio_1.downloadAudio)({
            requester: async (requestUrl, init) => fetch(requestUrl, init),
            url,
            headers: {
                Accept: 'application/json, text/plain, */*',
                'User-Agent': env_1.default.USER_AGENT,
            },
        });
        if (!response.ok) {
            const body = await response.text();
            throw new Error(`CapCut audio download failed: ${response.status} ${response.statusText} ${(0, httpUtils_1.getResponseBodySnippet)(body)}`);
        }
        return response;
    }
    /**
     * edit-api 向け署名付き POST を送る
     * sign は最終 URL の path 末尾 7 文字と tdid を使うので、ここで組み立ててから送る
     */
    async requestSignedEditJson(options) {
        if (this.runtimeEditorBundleConfig.sourceUrls.length === 0) {
            await this.ensureEditorBundleConfig(true);
        }
        else if (!this.hasUsableEditorBundleConfig()) {
            await this.ensureEditorBundleConfig(true);
        }
        const searchParams = options.searchParams ?? {};
        const targetUrl = new URL(options.path, env_1.default.CAPCUT_EDIT_API_URL);
        for (const [key, value] of Object.entries(searchParams)) {
            targetUrl.searchParams.set(key, value);
        }
        const tdid = options.tdid ?? '';
        const { sign, deviceTime } = (0, apiClient_1.createEditApiSignature)(targetUrl.toString(), this.getResolvedPlatformId(), options.appVersion, tdid, this.getResolvedSignRecipe());
        return (0, responseUtils_1.unwrapJsonResponse)(await options.request({
            searchParams,
            headers: new Headers({
                Accept: 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                Origin: env_1.default.CAPCUT_WEB_URL,
                Referer: `${env_1.default.CAPCUT_WEB_URL}/`,
                'User-Agent': env_1.default.USER_AGENT,
                appid: appId,
                appvr: options.appVersion,
                'device-time': deviceTime,
                did: this.deviceId,
                pf: this.getResolvedPlatformId(),
                sign,
                'sign-ver': this.getResolvedSignVersion(),
                'store-country-code': env_1.default.CAPCUT_STORE_COUNTRY_CODE,
                'store-country-code-src': 'uid',
                tdid,
                ...options.extraHeaders,
            }),
            body: JSON.stringify(options.body),
        }), options.context);
    }
    /**
     * Cookie を差し込んで fetch する共通口
     */
    async fetchWithCookies(url, init) {
        // 復元前の空の Cookie jar で走らせない
        // /v2/speakers は認証を通らないため、ここで復元しないと空の jar のまま
        // sessionDirty が立ち、保存済みセッションを空で上書きしてしまう
        await this.ensureRestored();
        const headers = new Headers(init.headers);
        const cookieHeader = this.cookieJar.getCookieHeader(url);
        if (cookieHeader) {
            headers.set('Cookie', cookieHeader);
        }
        logger_1.default.debug('CapCut request', {
            method: init.method ?? 'GET',
            url,
            headers: sanitizeHeadersForDebugLog(headers),
            body: toLoggableBody(init.body),
        });
        const response = await fetch(url, {
            ...init,
            headers,
        });
        this.cookieJar.storeFromResponse(response, url);
        this.syncDeviceIdFromCookies();
        // ここで毎回書き込むと TTS ポーリング 1 回の合成で 30 回以上ストレージへ
        // 書きに行ってしまう ダーティフラグだけ立てて、リクエスト終端で 1 回流す
        this.sessionDirty = true;
        let responseBodySnippet = '';
        try {
            const clonedResponse = response.clone();
            responseBodySnippet = (0, httpUtils_1.getResponseBodySnippet)(await clonedResponse.text());
        }
        catch (error) {
            responseBodySnippet = `[unavailable: ${error instanceof Error ? error.message : 'unknown error'}]`;
        }
        logger_1.default.debug('CapCut response', {
            method: init.method ?? 'GET',
            url,
            status: response.status,
            statusText: response.statusText,
            headers: sanitizeHeadersForDebugLog(new Headers(response.headers)),
            body: responseBodySnippet,
        });
        return response;
    }
    /**
     * Cookie から did 候補を同期する
     * _tea_web_id が取れたときはそれを最優先する
     */
    syncDeviceIdFromCookies() {
        if (env_1.default.CAPCUT_DEVICE_ID) {
            return;
        }
        const cookieDeviceId = this.cookieJar.get('_tea_web_id') ??
            this.cookieJar.get('_tea_web_id', env_1.default.CAPCUT_WEB_URL) ??
            this.cookieJar.get('_tea_web_id', env_1.default.CAPCUT_LOGIN_HOST) ??
            this.cookieJar.get('web_id') ??
            this.cookieJar.get('did');
        if (cookieDeviceId) {
            this.deviceId = cookieDeviceId;
        }
    }
    /**
     * passport 系 API 向けの CSRF Cookie を取得する
     */
    getPassportCsrfToken(url) {
        return (this.cookieJar.get('passport_csrf_token', url) ??
            this.cookieJar.get('passport_csrf_token_default', url));
    }
    /**
     * Content-Disposition からファイル名を抽出する
     */
    extractFileName(response) {
        const disposition = response.headers.get('content-disposition');
        if (!disposition) {
            return undefined;
        }
        const match = disposition.match(/filename="?([^"]+)"?/i);
        return match?.[1];
    }
}
const normalizeString = (value) => typeof value === 'string' ? value : null;
const normalizeStringId = (value) => typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'bigint'
    ? String(value)
    : null;
/**
 * email/login 失敗時に user/login へフォールバックしてよいかを判定する
 * CapCut の業務エラー時は user/login へ進むと別のエラーで上書きされやすい
 */
const shouldFallbackToUserLogin = (error) => error instanceof responseUtils_1.CapCutApiError &&
    (error.statusCode === 404 || error.statusCode === 405);
/**
 * 別 login host へ再試行してよいかを判定する
 * error_code が返っている時は host を変えても改善しにくいため、その場で止める
 */
const shouldTryOtherLoginHost = (error) => !(error instanceof responseUtils_1.CapCutApiError && error.errorCode !== undefined);
const isSemverLike = (value) => typeof value === 'string' &&
    /^\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?$/.test(value);
/**
 * デバッグログ用に秘匿ヘッダーを伏せる
 */
const sanitizeHeadersForDebugLog = (headers) => {
    const hiddenHeaderNames = new Set([
        'cookie',
        'authorization',
        'x-tt-passport-csrf-token',
    ]);
    const entries = Object.fromEntries(headers.entries());
    for (const [key, value] of Object.entries(entries)) {
        if (hiddenHeaderNames.has(key.toLowerCase())) {
            entries[key] = value ? '[redacted]' : value;
        }
    }
    return entries;
};
/**
 * デバッグログ向けに本文を短く整形する
 */
const toLoggableBody = (body) => {
    if (typeof body === 'string') {
        return (0, httpUtils_1.getResponseBodySnippet)(body);
    }
    if (body === undefined || body === null) {
        return '';
    }
    return `[${body.constructor.name}]`;
};
let instance = null;
/** アカウント別インスタンス 資格情報が渡されたときだけ使う */
const accountInstances = new Map();
/** 1 プロセスで抱えるアカウント数の上限 無制限に増やさない */
const maxAccountInstances = 20;
/**
 * サービス本体を返す 初回参照時に生成する
 *
 * モジュール評価時に new すると env へ触れてしまい、
 * bindings がまだ無い Workers では起動に失敗するため遅延させる
 *
 * @param credentials - 指定するとそのアカウント専用のインスタンスを返す
 */
const getCapCutService = (credentials) => {
    if (credentials?.email && credentials.password) {
        const key = credentials.email.trim().toLowerCase();
        const existing = accountInstances.get(key);
        if (existing) {
            return existing;
        }
        // 単純な FIFO で打ち切る 古いものから捨てる
        if (accountInstances.size >= maxAccountInstances) {
            const oldest = accountInstances.keys().next().value;
            if (oldest !== undefined) {
                accountInstances.delete(oldest);
            }
        }
        const created = new CapCutService({
            email: credentials.email.trim(),
            password: credentials.password,
        });
        accountInstances.set(key, created);
        return created;
    }
    if (!instance) {
        instance = new CapCutService();
    }
    return instance;
};
exports.getCapCutService = getCapCutService;
// 既存の capCutService.method() という呼び出しを保ったまま生成だけ遅らせる
exports.capCutService = new Proxy({}, {
    get: (_target, property) => {
        const service = (0, exports.getCapCutService)();
        const value = service[property];
        return typeof value === 'function' ? value.bind(service) : value;
    },
});
let sessionRefreshTimer = null;
/**
 * CapCut セッションのバックグラウンド更新を開始する
 */
const startCapCutSessionTask = async () => {
    try {
        await exports.capCutService.warmup();
    }
    catch (error) {
        logger_1.default.warn('Initial CapCut session warmup failed. The service will retry in the background', { error });
    }
    if (sessionRefreshTimer) {
        clearInterval(sessionRefreshTimer);
    }
    sessionRefreshTimer = setInterval(() => {
        void exports.capCutService.ensureAuthenticated().catch((error) => {
            logger_1.default.warn('Background CapCut session validation failed', { error });
        });
    }, env_1.default.SESSION_REFRESH_INTERVAL_MINUTES * 60 * 1000);
    sessionRefreshTimer.unref?.();
};
exports.startCapCutSessionTask = startCapCutSessionTask;
exports.default = exports.capCutService;
//# sourceMappingURL=CapCutService.js.map