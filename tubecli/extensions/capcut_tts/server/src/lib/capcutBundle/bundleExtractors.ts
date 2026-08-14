import type {
  CapCutEditorBundleConfig,
  CapCutLoginBundleConfig,
  CapCutSignRecipe,
} from '@/types/capcutBundle';
import {
  extractFirst,
  extractStringAssignment,
} from '@/lib/capcutBundle/bundleExtractionUtils';

const isBundleVersionLike = (value: string | undefined): value is string =>
  Boolean(value && /^\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?$/.test(value));

const mergeSignRecipe = (
  base: Partial<CapCutSignRecipe> | undefined,
  next: Partial<CapCutSignRecipe> | undefined
) => {
  if (!base) {
    return next;
  }

  if (!next) {
    return base;
  }

  return {
    ...base,
    ...next,
  };
};

const preferLongerPath = (
  current: string | undefined,
  next: string | undefined
) => {
  if (!current) {
    return next;
  }

  if (!next) {
    return current;
  }

  return next.length >= current.length ? next : current;
};

const withPassportWebPrefix = (path: string | undefined) => {
  if (!path) {
    return undefined;
  }

  if (path.startsWith('/passport/')) {
    return path;
  }

  return `/passport/web${path}`;
};

const extractPathWithBaseVariable = (text: string, key: string) => {
  const match = text.match(
    new RegExp(`${key}:([A-Za-z_$][\\w$]*)\\+"([^"]+)"`)
  );

  if (!match) {
    return undefined;
  }

  const basePath = extractStringAssignment(text, match[1]);
  return basePath ? `${basePath}${match[2]}` : match[2];
};

/**
 * login/account bundle から抽出可能な設定を抜く
 */
export const extractLoginBundleConfig = (
  bundleText: string,
  bundleUrl?: string
): CapCutLoginBundleConfig => {
  const sdkVersion =
    extractFirst(bundleText, /sdk_version:"([^"]+)"/) ??
    extractFirst(bundleText, /sdk_version:"([^"]+-tiktok)"/);
  const xorKeyMatch = bundleText.match(
    /\((\d+)\^[A-Za-z_$][\w$]*\[[A-Za-z_$][\w$]*\]\)\.toString\(16\)/
  );

  const emailLoginPath = withPassportWebPrefix(
    extractPathWithBaseVariable(bundleText, 'EMAIL_LOGIN')
  );
  const userLoginPath = withPassportWebPrefix(
    extractPathWithBaseVariable(bundleText, 'PWD_LOGIN')
  );
  const regionPath =
    withPassportWebPrefix(
      extractPathWithBaseVariable(bundleText, 'REGION') ??
        extractPathWithBaseVariable(bundleText, 'REGION_ALERT')
    ) ??
    extractFirst(bundleText, /["'](\/passport\/web\/region\/)["']/);
  const accountInfoPath = withPassportWebPrefix(
    extractPathWithBaseVariable(bundleText, 'ACCOUNT_INFO') ??
      extractFirst(bundleText, /["'](\/passport\/web\/account\/info\/)["']/)
  );
  const emailHashSalt =
    extractFirst(
      bundleText,
      /hashed_id[^A-Za-z0-9_-]+["'`]([A-Za-z0-9_-]{24,})["'`]/
    ) ??
    extractFirst(
      bundleText,
      /sha256[^A-Za-z0-9_-]+["'`]([A-Za-z0-9_-]{24,})["'`]/
    );

  return {
    ...(bundleUrl ? { accountBundleUrl: bundleUrl } : {}),
    sdkVersion,
    xorKey: xorKeyMatch ? Number(xorKeyMatch[1]) : undefined,
    emailHashSalt,
    supportsVerifyFp: bundleText.includes('verifyFp'),
    emailLoginPath,
    userLoginPath,
    regionPath,
    accountInfoPath,
  };
};

/**
 * editor bundle から抽出可能な設定を抜く
 */
export const extractEditorBundleConfig = (
  bundleText: string,
  bundleUrl?: string
): CapCutEditorBundleConfig => {
  let signRecipe: Partial<CapCutSignRecipe> | undefined;

  if (bundleText.includes('9e2c|') && bundleText.includes('11ac')) {
    const pathTailLengthMatch = bundleText.match(/slice\(-(\d+)\)/);
    const platformIdMatch =
      bundleText.match(/pf:"(\d+)"/) ??
      bundleText.match(/pf='(\d+)'/) ??
      bundleText.match(/u\.pf="(\d+)"/);
    const signVersionMatch =
      bundleText.match(/["']sign-ver["']:(\d+)/) ??
      bundleText.match(/["']sign-ver["']=(\d+)/);
    const tdidDefaultMatch =
      bundleText.match(/tdid:"([^"]*)"/) ??
      bundleText.match(/tdid='([^']*)'/);

    signRecipe = {
      prefix: '9e2c',
      suffix: '11ac',
      pathTailLength: pathTailLengthMatch ? Number(pathTailLengthMatch[1]) : 7,
      platformId: platformIdMatch?.[1],
      signVersion: signVersionMatch?.[1],
      tdidDefault: tdidDefaultMatch?.[1],
    };
  }

  let webAppVersion: string | undefined;
  const webAppVersionVariableMatch = bundleText.match(
    /appvr:([A-Za-z_$][\w$]*),tdid:""/
  );
  if (webAppVersionVariableMatch) {
    webAppVersion = extractStringAssignment(
      bundleText,
      webAppVersionVariableMatch[1]
    );
  }

  const versionTupleMatch = bundleText.match(
    /version_name:null!=\w+\?\w+:"([^"]+)",version_code:"([^"]+)",sdk_version:null!=\w+\?\w+:([A-Za-z_$][\w$]*),effect_sdk_version:null!=\w+\?\w+:\3/
  );
  const sdkVersionCandidate = versionTupleMatch
    ? extractStringAssignment(bundleText, versionTupleMatch[3])
    : undefined;
  const sdkVersion = isBundleVersionLike(sdkVersionCandidate)
    ? sdkVersionCandidate
    : undefined;
  const versionName = versionTupleMatch?.[1];
  const versionCode = versionTupleMatch?.[2];

  const editorAppVersion =
    extractFirst(
      bundleText,
      /["']device-time["'][^]*?appvr:"([^"]+\.\d+\.\d+)"/
    ) ??
    extractFirst(bundleText, /appvr=([0-9]+\.[0-9]+\.[0-9]+)/);

  const voiceCategoryIds = Array.from(
    new Set(
      Array.from(
        bundleText.matchAll(/right_category\\?":\\?"(\d{4,})/g),
        (match) => Number(match[1])
      ).filter((value) => Number.isFinite(value))
    )
  );

  return {
    sourceUrls: bundleUrl ? [bundleUrl] : [],
    editorAppVersion,
    webAppVersion,
    versionName,
    versionCode,
    sdkVersion,
    effectSdkVersion: sdkVersion,
    signRecipe,
    multiPlatformPath: extractFirst(
      bundleText,
      /["'](\/storyboard\/v1\/tts\/multi_platform)["']/
    ),
    createTaskPath:
      extractFirst(
        bundleText,
        /["'](\/lv\/v2\/intelligence\/create)["']/
      ) ?? extractFirst(bundleText, /CREATE_VC_TASK:"([^"]+)"/),
    queryTaskPath:
      extractFirst(
        bundleText,
        /["'](\/lv\/v2\/intelligence\/query)["']/
      ) ?? extractFirst(bundleText, /QUERY_VC_TASK:"([^"]+)"/),
    workspacePath:
      extractFirst(
        bundleText,
        /["'](\/cc\/v1\/workspace\/get_user_workspaces)["']/
      ) ?? undefined,
    voiceListPath:
      extractFirst(
        bundleText,
        /GET_HEYCAN_RESOURCES_BY_CATEGORY_ID:\{[^}]*url:"([^"]+)"/
      ) ?? extractFirst(bundleText, /GET_CATEGORY_RESOURCE:"([^"]+)"/),
    homepageEffectListPath:
      extractFirst(bundleText, /GET_HOMEPAGE_EFFECT_LIST:"([^"]+)"/) ??
      extractFirst(
        bundleText,
        /["'](\/artist\/v1\/homepage\/get_effect_list)["']/
      ),
    voicePanel:
      bundleText.includes('o.Tone="tone"') || bundleText.includes('panel:"tone"')
        ? 'tone'
        : undefined,
    voicePanelSource: bundleText.includes('heycan') ? 'heycan' : undefined,
    voiceCategoryIds,
  };
};

/**
 * editor 設定を後勝ちでマージする
 */
export const mergeEditorBundleConfig = (
  current: CapCutEditorBundleConfig,
  next: CapCutEditorBundleConfig
): CapCutEditorBundleConfig => ({
  sourceUrls: Array.from(new Set([...current.sourceUrls, ...next.sourceUrls])),
  editorAppVersion: next.editorAppVersion ?? current.editorAppVersion,
  webAppVersion: next.webAppVersion ?? current.webAppVersion,
  versionName: next.versionName ?? current.versionName,
  versionCode: next.versionCode ?? current.versionCode,
  sdkVersion: next.sdkVersion ?? current.sdkVersion,
  effectSdkVersion: next.effectSdkVersion ?? current.effectSdkVersion,
  signRecipe: mergeSignRecipe(current.signRecipe, next.signRecipe),
  multiPlatformPath: preferLongerPath(
    current.multiPlatformPath,
    next.multiPlatformPath
  ),
  createTaskPath: preferLongerPath(current.createTaskPath, next.createTaskPath),
  queryTaskPath: preferLongerPath(current.queryTaskPath, next.queryTaskPath),
  workspacePath: preferLongerPath(current.workspacePath, next.workspacePath),
  voiceListPath: preferLongerPath(current.voiceListPath, next.voiceListPath),
  homepageEffectListPath: preferLongerPath(
    current.homepageEffectListPath,
    next.homepageEffectListPath
  ),
  voicePanel: next.voicePanel ?? current.voicePanel,
  voicePanelSource: next.voicePanelSource ?? current.voicePanelSource,
  voiceCategoryIds:
    next.voiceCategoryIds && next.voiceCategoryIds.length > 0
      ? Array.from(
          new Set([...(current.voiceCategoryIds ?? []), ...next.voiceCategoryIds])
        )
      : current.voiceCategoryIds,
});

/**
 * login 設定を後勝ちでマージする
 */
export const mergeLoginBundleConfig = (
  current: CapCutLoginBundleConfig,
  next: CapCutLoginBundleConfig
): CapCutLoginBundleConfig => ({
  accountBundleUrl: next.accountBundleUrl ?? current.accountBundleUrl,
  sdkVersion: next.sdkVersion ?? current.sdkVersion,
  xorKey: next.xorKey ?? current.xorKey,
  emailHashSalt: next.emailHashSalt ?? current.emailHashSalt,
  supportsVerifyFp: next.supportsVerifyFp ?? current.supportsVerifyFp,
  emailLoginPath: next.emailLoginPath ?? current.emailLoginPath,
  userLoginPath: next.userLoginPath ?? current.userLoginPath,
  regionPath: next.regionPath ?? current.regionPath,
  accountInfoPath: next.accountInfoPath ?? current.accountInfoPath,
});
