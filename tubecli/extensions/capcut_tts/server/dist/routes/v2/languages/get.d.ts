import type { Request, Response } from 'express';
/**
 * ### get
 * `/v2/languages` を処理する
 *
 * 利用可能な言語コードと該当話者数を返す
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
export declare const get: (req: Request, res: Response) => Promise<void>;
