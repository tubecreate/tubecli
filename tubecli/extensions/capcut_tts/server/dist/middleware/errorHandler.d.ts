import type { NextFunction, Request, Response } from 'express';
/**
 * ### errorHandler
 * 例外を API 共通のエラーレスポンスへ正規化する
 *
 * @param err - 発生した例外
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export declare const errorHandler: (err: unknown, req: Request, res: Response, next: NextFunction) => void;
