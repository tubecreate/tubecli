"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CapCutMediaApiClient = void 0;
/**
 * 音声ダウンロード向けの共通リクエスト
 */
const request = async ({ requester, url, method = 'GET', headers, body, }) => requester(url, {
    method,
    headers,
    body,
});
exports.CapCutMediaApiClient = {
    request,
};
//# sourceMappingURL=apiClient.js.map