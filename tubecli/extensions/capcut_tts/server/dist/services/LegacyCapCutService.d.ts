import type { AudioResult, AudioStreamResult } from '../types/capcut';
import type { LegacySynthesizeOptions, LegacyTokenState } from '../types/capcutLegacy';
declare class LegacyCapCutService {
    private readonly tokenState;
    private refreshPromise;
    private refreshTimer;
    /**
     * 旧 token + websocket フローに必要な環境変数が揃っているか
     */
    isConfigured(): boolean;
    /**
     * 起動時の事前ウォームアップ
     */
    warmup(): Promise<void>;
    /**
     * 旧 websocket フローで音声をバッファとして取得する
     */
    synthesizeBuffer(options: LegacySynthesizeOptions): Promise<AudioResult>;
    /**
     * 旧 websocket フローで音声をストリームとして取得する
     */
    synthesizeStream(options: LegacySynthesizeOptions): Promise<AudioStreamResult>;
    /**
     * 現在有効な token を返す
     */
    getTokenState(): Promise<LegacyTokenState>;
    /**
     * token を取得し、以降の更新も予約する
     */
    refreshToken(): Promise<LegacyTokenState>;
    /**
     * 起動中のバックグラウンド更新を開始する
     */
    startRefreshTask(): Promise<void>;
    /**
     * 旧 token API を叩く
     */
    private fetchToken;
    /**
     * バッファ用 websocket フロー
     */
    private getAudioBuffer;
    /**
     * ストリーム用 websocket フロー
     */
    private createAudioStream;
    /**
     * websocket に送る StartTask メッセージを作る
     */
    private buildTaskMessage;
    /**
     * websocket の接続先 URL を返す
     */
    private getWebSocketUrl;
    /**
     * token 更新予約を入れ直す
     */
    private scheduleRefresh;
    /**
     * token キャッシュが埋まっているか
     */
    private isTokenReady;
    /**
     * 旧ルートが利用可能かをチェックする
     */
    private assertConfigured;
}
export declare const legacyCapCutService: LegacyCapCutService;
export declare const startLegacyTokenTask: () => Promise<void>;
export default legacyCapCutService;
