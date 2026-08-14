/**
 * bundle 解析に使うユーティリティ
 */
export declare const escapeRegExp: (value: string) => string;
/**
 * HTML から script src を抽出する
 */
export declare const extractScriptUrlsFromHtml: (html: string) => string[];
/**
 * バージョンっぽい文字列を重複なく返す
 */
export declare const extractVersionStrings: (text: string) => string[];
/**
 * 変数代入から文字列値を探す
 */
export declare const extractStringAssignment: (text: string, variableName: string) => string | undefined;
/**
 * 正規表現にヒットした最初の文字列を返す
 */
export declare const extractFirst: (text: string, pattern: RegExp) => string | undefined;
