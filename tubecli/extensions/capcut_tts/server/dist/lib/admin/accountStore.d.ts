import type { D1Like } from '../../lib/storage/sessionStore';
/**
 * 管理 UI へ返すアカウント 資格情報は含めない
 */
export interface AccountSummary {
    email: string;
    label: string;
    enabled: boolean;
    createdAt: number;
    lastUsedAt: number;
    lastError: string;
    /** セッションの状態 未ログインなら null */
    session: {
        version: number;
        bytes: number;
        expiresAt: number;
        lockedUntil: number;
        failUntil: number;
    } | null;
}
/**
 * CapCutService が使うセッションキーと同じ規則
 * 変えると既存セッションと紐付かなくなる
 */
export declare const sessionKeyFor: (email: string, basePath: string) => string;
/**
 * 管理 UI 用のアカウント台帳
 */
export declare class AccountStore {
    private readonly db;
    private readonly encKey;
    private readonly sessionBasePath;
    constructor(db: D1Like, encKey: string, sessionBasePath: string);
    /**
     * セッション状態を突き合わせて一覧を返す
     */
    list(): Promise<AccountSummary[]>;
    private toSummary;
    add(email: string, password: string, label: string): Promise<void>;
    remove(email: string): Promise<void>;
    setEnabled(email: string, enabled: boolean): Promise<void>;
    /**
     * セッションを捨てて次回ログインし直させる
     * backoff も解除するので、様子見待ちを飛ばせる
     */
    resetSession(email: string): Promise<void>;
    clearBackoff(email: string): Promise<void>;
    /**
     * 資格情報を取り出す 合成を実行するときだけ使う
     */
    credentialsFor(email: string): Promise<{
        email: string;
        password: string;
    } | null>;
    recordUsage(email: string, error: string): Promise<void>;
}
