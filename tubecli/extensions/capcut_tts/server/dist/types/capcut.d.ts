import type { Readable } from 'node:stream';
/**
 * 音声合成リクエストの入力
 */
export interface SynthesizeOptions {
    text: string;
    type: number | string;
    speaker?: string;
    pitch: number;
    speed: number;
    volume: number;
    /** カタログ外の voice ID を使うときに指定する engine 例 11labs */
    platform?: string;
    /** 単語タイムスタンプ付きで返す WebSocket 経路を使う */
    timestamps?: boolean;
    /** 音素レベルのタイムスタンプまで返す timestamps と併用する */
    phonemes?: boolean;
}
/**
 * 音声プリセットの内部表現
 */
export interface Speaker {
    title: string;
    description: string;
    speaker: string;
    effectId: string;
    resourceId: string;
    style?: string;
    language?: string;
    /** 取得元カテゴリの category_key 群 例 vietnamese english */
    categories?: string[];
    /** tonetype.platform 例 11labs 未指定なら CapCut 既定エンジン */
    platform?: string;
}
/**
 * /speakers エンドポイントで返す話者
 */
export interface SpeakerInfo {
    id: string;
    resourceId: string;
    effectId: string;
    name: string;
    description: string;
    style: string;
    language: string;
    categories: string[];
    /** 読み上げエンジン 例 11labs 未指定なら CapCut 既定 */
    platform: string;
}
/**
 * 話者一覧の絞り込み条件
 */
export interface SpeakerFilter {
    /** ISO 639-1 相当の言語コード 例 vi en ja */
    language?: string;
    /** CapCut のカテゴリキー 例 vietnamese female_voice */
    category?: string;
}
/**
 * CapCut ログイン済みセッション
 */
export interface CapCutSessionState {
    userId: string;
    screenName: string;
    workspaceId: string;
    loginHost: string;
    verifyFp: string;
    deviceId: string;
    loggedInAt: number;
    verifiedAt: number;
}
/**
 * バッファ取得時の音声レスポンス
 */
export interface AudioResult {
    buffer: Buffer;
    contentType: string;
    contentLength?: string;
    fileName?: string;
}
/**
 * ストリーム取得時の音声レスポンス
 */
export interface AudioStreamResult {
    stream: Readable;
    contentType: string;
    contentLength?: string;
    fileName?: string;
}
