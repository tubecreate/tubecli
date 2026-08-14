"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getAccountInfo = void 0;
const apiClient_1 = require("../../../api/capcut-web/apiClient");
/**
 * ログイン済みアカウント情報を取得する
 */
const getAccountInfo = ({ requester, path, searchParams, headers, }) => apiClient_1.CapCutWebApiClient.request({
    requester,
    path: path ?? '/passport/web/account/info/',
    searchParams,
    method: 'GET',
    headers,
});
exports.getAccountInfo = getAccountInfo;
//# sourceMappingURL=getAccountInfo.js.map