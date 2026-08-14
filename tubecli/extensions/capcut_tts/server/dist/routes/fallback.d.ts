import type { NextFunction, Request, Response } from 'express';
/**
 * ### fallback
 * `/v2` 以外へのアクセスを拒否する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export declare const fallback: (req: Request, res: Response, next: NextFunction) => void;
