"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.get = void 0;
const capcutLegacySpeakers_1 = require("../../../models/capcutLegacySpeakers");
/**
 * ### get
 * `/v1/models` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
const get = async (req, res) => {
    void req;
    res.status(200).json(capcutLegacySpeakers_1.capCutLegacySpeakers.map((model) => ({
        id: model.id,
        name: model.title,
        description: model.description,
        language: model.language,
        type: model.type,
    })));
};
exports.get = get;
//# sourceMappingURL=get.js.map