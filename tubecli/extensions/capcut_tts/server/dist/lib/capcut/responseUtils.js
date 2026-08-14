"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.unwrapJsonResponse = exports.unwrapPayload = exports.parseNestedJsonRecord = exports.CapCutApiError = void 0;
const httpUtils_1 = require("../../utils/httpUtils");
const isRecord = (value) => typeof value === 'object' && value !== null;
const asString = (value) => {
    if (typeof value === 'string') {
        return value;
    }
    if (typeof value === 'number' || typeof value === 'bigint') {
        return String(value);
    }
    return null;
};
/**
 * CapCut API 応答の失敗を表すエラー
 */
class CapCutApiError extends Error {
    statusCode;
    errorCode;
    descUrl;
    constructor(message, options = {}) {
        super(message, { cause: options.cause });
        this.name = 'CapCutApiError';
        this.statusCode = options.statusCode;
        this.errorCode = options.errorCode;
        this.descUrl = options.descUrl;
    }
}
exports.CapCutApiError = CapCutApiError;
/**
 * JSON 文字列の中身が object なら返す
 */
const parseNestedJsonRecord = (value) => {
    if (typeof value !== 'string' || !value) {
        return null;
    }
    try {
        const parsed = JSON.parse(value);
        return isRecord(parsed) ? parsed : null;
    }
    catch {
        return null;
    }
};
exports.parseNestedJsonRecord = parseNestedJsonRecord;
/**
 * CapCut の共通 payload を unwrap する
 */
const unwrapPayload = (raw, context) => {
    if (!isRecord(raw)) {
        throw new Error(`${context} returned an unexpected payload`);
    }
    const nestedData = isRecord(raw.data) ? raw.data : null;
    const errorCodeValue = typeof nestedData?.error_code === 'number'
        ? nestedData.error_code
        : typeof raw.error_code === 'number'
            ? raw.error_code
            : undefined;
    const descUrlValue = asString(nestedData?.desc_url) ?? asString(raw.desc_url) ?? undefined;
    const failureMessage = asString(raw.description) ??
        asString(nestedData?.description) ??
        asString(nestedData?.desc_url) ??
        asString(raw.errmsg) ??
        asString(raw.message) ??
        context;
    if (raw.ret !== undefined && raw.ret !== '0' && raw.ret !== 0) {
        throw new CapCutApiError(`${context} failed: ${failureMessage}`, {
            errorCode: errorCodeValue,
            descUrl: descUrlValue,
        });
    }
    if (raw.message !== undefined && raw.message !== 'success') {
        throw new CapCutApiError(`${context} failed: ${failureMessage}`, {
            errorCode: errorCodeValue,
            descUrl: descUrlValue,
        });
    }
    if (isRecord(raw.data) || Array.isArray(raw.data)) {
        return raw.data;
    }
    return raw;
};
exports.unwrapPayload = unwrapPayload;
/**
 * Response を text → json → payload unwrap まで処理する
 */
const unwrapJsonResponse = async (response, context) => {
    const body = await response.text();
    if (!response.ok) {
        throw new CapCutApiError(`${context} failed: ${response.status} ${response.statusText} ${(0, httpUtils_1.getResponseBodySnippet)(body)}`, {
            statusCode: response.status,
        });
    }
    return (0, exports.unwrapPayload)((0, httpUtils_1.parseJson)(body, context), context);
};
exports.unwrapJsonResponse = unwrapJsonResponse;
//# sourceMappingURL=responseUtils.js.map