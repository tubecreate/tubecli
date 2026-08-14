/**
 * CapCut 固定値群
 * HAR と実通信から確認できた値だけを集約している
 */
export const capCutConstants = {
  appId: '348188',
  loginSdkVersion: '2.1.10-tiktok',
  webAppVersion: '5.8.0',
  editorAppVersion: '8.4.0',
  platformId: '7',
  signVersion: '1',
  voicePanel: 'tone',
  voicePanelSource: 'heycan',
  voicePanelInfoPath: '/artist/v1/panel/get_panel_info',
  ttsSmartToolType: 39,
  ttsScene: 3,
  /** 話者側に platform 指定がないときの既定値 CapCut bundle の TTAM */
  ttsPlatform: 1,
  /**
   * tonetype.platform 文字列から CapCut の platform 番号へ
   * bundle の enum TTAM=1 SAMI=2 ELEVENLABS=3 VIMO=6 に対応する
   */
  ttsPlatformIds: {
    ttam: 1,
    sami: 2,
    '11labs': 3,
    source_11labs: 3,
    vimo: 6,
  } as Record<string, number>,
  /** 単語タイムスタンプ付き合成に使う SAMI 経路 */
  ttsTokenPath: '/lv/v1/common/tts/token',
  ttsWebSocketUrl: 'wss://sami-sg1.byteintlapi.com/internal/api/v1/ws',
  ttsSampleRate: 24000,
  voiceCacheMs: 10 * 60 * 1000,
  voiceCategoryCacheMs: 30 * 60 * 1000,
  voiceFallbackRetryMs: 60 * 1000,
  voiceListPageSize: 200,
  voiceListMaxPages: 20,
  sessionValidateMs: 10 * 60 * 1000,
  /** セッションを使い回す上限 これを過ぎたら作り直す */
  sessionLifetimeMs: 12 * 60 * 60 * 1000,
  /** ログイン権の保持時間 ログイン 1 回分より少し長く */
  loginLockMs: 90 * 1000,
  /** 他 isolate のログインを待つ回数と間隔 */
  loginWaitAttempts: 20,
  loginWaitIntervalMs: 1000,
  /** ログイン失敗後、全 isolate が再試行を控える時間 */
  loginFailureBackoffMs: 5 * 60 * 1000,
  /**
   * 試行回数の上限に当たったときの待ち時間
   *
   * CapCut 側のロックは数時間単位で解けるため、5 分で再挑戦すると
   * 解除前に試行を使い切り、いつまでも開かなくなる
   */
  loginAttemptLimitBackoffMs: 60 * 60 * 1000,
  ttsPollIntervalMs: 700,
  ttsMaxPollAttempts: 30,
};
