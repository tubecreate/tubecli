"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.CapCutEditApiClient = exports.createEditApiSignature = void 0;
const node_crypto_1 = __importDefault(require("node:crypto"));
const env_1 = __importDefault(require("../../configs/env"));
const resolveUrl = (path, searchParams = {}) => {
    const url = new URL(path, env_1.default.CAPCUT_EDIT_API_URL);
    for (const [key, value] of Object.entries(searchParams)) {
        url.searchParams.set(key, value);
    }
    return url.toString();
};
const createEditApiSignature = (requestUrl, platformId, appVersion, tdid = '', recipe = {}) => {
    const url = new URL(requestUrl);
    const prefix = recipe.prefix ?? '9e2c';
    const suffix = recipe.suffix ?? '11ac';
    const pathTailLength = recipe.pathTailLength ?? 7;
    const deviceTime = Math.floor(Date.now() / 1000).toString();
    const raw = `${prefix}|${url.pathname.slice(-pathTailLength)}|${platformId}|${appVersion}|${deviceTime}|${tdid}|${suffix}`;
    return {
        sign: node_crypto_1.default.createHash('md5').update(raw).digest('hex').toLowerCase(),
        deviceTime,
    };
};
exports.createEditApiSignature = createEditApiSignature;
/**
 * edit-api ドメイン向けの共通リクエスト
 */
const request = async ({ requester, path, searchParams = {}, method = 'POST', headers, body, }) => requester(resolveUrl(path, searchParams), {
    method,
    headers,
    body,
});
exports.CapCutEditApiClient = {
    resolveUrl,
    request,
};
//# sourceMappingURL=apiClient.js.map