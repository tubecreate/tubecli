/**
 * CapCut の verifyFp 形式に寄せた識別子を生成する
 */
export declare const createVerifyFp: () => string;
/**
 * CapCut の did として使うデバイス ID を生成する
 */
export declare const createDeviceId: () => string;
/**
 * CapCut の tdid として使うトラッキング ID を生成する
 */
export declare const createTrackingId: () => string;
/**
 * speed パラメータを CapCut の再生速度に変換する
 */
export declare const toPlaybackRate: (speed: number) => number;
/**
 * volume パラメータを CapCut の音量レベルに変換する
 */
export declare const toVolumeLevel: (volume: number) => number;
/**
 * CapCut login SDK が使う XOR5 + hex 変換
 */
export declare const xorFiveHexEncode: (value: string) => string;
/**
 * SHA-256 の hex 文字列を返す
 */
export declare const sha256Hex: (value: string) => string;
/**
 * email をリージョン解決用の正規化形式へ揃える
 */
export declare const normalizeEmailForRegion: (email: string) => string;
/**
 * region 解決用の hashed_id を生成する
 */
export declare const createEmailRegionHash: (email: string) => string;
/**
 * region 解決用の hashed_id を任意 salt で生成する
 */
export declare const createEmailRegionHashWithSalt: (email: string, salt?: string) => string;
/**
 * 秘匿項目だけ XOR5 + hex で包んだ form body を作る
 */
export declare const buildSensitiveFormBody: (values: Record<string, string>, keys: string[]) => string;
/**
 * CapCut がログイン試行回数の上限を返したかを判定する
 *
 * この状態で別 host を試しても通らず、残り試行を減らすだけになる
 * errorCode 7 のほか、文言でも拾えるようにしておく
 */
export declare const isLoginAttemptLimitError: (error: unknown) => boolean;
/**
 * セッション失効らしいエラーかを判定する
 */
export declare const isSessionExpiredError: (error: unknown) => boolean;
