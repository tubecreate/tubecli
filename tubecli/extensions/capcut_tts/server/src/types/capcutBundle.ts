/**
 * CapCut の sign 生成式を表す
 */
export interface CapCutSignRecipe {
  prefix: string;
  suffix: string;
  pathTailLength: number;
  platformId?: string;
  signVersion?: string;
  tdidDefault?: string;
}

/**
 * 抽出処理で扱う bundle ソース
 */
export interface CapCutBundleSource {
  url: string;
  text: string;
  sourceType: 'har' | 'live';
}

/**
 * bundle 抽出で見つかった version 群
 */
export interface CapCutBundleVersionInfo {
  accountApiVersion?: string;
  loginSdkVersion?: string;
  webAppVersion?: string;
  editorAppVersion?: string;
  versionName?: string;
  versionCode?: string;
  sdkVersion?: string;
  effectSdkVersion?: string;
}

/**
 * bundle 抽出で見つかった endpoint 群
 */
export interface CapCutBundleEndpointInfo {
  loginEmailPath?: string;
  loginUserPath?: string;
  regionPath?: string;
  accountInfoPath?: string;
  workspacePath?: string;
  voiceListPath?: string;
  homepageEffectListPath?: string;
  multiPlatformTtsPath?: string;
  createTtsTaskPath?: string;
  queryTtsTaskPath?: string;
}

/**
 * bundle 抽出で見つかった署名関連設定
 */
export interface CapCutBundleSignInfo {
  prefix?: string;
  suffix?: string;
  pathSliceLength?: number;
  platformId?: string;
  signVersion?: string;
  appVersionCandidates: string[];
}

/**
 * login bundle から得られる設定
 */
export interface CapCutLoginBundleConfig {
  accountBundleUrl?: string;
  sdkVersion?: string;
  xorKey?: number;
  emailHashSalt?: string;
  supportsVerifyFp?: boolean;
  emailLoginPath?: string;
  userLoginPath?: string;
  regionPath?: string;
  accountInfoPath?: string;
}

/**
 * editor bundle から得られる設定
 */
export interface CapCutEditorBundleConfig {
  sourceUrls: string[];
  editorAppVersion?: string;
  webAppVersion?: string;
  versionName?: string;
  versionCode?: string;
  sdkVersion?: string;
  effectSdkVersion?: string;
  signRecipe?: Partial<CapCutSignRecipe>;
  multiPlatformPath?: string;
  createTaskPath?: string;
  queryTaskPath?: string;
  workspacePath?: string;
  voiceListPath?: string;
  homepageEffectListPath?: string;
  voicePanel?: string;
  voicePanelSource?: string;
  voiceCategoryIds?: number[];
}

/**
 * 抽出済み bundle 設定の全体像
 */
export interface CapCutBundleConfig {
  discoveredAt: number;
  login: CapCutLoginBundleConfig;
  editor: CapCutEditorBundleConfig;
}

/**
 * bundle 抽出結果
 */
export interface CapCutBundleExtractionResult {
  generatedAt: string;
  sources: string[];
  versions: CapCutBundleVersionInfo;
  sign: CapCutBundleSignInfo;
  endpoints: CapCutBundleEndpointInfo;
  auth: {
    passwordEncoding?: 'xor5hex';
    hasMixMode?: boolean;
    hasFixedMixMode?: boolean;
    csrfCookieNames: string[];
  };
  voice: {
    categoryIds: number[];
    categoryIdsFromApiResponses: number[];
  };
  notes: string[];
}
