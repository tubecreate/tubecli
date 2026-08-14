"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.fallback = void 0;
const apiError_1 = require("../lib/apiError");
/**
 * ### fallback
 * `/v2` 以外へのアクセスを拒否する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
const fallback = (req, res, next) => {
    next((0, apiError_1.apiError)(apiError_1.ErrorCode.FORBIDDEN));
};
exports.fallback = fallback;
//# sourceMappingURL=fallback.js.map