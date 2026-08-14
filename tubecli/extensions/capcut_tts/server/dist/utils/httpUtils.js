"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getResponseBodySnippet = exports.parseJson = void 0;
/**
 * JSON 文字列を安全に parse する
 */
const parseJson = (text, context) => {
    try {
        return JSON.parse(text);
    }
    catch (error) {
        throw new Error(`${context} returned invalid JSON`, {
            cause: error,
        });
    }
};
exports.parseJson = parseJson;
/**
 * 長すぎるレスポンス本文をログ向けに短縮する
 */
const getResponseBodySnippet = (body) => body.length > 400 ? `${body.slice(0, 400)}...` : body;
exports.getResponseBodySnippet = getResponseBodySnippet;
//# sourceMappingURL=httpUtils.js.map