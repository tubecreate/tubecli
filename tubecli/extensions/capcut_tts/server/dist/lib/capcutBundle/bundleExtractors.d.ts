import type { CapCutEditorBundleConfig, CapCutLoginBundleConfig } from '../../types/capcutBundle';
/**
 * login/account bundle から抽出可能な設定を抜く
 */
export declare const extractLoginBundleConfig: (bundleText: string, bundleUrl?: string) => CapCutLoginBundleConfig;
/**
 * editor bundle から抽出可能な設定を抜く
 */
export declare const extractEditorBundleConfig: (bundleText: string, bundleUrl?: string) => CapCutEditorBundleConfig;
/**
 * editor 設定を後勝ちでマージする
 */
export declare const mergeEditorBundleConfig: (current: CapCutEditorBundleConfig, next: CapCutEditorBundleConfig) => CapCutEditorBundleConfig;
/**
 * login 設定を後勝ちでマージする
 */
export declare const mergeLoginBundleConfig: (current: CapCutLoginBundleConfig, next: CapCutLoginBundleConfig) => CapCutLoginBundleConfig;
