import type { Request, Response } from 'express';
import { apiError, ErrorCode } from '@/lib/apiError';
import capCutService from '@/services/CapCutService';
import logger from '@/services/logger';

/**
 * ### get
 * `/v2/languages` を処理する
 *
 * 利用可能な言語コードと該当話者数を返す
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
export const get = async (req: Request, res: Response): Promise<void> => {
  void req;

  try {
    const languages = await capCutService.listSpeakerLanguages();
    res.status(200).json(languages);
  } catch (error) {
    logger.error('Failed to fetch CapCut speaker languages', error);
    throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to fetch speaker languages');
  }
};
