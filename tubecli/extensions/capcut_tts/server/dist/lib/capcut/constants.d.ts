/**
 * CapCut 固定値群
 * HAR と実通信から確認できた値だけを集約している
 */
export declare const capCutConstants: {
    appId: string;
    loginSdkVersion: string;
    webAppVersion: string;
    editorAppVersion: string;
    platformId: string;
    signVersion: string;
    voicePanel: string;
    voicePanelSource: string;
    voicePanelInfoPath: string;
    ttsSmartToolType: number;
    ttsScene: number;
    /** 話者側に platform 指定がないときの既定値 CapCut bundle の TTAM */
    ttsPlatform: number;
    /**
     * tonetype.platform 文字列から CapCut の platform 番号へ
     * bundle の enum TTAM=1 SAMI=2 ELEVENLABS=3 VIMO=6 に対応する
     */
    ttsPlatformIds: Record<string, number>;
    /** 単語タイムスタンプ付き合成に使う SAMI 経路 */
    ttsTokenPath: string;
    ttsWebSocketUrl: string;
    ttsSampleRate: number;
    voiceCacheMs: number;
    voiceCategoryCacheMs: number;
    voiceFallbackRetryMs: number;
    voiceListPageSize: number;
    voiceListMaxPages: number;
    sessionValidateMs: number;
    /** セッションを使い回す上限 これを過ぎたら作り直す */
    sessionLifetimeMs: number;
    /** ログイン権の保持時間 ログイン 1 回分より少し長く */
    loginLockMs: number;
    /** 他 isolate のログインを待つ回数と間隔 */
    loginWaitAttempts: number;
    loginWaitIntervalMs: number;
    /** ログイン失敗後、全 isolate が再試行を控える時間 */
    loginFailureBackoffMs: number;
    /**
     * 試行回数の上限に当たったときの待ち時間
     *
     * CapCut 側のロックは数時間単位で解けるため、5 分で再挑戦すると
     * 解除前に試行を使い切り、いつまでも開かなくなる
     */
    loginAttemptLimitBackoffMs: number;
    ttsPollIntervalMs: number;
    ttsMaxPollAttempts: number;
};
