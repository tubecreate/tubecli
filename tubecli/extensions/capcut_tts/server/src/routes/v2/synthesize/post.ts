import type { NextFunction, Request, Response } from 'express';
import {
  sendAudioBufferResponse,
  sendAudioStreamResponse,
  toMarkedResponse,
} from '@/lib/audioResponse';
import { apiError, ErrorCode } from '@/lib/apiError';
import { CapCutApiError } from '@/lib/capcut/responseUtils';
import { SynthesizeBodySchema } from '@/schemas/synthesize';
import { extractRequestCredentials } from '@/lib/capcut/requestCredentials';
import { getCapCutService } from '@/services/CapCutService';
import logger from '@/services/logger';

/**
 * ### post
 * `/v2/synthesize` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 * @param next - NextFunction
 */
export const post = async (
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> => {
  const synthesizeBodyValidation = SynthesizeBodySchema.safeParse(req.body);

  if (!synthesizeBodyValidation.success) {
    throw apiError(
      ErrorCode.VALIDATION_ERROR,
      synthesizeBodyValidation.error.issues
    );
  }

  const synthesizeBody = synthesizeBodyValidation.data;
  const capCutService = getCapCutService(
    extractRequestCredentials({
      headers: req.headers as Record<string, unknown>,
      body: req.body as Record<string, unknown>,
    })
  );

  if (synthesizeBody.timestamps) {
    try {
      const marked = await capCutService.synthesizeWithMarks(synthesizeBody);
      res.status(200).json(
        toMarkedResponse(marked, synthesizeBody.phonemes ?? false)
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

  if (synthesizeBody.method === 'stream') {
    try {
      const audioStream = await capCutService.synthesizeStream(synthesizeBody);

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
    const audioResult = await capCutService.synthesizeBuffer(synthesizeBody);
    sendAudioBufferResponse(res, audioResult);
  } catch (error) {
    logger.error('Failed to synthesize audio', error);
    throw apiError(ErrorCode.BAD_GATEWAY, 'Failed to synthesize audio');
  }
};