"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.get = void 0;
const audioResponse_1 = require("../../../lib/audioResponse");
const apiError_1 = require("../../../lib/apiError");
const responseUtils_1 = require("../../../lib/capcut/responseUtils");
const synthesize_1 = require("../../../schemas/synthesize");
const requestCredentials_1 = require("../../../lib/capcut/requestCredentials");
const CapCutService_1 = require("../../../services/CapCutService");
const logger_1 = __importDefault(require("../../../services/logger"));
/**
 * ### get
 * `/v2/synthesize` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - NextFunction
 */
const get = async (req, res, next) => {
    const synthesizeQueryValidation = synthesize_1.SynthesizeQuerySchema.safeParse(req.query);
    if (!synthesizeQueryValidation.success) {
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.VALIDATION_ERROR, synthesizeQueryValidation.error.issues);
    }
    const synthesizeQuery = synthesizeQueryValidation.data;
    const capCutService = (0, CapCutService_1.getCapCutService)((0, requestCredentials_1.extractRequestCredentials)({
        headers: req.headers,
        query: req.query,
    }));
    if (synthesizeQuery.timestamps) {
        try {
            const marked = await capCutService.synthesizeWithMarks(synthesizeQuery);
            res.status(200).json((0, audioResponse_1.toMarkedResponse)(marked, synthesizeQuery.phonemes ?? false));
            return;
        }
        catch (error) {
            if (error instanceof responseUtils_1.CapCutApiError && error.statusCode === 400) {
                throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, error.message);
            }
            logger_1.default.error('Failed to synthesize audio with timestamps', error);
            throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
        }
    }
    if (synthesizeQuery.method === 'stream') {
        try {
            const audioStream = await capCutService.synthesizeStream(synthesizeQuery);
            (0, audioResponse_1.sendAudioStreamResponse)(res, audioStream, (error) => {
                logger_1.default.error('Failed to synthesize audio stream', error);
                if (!res.headersSent) {
                    next((0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio'));
                    return;
                }
                res.end();
            });
            return;
        }
        catch (error) {
            logger_1.default.error('Failed to synthesize audio stream', error);
            throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
        }
    }
    try {
        const audioResult = await capCutService.synthesizeBuffer(synthesizeQuery);
        (0, audioResponse_1.sendAudioBufferResponse)(res, audioResult);
    }
    catch (error) {
        logger_1.default.error('Failed to synthesize audio', error);
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
    }
};
exports.get = get;
//# sourceMappingURL=get.js.map