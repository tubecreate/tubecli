import type { NextFunction, Request, Response } from 'express';
import { apiError, ErrorCode } from '@/lib/apiError';

/**
 * ### fallback
 * `/v2` 配下の未定義 route を 404 として扱う
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
  void req;
  void res;
  next(apiError(ErrorCode.NOT_FOUND));
};
