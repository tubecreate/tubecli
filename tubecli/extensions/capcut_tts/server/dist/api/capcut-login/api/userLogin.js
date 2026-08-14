"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.userLogin = void 0;
const apiClient_1 = require("../../../api/capcut-login/apiClient");
/**
 * user/login 互換 API を呼ぶ
 */
const userLogin = (params) => apiClient_1.CapCutLoginApiClient.request({
    ...params,
    path: params.path ?? '/passport/web/user/login/',
    method: 'POST',
});
exports.userLogin = userLogin;
//# sourceMappingURL=userLogin.js.map