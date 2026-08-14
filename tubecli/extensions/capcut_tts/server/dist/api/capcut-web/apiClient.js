"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.CapCutWebApiClient = void 0;
const env_1 = __importDefault(require("../../configs/env"));
const resolveUrl = (path, searchParams = {}) => {
    const url = new URL(path, env_1.default.CAPCUT_WEB_URL);
    for (const [key, value] of Object.entries(searchParams)) {
        url.searchParams.set(key, value);
    }
    return url.toString();
};
/**
 * web ドメイン向けの共通リクエスト
 */
const request = async ({ requester, path, searchParams = {}, method = 'GET', headers, body, }) => requester(resolveUrl(path, searchParams), {
    method,
    headers,
    body,
});
exports.CapCutWebApiClient = {
    resolveUrl,
    request,
};
//# sourceMappingURL=apiClient.js.map