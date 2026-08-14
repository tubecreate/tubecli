"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.queryTtsTask = void 0;
const apiClient_1 = require("../../../api/capcut-edit/apiClient");
/**
 * editor intelligence TTS タスク状態を照会する
 */
const queryTtsTask = ({ requester, path, searchParams, headers, body, }) => apiClient_1.CapCutEditApiClient.request({
    requester,
    path: path ?? '/lv/v2/intelligence/query',
    searchParams,
    method: 'POST',
    headers,
    body,
});
exports.queryTtsTask = queryTtsTask;
//# sourceMappingURL=queryTtsTask.js.map