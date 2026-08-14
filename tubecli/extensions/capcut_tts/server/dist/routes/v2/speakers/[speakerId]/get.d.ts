import type { NextFunction, Request, Response } from 'express';
/**
 * ### get
 * `/v2/speakers/:speakerId/preview` のプレビュー音声取得を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export declare const get: (req: Request, res: Response, next: NextFunction) => Promise<void>;
