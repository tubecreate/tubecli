"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getUserWorkspaces = void 0;
const apiClient_1 = require("../../../api/capcut-edit/apiClient");
/**
 * ワークスペース一覧を取得する
 */
const getUserWorkspaces = ({ requester, path, headers, body, }) => apiClient_1.CapCutEditApiClient.request({
    requester,
    path: path ?? '/cc/v1/workspace/get_user_workspaces',
    method: 'POST',
    headers,
    body,
});
exports.getUserWorkspaces = getUserWorkspaces;
//# sourceMappingURL=getUserWorkspaces.js.map