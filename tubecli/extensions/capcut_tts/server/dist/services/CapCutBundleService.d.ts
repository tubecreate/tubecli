import type { ApiRequester } from '../types/api';
/**
 * CapCut の live bundle から設定値を抽出してキャッシュする
 */
declare class CapCutBundleService {
    private loginBundleConfig;
    private editorBundleConfig;
    private loginBundleDiscoveredAt;
    private editorBundleDiscoveredAt;
    private loginBundlePromise;
    private editorBundlePromise;
    /**
     * workspace / TTS 実行に足りる editor bundle 設定かを判定する
     */
    private hasUsableEditorBundleConfig;
    /**
     * login bundle 設定を返す
     */
    resolveLoginBundleConfig(): Promise<import("../types/capcutBundle").CapCutLoginBundleConfig>;
    /**
     * editor bundle 設定を返す
     */
    resolveEditorBundleConfig(requester?: ApiRequester, forceRefresh?: boolean): Promise<import("../types/capcutBundle").CapCutEditorBundleConfig>;
    /**
     * 抽出済み設定ファイルがあれば読み込む
     */
    private loadBundleConfigFromFile;
    /**
     * 現在の bundle 設定をファイルへ保存する
     */
    private persistBundleConfig;
    /**
     * login ページから account bundle を辿って抽出する
     */
    private fetchLoginBundleConfig;
    /**
     * editor 系ページから bundle を辿って抽出する
     */
    private fetchEditorBundleConfig;
}
export declare const capCutBundleService: CapCutBundleService;
export default capCutBundleService;
