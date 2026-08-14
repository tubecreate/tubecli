import type { Request, Response } from 'express';
/**
 * ### get
 * `/v2/speakers` を処理する
 *
 * `?language=vi` `?country=vn` `?category=vietnamese` で絞り込める
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
export declare const get: (req: Request, res: Response) => Promise<void>;
