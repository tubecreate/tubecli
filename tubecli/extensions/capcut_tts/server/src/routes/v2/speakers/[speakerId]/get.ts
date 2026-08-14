import type { NextFunction, Request, Response } from 'express';
import { apiError, ErrorCode } from '@/lib/apiError';
import capCutService from '@/services/CapCutService';
import logger from '@/services/logger';

/**
 * ### get
 * `/v2/speakers/:speakerId/preview` のプレビュー音声取得を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - 次のミドルウェア
 */
export const get = async (
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> => {
  const rawSpeakerId = req.params.speakerId;
  const speakerId =
    typeof rawSpeakerId === 'string' ? rawSpeakerId.trim() : undefined;

  if (!speakerId) {
    next(apiError(ErrorCode.NOT_FOUND, 'Speaker'));
    return;
  }

  try {
    const audioResult = await capCutService.getSpeakerPreviewAudio(speakerId);

    if (audioResult.contentLength) {
      res.setHeader('Content-Length', audioResult.contentLength);
    }

    if (audioResult.fileName) {
      res.setHeader(
        'Content-Disposition',
        `inline; filename="${audioResult.fileName}"`
      );
    }

    res.type(audioResult.contentType).status(200).end(audioResult.buffer);
  } catch (error) {
    logger.error('Failed to get speaker preview audio', error);
    next(
      apiError(ErrorCode.BAD_GATEWAY, 'Failed to get speaker preview audio')
    );
  }
};
