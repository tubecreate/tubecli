"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.emailLogin = void 0;
const apiClient_1 = require("../../../api/capcut-login/apiClient");
/**
 * email/password ログイン API を呼ぶ
 */
const emailLogin = (params) => apiClient_1.CapCutLoginApiClient.request({
    ...params,
    path: params.path ?? '/passport/web/email/login/',
    method: 'POST',
});
exports.emailLogin = emailLogin;
//# sourceMappingURL=emailLogin.js.map