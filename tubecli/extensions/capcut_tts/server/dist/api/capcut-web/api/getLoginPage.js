"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getLoginPage = void 0;
const apiClient_1 = require("../../../api/capcut-web/apiClient");
/**
 * login ページを取得して初期 Cookie を得る
 */
const getLoginPage = ({ requester, path, headers }) => apiClient_1.CapCutWebApiClient.request({
    requester,
    path,
    method: 'GET',
    headers,
});
exports.getLoginPage = getLoginPage;
//# sourceMappingURL=getLoginPage.js.map