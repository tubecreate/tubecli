"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createTtsTask = void 0;
const apiClient_1 = require("../../../api/capcut-edit/apiClient");
/**
 * editor intelligence TTS タスクを作成する
 */
const createTtsTask = ({ requester, path, searchParams, headers, body, }) => apiClient_1.CapCutEditApiClient.request({
    requester,
    path: path ?? '/lv/v2/intelligence/create',
    searchParams,
    method: 'POST',
    headers,
    body,
});
exports.createTtsTask = createTtsTask;
//# sourceMappingURL=createTtsTask.js.map