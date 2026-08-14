import type { NextFunction, Request, Response } from 'express';
/**
 * ### fallback
 * `/v2` 配下の未定義 route を 404 として扱う
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export declare const fallback: (req: Request, res: Response, next: NextFunction) => void;
