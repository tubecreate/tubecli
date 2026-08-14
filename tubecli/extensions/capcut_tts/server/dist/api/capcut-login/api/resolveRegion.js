"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.resolveRegion = void 0;
const apiClient_1 = require("../../../api/capcut-login/apiClient");
/**
 * email から login host を解決する API を呼ぶ
 */
const resolveRegion = (params) => apiClient_1.CapCutLoginApiClient.request({
    ...params,
    path: params.path ?? '/passport/web/region/',
    method: 'POST',
});
exports.resolveRegion = resolveRegion;
//# sourceMappingURL=resolveRegion.js.map