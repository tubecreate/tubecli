"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getVoicePanelInfo = void 0;
const apiClient_1 = require("../../../api/capcut-edit/apiClient");
/**
 * 音声パネル情報を取得する
 * ここで返る categories が音声カテゴリの生存 ID になる
 */
const getVoicePanelInfo = ({ requester, path, searchParams, headers, body, }) => apiClient_1.CapCutEditApiClient.request({
    requester,
    path: path ?? '/artist/v1/panel/get_panel_info',
    searchParams,
    method: 'POST',
    headers,
    body,
});
exports.getVoicePanelInfo = getVoicePanelInfo;
//# sourceMappingURL=getVoicePanelInfo.js.map