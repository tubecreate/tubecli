import type { Request, Response } from 'express';
import { apiError, ErrorCode } from '@/lib/apiError';
import { extractRequestCredentials } from '@/lib/capcut/requestCredentials';
import { getCapCutService } from '@/services/CapCutService';
import logger from '@/services/logger';

/**
 * クエリから単一文字列を取り出す
 */
const singleQueryValue = (value: unknown): string | undefined => {
  const raw = Array.isArray(value) ? value[0] : value;

  if (typeof raw !== 'string') {
    return undefined;
  }

  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

/**
 * ### get
 * `/v2/speakers` を処理する
 *
 * `?language=vi` `?country=vn` `?category=vietnamese` で絞り込める
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
export const get = async (req: Request, res: Response): Promise<void> => {
  const language =
    singleQueryValue(req.query.language) ?? singleQueryValue(req.query.country);
  const category = singleQueryValue(req.query.category);

  const capCutService = getCapCutService(
    extractRequestCredentials({
      headers: req.headers as Record<string, unknown>,
      query: req.query as Record<string, unknown>,
    })
  );

  try {
    const speakers = await capCutService.listSpeakers({ language, category });
    res.status(200).json(speakers);
  } catch (error) {
    logger.error('Failed to fetch CapCut speakers', error);
    throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to fetch CapCut speakers');
  }
};
