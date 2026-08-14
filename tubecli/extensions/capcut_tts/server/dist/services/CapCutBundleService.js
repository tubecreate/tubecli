"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.capCutBundleService = void 0;
const env_1 = __importDefault(require("../configs/env"));
const storage_1 = require("../lib/storage");
const bundleExtractionUtils_1 = require("../lib/capcutBundle/bundleExtractionUtils");
const bundleExtractors_1 = require("../lib/capcutBundle/bundleExtractors");
const logger_1 = __importDefault(require("../services/logger"));
const bundleCacheTtlMs = 30 * 60 * 1000;
const defaultBundleConfig = () => ({
    discoveredAt: 0,
    login: {},
    editor: {
        sourceUrls: [],
    },
});
const toAbsoluteUrl = (url) => new URL(url, env_1.default.CAPCUT_WEB_URL).toString();
/**
 * CapCut の live bundle から設定値を抽出してキャッシュする
 */
class CapCutBundleService {
    loginBundleConfig = null;
    editorBundleConfig = null;
    loginBundleDiscoveredAt = 0;
    editorBundleDiscoveredAt = 0;
    loginBundlePromise = null;
    editorBundlePromise = null;
    /**
     * workspace / TTS 実行に足りる editor bundle 設定かを判定する
     */
    hasUsableEditorBundleConfig(config) {
        return (typeof config.editorAppVersion === 'string' &&
            /^\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?$/.test(config.editorAppVersion) &&
            (config.signRecipe?.pathTailLength ?? 0) >= 7);
    }
    /**
     * login bundle 設定を返す
     */
    async resolveLoginBundleConfig() {
        await this.loadBundleConfigFromFile();
        if (this.loginBundleConfig &&
            Date.now() - this.loginBundleDiscoveredAt < bundleCacheTtlMs) {
            return this.loginBundleConfig;
        }
        if (this.loginBundlePromise) {
            return this.loginBundlePromise;
        }
        this.loginBundlePromise = this.fetchLoginBundleConfig().finally(() => {
            this.loginBundlePromise = null;
        });
        return this.loginBundlePromise;
    }
    /**
     * editor bundle 設定を返す
     */
    async resolveEditorBundleConfig(requester, forceRefresh = false) {
        await this.loadBundleConfigFromFile();
        if (!forceRefresh &&
            this.editorBundleConfig &&
            Date.now() - this.editorBundleDiscoveredAt < bundleCacheTtlMs &&
            this.hasUsableEditorBundleConfig(this.editorBundleConfig)) {
            return this.editorBundleConfig;
        }
        if (this.editorBundlePromise) {
            return this.editorBundlePromise;
        }
        this.editorBundlePromise = this.fetchEditorBundleConfig(requester).finally(() => {
            this.editorBundlePromise = null;
        });
        return this.editorBundlePromise;
    }
    /**
     * 抽出済み設定ファイルがあれば読み込む
     */
    async loadBundleConfigFromFile() {
        if (this.loginBundleConfig || this.editorBundleConfig) {
            return;
        }
        try {
            const raw = await (0, storage_1.getBlobStorage)().readText(env_1.default.CAPCUT_BUNDLE_CONFIG_PATH);
            if (!raw) {
                return;
            }
            const parsed = JSON.parse(raw);
            this.loginBundleConfig = parsed.login;
            this.editorBundleConfig = parsed.editor;
            this.loginBundleDiscoveredAt = parsed.discoveredAt;
            this.editorBundleDiscoveredAt = parsed.discoveredAt;
            logger_1.default.info('CapCut bundle config loaded from file', {
                path: env_1.default.CAPCUT_BUNDLE_CONFIG_PATH,
            });
        }
        catch (error) {
            logger_1.default.warn('Failed to load CapCut bundle config file', { error });
        }
    }
    /**
     * 現在の bundle 設定をファイルへ保存する
     */
    async persistBundleConfig() {
        const currentConfig = {
            discoveredAt: Math.max(this.loginBundleDiscoveredAt, this.editorBundleDiscoveredAt),
            login: this.loginBundleConfig ?? defaultBundleConfig().login,
            editor: this.editorBundleConfig ?? defaultBundleConfig().editor,
        };
        try {
            await (0, storage_1.getBlobStorage)().writeText(env_1.default.CAPCUT_BUNDLE_CONFIG_PATH, JSON.stringify(currentConfig, null, 2));
            logger_1.default.info('CapCut bundle config saved to file', {
                path: env_1.default.CAPCUT_BUNDLE_CONFIG_PATH,
            });
        }
        catch (error) {
            logger_1.default.warn('Failed to save CapCut bundle config file', { error });
        }
    }
    /**
     * login ページから account bundle を辿って抽出する
     */
    async fetchLoginBundleConfig() {
        try {
            const response = await fetch(`${env_1.default.CAPCUT_WEB_URL}/${env_1.default.CAPCUT_PAGE_LOCALE}/login`, {
                headers: {
                    'User-Agent': env_1.default.USER_AGENT,
                    Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                },
            });
            if (!response.ok) {
                throw new Error(`Failed to fetch login page: ${response.status} ${response.statusText}`);
            }
            const html = await response.text();
            const scriptUrls = (0, bundleExtractionUtils_1.extractScriptUrlsFromHtml)(html)
                .map(toAbsoluteUrl)
                .filter((url) => url.includes('npm.byted-sdk.account-api'));
            let loginConfig = defaultBundleConfig().login;
            for (const scriptUrl of scriptUrls) {
                const scriptResponse = await fetch(scriptUrl, {
                    headers: {
                        'User-Agent': env_1.default.USER_AGENT,
                        Accept: '*/*',
                    },
                });
                if (!scriptResponse.ok) {
                    continue;
                }
                const bundleText = await scriptResponse.text();
                loginConfig = (0, bundleExtractors_1.mergeLoginBundleConfig)(loginConfig, (0, bundleExtractors_1.extractLoginBundleConfig)(bundleText, scriptUrl));
            }
            this.loginBundleConfig = loginConfig;
            this.loginBundleDiscoveredAt = Date.now();
            await this.persistBundleConfig();
            logger_1.default.info('CapCut login bundle config extracted', loginConfig);
            return loginConfig;
        }
        catch (error) {
            logger_1.default.warn('Failed to extract CapCut login bundle config', { error });
            return this.loginBundleConfig ?? defaultBundleConfig().login;
        }
    }
    /**
     * editor 系ページから bundle を辿って抽出する
     */
    async fetchEditorBundleConfig(requester) {
        const pageRequester = requester ??
            (async (url, init) => fetch(url, init));
        const candidatePages = [
            `${env_1.default.CAPCUT_WEB_URL}/my-edit?from_page=landing_page&start_tab=video`,
            `${env_1.default.CAPCUT_WEB_URL}/editor?from_page=landing_page&start_tab=video`,
            `${env_1.default.CAPCUT_WEB_URL}/tools/text-to-speech`,
        ];
        try {
            let editorConfig = defaultBundleConfig().editor;
            for (const pageUrl of candidatePages) {
                const response = await pageRequester(pageUrl, {
                    method: 'GET',
                    headers: {
                        'User-Agent': env_1.default.USER_AGENT,
                        Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    },
                });
                if (!response.ok) {
                    continue;
                }
                const html = await response.text();
                const scriptUrls = (0, bundleExtractionUtils_1.extractScriptUrlsFromHtml)(html)
                    .map(toAbsoluteUrl)
                    .filter((url) => /video_online\/static\/js\/(editor|editor-template|services-|vendors-5\.0bd5a122)|smart_tools_online\/static\/js\/(tts|tts-initial)|platform_online\/static\/js\/async\/48427/.test(url));
                for (const scriptUrl of scriptUrls) {
                    const scriptResponse = await pageRequester(scriptUrl, {
                        method: 'GET',
                        headers: {
                            'User-Agent': env_1.default.USER_AGENT,
                            Accept: '*/*',
                        },
                    });
                    if (!scriptResponse.ok) {
                        continue;
                    }
                    const bundleText = await scriptResponse.text();
                    editorConfig = (0, bundleExtractors_1.mergeEditorBundleConfig)(editorConfig, (0, bundleExtractors_1.extractEditorBundleConfig)(bundleText, scriptUrl));
                }
                if (this.hasUsableEditorBundleConfig(editorConfig)) {
                    break;
                }
            }
            this.editorBundleConfig = editorConfig;
            this.editorBundleDiscoveredAt = Date.now();
            await this.persistBundleConfig();
            logger_1.default.info('CapCut editor bundle config extracted', editorConfig);
            return editorConfig;
        }
        catch (error) {
            logger_1.default.warn('Failed to extract CapCut editor bundle config', { error });
            return this.editorBundleConfig ?? defaultBundleConfig().editor;
        }
    }
}
exports.capCutBundleService = new CapCutBundleService();
exports.default = exports.capCutBundleService;
//# sourceMappingURL=CapCutBundleService.js.map