import type { ZodIssue } from 'zod';

export const ErrorCode = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  FORBIDDEN: 'FORBIDDEN',
  BAD_GATEWAY: 'BAD_GATEWAY',
  SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
  INTERNAL_SERVER_ERROR: 'INTERNAL_SERVER_ERROR',
} as const;

export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

export type ValidationErrorDetails = ZodIssue[];

type ValidationErrorResponse = {
  code: typeof ErrorCode.VALIDATION_ERROR;
  message: string;
  details: ValidationErrorDetails;
};

export type ErrorResponse = {
  code: Exclude<ErrorCode, typeof ErrorCode.VALIDATION_ERROR>;
  message: string;
};

export type ApiErrorResponse = ValidationErrorResponse | ErrorResponse;

/**
 * # ApiError
 * API レスポンスとして返す情報を保持する共通エラー
 *
 * ### 特徴
 * - HTTP ステータスとエラーコードを一元管理する
 * - バリデーション失敗時だけ details を返す
 */
export class ApiError extends Error {
  public readonly statusCode: number;

  public readonly code: ErrorCode;

  public readonly details?: ValidationErrorDetails;

  public readonly isExpected: boolean;

  public constructor(
    statusCode: number,
    code: ErrorCode,
    message: string,
    details?: ValidationErrorDetails,
    isExpected = true
  ) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.code = code;
    this.details =
      code === ErrorCode.VALIDATION_ERROR ? details : undefined;
    this.isExpected = isExpected;
  }

  /**
   * ### toResponse
   * クライアントへ返すエラー JSON を生成する
   *
   * @returns API 共通エラーレスポンス
   */
  public toResponse(): ApiErrorResponse {
    if (this.code === ErrorCode.VALIDATION_ERROR) {
      return {
        code: ErrorCode.VALIDATION_ERROR,
        message: this.message,
        details: this.details ?? [],
      };
    }

    return {
      code: this.code,
      message: this.message,
    };
  }
}

type ApiErrorArgs = {
  [ErrorCode.VALIDATION_ERROR]: [details: ValidationErrorDetails];
  [ErrorCode.NOT_FOUND]: [resource?: string];
  [ErrorCode.FORBIDDEN]: [message?: string];
  [ErrorCode.BAD_GATEWAY]: [message?: string];
  [ErrorCode.SERVICE_UNAVAILABLE]: [message?: string];
  [ErrorCode.INTERNAL_SERVER_ERROR]: [message?: string];
};

type ApiErrorBuilderMap = {
  [K in ErrorCode]: (...args: ApiErrorArgs[K]) => ApiError;
};

// message と status code の揺れを防ぐため、生成口をここへ寄せる
const apiErrorBuilders: ApiErrorBuilderMap = {
  [ErrorCode.VALIDATION_ERROR]: (details: ValidationErrorDetails) =>
    new ApiError(
      400,
      ErrorCode.VALIDATION_ERROR,
      'Validation failed',
      details,
      true
    ),
  [ErrorCode.NOT_FOUND]: (resource = 'Resource') =>
    new ApiError(
      404,
      ErrorCode.NOT_FOUND,
      `${resource} not found`,
      undefined,
      true
    ),
  [ErrorCode.FORBIDDEN]: (message = 'Forbidden') =>
    new ApiError(403, ErrorCode.FORBIDDEN, message, undefined, true),
  [ErrorCode.BAD_GATEWAY]: (message = 'Bad gateway') =>
    new ApiError(502, ErrorCode.BAD_GATEWAY, message, undefined, true),
  [ErrorCode.SERVICE_UNAVAILABLE]: (
    message = 'Service unavailable'
  ) =>
    new ApiError(
      503,
      ErrorCode.SERVICE_UNAVAILABLE,
      message,
      undefined,
      true
    ),
  [ErrorCode.INTERNAL_SERVER_ERROR]: (
    message = 'Internal server error'
  ) =>
    new ApiError(
      500,
      ErrorCode.INTERNAL_SERVER_ERROR,
      message,
      undefined,
      false
    ),
};

/**
 * ### apiError
 * エラーコードに対応した API エラーを生成する
 *
 * @param code - エラー種別
 * @param args - エラーコードごとの追加情報
 * @returns 共通 API エラー
 */
export const apiError = <K extends ErrorCode>(
  code: K,
  ...args: ApiErrorArgs[K]
): ApiError => {
  const builder = apiErrorBuilders[code];
  return builder(...args);
};
