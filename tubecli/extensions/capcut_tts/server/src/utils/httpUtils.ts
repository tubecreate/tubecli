/**
 * JSON 文字列を安全に parse する
 */
export const parseJson = (text: string, context: string): unknown => {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${context} returned invalid JSON`, {
      cause: error,
    });
  }
};

/**
 * 長すぎるレスポンス本文をログ向けに短縮する
 */
export const getResponseBodySnippet = (body: string) =>
  body.length > 400 ? `${body.slice(0, 400)}...` : body;
