import type { NextFunction, Request, Response } from 'express';
import { apiError, ErrorCode } from '@/lib/apiError';

/**
 * ### fallback
 * `/v2` 以外へのアクセスを拒否する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export const fallback = (
  req: Request,
  res: Response,
  next: NextFunction
): void => {
  next(apiError(ErrorCode.FORBIDDEN));
};
