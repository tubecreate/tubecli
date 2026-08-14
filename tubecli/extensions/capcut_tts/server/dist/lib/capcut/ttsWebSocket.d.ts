/**
 * 単語レベルのタイムスタンプ
 */
export interface WordMark {
    word: string;
    /** 秒 */
    start: number;
    /** 秒 */
    end: number;
}
/**
 * 音素レベルのタイムスタンプ 単語より細かい
 */
export interface PhonemeMark {
    phone: string;
    start: number;
    end: number;
}
/**
 * WebSocket 経路の合成結果
 */
export interface TtsWebSocketResult {
    audio: Buffer;
    text: string;
    duration: number | null;
    words: WordMark[];
    phonemes: PhonemeMark[];
}
export interface TtsWebSocketOptions {
    text: string;
    speaker: string;
    tokenUrl: string;
    wsUrl: string;
    appId: string;
    appVersion: string;
    platformId: string;
    signVersion: string;
    sampleRate: number;
    userAgent: string;
    origin: string;
    /** 音素まで返すか 単語だけで足りるなら false */
    includePhonemes?: boolean;
    timeoutMs?: number;
}
/**
 * SAMI 用の短命トークンを取る
 * Cookie もログインも要らないので、セッションと独立に動く
 */
export declare const fetchTtsToken: (options: {
    tokenUrl: string;
    appVersion: string;
    platformId: string;
    signVersion: string;
    userAgent: string;
    origin: string;
}) => Promise<{
    token: string;
    appKey: string;
}>;
/**
 * WebSocket 経路で合成し、単語タイムスタンプまで受け取る
 *
 * REST 経路は caption を返さない (draft_info.subtitle_list が常に null) が
 * こちらは合成エンジンが出した alignment をそのまま返してくる
 * enable_text_seg と internal を送らないと alignment が空になる
 */
export declare const synthesizeWithTimestamps: (options: TtsWebSocketOptions) => Promise<TtsWebSocketResult>;
