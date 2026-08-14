"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.toMarkedResponse = exports.sendAudioStreamResponse = exports.sendAudioBufferResponse = void 0;
const applyAudioHeaders = (res, audio) => {
    if (audio.contentLength) {
        res.setHeader('Content-Length', audio.contentLength);
    }
    if (audio.fileName) {
        res.setHeader('Content-Disposition', `inline; filename="${audio.fileName}"`);
    }
};
/**
 * ### sendAudioBufferResponse
 * バッファ取得済みの音声レスポンスを返す
 *
 * @param res - Express レスポンス
 * @param audioResult - 返却する音声
 */
const sendAudioBufferResponse = (res, audioResult) => {
    applyAudioHeaders(res, audioResult);
    res.type(audioResult.contentType).status(200).end(audioResult.buffer);
};
exports.sendAudioBufferResponse = sendAudioBufferResponse;
/**
 * ### sendAudioStreamResponse
 * ストリーム音声レスポンスを返す
 *
 * @param res - Express レスポンス
 * @param audioStreamResult - 返却する音声ストリーム
 * @param onStreamError - ストリーム中断時の処理
 */
const sendAudioStreamResponse = (res, audioStreamResult, onStreamError) => {
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
exports.sendAudioStreamResponse = sendAudioStreamResponse;
/**
 * 単語タイムスタンプ付きレスポンスへ整形する
 */
const toMarkedResponse = (result, includePhonemes) => ({
    text: result.text,
    duration: result.duration,
    contentType: 'audio/mpeg',
    byteLength: result.audio.byteLength,
    audio: result.audio.toString('base64'),
    words: result.words,
    ...(includePhonemes ? { phonemes: result.phonemes } : {}),
});
exports.toMarkedResponse = toMarkedResponse;
//# sourceMappingURL=audioResponse.js.map