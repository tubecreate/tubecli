import crypto from 'node:crypto';
import { Readable } from 'node:stream';
import { checkEmailRegistered } from '@/api/capcut-login/api/checkEmailRegistered';
import { emailLogin } from '@/api/capcut-login/api/emailLogin';
import { resolveRegion } from '@/api/capcut-login/api/resolveRegion';
import { userLogin } from '@/api/capcut-login/api/userLogin';
import { createEditApiSignature } from '@/api/capcut-edit/apiClient';
import { createMultiPlatformTts } from '@/api/capcut-edit/api/createMultiPlatformTts';
import { createTtsTask } from '@/api/capcut-edit/api/createTtsTask';
import { getUserWorkspaces } from '@/api/capcut-edit/api/getUserWorkspaces';
import { getVoiceModels } from '@/api/capcut-edit/api/getVoiceModels';
import { getVoicePanelInfo } from '@/api/capcut-edit/api/getVoicePanelInfo';
import { queryTtsTask } from '@/api/capcut-edit/api/queryTtsTask';
import { downloadAudio } from '@/api/capcut-media/api/downloadAudio';
import { getAccountInfo } from '@/api/capcut-web/api/getAccountInfo';
import { getLoginPage } from '@/api/capcut-web/api/getLoginPage';
import env from '@/configs/env';
import { CookieJar } from '@/lib/capcut/cookieJar';
import { getBlobStorage } from '@/lib/storage';
import { getSessionStore } from '@/lib/storage/sessionStore';
import { capCutConstants } from '@/lib/capcut/constants';
import { CapCutApiError, unwrapJsonResponse } from '@/lib/capcut/responseUtils';
import { splitTtsText } from '@/lib/string';
import { synthesizeWithTimestamps } from '@/lib/capcut/ttsWebSocket';
import type { TtsWebSocketResult } from '@/lib/capcut/ttsWebSocket';
import {
  filterSpeakerInfoList,
  normalizeLanguageCode,
  parseSpeaker,
  resolveSpeaker,
  toSpeakerInfoList,
} from '@/lib/capcut/voiceUtils';
import {
  capCutLanguageCountries,
  capCutVoiceCategoryIds,
} from '@/models/capcutVoiceCategories';
import { fallbackSpeakers } from '@/models/capcutSpeakers';
import {
  brokenVoiceCombos,
  isBrokenVoice,
} from '@/models/capcutVoiceQuality';
import capCutBundleService from '@/services/CapCutBundleService';
import logger from '@/services/logger';
import type {
  CapCutEditorBundleConfig,
  CapCutLoginBundleConfig,
} from '@/types/capcutBundle';
import type {
  AccountInfo,
  LoginResponse,
  MultiPlatformTtsResponse,
  RegionResponse,
  TtsQueryResponse,
  TtsTaskDetail,
  TtsTaskResponse,
  VoiceListResponse,
  VoicePanelInfoResponse,
  WorkspaceInfo,
  WorkspaceListResponse,
} from '@/types/capcutApi';
import type {
  AudioResult,
  AudioStreamResult,
  CapCutSessionState,
  SpeakerFilter,
  SpeakerInfo,
  Speaker,
  SynthesizeOptions,
} from '@/types/capcut';
import type { PersistedSessionState } from '@/types/capcutSession';
import {
  buildSensitiveFormBody,
  createDeviceId,
  createEmailRegionHashWithSalt,
  createTrackingId,
  createVerifyFp,
  isLoginAttemptLimitError,
  isSessionExpiredError,
  toPlaybackRate,
  toVolumeLevel,
} from '@/utils/capcutUtils';
import { getResponseBodySnippet } from '@/utils/httpUtils';

const {
  appId,
  editorAppVersion,
  loginSdkVersion,
  platformId,
  sessionValidateMs,
  sessionLifetimeMs,
  loginLockMs,
  loginWaitAttempts,
  loginWaitIntervalMs,
  loginFailureBackoffMs,
  loginAttemptLimitBackoffMs,
  signVersion,
  ttsMaxPollAttempts,
  ttsPlatform,
  ttsPlatformIds,
  ttsPollIntervalMs,
  ttsScene,
  ttsSmartToolType,
  ttsTokenPath,
  ttsWebSocketUrl,
  ttsSampleRate,
  voiceCacheMs,
  voiceCategoryCacheMs,
  voiceFallbackRetryMs,
  voiceListMaxPages,
  voiceListPageSize,
  voicePanel,
  voicePanelInfoPath,
  voicePanelSource,
  webAppVersion,
} = capCutConstants;

/**
 * CapCut とのセッション維持と TTS 実行を担当するサービス
 * 状態を持つ本体は services に残し、通信や変換の詳細は lib utils api へ逃がしている
 */
/**
 * リクエストごとに差し替え可能な CapCut 資格情報
 */
export interface CapCutCredentials {
  email: string;
  password: string;
}

class CapCutService {
  private readonly cookieJar = new CookieJar();

  private readonly credentials: CapCutCredentials | null;

  constructor(credentials: CapCutCredentials | null = null) {
    this.credentials = credentials;
  }

  private get accountEmail() {
    return this.credentials?.email ?? env.CAPCUT_EMAIL;
  }

  private get accountPassword() {
    return this.credentials?.password ?? env.CAPCUT_PASSWORD;
  }

  /**
   * セッション JSON の保存キー
   * Node ではファイルパス、Workers では R2 のオブジェクトキーになる
   *
   * アカウントごとにセッションが混ざらないよう、既定以外の資格情報では
   * メールアドレスのハッシュを鍵へ混ぜる
   */
  private get sessionStoreKey() {
    const base = env.CAPCUT_SESSION_STORE_PATH;

    if (!this.credentials) {
      return base;
    }

    const suffix = crypto
      .createHash('sha256')
      .update(this.credentials.email.trim().toLowerCase())
      .digest('hex')
      .slice(0, 16);

    return base.replace(/(\.json)?$/i, `.${suffix}$1`);
  }

  private restorePromise: Promise<void> | null = null;

  // 以下 3 つは env に依存するため、フィールド初期化ではなく初回参照時に解決する
  // Workers では bindings が届く前にモジュールが評価されるため
  /**
   * アカウント固有の派生シード
   *
   * env で固定した device fingerprint を全アカウントで共有すると、
   * 別アカウントのログイン失敗が本体アカウントまで巻き込んで
   * CapCut 側のログイン試行制限に引っかかる 実際に発生させたので分離する
   */
  private get accountSeed(): string | null {
    if (!this.credentials) {
      return null;
    }

    return crypto
      .createHash('sha256')
      .update(this.credentials.email.trim().toLowerCase())
      .digest('hex');
  }

  private deviceIdValue: string | null = null;

  private get deviceId(): string {
    if (!this.deviceIdValue) {
      const seed = this.accountSeed;
      this.deviceIdValue = seed
        ? `7${BigInt('0x' + seed.slice(0, 15)).toString().padStart(18, '0').slice(0, 18)}`
        : (env.CAPCUT_DEVICE_ID ?? createDeviceId());
    }

    return this.deviceIdValue;
  }

  private set deviceId(value: string) {
    this.deviceIdValue = value;
  }

  private tdidValue: string | null = null;

  private get tdid(): string {
    if (!this.tdidValue) {
      const seed = this.accountSeed;
      this.tdidValue = seed
        ? BigInt('0x' + seed.slice(15, 29)).toString().padStart(17, '0').slice(0, 17)
        : (env.CAPCUT_TDID ?? createTrackingId());
    }

    return this.tdidValue;
  }

  private set tdid(value: string) {
    this.tdidValue = value;
  }

  private session: CapCutSessionState | null = null;

  private sessionPromise: Promise<CapCutSessionState> | null = null;

  private speakers: Speaker[] | null = null;

  private speakersLoadedAt = 0;

  /** 生きた音声カタログを引けず fallback で凌いでいる状態か */
  private speakersDegraded = false;

  private liveVoiceCategoryIds: number[] | null = null;

  private liveVoiceCategoryIdsLoadedAt = 0;

  private verifyFpValue: string | null = null;

  private get verifyFp(): string {
    if (!this.verifyFpValue) {
      this.verifyFpValue = this.accountSeed
        ? createVerifyFp()
        : (env.CAPCUT_VERIFY_FP ?? createVerifyFp());
    }

    return this.verifyFpValue;
  }

  private set verifyFp(value: string) {
    this.verifyFpValue = value;
  }

  private runtimeLoginBundleConfig: CapCutLoginBundleConfig = {};

  private runtimeEditorBundleConfig: CapCutEditorBundleConfig = {
    sourceUrls: [],
  };

  /**
   * 永続化済みセッションの復元を一度だけ走らせる
   *
   * コンストラクタで起動すると Workers では bindings 到着前に走ってしまうため
   * 最初に必要になった時点まで遅らせる
   */
  private ensureRestored(): Promise<void> {
    if (!this.restorePromise) {
      this.restorePromise = this.restorePersistedSession();
    }

    return this.restorePromise;
  }

  /**
   * 音声をバッファとして取得する
   */
  async synthesizeBuffer(options: SynthesizeOptions): Promise<AudioResult> {
    const chunkedTexts = splitTtsText(
      options.text,
      env.CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH,
      env.CAPCUT_TTS_TEXT_CHUNK_BOUNDARY_SEARCH_RATIO
    );
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

    const chunkedResults = await this.synthesizeChunkedBuffers(
      options,
      chunkedTexts
    );
    const buffer = Buffer.concat(
      chunkedResults.map((chunkResult) => chunkResult.buffer)
    );

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
  async synthesizeStream(
    options: SynthesizeOptions
  ): Promise<AudioStreamResult> {
    const chunkedTexts = splitTtsText(
      options.text,
      env.CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH,
      env.CAPCUT_TTS_TEXT_CHUNK_BOUNDARY_SEARCH_RATIO
    );
    if (chunkedTexts.length === 1) {
      const response = await this.createAudioResponse(options);

      if (!response.body) {
        throw new Error('CapCut audio response did not contain a body');
      }

      return {
        stream: Readable.fromWeb(
          response.body as unknown as import('node:stream/web').ReadableStream
        ),
        contentType: response.headers.get('content-type') ?? 'audio/mpeg',
        contentLength: response.headers.get('content-length') ?? undefined,
        fileName: this.extractFileName(response),
      };
    }

    const audioResult = await this.synthesizeBuffer(options);

    return {
      stream: Readable.from([audioResult.buffer]),
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
  async synthesizeWithMarks(
    options: SynthesizeOptions
  ): Promise<TtsWebSocketResult> {
    const speakers = await this.loadSpeakers();
    const resolvedSpeaker = resolveSpeaker(
      options.type,
      speakers,
      options.speaker,
      options.platform
    );

    // WebSocket 経路は SAMI 専用 11labs の話者を渡すと
    // 音声 0 バイト alignment 空のまま 200 で返ってくるので先に弾く
    const speakerPlatform = resolvedSpeaker.platform?.trim().toLowerCase();

    if (speakerPlatform && speakerPlatform !== 'sami') {
      throw new CapCutApiError(
        `Word timestamps are only available for sami voices. Speaker "${resolvedSpeaker.speaker}" runs on ${resolvedSpeaker.platform}`,
        // 呼び出し側の入力が原因なので 400 として扱わせる
        { statusCode: 400 }
      );
    }

    return synthesizeWithTimestamps({
      text: options.text,
      speaker: resolvedSpeaker.speaker,
      tokenUrl: new URL(ttsTokenPath, env.CAPCUT_EDIT_API_URL).toString(),
      wsUrl: ttsWebSocketUrl,
      appId: appId,
      appVersion: this.getResolvedEditorAppVersion(),
      platformId: this.getResolvedPlatformId(),
      signVersion: this.getResolvedSignVersion(),
      sampleRate: ttsSampleRate,
      userAgent: env.USER_AGENT,
      origin: env.CAPCUT_WEB_URL,
      includePhonemes: options.phonemes ?? false,
    });
  }

  /**
   * 利用可能な話者一覧を返す
   *
   * @param filter - 言語 国 カテゴリでの絞り込み条件
   */
  async listSpeakers(filter: SpeakerFilter = {}): Promise<SpeakerInfo[]> {
    const speakers = toSpeakerInfoList(await this.loadSpeakers());

    if (!filter.language && !filter.category) {
      return speakers;
    }

    return filterSpeakerInfoList(speakers, filter);
  }

  /**
   * 話者が持つ言語コード一覧を返す
   */
  async listSpeakerLanguages(): Promise<
    Array<{ language: string; countries: string[]; speakerCount: number }>
  > {
    const speakers = toSpeakerInfoList(await this.loadSpeakers());
    const counts = new Map<string, number>();

    for (const speaker of speakers) {
      const language = normalizeLanguageCode(speaker.language);
      counts.set(language, (counts.get(language) ?? 0) + 1);
    }

    return Array.from(counts, ([language, speakerCount]) => ({
      language,
      countries: capCutLanguageCountries[language] ?? [],
      speakerCount,
    })).sort((a, b) => b.speakerCount - a.speakerCount);
  }

  /**
   * 話者プレビュー音声をキャッシュ付きで返す
   */
  async getSpeakerPreviewAudio(speakerId: string): Promise<AudioResult> {
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
  private async ensureSpeakerPreviewAudio(speakerId: string): Promise<Buffer> {
    const speakers = await this.loadSpeakers();
    const resolvedSpeaker = resolveSpeaker(speakerId, speakers, speakerId);
    const previewKey = `${env.CAPCUT_SPEAKER_PREVIEW_TEMP_DIR.replace(
      /\/+$/,
      ''
    )}/${resolvedSpeaker.speaker}.mp3`;
    const storage = getBlobStorage();
    const maxAgeMs =
      env.CAPCUT_SPEAKER_PREVIEW_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;

    const cached = await storage.readBlob(previewKey);

    if (cached && Date.now() - cached.uploadedAt < maxAgeMs) {
      return Buffer.from(cached.body);
    }

    const previewAudio = await this.synthesizeBuffer({
      text: env.CAPCUT_SPEAKER_PREVIEW_TEXT,
      speaker: resolvedSpeaker.speaker,
      type: 0,
      pitch: 10,
      speed: 10,
      volume: 10,
    });

    await storage.writeBlob(
      previewKey,
      new Uint8Array(previewAudio.buffer),
      'audio/mpeg'
    );

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
  async ensureAuthenticated(force = false): Promise<CapCutSessionState> {
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
        } catch (error) {
          logger.info('CapCut session validation failed. Re-authenticating', {
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
  private async refreshLoginBundleConfig() {
    this.runtimeLoginBundleConfig =
      await capCutBundleService.resolveLoginBundleConfig();
  }

  /**
   * editor bundle 由来の設定を更新する
   */
  private async refreshEditorBundleConfig() {
    this.runtimeEditorBundleConfig =
      await capCutBundleService.resolveEditorBundleConfig(
        this.fetchWithCookies.bind(this)
      );
  }

  /**
   * workspace / TTS 実行に足りる editor bundle 設定かを判定する
   */
  private hasUsableEditorBundleConfig() {
    return this.runtimeEditorBundleConfig.sourceUrls.length > 0;
  }

  /**
   * 必要なら live bundle から editor 設定を再取得する
   */
  private async ensureEditorBundleConfig(forceRefresh = false) {
    if (!forceRefresh && this.hasUsableEditorBundleConfig()) {
      return;
    }

    this.runtimeEditorBundleConfig =
      await capCutBundleService.resolveEditorBundleConfig(
        this.fetchWithCookies.bind(this),
        true
      );
  }

  /**
   * bundle 由来 login sdk version を返す
   */
  private getResolvedLoginSdkVersion() {
    return isSemverLike(this.runtimeLoginBundleConfig.sdkVersion)
      ? this.runtimeLoginBundleConfig.sdkVersion
      : loginSdkVersion;
  }

  /**
   * bundle 由来 login email path を返す
   */
  private getResolvedEmailLoginPath() {
    return (
      this.runtimeLoginBundleConfig.emailLoginPath ??
      '/passport/web/email/login/'
    );
  }

  /**
   * bundle 由来 login user path を返す
   */
  private getResolvedUserLoginPath() {
    return (
      this.runtimeLoginBundleConfig.userLoginPath ?? '/passport/web/user/login/'
    );
  }

  /**
   * bundle 由来 region path を返す
   */
  private getResolvedRegionPath() {
    return this.runtimeLoginBundleConfig.regionPath ?? '/passport/web/region/';
  }

  /**
   * bundle 由来 account info path を返す
   */
  private getResolvedAccountInfoPath() {
    return (
      this.runtimeLoginBundleConfig.accountInfoPath ??
      '/passport/web/account/info/'
    );
  }

  /**
   * bundle 由来 editor app version を返す
   */
  private getResolvedEditorAppVersion() {
    return isSemverLike(this.runtimeEditorBundleConfig.editorAppVersion)
      ? this.runtimeEditorBundleConfig.editorAppVersion
      : editorAppVersion;
  }

  /**
   * bundle 由来 web app version を返す
   */
  private getResolvedWebAppVersion() {
    return isSemverLike(this.runtimeEditorBundleConfig.webAppVersion)
      ? this.runtimeEditorBundleConfig.webAppVersion
      : webAppVersion;
  }

  /**
   * bundle 由来 version_name を返す
   */
  private getResolvedVersionName() {
    return isSemverLike(this.runtimeEditorBundleConfig.versionName)
      ? this.runtimeEditorBundleConfig.versionName
      : '11.0.0';
  }

  /**
   * bundle 由来 version_code を返す
   */
  private getResolvedVersionCode() {
    return isSemverLike(this.runtimeEditorBundleConfig.versionCode)
      ? this.runtimeEditorBundleConfig.versionCode
      : '11.0.0';
  }

  /**
   * bundle 由来 sdk_version を返す
   */
  private getResolvedSdkVersion() {
    return isSemverLike(this.runtimeEditorBundleConfig.sdkVersion)
      ? this.runtimeEditorBundleConfig.sdkVersion
      : '19.3.0';
  }

  /**
   * bundle 由来 effect_sdk_version を返す
   */
  private getResolvedEffectSdkVersion() {
    return isSemverLike(this.runtimeEditorBundleConfig.effectSdkVersion)
      ? this.runtimeEditorBundleConfig.effectSdkVersion
      : '19.3.0';
  }

  /**
   * bundle 由来 voice panel を返す
   */
  private getResolvedVoicePanel() {
    return this.runtimeEditorBundleConfig.voicePanel ?? voicePanel;
  }

  /**
   * bundle 由来 voice panel source を返す
   */
  private getResolvedVoicePanelSource() {
    return this.runtimeEditorBundleConfig.voicePanelSource ?? voicePanelSource;
  }

  /**
   * 設定由来の voice category ids を返す
   * CapCut 側で ID が入れ替わるため、実行時取得できなかったときの保険として使う
   */
  private getFallbackVoiceCategoryIds(): number[] {
    return this.runtimeEditorBundleConfig.voiceCategoryIds?.length
      ? this.runtimeEditorBundleConfig.voiceCategoryIds
      : [...capCutVoiceCategoryIds];
  }

  /**
   * bundle 由来 voice list path を返す
   */
  private getResolvedVoiceListPath() {
    return (
      this.runtimeEditorBundleConfig.voiceListPath ??
      '/artist/v1/effect/get_resources_by_category_id'
    );
  }

  /**
   * bundle 由来 workspace path を返す
   */
  private getResolvedWorkspacePath() {
    return (
      this.runtimeEditorBundleConfig.workspacePath ??
      '/cc/v1/workspace/get_user_workspaces'
    );
  }

  /**
   * bundle 由来 multi_platform path を返す
   */
  private getResolvedMultiPlatformPath() {
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
  private getResolvedCreateTaskPath() {
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
  private getResolvedQueryTaskPath() {
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
  private getResolvedSignRecipe() {
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
  private getResolvedPlatformId() {
    return this.runtimeEditorBundleConfig.signRecipe?.platformId ?? platformId;
  }

  /**
   * bundle 由来 sign version を返す
   */
  private getResolvedSignVersion() {
    return (
      this.runtimeEditorBundleConfig.signRecipe?.signVersion ?? signVersion
    );
  }

  /**
   * 永続化済みセッションを復元する
   */
  private async restorePersistedSession() {
    // deviceId と verifyFp が env で固定されていても、ここで打ち切ってはいけない
    // Cookie とセッションの復元まで飛ばしてしまい、起動のたびに再ログインが走る
    // env 側の値を優先する処理は下の各分岐が既に担当している
    try {
      const raw = await this.readSessionPayload();

      if (!raw) {
        return;
      }

      const parsed = JSON.parse(raw) as PersistedSessionState;

      if (
        !parsed ||
        !Array.isArray(parsed.cookies) ||
        typeof parsed.verifyFp !== 'string' ||
        typeof parsed.deviceId !== 'string'
      ) {
        return;
      }

      if (!env.CAPCUT_DEVICE_ID) {
        this.deviceId = parsed.deviceId;
      }

      if (!env.CAPCUT_VERIFY_FP) {
        this.verifyFp = parsed.verifyFp;
      }

      if (!env.CAPCUT_TDID && typeof parsed.tdid === 'string' && parsed.tdid) {
        this.tdid = parsed.tdid;
      }

      this.cookieJar.hydrate(parsed.cookies);
      this.syncDeviceIdFromCookies();
      this.session = parsed.session ?? null;
    } catch (error) {
      logger.warn('Failed to restore persisted CapCut session', { error });
    }
  }

  /**
   * セッションをディスクへ保存する
   */
  /** Cookie などが変わったが、まだ保存していない状態か */
  private sessionDirty = false;

  /** D1 の楽観ロック用 読み出したときの version */
  private sessionVersion: number | null = null;

  /**
   * 変更があれば保存する
   *
   * Workers ではレスポンス返却後に未完了の promise が打ち切られるため
   * 呼び出し側で ctx.waitUntil に載せて使う
   */
  async flushSession(): Promise<void> {
    if (!this.sessionDirty) {
      return;
    }

    // 読み込んでいないものを上書きしない
    // 復元が走っていない状態で保存すると、保存済みセッションを空の jar で潰す
    if (!this.restorePromise) {
      logger.warn('Skipped session flush before restore');
      this.sessionDirty = false;
      return;
    }

    await this.persistSession();
  }

  private async persistSession() {
    // ログインが確立していない状態で保存しない
    //
    // 失敗した試行の中途半端な Cookie jar を書くと、次の isolate が
    // それを復元して壊れたセッションを掴み、また再ログインを始めてしまう
    if (!this.session) {
      this.sessionDirty = false;
      return;
    }

    try {
      const payload: PersistedSessionState = {
        session: this.session,
        cookies: this.cookieJar.serialize(),
        verifyFp: this.verifyFp,
        deviceId: this.deviceId,
        tdid: this.tdid,
      };

      await this.writeSessionPayload(JSON.stringify(payload, null, 2));
      this.sessionDirty = false;
    } catch (error) {
      logger.warn('Failed to persist CapCut session', { error });
    }
  }

  /**
   * セッション JSON を読む D1 があればそちら優先
   */
  private async readSessionPayload(): Promise<string | null> {
    const store = getSessionStore();

    if (store) {
      const record = await store.read(this.sessionStoreKey);
      this.sessionVersion = record?.version ?? null;

      return record?.payload ? record.payload : null;
    }

    return getBlobStorage().readText(this.sessionStoreKey);
  }

  /**
   * セッション JSON を書く
   *
   * D1 では version が一致したときだけ書く 負けた側は書かない
   * 先に他 isolate が更新していれば、そちらの方が新しいので上書きしない
   */
  private async writeSessionPayload(payload: string): Promise<void> {
    const store = getSessionStore();

    if (!store) {
      await getBlobStorage().writeText(this.sessionStoreKey, payload);
      return;
    }

    const expiresAt = Date.now() + sessionLifetimeMs;
    const written = await store.write(
      this.sessionStoreKey,
      payload,
      expiresAt,
      this.sessionVersion
    );

    if (written) {
      this.sessionVersion =
        this.sessionVersion === null ? 1 : this.sessionVersion + 1;
      return;
    }

    // 競り負けた 相手の方が新しいので読み直しておく
    const latest = await store.read(this.sessionStoreKey);
    this.sessionVersion = latest?.version ?? null;
    logger.debug('Session write skipped, another writer was ahead');
  }

  /**
   * passport 系 API 用の CSRF Cookie を事前に投入する
   */
  private seedPassportCookies() {
    const csrf = crypto.randomBytes(16).toString('hex');
    const domains = [
      new URL(env.CAPCUT_WEB_URL).hostname,
      new URL(env.CAPCUT_LOGIN_HOST).hostname,
      new URL(env.CAPCUT_FALLBACK_LOGIN_HOST).hostname,
    ];

    for (const domain of domains) {
      this.cookieJar.set('passport_csrf_token', csrf, domain);
      this.cookieJar.set('passport_csrf_token_default', csrf, domain);
    }
  }

  /**
   * login host を切り替える前に Cookie 状態を初期化する
   */
  private async resetLoginAttemptState() {
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
  private async loginWithGlobalLock(): Promise<CapCutSessionState> {
    const store = getSessionStore();

    if (!store) {
      return this.login();
    }

    const key = this.sessionStoreKey;
    const existing = await store.read(key);

    // 直前のログインが失敗している間は誰も試さない
    // ここで殺到させると CapCut のログイン試行上限を一瞬で使い切る
    if (existing && existing.failUntil > Date.now()) {
      const waitSeconds = Math.ceil((existing.failUntil - Date.now()) / 1000);

      throw new CapCutApiError(
        `CapCut login is backing off after a recent failure. Retry in ${waitSeconds}s`
      );
    }

    if (await store.acquireLock(key, loginLockMs)) {
      try {
        const session = await this.login();
        await store.releaseLock(key).catch(() => undefined);

        return session;
      } catch (error) {
        // 失敗を全 isolate へ伝える 次の試行はこの後まで止まる
        // 試行上限に当たった場合は長めに待つ 短く刻むと解除前に使い切る
        const backoffMs = isLoginAttemptLimitError(error)
          ? loginAttemptLimitBackoffMs
          : loginFailureBackoffMs;

        await store.markLoginFailure(key, backoffMs).catch(() => undefined);
        logger.warn('CapCut login failed. Backing off', {
          minutes: Math.round(backoffMs / 60000),
        });
        throw error;
      }
    }

    logger.info('Another worker is logging in. Waiting for its session');

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
        throw new CapCutApiError(
          'CapCut login failed on another worker. Backing off'
        );
      }
    }

    // ここで自分もログインしに行くと、障害時に全 isolate が殺到してしまう
    // 呼び出し側にはエラーを返し、次のリクエストへ委ねる
    throw new CapCutApiError(
      'Timed out waiting for the shared CapCut session. Try again shortly'
    );
  }

  /**
   * CapCut へログインしてワークスペースまで確定させる
   */
  private async login(): Promise<CapCutSessionState> {
    logger.info('CapCut login flow started');
    this.verifyFp = env.CAPCUT_VERIFY_FP ?? createVerifyFp();
    await this.refreshLoginBundleConfig();
    await this.resetLoginAttemptState();

    const resolvedRegion = await this.resolveLoginRegion().catch((error) => {
      logger.info('CapCut region bootstrap failed. Falling back to defaults', {
        error,
      });
      return null;
    });

    const loginHosts = [
      resolvedRegion?.domain,
      env.CAPCUT_LOGIN_HOST,
      env.CAPCUT_FALLBACK_LOGIN_HOST,
    ].filter(
      (value, index, values): value is string =>
        Boolean(value) && values.indexOf(value) === index
    );

    let lastError: unknown;

    for (const [index, loginHost] of loginHosts.entries()) {
      try {
        if (index > 0) {
          // 前回 host の session cookie を持ち越すと account/info が失効扱いになりやすい
          await this.resetLoginAttemptState();
        }

        await this.primeLoginState(loginHost);
        const loginData = await this.loginWithHost(loginHost);
        const accountInfo = await this.fetchAccountInfo().catch((error) => {
          logger.info(
            `CapCut account info lookup failed after login via ${loginHost}`,
            { error }
          );
          return null;
        });
        await this.ensureEditorBundleConfig(true);
        const workspace = await this.fetchPrimaryWorkspace();

        const session: CapCutSessionState = {
          userId:
            normalizeStringId(accountInfo?.user_id) ??
            normalizeStringId(loginData.user_id_str) ??
            normalizeStringId(loginData.user_id) ??
            '',
          screenName:
            normalizeString(accountInfo?.screen_name) ??
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
        logger.info('CapCut session established', {
          userId: session.userId,
          workspaceId: session.workspaceId,
          loginHost,
        });
        return session;
      } catch (error) {
        lastError = error;
        logger.warn(`CapCut login via ${loginHost} failed`, { error });

        // 試行回数の上限に当たったら、別 host を試しても無意味で
        // 残り試行を減らすだけなので、ここで打ち切る
        if (isLoginAttemptLimitError(error)) {
          logger.warn(
            'CapCut reported the login attempt limit. Stopping without trying other hosts'
          );
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
  private async primeCookies() {
    const response = await getLoginPage({
      requester: this.fetchWithCookies.bind(this),
      path: `/${env.CAPCUT_PAGE_LOCALE}/login`,
      headers: {
        Accept:
          'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': env.CAPCUT_LOCALE,
        'User-Agent': env.USER_AGENT,
      },
    });

    this.syncDeviceIdFromCookies();

    if (!response.ok) {
      const body = await response.text();
      throw new Error(
        `CapCut login page bootstrap failed: ${response.status} ${response.statusText} ${getResponseBodySnippet(
          body
        )}`
      );
    }
  }

  /**
   * login 前に check_email_registered を叩いて SDK の前提状態を近づける
   */
  private async primeLoginState(loginHost: string) {
    try {
      await checkEmailRegistered({
        requester: this.fetchWithCookies.bind(this),
        host: loginHost,
        searchParams: {
          aid: appId,
          account_sdk_source: 'web',
          sdk_version: this.getResolvedLoginSdkVersion(),
          language: env.CAPCUT_LOCALE,
          verifyFp: this.verifyFp,
        },
        headers: {
          Accept: 'application/json, text/javascript',
          'Content-Type': 'application/x-www-form-urlencoded',
          'User-Agent': env.USER_AGENT,
          appid: appId,
          did: this.deviceId,
          Origin: env.CAPCUT_WEB_URL,
          Referer: `${env.CAPCUT_WEB_URL}/${env.CAPCUT_PAGE_LOCALE}/login`,
          'store-country-code': env.CAPCUT_STORE_COUNTRY_CODE,
          'store-country-code-src': 'uid',
          'x-tt-passport-csrf-token':
            this.getPassportCsrfToken(loginHost) ?? '',
        },
        body: buildSensitiveFormBody(
          {
            email: this.accountEmail,
          },
          ['email']
        ),
      });
    } catch (error) {
      logger.debug('CapCut login preflight failed', { error, loginHost });
    }
  }

  /**
   * メールアドレスに応じた login host を問い合わせる
   */
  private async resolveLoginRegion(): Promise<RegionResponse> {
    const response = await resolveRegion({
      requester: this.fetchWithCookies.bind(this),
      host: env.CAPCUT_LOGIN_HOST,
      path: this.getResolvedRegionPath(),
      searchParams: {
        aid: appId,
        account_sdk_source: 'web',
        sdk_version: this.getResolvedLoginSdkVersion(),
        language: env.CAPCUT_LOCALE,
        verifyFp: this.verifyFp,
        mix_mode: '1',
      },
      headers: {
        Accept: 'application/json, text/javascript',
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': env.USER_AGENT,
        appid: appId,
        did: this.deviceId,
        Origin: env.CAPCUT_WEB_URL,
        Referer: `${env.CAPCUT_WEB_URL}/`,
        'store-country-code': env.CAPCUT_STORE_COUNTRY_CODE,
        'store-country-code-src': 'cdn',
        'x-tt-passport-csrf-token': '',
      },
      body: new URLSearchParams({
        type: '2',
        hashed_id: createEmailRegionHashWithSalt(
          this.accountEmail,
          this.runtimeLoginBundleConfig.emailHashSalt
        ),
      }).toString(),
    });

    return unwrapJsonResponse<RegionResponse>(
      response,
      'CapCut region bootstrap'
    );
  }

  /**
   * email/password ログインを実行する
   * まず email/login を試し、endpoint 不整合らしい場合だけ user/login へフォールバックする
   */
  private async loginWithHost(loginHost: string): Promise<LoginResponse> {
    const searchParams = {
      aid: appId,
      account_sdk_source: 'web',
      sdk_version: this.getResolvedLoginSdkVersion(),
      language: env.CAPCUT_LOCALE,
      verifyFp: this.verifyFp,
    };
    const headers = {
      Accept: 'application/json, text/javascript',
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': env.USER_AGENT,
      appid: appId,
      did: this.deviceId,
      Origin: env.CAPCUT_WEB_URL,
      Referer: `${env.CAPCUT_WEB_URL}/${env.CAPCUT_PAGE_LOCALE}/login`,
      'store-country-code': env.CAPCUT_STORE_COUNTRY_CODE,
      'store-country-code-src': 'uid',
      'x-tt-passport-csrf-token': this.getPassportCsrfToken(loginHost) ?? '',
    };
    const body = buildSensitiveFormBody(
      {
        email: this.accountEmail,
        password: this.accountPassword,
      },
      ['email', 'password']
    );

    try {
      return await unwrapJsonResponse<LoginResponse>(
        await emailLogin({
          requester: this.fetchWithCookies.bind(this),
          host: loginHost,
          path: this.getResolvedEmailLoginPath(),
          searchParams,
          headers,
          body,
        }),
        'CapCut passport /passport/web/email/login/'
      );
    } catch (error) {
      if (!shouldFallbackToUserLogin(error)) {
        throw error;
      }

      logger.info('CapCut email/login fallback to user/login', { error });
      return unwrapJsonResponse<LoginResponse>(
        await userLogin({
          requester: this.fetchWithCookies.bind(this),
          host: loginHost,
          path: this.getResolvedUserLoginPath(),
          searchParams,
          headers,
          body,
        }),
        'CapCut passport /passport/web/user/login/'
      );
    }
  }

  /**
   * アカウント情報を取得する
   */
  private async fetchAccountInfo(): Promise<AccountInfo> {
    return unwrapJsonResponse<AccountInfo>(
      await getAccountInfo({
        requester: this.fetchWithCookies.bind(this),
        path: this.getResolvedAccountInfoPath(),
        searchParams: {
          aid: appId,
          account_sdk_source: 'web',
          sdk_version: this.getResolvedLoginSdkVersion(),
          language: env.CAPCUT_LOCALE,
          verifyFp: this.verifyFp,
        },
        headers: {
          Accept: 'application/json, text/javascript',
          'Content-Type': 'application/x-www-form-urlencoded',
          'User-Agent': env.USER_AGENT,
          appid: appId,
          did: this.deviceId,
          Referer: `${env.CAPCUT_WEB_URL}/${env.CAPCUT_PAGE_LOCALE}/login`,
          'store-country-code': env.CAPCUT_STORE_COUNTRY_CODE,
          'store-country-code-src': 'uid',
          'x-tt-passport-csrf-token':
            this.getPassportCsrfToken(env.CAPCUT_WEB_URL) ?? '',
        },
      }),
      'CapCut account info'
    );
  }

  /**
   * デフォルトのワークスペースを取得する
   */
  private async fetchPrimaryWorkspace(): Promise<WorkspaceInfo> {
    const data = await this.requestSignedEditJson<WorkspaceListResponse>({
      path: this.getResolvedWorkspacePath(),
      appVersion: this.getResolvedEditorAppVersion(),
      extraHeaders: {
        lan: env.CAPCUT_LOCALE,
        loc: env.CAPCUT_REGION,
      },
      body: {
        cursor: '0',
        count: 100,
        need_convert_workspace: true,
      },
      request: ({ headers, body }) =>
        getUserWorkspaces({
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
    const workspace =
      workspaces.find((item) => item.role === 'owner') ?? workspaces[0];

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
  private async loadSpeakers(): Promise<Speaker[]> {
    const cacheAge = Date.now() - this.speakersLoadedAt;
    const cacheTtl = this.speakersDegraded ? voiceFallbackRetryMs : voiceCacheMs;

    if (this.speakers && cacheAge < cacheTtl) {
      return this.speakers;
    }

    try {
      const speakers = this.excludeBrokenVoices(
        await this.requestSpeakerList()
      );

      if (speakers.length === 0) {
        throw new Error('CapCut voice catalog returned no usable speaker');
      }

      if (this.speakersDegraded) {
        logger.info('CapCut voice catalog recovered', {
          speakerCount: speakers.length,
        });
      }

      this.speakers = speakers;
      this.speakersDegraded = false;
      this.speakersLoadedAt = Date.now();
      return this.speakers;
    } catch (error) {
      logger.error(
        `CapCut voice catalog unavailable. Serving ${fallbackSpeakers.length} built-in fallback voices instead of the live catalog. Retrying in ${Math.round(
          voiceFallbackRetryMs / 1000
        )}s`,
        { error }
      );
      this.speakers = fallbackSpeakers;
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
  private excludeBrokenVoices(speakers: Speaker[]): Speaker[] {
    if (!env.CAPCUT_EXCLUDE_BROKEN_VOICES) {
      return speakers;
    }

    const dropped: string[] = [];
    const kept = speakers.filter((speaker) => {
      const broken = isBrokenVoice(speaker.language, speaker.platform);

      if (broken) {
        dropped.push(speaker.speaker);
        return false;
      }

      return true;
    });

    if (dropped.length > 0) {
      logger.info('Excluded known-broken CapCut voices', {
        count: dropped.length,
        combos: brokenVoiceCombos.map(
          (combo) => `${combo.language}/${combo.platform}`
        ),
      });
    }

    return kept;
  }

  /**
   * artist API 共通の search params
   */
  private buildArtistSearchParams(): Record<string, string> {
    return {
      aid: appId,
      version_name: this.getResolvedVersionName(),
      version_code: this.getResolvedVersionCode(),
      sdk_version: this.getResolvedSdkVersion(),
      effect_sdk_version: this.getResolvedEffectSdkVersion(),
      device_platform: 'web',
      region: env.CAPCUT_REGION,
      language: env.CAPCUT_LOCALE,
      device_type: 'web',
      channel: 'online',
    };
  }

  /**
   * artist API 共通のヘッダ
   * この系統は sign を要求しないので Cookie と did だけで通る
   */
  private buildArtistHeaders(): Record<string, string> {
    return {
      Accept: 'application/json, text/plain, */*',
      'Content-Type': 'application/json',
      Origin: env.CAPCUT_WEB_URL,
      Referer: `${env.CAPCUT_WEB_URL}/`,
      'User-Agent': env.USER_AGENT,
      appid: appId,
      did: this.deviceId,
      'store-country-code': env.CAPCUT_STORE_COUNTRY_CODE,
      'store-country-code-src': 'uid',
    };
  }

  /**
   * 音声カテゴリ一覧を実行時に取得する
   *
   * CapCut 側でカテゴリ ID は入れ替わるため固定値に頼らない
   * 取得に失敗したときだけ設定値へフォールバックする
   */
  private async loadVoiceCategories(): Promise<
    Array<{ id: number; key: string }>
  > {
    const cacheAge = Date.now() - this.liveVoiceCategoryIdsLoadedAt;

    if (this.liveVoiceCategoryIds && cacheAge < voiceCategoryCacheMs) {
      return this.liveVoiceCategoryIds.map((id) => ({ id, key: String(id) }));
    }

    try {
      const payload = await unwrapJsonResponse<VoicePanelInfoResponse>(
        await getVoicePanelInfo({
          requester: this.fetchWithCookies.bind(this),
          path: voicePanelInfoPath,
          searchParams: this.buildArtistSearchParams(),
          headers: this.buildArtistHeaders(),
          body: JSON.stringify({
            panel: this.getResolvedVoicePanel(),
            panel_source: this.getResolvedVoicePanelSource(),
          }),
        }),
        'CapCut voice panel info'
      );

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

      logger.info('CapCut voice categories resolved', {
        count: categories.length,
        categories: categories.map((category) => category.key),
      });

      return categories;
    } catch (error) {
      const fallbackIds = this.getFallbackVoiceCategoryIds();
      logger.warn(
        'Failed to resolve live CapCut voice categories. Falling back to configured ids',
        { error, fallbackIds }
      );

      return fallbackIds.map((id) => ({ id, key: String(id) }));
    }
  }

  /**
   * 単一カテゴリの音声を has_more に従って全ページ取得する
   */
  private async requestVoiceCategoryItems(category: {
    id: number;
    key: string;
  }): Promise<unknown[]> {
    const items: unknown[] = [];
    let offset = 0;

    for (let page = 0; page < voiceListMaxPages; page += 1) {
      const payload = await unwrapJsonResponse<VoiceListResponse>(
        await getVoiceModels({
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
        }),
        `CapCut voice catalog category ${category.key}`
      );

      const pageItems = Array.isArray(payload.effect_item_list)
        ? payload.effect_item_list
        : [];
      items.push(...pageItems);

      const nextOffset = Number(payload.next_offset);
      const hasUsableNextOffset =
        Number.isFinite(nextOffset) && nextOffset > offset;

      if (!payload.has_more || pageItems.length === 0) {
        break;
      }

      if (page === voiceListMaxPages - 1) {
        logger.warn('CapCut voice category page limit reached. Truncating', {
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
  private async requestSpeakerList(): Promise<Speaker[]> {
    // カタログはアカウントごとに中身が違う 未ログインだと CapCut は
    // 既定のカタログを返すため、取得前に必ずログイン状態にしておく
    // これが無いと別アカウントの資格情報を渡しても既定カタログが返る
    await this.ensureAuthenticated();

    const categories = await this.loadVoiceCategories();
    const voiceResponses = await Promise.allSettled(
      categories.map(async (category) => ({
        category,
        items: await this.requestVoiceCategoryItems(category),
      }))
    );

    const speakerMap = new Map<string, Speaker>();
    const failedCategories: string[] = [];

    for (const result of voiceResponses) {
      if (result.status !== 'fulfilled') {
        failedCategories.push(String(result.reason?.message ?? result.reason));
        continue;
      }

      const { category, items } = result.value;

      for (const item of items) {
        const resolvedSpeaker = parseSpeaker(item, category.key);

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
      logger.warn('Some CapCut voice categories failed', {
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
  private async createAudioResponse(
    options: SynthesizeOptions
  ): Promise<Response> {
    return this.createAudioResponseWithRetry(options, true);
  }

  /**
   * 分割したテキストを並列で音声化する
   */
  private async synthesizeChunkedBuffers(
    options: SynthesizeOptions,
    chunkedTexts: string[]
  ): Promise<AudioResult[]> {
    const chunkResults = await Promise.all(
      chunkedTexts.map(async (chunkText) => {
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
      })
    );

    return chunkResults;
  }

  /**
   * セッション切れだけ 1 回だけ再ログインして再試行する
   */
  private async createAudioResponseWithRetry(
    options: SynthesizeOptions,
    allowRetry: boolean
  ): Promise<Response> {
    try {
      const speakers = await this.loadSpeakers();
      const resolvedSpeaker = resolveSpeaker(
        options.type,
        speakers,
        options.speaker,
        options.platform
      );
      await this.ensureAuthenticated();

      try {
        return await this.createAudioViaMultiPlatform(resolvedSpeaker, options);
      } catch (error) {
        logger.info(
          'CapCut multi_platform TTS failed. Falling back to editor intelligence flow',
          { error }
        );
      }

      const session = await this.ensureAuthenticated();
      const taskId = await this.createTtsTask(
        session.workspaceId,
        resolvedSpeaker,
        options
      );
      const taskDetail = await this.waitForTtsTask(session.workspaceId, taskId);

      if (taskDetail.url) {
        return this.fetchDirectAudio(taskDetail.url);
      }

      const fallbackUrl = taskDetail.transcode_audio_info?.[0]?.url;
      if (fallbackUrl) {
        return this.fetchDirectAudio(fallbackUrl);
      }

      throw new Error('CapCut TTS task completed without an audio URL');
    } catch (error) {
      if (allowRetry && isSessionExpiredError(error)) {
        logger.info('CapCut session appears expired. Re-authenticating once', {
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
  private async createAudioViaMultiPlatform(
    resolvedSpeaker: Speaker,
    options: SynthesizeOptions
  ): Promise<Response> {
    const ttsData = await this.requestSignedEditJson<MultiPlatformTtsResponse>({
      path: this.getResolvedMultiPlatformPath(),
      appVersion: this.getResolvedEditorAppVersion(),
      tdid: this.tdid,
      // lan を送らないと engine が読み上げ言語を取り違える
      // ベトナム語のテキストをマレー語として読む事例を確認している
      extraHeaders: {
        lan: env.CAPCUT_LOCALE,
        loc: env.CAPCUT_REGION,
      },
      body: {
        texts: [options.text],
        tts_conf: {
          speaker: resolvedSpeaker.speaker,
          rate: toPlaybackRate(options.speed),
          volume: toVolumeLevel(options.volume),
          name: resolvedSpeaker.title,
          platform: resolvedSpeaker.platform ?? 'sami',
          effect_id: resolvedSpeaker.effectId,
          resource_id: resolvedSpeaker.resourceId,
          is_clone: false,
        },
        need_url: true,
      },
      request: ({ headers, body }) =>
        createMultiPlatformTts({
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
  private resolveTtsPlatformId(resolvedSpeaker: Speaker): number {
    const platformKey = resolvedSpeaker.platform?.trim().toLowerCase();

    if (!platformKey) {
      return ttsPlatform;
    }

    const platformId = ttsPlatformIds[platformKey];

    if (!platformId) {
      logger.warn('Unknown CapCut TTS platform. Falling back to default', {
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
  private async createTtsTask(
    workspaceId: string,
    resolvedSpeaker: Speaker,
    options: SynthesizeOptions
  ) {
    const data = await this.requestSignedEditJson<TtsTaskResponse>({
      path: this.getResolvedCreateTaskPath(),
      appVersion: this.getResolvedEditorAppVersion(),
      extraHeaders: {
        lan: env.CAPCUT_LOCALE,
      },
      searchParams: {
        aid: appId,
        device_platform: 'web',
        region: env.CAPCUT_REGION,
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
      request: ({ searchParams, headers, body }) =>
        createTtsTask({
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
  private async waitForTtsTask(
    workspaceId: string,
    taskId: string
  ): Promise<TtsTaskDetail> {
    for (let attempt = 0; attempt < ttsMaxPollAttempts; attempt += 1) {
      const data = await this.requestSignedEditJson<TtsQueryResponse>({
        path: this.getResolvedQueryTaskPath(),
        appVersion: this.getResolvedEditorAppVersion(),
        extraHeaders: {
          lan: env.CAPCUT_LOCALE,
        },
        searchParams: {
          aid: appId,
          device_platform: 'web',
          region: env.CAPCUT_REGION,
          web_id: this.deviceId,
        },
        body: {
          task_id: taskId,
          workspace_id: workspaceId,
          smart_tool_type: ttsSmartToolType,
        },
        request: ({ searchParams, headers, body }) =>
          queryTtsTask({
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
  private async fetchDirectAudio(url: string) {
    const response = await downloadAudio({
      requester: async (requestUrl, init) => fetch(requestUrl, init),
      url,
      headers: {
        Accept: 'application/json, text/plain, */*',
        'User-Agent': env.USER_AGENT,
      },
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(
        `CapCut audio download failed: ${response.status} ${response.statusText} ${getResponseBodySnippet(
          body
        )}`
      );
    }

    return response;
  }

  /**
   * edit-api 向け署名付き POST を送る
   * sign は最終 URL の path 末尾 7 文字と tdid を使うので、ここで組み立ててから送る
   */
  private async requestSignedEditJson<T>(options: {
    path: string;
    appVersion: string;
    body: unknown;
    searchParams?: Record<string, string>;
    extraHeaders?: Record<string, string>;
    tdid?: string;
    request: (params: {
      searchParams: Record<string, string>;
      headers: Headers;
      body: string;
    }) => Promise<Response>;
    context: string;
  }) {
    if (this.runtimeEditorBundleConfig.sourceUrls.length === 0) {
      await this.ensureEditorBundleConfig(true);
    } else if (!this.hasUsableEditorBundleConfig()) {
      await this.ensureEditorBundleConfig(true);
    }

    const searchParams = options.searchParams ?? {};
    const targetUrl = new URL(options.path, env.CAPCUT_EDIT_API_URL);

    for (const [key, value] of Object.entries(searchParams)) {
      targetUrl.searchParams.set(key, value);
    }

    const tdid = options.tdid ?? '';
    const { sign, deviceTime } = createEditApiSignature(
      targetUrl.toString(),
      this.getResolvedPlatformId(),
      options.appVersion,
      tdid,
      this.getResolvedSignRecipe()
    );

    return unwrapJsonResponse<T>(
      await options.request({
        searchParams,
        headers: new Headers({
          Accept: 'application/json, text/plain, */*',
          'Content-Type': 'application/json',
          Origin: env.CAPCUT_WEB_URL,
          Referer: `${env.CAPCUT_WEB_URL}/`,
          'User-Agent': env.USER_AGENT,
          appid: appId,
          appvr: options.appVersion,
          'device-time': deviceTime,
          did: this.deviceId,
          pf: this.getResolvedPlatformId(),
          sign,
          'sign-ver': this.getResolvedSignVersion(),
          'store-country-code': env.CAPCUT_STORE_COUNTRY_CODE,
          'store-country-code-src': 'uid',
          tdid,
          ...options.extraHeaders,
        }),
        body: JSON.stringify(options.body),
      }),
      options.context
    );
  }

  /**
   * Cookie を差し込んで fetch する共通口
   */
  private async fetchWithCookies(url: string, init: RequestInit) {
    // 復元前の空の Cookie jar で走らせない
    // /v2/speakers は認証を通らないため、ここで復元しないと空の jar のまま
    // sessionDirty が立ち、保存済みセッションを空で上書きしてしまう
    await this.ensureRestored();

    const headers = new Headers(init.headers);
    const cookieHeader = this.cookieJar.getCookieHeader(url);

    if (cookieHeader) {
      headers.set('Cookie', cookieHeader);
    }

    logger.debug('CapCut request', {
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
      responseBodySnippet = getResponseBodySnippet(await clonedResponse.text());
    } catch (error) {
      responseBodySnippet = `[unavailable: ${
        error instanceof Error ? error.message : 'unknown error'
      }]`;
    }

    logger.debug('CapCut response', {
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
  private syncDeviceIdFromCookies() {
    if (env.CAPCUT_DEVICE_ID) {
      return;
    }

    const cookieDeviceId =
      this.cookieJar.get('_tea_web_id') ??
      this.cookieJar.get('_tea_web_id', env.CAPCUT_WEB_URL) ??
      this.cookieJar.get('_tea_web_id', env.CAPCUT_LOGIN_HOST) ??
      this.cookieJar.get('web_id') ??
      this.cookieJar.get('did');

    if (cookieDeviceId) {
      this.deviceId = cookieDeviceId;
    }
  }

  /**
   * passport 系 API 向けの CSRF Cookie を取得する
   */
  private getPassportCsrfToken(url: string) {
    return (
      this.cookieJar.get('passport_csrf_token', url) ??
      this.cookieJar.get('passport_csrf_token_default', url)
    );
  }

  /**
   * Content-Disposition からファイル名を抽出する
   */
  private extractFileName(response: Response) {
    const disposition = response.headers.get('content-disposition');
    if (!disposition) {
      return undefined;
    }

    const match = disposition.match(/filename="?([^"]+)"?/i);
    return match?.[1];
  }
}

const normalizeString = (value: unknown) =>
  typeof value === 'string' ? value : null;

const normalizeStringId = (value: unknown) =>
  typeof value === 'string' ||
  typeof value === 'number' ||
  typeof value === 'bigint'
    ? String(value)
    : null;

/**
 * email/login 失敗時に user/login へフォールバックしてよいかを判定する
 * CapCut の業務エラー時は user/login へ進むと別のエラーで上書きされやすい
 */
const shouldFallbackToUserLogin = (error: unknown) =>
  error instanceof CapCutApiError &&
  (error.statusCode === 404 || error.statusCode === 405);

/**
 * 別 login host へ再試行してよいかを判定する
 * error_code が返っている時は host を変えても改善しにくいため、その場で止める
 */
const shouldTryOtherLoginHost = (error: unknown) =>
  !(error instanceof CapCutApiError && error.errorCode !== undefined);

const isSemverLike = (value: string | undefined): value is string =>
  typeof value === 'string' &&
  /^\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?$/.test(value);

/**
 * デバッグログ用に秘匿ヘッダーを伏せる
 */
const sanitizeHeadersForDebugLog = (headers: Headers) => {
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
const toLoggableBody = (body: BodyInit | null | undefined) => {
  if (typeof body === 'string') {
    return getResponseBodySnippet(body);
  }

  if (body === undefined || body === null) {
    return '';
  }

  return `[${body.constructor.name}]`;
};

let instance: CapCutService | null = null;

/** アカウント別インスタンス 資格情報が渡されたときだけ使う */
const accountInstances = new Map<string, CapCutService>();

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
export const getCapCutService = (
  credentials?: CapCutCredentials | null
): CapCutService => {
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

// 既存の capCutService.method() という呼び出しを保ったまま生成だけ遅らせる
export const capCutService = new Proxy({} as CapCutService, {
  get: (_target, property: string | symbol) => {
    const service = getCapCutService();
    const value = service[property as keyof CapCutService];

    return typeof value === 'function' ? value.bind(service) : value;
  },
}) as CapCutService;

let sessionRefreshTimer: NodeJS.Timeout | null = null;

/**
 * CapCut セッションのバックグラウンド更新を開始する
 */
export const startCapCutSessionTask = async () => {
  try {
    await capCutService.warmup();
  } catch (error) {
    logger.warn(
      'Initial CapCut session warmup failed. The service will retry in the background',
      { error }
    );
  }

  if (sessionRefreshTimer) {
    clearInterval(sessionRefreshTimer);
  }

  sessionRefreshTimer = setInterval(
    () => {
      void capCutService.ensureAuthenticated().catch((error) => {
        logger.warn('Background CapCut session validation failed', { error });
      });
    },
    env.SESSION_REFRESH_INTERVAL_MINUTES * 60 * 1000
  );

  sessionRefreshTimer.unref?.();
};

export default capCutService;
