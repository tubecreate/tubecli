"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.checkEmailRegistered = void 0;
const apiClient_1 = require("../../../api/capcut-login/apiClient");
/**
 * email 登録状態確認 API を呼ぶ
 */
const checkEmailRegistered = ({ requester, host, searchParams, headers, body, }) => apiClient_1.CapCutLoginApiClient.request({
    requester,
    host,
    path: '/passport/web/user/check_email_registered',
    searchParams,
    method: 'POST',
    headers,
    body,
});
exports.checkEmailRegistered = checkEmailRegistered;
//# sourceMappingURL=checkEmailRegistered.js.map