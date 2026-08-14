"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.fallback = void 0;
const apiError_1 = require("../../lib/apiError");
/**
 * ### fallback
 * `/v2` 配下の未定義 route を 404 として扱う
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
const fallback = (req, res, next) => {
    void req;
    void res;
    next((0, apiError_1.apiError)(apiError_1.ErrorCode.NOT_FOUND));
};
exports.fallback = fallback;
//# sourceMappingURL=fallback.js.map