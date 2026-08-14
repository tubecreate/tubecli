import type { NextFunction, Request, Response } from 'express';
/**
 * リクエストとレスポンス時間をログへ出す
 */
export declare const loggerMiddleware: (req: Request, res: Response, next: NextFunction) => void;
