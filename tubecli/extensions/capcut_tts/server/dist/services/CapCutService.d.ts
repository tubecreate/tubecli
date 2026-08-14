import type { TtsWebSocketResult } from '../lib/capcut/ttsWebSocket';
import type { AudioResult, AudioStreamResult, CapCutSessionState, SpeakerFilter, SpeakerInfo, SynthesizeOptions } from '../types/capcut';
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
declare class CapCutService {
    private readonly cookieJar;
    private readonly credentials;
    constructor(credentials?: CapCutCredentials | null);
    private get accountEmail();
    private get accountPassword();
    /**
     * セッション JSON の保存キー
     * Node ではファイルパス、Workers では R2 のオブジェクトキーになる
     *
     * アカウントごとにセッションが混ざらないよう、既定以外の資格情報では
     * メールアドレスのハッシュを鍵へ混ぜる
     */
    private get sessionStoreKey();
    private restorePromise;
    /**
     * アカウント固有の派生シード
     *
     * env で固定した device fingerprint を全アカウントで共有すると、
     * 別アカウントのログイン失敗が本体アカウントまで巻き込んで
     * CapCut 側のログイン試行制限に引っかかる 実際に発生させたので分離する
     */
    private get accountSeed();
    private deviceIdValue;
    private get deviceId();
    private set deviceId(value);
    private tdidValue;
    private get tdid();
    private set tdid(value);
    private session;
    private sessionPromise;
    private speakers;
    private speakersLoadedAt;
    /** 生きた音声カタログを引けず fallback で凌いでいる状態か */
    private speakersDegraded;
    private liveVoiceCategoryIds;
    private liveVoiceCategoryIdsLoadedAt;
    private verifyFpValue;
    private get verifyFp();
    private set verifyFp(value);
    private runtimeLoginBundleConfig;
    private runtimeEditorBundleConfig;
    /**
     * 永続化済みセッションの復元を一度だけ走らせる
     *
     * コンストラクタで起動すると Workers では bindings 到着前に走ってしまうため
     * 最初に必要になった時点まで遅らせる
     */
    private ensureRestored;
    /**
     * 音声をバッファとして取得する
     */
    synthesizeBuffer(options: SynthesizeOptions): Promise<AudioResult>;
    /**
     * 音声をストリームとして取得する
     */
    synthesizeStream(options: SynthesizeOptions): Promise<AudioStreamResult>;
    /**
     * 単語タイムスタンプ付きで合成する
     *
     * REST 経路は caption を返さないため、SAMI の WebSocket 経路を使う
     * こちらは合成エンジンが出した alignment をそのまま受け取れる
     */
    synthesizeWithMarks(options: SynthesizeOptions): Promise<TtsWebSocketResult>;
    /**
     * 利用可能な話者一覧を返す
     *
     * @param filter - 言語 国 カテゴリでの絞り込み条件
     */
    listSpeakers(filter?: SpeakerFilter): Promise<SpeakerInfo[]>;
    /**
     * 話者が持つ言語コード一覧を返す
     */
    listSpeakerLanguages(): Promise<Array<{
        language: string;
        countries: string[];
        speakerCount: number;
    }>>;
    /**
     * 話者プレビュー音声をキャッシュ付きで返す
     */
    getSpeakerPreviewAudio(speakerId: string): Promise<AudioResult>;
    /**
     * 話者プレビュー音声を必要に応じて生成または再生成する
     *
     * 保存先は BlobStorage 経由なので、Node ではローカルディレクトリ、
     * Workers では R2 バケットがそのまま置き場になる
     */
    private ensureSpeakerPreviewAudio;
    /**
     * 起動時の事前ウォームアップ
     */
    warmup(): Promise<void>;
    /**
     * セッションを確保する
     * 既存セッションが生きていれば再利用し、失効時だけ再ログインする
     */
    ensureAuthenticated(force?: boolean): Promise<CapCutSessionState>;
    /**
     * login bundle 由来の設定を更新する
     */
    private refreshLoginBundleConfig;
    /**
     * editor bundle 由来の設定を更新する
     */
    private refreshEditorBundleConfig;
    /**
     * workspace / TTS 実行に足りる editor bundle 設定かを判定する
     */
    private hasUsableEditorBundleConfig;
    /**
     * 必要なら live bundle から editor 設定を再取得する
     */
    private ensureEditorBundleConfig;
    /**
     * bundle 由来 login sdk version を返す
     */
    private getResolvedLoginSdkVersion;
    /**
     * bundle 由来 login email path を返す
     */
    private getResolvedEmailLoginPath;
    /**
     * bundle 由来 login user path を返す
     */
    private getResolvedUserLoginPath;
    /**
     * bundle 由来 region path を返す
     */
    private getResolvedRegionPath;
    /**
     * bundle 由来 account info path を返す
     */
    private getResolvedAccountInfoPath;
    /**
     * bundle 由来 editor app version を返す
     */
    private getResolvedEditorAppVersion;
    /**
     * bundle 由来 web app version を返す
     */
    private getResolvedWebAppVersion;
    /**
     * bundle 由来 version_name を返す
     */
    private getResolvedVersionName;
    /**
     * bundle 由来 version_code を返す
     */
    private getResolvedVersionCode;
    /**
     * bundle 由来 sdk_version を返す
     */
    private getResolvedSdkVersion;
    /**
     * bundle 由来 effect_sdk_version を返す
     */
    private getResolvedEffectSdkVersion;
    /**
     * bundle 由来 voice panel を返す
     */
    private getResolvedVoicePanel;
    /**
     * bundle 由来 voice panel source を返す
     */
    private getResolvedVoicePanelSource;
    /**
     * 設定由来の voice category ids を返す
     * CapCut 側で ID が入れ替わるため、実行時取得できなかったときの保険として使う
     */
    private getFallbackVoiceCategoryIds;
    /**
     * bundle 由来 voice list path を返す
     */
    private getResolvedVoiceListPath;
    /**
     * bundle 由来 workspace path を返す
     */
    private getResolvedWorkspacePath;
    /**
     * bundle 由来 multi_platform path を返す
     */
    private getResolvedMultiPlatformPath;
    /**
     * bundle 由来 create task path を返す
     */
    private getResolvedCreateTaskPath;
    /**
     * bundle 由来 query task path を返す
     */
    private getResolvedQueryTaskPath;
    /**
     * bundle 由来 sign recipe を返す
     */
    private getResolvedSignRecipe;
    /**
     * bundle 由来 platform id を返す
     */
    private getResolvedPlatformId;
    /**
     * bundle 由来 sign version を返す
     */
    private getResolvedSignVersion;
    /**
     * 永続化済みセッションを復元する
     */
    private restorePersistedSession;
    /**
     * セッションをディスクへ保存する
     */
    /** Cookie などが変わったが、まだ保存していない状態か */
    private sessionDirty;
    /** D1 の楽観ロック用 読み出したときの version */
    private sessionVersion;
    /**
     * 変更があれば保存する
     *
     * Workers ではレスポンス返却後に未完了の promise が打ち切られるため
     * 呼び出し側で ctx.waitUntil に載せて使う
     */
    flushSession(): Promise<void>;
    private persistSession;
    /**
     * セッション JSON を読む D1 があればそちら優先
     */
    private readSessionPayload;
    /**
     * セッション JSON を書く
     *
     * D1 では version が一致したときだけ書く 負けた側は書かない
     * 先に他 isolate が更新していれば、そちらの方が新しいので上書きしない
     */
    private writeSessionPayload;
    /**
     * passport 系 API 用の CSRF Cookie を事前に投入する
     */
    private seedPassportCookies;
    /**
     * login host を切り替える前に Cookie 状態を初期化する
     */
    private resetLoginAttemptState;
    /**
     * ログインを全 isolate で 1 回だけにする
     *
     * sessionPromise の重複排除は isolate 内でしか効かない
     * Workers は isolate が多数動くため、実測で同時 6 リクエストが
     * 5 回のログインを起こし、CapCut から複数デバイス扱いされていた
     *
     * ロックを取れなかった側はログインせず、勝った側が書いたセッションを待つ
     */
    private loginWithGlobalLock;
    /**
     * CapCut へログインしてワークスペースまで確定させる
     */
    private login;
    /**
     * login ページ取得で Cookie 群を初期化する
     */
    private primeCookies;
    /**
     * login 前に check_email_registered を叩いて SDK の前提状態を近づける
     */
    private primeLoginState;
    /**
     * メールアドレスに応じた login host を問い合わせる
     */
    private resolveLoginRegion;
    /**
     * email/password ログインを実行する
     * まず email/login を試し、endpoint 不整合らしい場合だけ user/login へフォールバックする
     */
    private loginWithHost;
    /**
     * アカウント情報を取得する
     */
    private fetchAccountInfo;
    /**
     * デフォルトのワークスペースを取得する
     */
    private fetchPrimaryWorkspace;
    /**
     * 音声一覧をロードする
     *
     * 生カタログを引けなかったときは fallback で応答を保つが
     * 縮退していることを error で明示し、次の再取得も早める
     */
    private loadSpeakers;
    /**
     * 実測で読み上げが破綻している話者をカタログから外す
     *
     * 例 ベトナム語 x 11labs はベトナム語テキストを別言語として読むため
     * 一覧にも合成にも出さない CAPCUT_EXCLUDE_BROKEN_VOICES=false で無効化できる
     */
    private excludeBrokenVoices;
    /**
     * artist API 共通の search params
     */
    private buildArtistSearchParams;
    /**
     * artist API 共通のヘッダ
     * この系統は sign を要求しないので Cookie と did だけで通る
     */
    private buildArtistHeaders;
    /**
     * 音声カテゴリ一覧を実行時に取得する
     *
     * CapCut 側でカテゴリ ID は入れ替わるため固定値に頼らない
     * 取得に失敗したときだけ設定値へフォールバックする
     */
    private loadVoiceCategories;
    /**
     * 単一カテゴリの音声を has_more に従って全ページ取得する
     */
    private requestVoiceCategoryItems;
    /**
     * CapCut の音声モデル一覧 API を叩く
     * カテゴリは実行時解決し、各カテゴリはページングして取り切る
     */
    private requestSpeakerList;
    /**
     * 実際の音声レスポンスを組み立てる
     * まず multi_platform を使い、失敗時だけ editor の create/query に退避する
     */
    private createAudioResponse;
    /**
     * 分割したテキストを並列で音声化する
     */
    private synthesizeChunkedBuffers;
    /**
     * セッション切れだけ 1 回だけ再ログインして再試行する
     */
    private createAudioResponseWithRetry;
    /**
     * 直接音声 URL を返す multi_platform フロー
     */
    private createAudioViaMultiPlatform;
    /**
     * 話者が属する TTS エンジンの platform 番号を返す
     *
     * 11labs の話者へ既定値を送ると別エンジンで読み上げられ
     * ベトナム語などが正しく発音されないため必ず話者側の指定に従う
     */
    private resolveTtsPlatformId;
    /**
     * editor intelligence タスクを作成する
     */
    private createTtsTask;
    /**
     * editor intelligence タスクの完了を待つ
     */
    private waitForTtsTask;
    /**
     * 直接音声 URL を取得する
     */
    private fetchDirectAudio;
    /**
     * edit-api 向け署名付き POST を送る
     * sign は最終 URL の path 末尾 7 文字と tdid を使うので、ここで組み立ててから送る
     */
    private requestSignedEditJson;
    /**
     * Cookie を差し込んで fetch する共通口
     */
    private fetchWithCookies;
    /**
     * Cookie から did 候補を同期する
     * _tea_web_id が取れたときはそれを最優先する
     */
    private syncDeviceIdFromCookies;
    /**
     * passport 系 API 向けの CSRF Cookie を取得する
     */
    private getPassportCsrfToken;
    /**
     * Content-Disposition からファイル名を抽出する
     */
    private extractFileName;
}
/**
 * サービス本体を返す 初回参照時に生成する
 *
 * モジュール評価時に new すると env へ触れてしまい、
 * bindings がまだ無い Workers では起動に失敗するため遅延させる
 *
 * @param credentials - 指定するとそのアカウント専用のインスタンスを返す
 */
export declare const getCapCutService: (credentials?: CapCutCredentials | null) => CapCutService;
export declare const capCutService: CapCutService;
/**
 * CapCut セッションのバックグラウンド更新を開始する
 */
export declare const startCapCutSessionTask: () => Promise<void>;
export default capCutService;
