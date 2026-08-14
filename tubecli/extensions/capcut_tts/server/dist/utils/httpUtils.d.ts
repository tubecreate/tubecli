/**
 * JSON 文字列を安全に parse する
 */
export declare const parseJson: (text: string, context: string) => unknown;
/**
 * 長すぎるレスポンス本文をログ向けに短縮する
 */
export declare const getResponseBodySnippet: (body: string) => string;
