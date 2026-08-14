"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.get = void 0;
const apiError_1 = require("../../../lib/apiError");
const CapCutService_1 = __importDefault(require("../../../services/CapCutService"));
const logger_1 = __importDefault(require("../../../services/logger"));
/**
 * ### get
 * `/v2/languages` を処理する
 *
 * 利用可能な言語コードと該当話者数を返す
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
const get = async (req, res) => {
    void req;
    try {
        const languages = await CapCutService_1.default.listSpeakerLanguages();
        res.status(200).json(languages);
    }
    catch (error) {
        logger_1.default.error('Failed to fetch CapCut speaker languages', error);
        throw (0, apiError_1.apiError)(apiError_1.ErrorCode.BAD_GATEWAY, 'Failed to fetch speaker languages');
    }
};
exports.get = get;
//# sourceMappingURL=get.js.map