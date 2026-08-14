import type { NextFunction, Request, Response } from 'express';
import { ApiError, ErrorCode } from '@/lib/apiError';
import logger from '@/services/logger';

/**
 * ### errorHandler
 * 例外を API 共通のエラーレスポンスへ正規化する
 *
 * @param err - 発生した例外
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export const errorHandler = (
  err: unknown,
  req: Request,
  res: Response,
  next: NextFunction
): void => {
  void req;

  if (res.headersSent) {
    next(err);
    return;
  }

  if (err instanceof ApiError) {
    if (err.isExpected) {
      logger.warn(`ApiError: ${err.code} - ${err.message}`);
    } else {
      logger.error(`ApiError: ${err.code}`, err);
    }

    res.status(err.statusCode).json(err.toResponse());
    return;
  }

  logger.error('Unexpected error', err);
  res.status(500).json({
    code: ErrorCode.INTERNAL_SERVER_ERROR,
    message: 'Internal server error',
  });
};
