"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.errorHandler = void 0;
const apiError_1 = require("../lib/apiError");
const logger_1 = __importDefault(require("../services/logger"));
/**
 * ### errorHandler
 * 例外を API 共通のエラーレスポンスへ正規化する
 *
 * @param err - 発生した例外
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
const errorHandler = (err, req, res, next) => {
    void req;
    if (res.headersSent) {
        next(err);
        return;
    }
    if (err instanceof apiError_1.ApiError) {
        if (err.isExpected) {
            logger_1.default.warn(`ApiError: ${err.code} - ${err.message}`);
        }
        else {
            logger_1.default.error(`ApiError: ${err.code}`, err);
        }
        res.status(err.statusCode).json(err.toResponse());
        return;
    }
    logger_1.default.error('Unexpected error', err);
    res.status(500).json({
        code: apiError_1.ErrorCode.INTERNAL_SERVER_ERROR,
        message: 'Internal server error',
    });
};
exports.errorHandler = errorHandler;
//# sourceMappingURL=errorHandler.js.map