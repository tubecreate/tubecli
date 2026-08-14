"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.get = void 0;
const apiError_1 = require("../../../../lib/apiError");
const CapCutService_1 = __importDefault(require("../../../../services/CapCutService"));
const logger_1 = __importDefault(require("../../../../services/logger"));
/**
 * ### get
 * `/v2/speakers/:speakerId/preview` のプレビュー音声取得を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
const get = async (req, res, next) => {
    const rawSpeakerId = req.params.speakerId;
    const speakerId = typeof rawSpeakerId === 'string' ? rawSpeakerId.trim() : undefined;
    if (!speakerId) {
        next((0, apiError_1.apiError)(apiError_1.ErrorCode.NOT_FOUND, 'Speaker'));
        return;
    }
    try {
        const audioResult = await CapCutService_1.default.getSpeakerPreviewAudio(speakerId);
        if (audioResult.contentLength) {
            res.setHeader('Content-Length', audioResult.contentLength);
        }
        if (audioResult.fileName) {
            res.setHeader('Content-Disposition', `inline; filename="${audioResult.fileName}"`);
        }
        res.type(audioResult.contentType).status(200).end(audioResult.buffer);
    }
    catch (error) {
        logger_1.default.error('Failed to get speaker preview audio', error);
        next((0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to get speaker preview audio'));
    }
};
exports.get = get;
//# sourceMappingURL=get.js.map