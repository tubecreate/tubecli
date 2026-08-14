import type { NextFunction, Request, Response } from 'express';
import {
  sendAudioBufferResponse,
  sendAudioStreamResponse,
  toMarkedResponse,
} from '@/lib/audioResponse';
import { apiError, ErrorCode } from '@/lib/apiError';
import { CapCutApiError } from '@/lib/capcut/responseUtils';
import { SynthesizeQuerySchema } from '@/schemas/synthesize';
import { extractRequestCredentials } from '@/lib/capcut/requestCredentials';
import { getCapCutService } from '@/services/CapCutService';
import logger from '@/services/logger';

/**
 * ### get
 * `/v2/synthesize` を処理する
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
  const synthesizeQueryValidation = SynthesizeQuerySchema.safeParse(req.query);

  if (!synthesizeQueryValidation.success) {
    throw apiError(
      ErrorCode.VALIDATION_ERROR,
      synthesizeQueryValidation.error.issues
    );
  }

  const synthesizeQuery = synthesizeQueryValidation.data;
  const capCutService = getCapCutService(
    extractRequestCredentials({
      headers: req.headers as Record<string, unknown>,
      query: req.query as Record<string, unknown>,
    })
  );

  if (synthesizeQuery.timestamps) {
    try {
      const marked = await capCutService.synthesizeWithMarks(synthesizeQuery);
      res.status(200).json(
        toMarkedResponse(marked, synthesizeQuery.phonemes ?? false)
      );
      return;
    } catch (error) {
      if (error instanceof CapCutApiError && error.statusCode === 400) {
        throw apiError(ErrorCode.BAD_GATEWAY, error.message);
      }

      logger.error('Failed to synthesize audio with timestamps', error);
      throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
    }
  }

  if (synthesizeQuery.method === 'stream') {
    try {
      const audioStream = await capCutService.synthesizeStream(synthesizeQuery);

      sendAudioStreamResponse(res, audioStream, (error: Error) => {
        logger.error('Failed to synthesize audio stream', error);

        if (!res.headersSent) {
          next(apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio'));
          return;
        }

        res.end();
      });
      return;
    } catch (error) {
      logger.error('Failed to synthesize audio stream', error);
      throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
    }
  }

  try {
    const audioResult = await capCutService.synthesizeBuffer(synthesizeQuery);
    sendAudioBufferResponse(res, audioResult);
  } catch (error) {
    logger.error('Failed to synthesize audio', error);
    throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
  }
};
