"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getVoiceModels = void 0;
const apiClient_1 = require("../../../api/capcut-edit/apiClient");
/**
 * 音声モデル一覧を取得する
 */
const getVoiceModels = ({ requester, path, searchParams, headers, body, }) => apiClient_1.CapCutEditApiClient.request({
    requester,
    path: path ?? '/artist/v1/effect/get_resources_by_category_id',
    searchParams,
    method: 'POST',
    headers,
    body,
});
exports.getVoiceModels = getVoiceModels;
//# sourceMappingURL=getVoiceModels.js.map