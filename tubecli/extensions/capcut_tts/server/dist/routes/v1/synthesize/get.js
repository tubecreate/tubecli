"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.get = void 0;
const audioResponse_1 = require("../../../lib/audioResponse");
const apiError_1 = require("../../../lib/apiError");
const legacySynthesize_1 = require("../../../schemas/legacySynthesize");
const LegacyCapCutService_1 = __importDefault(require("../../../services/LegacyCapCutService"));
const logger_1 = __importDefault(require("../../../services/logger"));
const legacyNotConfiguredMessage = 'Legacy CapCut endpoint is not configured. Set LEGACY_DEVICE_TIME and LEGACY_SIGN';
/**
 * ### get
 * `/v1/synthesize` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - NextFunction
 */
const get = async (req, res, next) => {
    const synthesizeQueryValidation = legacySynthesize_1.LegacySynthesizeQuerySchema.safeParse(req.query);
    if (!synthesizeQueryValidation.success) {
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.VALIDATION_ERROR, synthesizeQueryValidation.error.issues);
    }
    if (!LegacyCapCutService_1.default.isConfigured()) {
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.SERVICE_UNAVAILABLE, legacyNotConfiguredMessage);
    }
    const synthesizeQuery = synthesizeQueryValidation.data;
    if (synthesizeQuery.method === 'stream') {
        try {
            const audioStream = await LegacyCapCutService_1.default.synthesizeStream(synthesizeQuery);
            (0, audioResponse_1.sendAudioStreamResponse)(res, audioStream, (error) => {
                logger_1.default.error('Failed to synthesize legacy audio stream', error);
                if (!res.headersSent) {
                    next((0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize legacy audio'));
                    return;
                }
                res.end();
            });
            return;
        }
        catch (error) {
            logger_1.default.error('Failed to synthesize legacy audio stream', error);
            throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize legacy audio');
        }
    }
    try {
        const audioResult = await LegacyCapCutService_1.default.synthesizeBuffer(synthesizeQuery);
        (0, audioResponse_1.sendAudioBufferResponse)(res, audioResult);
    }
    catch (error) {
        logger_1.default.error('Failed to synthesize legacy audio', error);
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize legacy audio');
    }
};
exports.get = get;
//# sourceMappingURL=get.js.map