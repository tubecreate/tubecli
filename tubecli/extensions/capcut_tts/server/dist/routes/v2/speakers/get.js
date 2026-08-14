"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.get = void 0;
const apiError_1 = require("../../../lib/apiError");
const requestCredentials_1 = require("../../../lib/capcut/requestCredentials");
const CapCutService_1 = require("../../../services/CapCutService");
const logger_1 = __importDefault(require("../../../services/logger"));
/**
 * クエリから単一文字列を取り出す
 */
const singleQueryValue = (value) => {
    const raw = Array.isArray(value) ? value[0] : value;
    if (typeof raw !== 'string') {
        return undefined;
    }
    const trimmed = raw.trim();
    return trimmed.length > 0 ? trimmed : undefined;
};
/**
 * ### get
 * `/v2/speakers` を処理する
 *
 * `?language=vi` `?country=vn` `?category=vietnamese` で絞り込める
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
const get = async (req, res) => {
    const language = singleQueryValue(req.query.language) ?? singleQueryValue(req.query.country);
    const category = singleQueryValue(req.query.category);
    const capCutService = (0, CapCutService_1.getCapCutService)((0, requestCredentials_1.extractRequestCredentials)({
        headers: req.headers,
        query: req.query,
    }));
    try {
        const speakers = await capCutService.listSpeakers({ language, category });
        res.status(200).json(speakers);
    }
    catch (error) {
        logger_1.default.error('Failed to fetch CapCut speakers', error);
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to fetch CapCut speakers');
    }
};
exports.get = get;
//# sourceMappingURL=get.js.map