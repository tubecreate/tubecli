/**
 * bundle 解析に使うユーティリティ
 */
export const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * HTML から script src を抽出する
 */
export const extractScriptUrlsFromHtml = (html: string) =>
  Array.from(html.matchAll(/<script[^>]+src="([^"]+)"/g), (match) => match[1]);

/**
 * バージョンっぽい文字列を重複なく返す
 */
export const extractVersionStrings = (text: string) =>
  Array.from(new Set(text.match(/\b\d+\.\d+\.\d+(?:-[A-Za-z0-9._-]+)?\b/g) ?? []));

/**
 * 変数代入から文字列値を探す
 */
export const extractStringAssignment = (text: string, variableName: string) => {
  const escapedVariableName = escapeRegExp(variableName);
  const pattern = new RegExp(
    `(?:let|const|var)\\s+${escapedVariableName}\\s*=\\s*["']([^"']+)["']`
  );
  return text.match(pattern)?.[1];
};

/**
 * 正規表現にヒットした最初の文字列を返す
 */
export const extractFirst = (text: string, pattern: RegExp) => text.match(pattern)?.[1];
