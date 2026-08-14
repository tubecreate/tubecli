import type { NextFunction, Request, Response } from 'express';
import {
  sendAudioBufferResponse,
  sendAudioStreamResponse,
} from '@/lib/audioResponse';
import { apiError, ErrorCode } from '@/lib/apiError';
import { LegacySynthesizeQuerySchema } from '@/schemas/legacySynthesize';
import legacyCapCutService from '@/services/LegacyCapCutService';
import logger from '@/services/logger';

const legacyNotConfiguredMessage =
  'Legacy CapCut endpoint is not configured. Set LEGACY_DEVICE_TIME and LEGACY_SIGN';

/**
 * ### get
 * `/v1/synthesize` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - NextFunction
 */
export const get = async (
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> => {
  const synthesizeQueryValidation = LegacySynthesizeQuerySchema.safeParse(
    req.query
  );

  if (!synthesizeQueryValidation.success) {
    throw apiError(
      ErrorCode.VALIDATION_ERROR,
      synthesizeQueryValidation.error.issues
    );
  }

  if (!legacyCapCutService.isConfigured()) {
    throw apiError(ErrorCode.SERVICE_UNAVAILABLE, legacyNotConfiguredMessage);
  }

  const synthesizeQuery = synthesizeQueryValidation.data;

  if (synthesizeQuery.method === 'stream') {
    try {
      const audioStream =
        await legacyCapCutService.synthesizeStream(synthesizeQuery);

      sendAudioStreamResponse(res, audioStream, (error: Error) => {
        logger.error('Failed to synthesize legacy audio stream', error);

        if (!res.headersSent) {
          next(
            apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize legacy audio')
          );
          return;
        }

        res.end();
      });
      return;
    } catch (error) {
      logger.error('Failed to synthesize legacy audio stream', error);
      throw apiError(
        ErrorCode.BAD_GATEWAY,
        'Failed to synthesize legacy audio'
      );
    }
  }

  try {
    const audioResult =
      await legacyCapCutService.synthesizeBuffer(synthesizeQuery);
    sendAudioBufferResponse(res, audioResult);
  } catch (error) {
    logger.error('Failed to synthesize legacy audio', error);
    throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize legacy audio');
  }
};
