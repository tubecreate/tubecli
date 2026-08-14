/**
 * 読み出したセッション行
 */
export interface SessionRecord {
    payload: string;
    version: number;
    expiresAt: number;
    lockUntil: number;
    failUntil: number;
}
/**
 * セッションの保管先
 *
 * 複数 isolate から同時に触られる前提で、
 * 書き込みは version 一致時のみ、ログインは lock を取れた 1 つだけが行う
 */
export interface SessionStore {
    read(accountKey: string): Promise<SessionRecord | null>;
    /** version が一致したときだけ書く 一致しなければ false */
    write(accountKey: string, payload: string, expiresAt: number, expectedVersion: number | null): Promise<boolean>;
    /** ログイン権を取る 取れたら true */
    acquireLock(accountKey: string, lockMs: number): Promise<boolean>;
    releaseLock(accountKey: string): Promise<void>;
    /** ログイン失敗を記録し、全 isolate を一定時間止める */
    markLoginFailure(accountKey: string, backoffMs: number): Promise<void>;
}
/**
 * Workers が渡してくる D1 の最小インターフェース
 */
export interface D1Like {
    prepare(query: string): {
        bind(...values: unknown[]): {
            first<T = unknown>(): Promise<T | null>;
            all<T = unknown>(): Promise<{
                results?: T[];
            }>;
            run(): Promise<{
                meta?: {
                    changes?: number;
                };
            }>;
        };
    };
}
/**
 * D1 上のセッションストア
 *
 * 1 アカウント 1 行 同時実行は version と lock_until で捌く
 */
export declare class D1SessionStore implements SessionStore {
    private readonly db;
    constructor(db: D1Like);
    read(accountKey: string): Promise<SessionRecord | null>;
    write(accountKey: string, payload: string, expiresAt: number, expectedVersion: number | null): Promise<boolean>;
    /**
     * ログイン権を取る
     *
     * 行が無ければ作ってから取る 期限切れの lock は奪ってよい
     */
    acquireLock(accountKey: string, lockMs: number): Promise<boolean>;
    markLoginFailure(accountKey: string, backoffMs: number): Promise<void>;
    releaseLock(accountKey: string): Promise<void>;
}
export declare const setSessionStore: (next: SessionStore | null) => void;
/**
 * セッションストアを返す 未設定なら null
 * null のときは従来どおり BlobStorage へ保存する
 */
export declare const getSessionStore: () => SessionStore | null;
