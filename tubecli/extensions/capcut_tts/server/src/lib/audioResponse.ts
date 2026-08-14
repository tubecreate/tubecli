import type { Response } from 'express';
import type { AudioResult, AudioStreamResult } from '@/types/capcut';

const applyAudioHeaders = (
  res: Response,
  audio: Pick<AudioResult, 'contentLength' | 'fileName'>
): void => {
  if (audio.contentLength) {
    res.setHeader('Content-Length', audio.contentLength);
  }

  if (audio.fileName) {
    res.setHeader(
      'Content-Disposition',
      `inline; filename="${audio.fileName}"`
    );
  }
};

/**
 * ### sendAudioBufferResponse
 * バッファ取得済みの音声レスポンスを返す
 *
 * @param res - Express レスポンス
 * @param audioResult - 返却する音声
 */
export const sendAudioBufferResponse = (
  res: Response,
  audioResult: AudioResult
): void => {
  applyAudioHeaders(res, audioResult);
  res.type(audioResult.contentType).status(200).end(audioResult.buffer);
};

/**
 * ### sendAudioStreamResponse
 * ストリーム音声レスポンスを返す
 *
 * @param res - Express レスポンス
 * @param audioStreamResult - 返却する音声ストリーム
 * @param onStreamError - ストリーム中断時の処理
 */
export const sendAudioStreamResponse = (
  res: Response,
  audioStreamResult: AudioStreamResult,
  onStreamError: (error: Error) => void
): void => {
  audioStreamResult.stream.on('error', onStreamError);

  res.on('close', () => {
    if (!audioStreamResult.stream.destroyed) {
      audioStreamResult.stream.destroy();
    }
  });

  applyAudioHeaders(res, audioStreamResult);
  res.status(200);
  res.type(audioStreamResult.contentType);
  audioStreamResult.stream.pipe(res);
};

/**
 * 単語タイムスタンプ付きレスポンスへ整形する
 */
export const toMarkedResponse = (
  result: {
    audio: Buffer;
    text: string;
    duration: number | null;
    words: Array<{ word: string; start: number; end: number }>;
    phonemes: Array<{ phone: string; start: number; end: number }>;
  },
  includePhonemes: boolean
) => ({
  text: result.text,
  duration: result.duration,
  contentType: 'audio/mpeg',
  byteLength: result.audio.byteLength,
  audio: result.audio.toString('base64'),
  words: result.words,
  ...(includePhonemes ? { phonemes: result.phonemes } : {}),
});
