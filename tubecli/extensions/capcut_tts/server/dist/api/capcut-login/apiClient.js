"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CapCutLoginApiClient = void 0;
const resolveUrl = (host, path, searchParams = {}) => {
    const url = new URL(path, host);
    for (const [key, value] of Object.entries(searchParams)) {
        url.searchParams.set(key, value);
    }
    return url.toString();
};
/**
 * login ドメイン向けの共通リクエスト
 */
const request = async ({ requester, host, path, searchParams = {}, method = 'GET', headers, body, }) => requester(resolveUrl(host, path, searchParams), {
    method,
    headers,
    body,
});
exports.CapCutLoginApiClient = {
    resolveUrl,
    request,
};
//# sourceMappingURL=apiClient.js.map