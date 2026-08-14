/**
 * CapCut API 応答の失敗を表すエラー
 */
export declare class CapCutApiError extends Error {
    statusCode?: number;
    errorCode?: number;
    descUrl?: string;
    constructor(message: string, options?: {
        statusCode?: number;
        errorCode?: number;
        descUrl?: string;
        cause?: unknown;
    });
}
/**
 * JSON 文字列の中身が object なら返す
 */
export declare const parseNestedJsonRecord: (value: unknown) => Record<string, unknown> | null;
/**
 * CapCut の共通 payload を unwrap する
 */
export declare const unwrapPayload: <T>(raw: unknown, context: string) => T;
/**
 * Response を text → json → payload unwrap まで処理する
 */
export declare const unwrapJsonResponse: <T>(response: Response, context: string) => Promise<T>;
