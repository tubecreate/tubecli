"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.extractFirst = exports.extractStringAssignment = exports.extractVersionStrings = exports.extractScriptUrlsFromHtml = exports.escapeRegExp = void 0;
/**
 * bundle 解析に使うユーティリティ
 */
const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
exports.escapeRegExp = escapeRegExp;
/**
 * HTML から script src を抽出する
 */
const extractScriptUrlsFromHtml = (html) => Array.from(html.matchAll(/<script[^>]+src="([^"]+)"/g), (match) => match[1]);
exports.extractScriptUrlsFromHtml = extractScriptUrlsFromHtml;
/**
 * バージョンっぽい文字列を重複なく返す
 */
const extractVersionStrings = (text) => Array.from(new Set(text.match(/\b\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?\b/g) ?? []));
exports.extractVersionStrings = extractVersionStrings;
/**
 * 変数代入から文字列値を探す
 */
const extractStringAssignment = (text, variableName) => {
    const escapedVariableName = (0, exports.escapeRegExp)(variableName);
    const pattern = new RegExp(`(?:let|const|var)\\s+${escapedVariableName}\\s*=\\s*["']([^"']+)["']`);
    return text.match(pattern)?.[1];
};
exports.extractStringAssignment = extractStringAssignment;
/**
 * 正規表現にヒットした最初の文字列を返す
 */
const extractFirst = (text, pattern) => text.match(pattern)?.[1];
exports.extractFirst = extractFirst;
//# sourceMappingURL=bundleExtractionUtils.js.map