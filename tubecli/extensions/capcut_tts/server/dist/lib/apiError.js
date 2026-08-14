"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.apiError = exports.ApiError = exports.ErrorCode = void 0;
exports.ErrorCode = {
    VALIDATION_ERROR: 'VALIDATION_ERROR',
    NOT_FOUND: 'NOT_FOUND',
    FORBIDDEN: 'FORBIDDEN',
    BAD_GATEWAY: 'BAD_GATEWAY',
    SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
    INTERNAL_SERVER_ERROR: 'INTERNAL_SERVER_ERROR',
};
/**
 * # ApiError
 * API レスポンスとして返す情報を保持する共通エラー
 *
 * ### 特徴
 * - HTTP ステータスとエラーコードを一元管理する
 * - バリデーション失敗時だけ details を返す
 */
class ApiError extends Error {
    statusCode;
    code;
    details;
    isExpected;
    constructor(statusCode, code, message, details, isExpected = true) {
        super(message);
        this.name = 'ApiError';
        this.statusCode = statusCode;
        this.code = code;
        this.details =
            code === exports.ErrorCode.VALIDATION_ERROR ? details : undefined;
        this.isExpected = isExpected;
    }
    /**
     * ### toResponse
     * クライアントへ返すエラー JSON を生成する
     *
     * @returns API 共通エラーレスポンス
     */
    toResponse() {
        if (this.code === exports.ErrorCode.VALIDATION_ERROR) {
            return {
                code: exports.ErrorCode.VALIDATION_ERROR,
                message: this.message,
                details: this.details ?? [],
            };
        }
        return {
            code: this.code,
            message: this.message,
        };
    }
}
exports.ApiError = ApiError;
// message と status code の揺れを防ぐため、生成口をここへ寄せる
const apiErrorBuilders = {
    [exports.ErrorCode.VALIDATION_ERROR]: (details) => new ApiError(400, exports.ErrorCode.VALIDATION_ERROR, 'Validation failed', details, true),
    [exports.ErrorCode.NOT_FOUND]: (resource = 'Resource') => new ApiError(404, exports.ErrorCode.NOT_FOUND, `${resource} not found`, undefined, true),
    [exports.ErrorCode.FORBIDDEN]: (message = 'Forbidden') => new ApiError(403, exports.ErrorCode.FORBIDDEN, message, undefined, true),
    [exports.ErrorCode.BAD_GATEWAY]: (message = 'Bad gateway') => new ApiError(502, exports.ErrorCode.BAD_GATEWAY, message, undefined, true),
    [exports.ErrorCode.SERVICE_UNAVAILABLE]: (message = 'Service unavailable') => new ApiError(503, exports.ErrorCode.SERVICE_UNAVAILABLE, message, undefined, true),
    [exports.ErrorCode.INTERNAL_SERVER_ERROR]: (message = 'Internal server error') => new ApiError(500, exports.ErrorCode.INTERNAL_SERVER_ERROR, message, undefined, false),
};
/**
 * ### apiError
 * エラーコードに対応した API エラーを生成する
 *
 * @param code - エラー種別
 * @param args - エラーコードごとの追加情報
 * @returns 共通 API エラー
 */
const apiError = (code, ...args) => {
    const builder = apiErrorBuilders[code];
    return builder(...args);
};
exports.apiError = apiError;
//# sourceMappingURL=apiError.js.map