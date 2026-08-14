import type { CapCutBundleConfig } from '../../types/capcutBundle';
/**
 * HAR ファイル内の JS bundle を走査して設定を抽出する
 */
export declare const extractCapCutBundleConfigFromHarFile: (harPath: string) => Promise<CapCutBundleConfig>;
