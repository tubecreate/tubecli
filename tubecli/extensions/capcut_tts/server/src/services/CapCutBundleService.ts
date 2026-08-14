import env from '@/configs/env';
import { getBlobStorage } from '@/lib/storage';
import {
  extractScriptUrlsFromHtml,
} from '@/lib/capcutBundle/bundleExtractionUtils';
import {
  extractEditorBundleConfig,
  extractLoginBundleConfig,
  mergeEditorBundleConfig,
  mergeLoginBundleConfig,
} from '@/lib/capcutBundle/bundleExtractors';
import logger from '@/services/logger';
import type { ApiRequester } from '@/types/api';
import type { CapCutBundleConfig } from '@/types/capcutBundle';

const bundleCacheTtlMs = 30 * 60 * 1000;

const defaultBundleConfig = (): CapCutBundleConfig => ({
  discoveredAt: 0,
  login: {},
  editor: {
    sourceUrls: [],
  },
});

const toAbsoluteUrl = (url: string) =>
  new URL(url, env.CAPCUT_WEB_URL).toString();

/**
 * CapCut の live bundle から設定値を抽出してキャッシュする
 */
class CapCutBundleService {
  private loginBundleConfig: CapCutBundleConfig['login'] | null = null;

  private editorBundleConfig: CapCutBundleConfig['editor'] | null = null;

  private loginBundleDiscoveredAt = 0;

  private editorBundleDiscoveredAt = 0;

  private loginBundlePromise: Promise<CapCutBundleConfig['login']> | null = null;

  private editorBundlePromise: Promise<CapCutBundleConfig['editor']> | null = null;

  /**
   * workspace / TTS 実行に足りる editor bundle 設定かを判定する
   */
  private hasUsableEditorBundleConfig(config: CapCutBundleConfig['editor']) {
    return (
      typeof config.editorAppVersion === 'string' &&
      /^\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?$/.test(config.editorAppVersion) &&
      (config.signRecipe?.pathTailLength ?? 0) >= 7
    );
  }

  /**
   * login bundle 設定を返す
   */
  async resolveLoginBundleConfig() {
    await this.loadBundleConfigFromFile();

    if (
      this.loginBundleConfig &&
      Date.now() - this.loginBundleDiscoveredAt < bundleCacheTtlMs
    ) {
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
  async resolveEditorBundleConfig(
    requester?: ApiRequester,
    forceRefresh = false
  ) {
    await this.loadBundleConfigFromFile();

    if (
      !forceRefresh &&
      this.editorBundleConfig &&
      Date.now() - this.editorBundleDiscoveredAt < bundleCacheTtlMs &&
      this.hasUsableEditorBundleConfig(this.editorBundleConfig)
    ) {
      return this.editorBundleConfig;
    }

    if (this.editorBundlePromise) {
      return this.editorBundlePromise;
    }

    this.editorBundlePromise = this.fetchEditorBundleConfig(requester).finally(
      () => {
        this.editorBundlePromise = null;
      }
    );

    return this.editorBundlePromise;
  }

  /**
   * 抽出済み設定ファイルがあれば読み込む
   */
  private async loadBundleConfigFromFile() {
    if (this.loginBundleConfig || this.editorBundleConfig) {
      return;
    }

    try {
      const raw = await getBlobStorage().readText(env.CAPCUT_BUNDLE_CONFIG_PATH);

      if (!raw) {
        return;
      }

      const parsed = JSON.parse(raw) as CapCutBundleConfig;

      this.loginBundleConfig = parsed.login;
      this.editorBundleConfig = parsed.editor;
      this.loginBundleDiscoveredAt = parsed.discoveredAt;
      this.editorBundleDiscoveredAt = parsed.discoveredAt;

      logger.info('CapCut bundle config loaded from file', {
        path: env.CAPCUT_BUNDLE_CONFIG_PATH,
      });
    } catch (error) {
      logger.warn('Failed to load CapCut bundle config file', { error });
    }
  }

  /**
   * 現在の bundle 設定をファイルへ保存する
   */
  private async persistBundleConfig() {
    const currentConfig: CapCutBundleConfig = {
      discoveredAt: Math.max(
        this.loginBundleDiscoveredAt,
        this.editorBundleDiscoveredAt
      ),
      login: this.loginBundleConfig ?? defaultBundleConfig().login,
      editor: this.editorBundleConfig ?? defaultBundleConfig().editor,
    };

    try {
      await getBlobStorage().writeText(
        env.CAPCUT_BUNDLE_CONFIG_PATH,
        JSON.stringify(currentConfig, null, 2)
      );

      logger.info('CapCut bundle config saved to file', {
        path: env.CAPCUT_BUNDLE_CONFIG_PATH,
      });
    } catch (error) {
      logger.warn('Failed to save CapCut bundle config file', { error });
    }
  }

  /**
   * login ページから account bundle を辿って抽出する
   */
  private async fetchLoginBundleConfig() {
    try {
      const response = await fetch(
        `${env.CAPCUT_WEB_URL}/${env.CAPCUT_PAGE_LOCALE}/login`,
        {
          headers: {
            'User-Agent': env.USER_AGENT,
            Accept:
              'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
          },
        }
      );

      if (!response.ok) {
        throw new Error(
          `Failed to fetch login page: ${response.status} ${response.statusText}`
        );
      }

      const html = await response.text();
      const scriptUrls = extractScriptUrlsFromHtml(html)
        .map(toAbsoluteUrl)
        .filter((url) => url.includes('npm.byted-sdk.account-api'));

      let loginConfig = defaultBundleConfig().login;

      for (const scriptUrl of scriptUrls) {
        const scriptResponse = await fetch(scriptUrl, {
          headers: {
            'User-Agent': env.USER_AGENT,
            Accept: '*/*',
          },
        });

        if (!scriptResponse.ok) {
          continue;
        }

        const bundleText = await scriptResponse.text();
        loginConfig = mergeLoginBundleConfig(
          loginConfig,
          extractLoginBundleConfig(bundleText, scriptUrl)
        );
      }

      this.loginBundleConfig = loginConfig;
      this.loginBundleDiscoveredAt = Date.now();
      await this.persistBundleConfig();
      logger.info('CapCut login bundle config extracted', loginConfig);
      return loginConfig;
    } catch (error) {
      logger.warn('Failed to extract CapCut login bundle config', { error });
      return this.loginBundleConfig ?? defaultBundleConfig().login;
    }
  }

  /**
   * editor 系ページから bundle を辿って抽出する
   */
  private async fetchEditorBundleConfig(requester?: ApiRequester) {
    const pageRequester: ApiRequester =
      requester ??
      (async (url, init) => fetch(url, init));

    const candidatePages = [
      `${env.CAPCUT_WEB_URL}/my-edit?from_page=landing_page&start_tab=video`,
      `${env.CAPCUT_WEB_URL}/editor?from_page=landing_page&start_tab=video`,
      `${env.CAPCUT_WEB_URL}/tools/text-to-speech`,
    ];

    try {
      let editorConfig = defaultBundleConfig().editor;

      for (const pageUrl of candidatePages) {
        const response = await pageRequester(pageUrl, {
          method: 'GET',
          headers: {
            'User-Agent': env.USER_AGENT,
            Accept:
              'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
          },
        });

        if (!response.ok) {
          continue;
        }

        const html = await response.text();
        const scriptUrls = extractScriptUrlsFromHtml(html)
          .map(toAbsoluteUrl)
          .filter((url) =>
            /video_online\/static\/js\/(editor|editor-template|services-|vendors-5\.0bd5a122)|smart_tools_online\/static\/js\/(tts|tts-initial)|platform_online\/static\/js\/async\/48427/.test(
              url
            )
          );

        for (const scriptUrl of scriptUrls) {
          const scriptResponse = await pageRequester(scriptUrl, {
            method: 'GET',
            headers: {
              'User-Agent': env.USER_AGENT,
              Accept: '*/*',
            },
          });

          if (!scriptResponse.ok) {
            continue;
          }

          const bundleText = await scriptResponse.text();
          editorConfig = mergeEditorBundleConfig(
            editorConfig,
            extractEditorBundleConfig(bundleText, scriptUrl)
          );
        }

        if (this.hasUsableEditorBundleConfig(editorConfig)) {
          break;
        }
      }

      this.editorBundleConfig = editorConfig;
      this.editorBundleDiscoveredAt = Date.now();
      await this.persistBundleConfig();
      logger.info('CapCut editor bundle config extracted', editorConfig);
      return editorConfig;
    } catch (error) {
      logger.warn('Failed to extract CapCut editor bundle config', { error });
      return this.editorBundleConfig ?? defaultBundleConfig().editor;
    }
  }
}

export const capCutBundleService = new CapCutBundleService();

export default capCutBundleService;
