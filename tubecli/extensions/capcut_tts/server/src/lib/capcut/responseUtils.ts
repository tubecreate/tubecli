import { getResponseBodySnippet, parseJson } from '@/utils/httpUtils';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const asString = (value: unknown): string | null => {
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
export class CapCutApiError extends Error {
  statusCode?: number;

  errorCode?: number;

  descUrl?: string;

  constructor(
    message: string,
    options: {
      statusCode?: number;
      errorCode?: number;
      descUrl?: string;
      cause?: unknown;
    } = {}
  ) {
    super(message, { cause: options.cause });
    this.name = 'CapCutApiError';
    this.statusCode = options.statusCode;
    this.errorCode = options.errorCode;
    this.descUrl = options.descUrl;
  }
}

/**
 * JSON 文字列の中身が object なら返す
 */
export const parseNestedJsonRecord = (
  value: unknown
): Record<string, unknown> | null => {
  if (typeof value !== 'string' || !value) {
    return null;
  }

  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
};

/**
 * CapCut の共通 payload を unwrap する
 */
export const unwrapPayload = <T>(raw: unknown, context: string): T => {
  if (!isRecord(raw)) {
    throw new Error(`${context} returned an unexpected payload`);
  }

  const nestedData = isRecord(raw.data) ? raw.data : null;
  const errorCodeValue =
    typeof nestedData?.error_code === 'number'
      ? nestedData.error_code
      : typeof raw.error_code === 'number'
        ? raw.error_code
        : undefined;
  const descUrlValue =
    asString(nestedData?.desc_url) ?? asString(raw.desc_url) ?? undefined;
  const failureMessage =
    asString(raw.description) ??
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
    return raw.data as T;
  }

  return raw as T;
};

/**
 * Response を text → json → payload unwrap まで処理する
 */
export const unwrapJsonResponse = async <T>(
  response: Response,
  context: string
) => {
  const body = await response.text();

  if (!response.ok) {
    throw new CapCutApiError(
      `${context} failed: ${response.status} ${response.statusText} ${getResponseBodySnippet(
        body
      )}`,
      {
        statusCode: response.status,
      }
    );
  }

  return unwrapPayload<T>(parseJson(body, context), context);
};
