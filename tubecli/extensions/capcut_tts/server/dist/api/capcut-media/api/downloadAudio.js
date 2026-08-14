"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.downloadAudio = void 0;
const apiClient_1 = require("../../../api/capcut-media/apiClient");
/**
 * 音声ファイルを直接ダウンロードする
 */
const downloadAudio = ({ requester, url, headers }) => apiClient_1.CapCutMediaApiClient.request({
    requester,
    url,
    method: 'GET',
    headers,
});
exports.downloadAudio = downloadAudio;
//# sourceMappingURL=downloadAudio.js.map