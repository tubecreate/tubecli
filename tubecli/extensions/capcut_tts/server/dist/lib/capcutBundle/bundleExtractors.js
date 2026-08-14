"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.mergeLoginBundleConfig = exports.mergeEditorBundleConfig = exports.extractEditorBundleConfig = exports.extractLoginBundleConfig = void 0;
const bundleExtractionUtils_1 = require("../../lib/capcutBundle/bundleExtractionUtils");
const isBundleVersionLike = (value) => Boolean(value && /^\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?$/.test(value));
const mergeSignRecipe = (base, next) => {
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
const preferLongerPath = (current, next) => {
    if (!current) {
        return next;
    }
    if (!next) {
        return current;
    }
    return next.length >= current.length ? next : current;
};
const withPassportWebPrefix = (path) => {
    if (!path) {
        return undefined;
    }
    if (path.startsWith('/passport/')) {
        return path;
    }
    return `/passport/web${path}`;
};
const extractPathWithBaseVariable = (text, key) => {
    const match = text.match(new RegExp(`${key}:([A-Za-z_$][\\w$]*)\\+"([^"]+)"`));
    if (!match) {
        return undefined;
    }
    const basePath = (0, bundleExtractionUtils_1.extractStringAssignment)(text, match[1]);
    return basePath ? `${basePath}${match[2]}` : match[2];
};
/**
 * login/account bundle から抽出可能な設定を抜く
 */
const extractLoginBundleConfig = (bundleText, bundleUrl) => {
    const sdkVersion = (0, bundleExtractionUtils_1.extractFirst)(bundleText, /sdk_version:"([^"]+)"/) ??
        (0, bundleExtractionUtils_1.extractFirst)(bundleText, /sdk_version:"([^"]+-tiktok)"/);
    const xorKeyMatch = bundleText.match(/\((\d+)\^[A-Za-z_$][\w$]*\[[A-Za-z_$][\w$]*\]\)\.toString\(16\)/);
    const emailLoginPath = withPassportWebPrefix(extractPathWithBaseVariable(bundleText, 'EMAIL_LOGIN'));
    const userLoginPath = withPassportWebPrefix(extractPathWithBaseVariable(bundleText, 'PWD_LOGIN'));
    const regionPath = withPassportWebPrefix(extractPathWithBaseVariable(bundleText, 'REGION') ??
        extractPathWithBaseVariable(bundleText, 'REGION_ALERT')) ??
        (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/passport\/web\/region\/)["']/);
    const accountInfoPath = withPassportWebPrefix(extractPathWithBaseVariable(bundleText, 'ACCOUNT_INFO') ??
        (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/passport\/web\/account\/info\/)["']/));
    const emailHashSalt = (0, bundleExtractionUtils_1.extractFirst)(bundleText, /hashed_id[^A-Za-z0-9_-]+["'`]([A-Za-z0-9_-]{24,})["'`]/) ??
        (0, bundleExtractionUtils_1.extractFirst)(bundleText, /sha256[^A-Za-z0-9_-]+["'`]([A-Za-z0-9_-]{24,})["'`]/);
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
exports.extractLoginBundleConfig = extractLoginBundleConfig;
/**
 * editor bundle から抽出可能な設定を抜く
 */
const extractEditorBundleConfig = (bundleText, bundleUrl) => {
    let signRecipe;
    if (bundleText.includes('9e2c|') && bundleText.includes('11ac')) {
        const pathTailLengthMatch = bundleText.match(/slice\(-(\d+)\)/);
        const platformIdMatch = bundleText.match(/pf:"(\d+)"/) ??
            bundleText.match(/pf='(\d+)'/) ??
            bundleText.match(/u\.pf="(\d+)"/);
        const signVersionMatch = bundleText.match(/["']sign-ver["']:(\d+)/) ??
            bundleText.match(/["']sign-ver["']=(\d+)/);
        const tdidDefaultMatch = bundleText.match(/tdid:"([^"]*)"/) ??
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
    let webAppVersion;
    const webAppVersionVariableMatch = bundleText.match(/appvr:([A-Za-z_$][\w$]*),tdid:""/);
    if (webAppVersionVariableMatch) {
        webAppVersion = (0, bundleExtractionUtils_1.extractStringAssignment)(bundleText, webAppVersionVariableMatch[1]);
    }
    const versionTupleMatch = bundleText.match(/version_name:null!=\w+\?\w+:"([^"]+)",version_code:"([^"]+)",sdk_version:null!=\w+\?\w+:([A-Za-z_$][\w$]*),effect_sdk_version:null!=\w+\?\w+:\3/);
    const sdkVersionCandidate = versionTupleMatch
        ? (0, bundleExtractionUtils_1.extractStringAssignment)(bundleText, versionTupleMatch[3])
        : undefined;
    const sdkVersion = isBundleVersionLike(sdkVersionCandidate)
        ? sdkVersionCandidate
        : undefined;
    const versionName = versionTupleMatch?.[1];
    const versionCode = versionTupleMatch?.[2];
    const editorAppVersion = (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["']device-time["'][^]*?appvr:"([^"]+\.\d+\.\d+)"/) ??
        (0, bundleExtractionUtils_1.extractFirst)(bundleText, /appvr=([0-9]+\.[0-9]+\.[0-9]+)/);
    const voiceCategoryIds = Array.from(new Set(Array.from(bundleText.matchAll(/right_category\\?":\\?"(\d{4,})/g), (match) => Number(match[1])).filter((value) => Number.isFinite(value))));
    return {
        sourceUrls: bundleUrl ? [bundleUrl] : [],
        editorAppVersion,
        webAppVersion,
        versionName,
        versionCode,
        sdkVersion,
        effectSdkVersion: sdkVersion,
        signRecipe,
        multiPlatformPath: (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/storyboard\/v1\/tts\/multi_platform)["']/),
        createTaskPath: (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/lv\/v2\/intelligence\/create)["']/) ?? (0, bundleExtractionUtils_1.extractFirst)(bundleText, /CREATE_VC_TASK:"([^"]+)"/),
        queryTaskPath: (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/lv\/v2\/intelligence\/query)["']/) ?? (0, bundleExtractionUtils_1.extractFirst)(bundleText, /QUERY_VC_TASK:"([^"]+)"/),
        workspacePath: (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/cc\/v1\/workspace\/get_user_workspaces)["']/) ?? undefined,
        voiceListPath: (0, bundleExtractionUtils_1.extractFirst)(bundleText, /GET_HEYCAN_RESOURCES_BY_CATEGORY_ID:\{[^}]*url:"([^"]+)"/) ?? (0, bundleExtractionUtils_1.extractFirst)(bundleText, /GET_CATEGORY_RESOURCE:"([^"]+)"/),
        homepageEffectListPath: (0, bundleExtractionUtils_1.extractFirst)(bundleText, /GET_HOMEPAGE_EFFECT_LIST:"([^"]+)"/) ??
            (0, bundleExtractionUtils_1.extractFirst)(bundleText, /["'](\/artist\/v1\/homepage\/get_effect_list)["']/),
        voicePanel: bundleText.includes('o.Tone="tone"') || bundleText.includes('panel:"tone"')
            ? 'tone'
            : undefined,
        voicePanelSource: bundleText.includes('heycan') ? 'heycan' : undefined,
        voiceCategoryIds,
    };
};
exports.extractEditorBundleConfig = extractEditorBundleConfig;
/**
 * editor 設定を後勝ちでマージする
 */
const mergeEditorBundleConfig = (current, next) => ({
    sourceUrls: Array.from(new Set([...current.sourceUrls, ...next.sourceUrls])),
    editorAppVersion: next.editorAppVersion ?? current.editorAppVersion,
    webAppVersion: next.webAppVersion ?? current.webAppVersion,
    versionName: next.versionName ?? current.versionName,
    versionCode: next.versionCode ?? current.versionCode,
    sdkVersion: next.sdkVersion ?? current.sdkVersion,
    effectSdkVersion: next.effectSdkVersion ?? current.effectSdkVersion,
    signRecipe: mergeSignRecipe(current.signRecipe, next.signRecipe),
    multiPlatformPath: preferLongerPath(current.multiPlatformPath, next.multiPlatformPath),
    createTaskPath: preferLongerPath(current.createTaskPath, next.createTaskPath),
    queryTaskPath: preferLongerPath(current.queryTaskPath, next.queryTaskPath),
    workspacePath: preferLongerPath(current.workspacePath, next.workspacePath),
    voiceListPath: preferLongerPath(current.voiceListPath, next.voiceListPath),
    homepageEffectListPath: preferLongerPath(current.homepageEffectListPath, next.homepageEffectListPath),
    voicePanel: next.voicePanel ?? current.voicePanel,
    voicePanelSource: next.voicePanelSource ?? current.voicePanelSource,
    voiceCategoryIds: next.voiceCategoryIds && next.voiceCategoryIds.length > 0
        ? Array.from(new Set([...(current.voiceCategoryIds ?? []), ...next.voiceCategoryIds]))
        : current.voiceCategoryIds,
});
exports.mergeEditorBundleConfig = mergeEditorBundleConfig;
/**
 * login 設定を後勝ちでマージする
 */
const mergeLoginBundleConfig = (current, next) => ({
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
exports.mergeLoginBundleConfig = mergeLoginBundleConfig;
//# sourceMappingURL=bundleExtractors.js.map