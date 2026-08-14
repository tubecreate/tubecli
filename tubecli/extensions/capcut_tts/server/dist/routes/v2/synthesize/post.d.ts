import type { NextFunction, Request, Response } from 'express';
/**
 * ### post
 * `/v2/synthesize` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - NextFunction
 */
export declare const post: (req: Request, res: Response, next: NextFunction) => Promise<void>;
