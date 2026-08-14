"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.extractCapCutBundleConfigFromHarFile = void 0;
const promises_1 = __importDefault(require("node:fs/promises"));
const bundleExtractors_1 = require("../../lib/capcutBundle/bundleExtractors");
const mergeCategoryIds = (current = [], next = []) => Array.from(new Set([...current, ...next])).sort((left, right) => left - right);
/**
 * HAR ファイル内の JS bundle を走査して設定を抽出する
 */
const extractCapCutBundleConfigFromHarFile = async (harPath) => {
    const raw = await promises_1.default.readFile(harPath, 'utf8');
    const har = JSON.parse(raw);
    const entries = har.log?.entries ?? [];
    let login = {};
    let editor = { sourceUrls: [] };
    for (const entry of entries) {
        const url = entry.request?.url ?? '';
        const mimeType = entry.response?.content?.mimeType ?? '';
        const text = entry.response?.content?.text ?? '';
        const requestHeaders = Object.fromEntries((entry.request?.headers ?? [])
            .filter((header) => typeof header.name === 'string' && typeof header.value === 'string')
            .map((header) => [header.name.toLowerCase(), header.value]));
        const requestUrl = url ? new URL(url) : null;
        if (/artist\/v1\/effect\/get_resources_by_category_id/.test(url) &&
            text.includes('category_ids')) {
            try {
                const parsed = JSON.parse(text);
                const categoryIds = (parsed.data?.effect_item_list ?? []).flatMap((item) => item.category_ids ?? []);
                editor.voiceCategoryIds = mergeCategoryIds(editor.voiceCategoryIds, categoryIds);
            }
            catch {
                // ignore invalid API response payload
            }
        }
        if (/artist\/v1\/effect\/get_resources_by_category_id/.test(url)) {
            try {
                const bodyText = entry.request?.postData?.text;
                if (bodyText) {
                    const body = JSON.parse(bodyText);
                    if (typeof body.category_id === 'number') {
                        editor.voiceCategoryIds = mergeCategoryIds(editor.voiceCategoryIds, [body.category_id]);
                    }
                }
            }
            catch {
                // ignore invalid request body
            }
        }
        if (/cc\/v1\/workspace\/get_user_workspaces/.test(url) &&
            requestHeaders.appvr) {
            editor.webAppVersion = requestHeaders.appvr;
        }
        if (/storyboard\/v1\/tts\/multi_platform|lv\/v2\/intelligence\/create|lv\/v2\/intelligence\/query/.test(url) &&
            requestHeaders.appvr) {
            editor.editorAppVersion = requestHeaders.appvr;
        }
        if (/artist\/v1\/effect\/get_resources_by_category_id/.test(url) &&
            requestUrl) {
            editor.versionName =
                requestUrl.searchParams.get('version_name') ?? editor.versionName;
            editor.versionCode =
                requestUrl.searchParams.get('version_code') ?? editor.versionCode;
            editor.sdkVersion =
                requestUrl.searchParams.get('sdk_version') ?? editor.sdkVersion;
            editor.effectSdkVersion =
                requestUrl.searchParams.get('effect_sdk_version') ??
                    editor.effectSdkVersion;
        }
        if (!mimeType.includes('javascript') || !text) {
            continue;
        }
        if (url.includes('npm.byted-sdk.account-api')) {
            login = (0, bundleExtractors_1.mergeLoginBundleConfig)(login, (0, bundleExtractors_1.extractLoginBundleConfig)(text, url));
            continue;
        }
        if (/video_online\/static\/js\/(editor|editor-template|services-|vendors-5\.0bd5a122)|smart_tools_online\/static\/js\/(tts|tts-initial)|platform_online\/static\/js\/async\/48427/.test(url)) {
            editor = (0, bundleExtractors_1.mergeEditorBundleConfig)(editor, (0, bundleExtractors_1.extractEditorBundleConfig)(text, url));
        }
    }
    return {
        discoveredAt: Date.now(),
        login,
        editor,
    };
};
exports.extractCapCutBundleConfigFromHarFile = extractCapCutBundleConfigFromHarFile;
//# sourceMappingURL=harBundleUtils.js.map