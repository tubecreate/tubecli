import type { ZodIssue } from 'zod';
export declare const ErrorCode: {
    readonly VALIDATION_ERROR: "VALIDATION_ERROR";
    readonly NOT_FOUND: "NOT_FOUND";
    readonly FORBIDDEN: "FORBIDDEN";
    readonly BAD_GATEWAY: "BAD_GATEWAY";
    readonly SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE";
    readonly INTERNAL_SERVER_ERROR: "INTERNAL_SERVER_ERROR";
};
export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];
export type ValidationErrorDetails = ZodIssue[];
type ValidationErrorResponse = {
    code: typeof ErrorCode.VALIDATION_ERROR;
    message: string;
    details: ValidationErrorDetails;
};
export type ErrorResponse = {
    code: Exclude<ErrorCode, typeof ErrorCode.VALIDATION_ERROR>;
    message: string;
};
export type ApiErrorResponse = ValidationErrorResponse | ErrorResponse;
/**
 * # ApiError
 * API レスポンスとして返す情報を保持する共通エラー
 *
 * ### 特徴
 * - HTTP ステータスとエラーコードを一元管理する
 * - バリデーション失敗時だけ details を返す
 */
export declare class ApiError extends Error {
    readonly statusCode: number;
    readonly code: ErrorCode;
    readonly details?: ValidationErrorDetails;
    readonly isExpected: boolean;
    constructor(statusCode: number, code: ErrorCode, message: string, details?: ValidationErrorDetails, isExpected?: boolean);
    /**
     * ### toResponse
     * クライアントへ返すエラー JSON を生成する
     *
     * @returns API 共通エラーレスポンス
     */
    toResponse(): ApiErrorResponse;
}
type ApiErrorArgs = {
    [ErrorCode.VALIDATION_ERROR]: [details: ValidationErrorDetails];
    [ErrorCode.NOT_FOUND]: [resource?: string];
    [ErrorCode.FORBIDDEN]: [message?: string];
    [ErrorCode.BAD_GATEWAY]: [message?: string];
    [ErrorCode.SERVICE_UNAVAILABLE]: [message?: string];
    [ErrorCode.INTERNAL_SERVER_ERROR]: [message?: string];
};
/**
 * ### apiError
 * エラーコードに対応した API エラーを生成する
 *
 * @param code - エラー種別
 * @param args - エラーコードごとの追加情報
 * @returns 共通 API エラー
 */
export declare const apiError: <K extends ErrorCode>(code: K, ...args: ApiErrorArgs[K]) => ApiError;
export {};
