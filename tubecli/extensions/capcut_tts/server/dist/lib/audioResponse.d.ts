import type { Response } from 'express';
import type { AudioResult, AudioStreamResult } from '../types/capcut';
/**
 * ### sendAudioBufferResponse
 * バッファ取得済みの音声レスポンスを返す
 *
 * @param res - Express レスポンス
 * @param audioResult - 返却する音声
 */
export declare const sendAudioBufferResponse: (res: Response, audioResult: AudioResult) => void;
/**
 * ### sendAudioStreamResponse
 * ストリーム音声レスポンスを返す
 *
 * @param res - Express レスポンス
 * @param audioStreamResult - 返却する音声ストリーム
 * @param onStreamError - ストリーム中断時の処理
 */
export declare const sendAudioStreamResponse: (res: Response, audioStreamResult: AudioStreamResult, onStreamError: (error: Error) => void) => void;
/**
 * 単語タイムスタンプ付きレスポンスへ整形する
 */
export declare const toMarkedResponse: (result: {
    audio: Buffer;
    text: string;
    duration: number | null;
    words: Array<{
        word: string;
        start: number;
        end: number;
    }>;
    phonemes: Array<{
        phone: string;
        start: number;
        end: number;
    }>;
}, includePhonemes: boolean) => {
    phonemes?: {
        phone: string;
        start: number;
        end: number;
    }[] | undefined;
    text: string;
    duration: number | null;
    contentType: string;
    byteLength: number;
    audio: string;
    words: {
        word: string;
        start: number;
        end: number;
    }[];
};
