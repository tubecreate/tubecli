import type { StoredCookie } from '../../types/capcutSession';
/**
 * CapCut 用の最小 CookieJar
 * fetch ベースでログインセッションを維持するために使う
 */
export declare class CookieJar {
    private readonly cookies;
    /**
     * すべての Cookie を破棄する
     */
    clear(): void;
    /**
     * 永続化済み Cookie を復元する
     */
    hydrate(cookies: StoredCookie[]): void;
    /**
     * 永続化用の Cookie 一覧を返す
     */
    serialize(): StoredCookie[];
    /**
     * Cookie を手動で投入する
     */
    set(name: string, value: string, domain: string, path?: string, hostOnly?: boolean): void;
    /**
     * 条件に合う Cookie 値を取得する
     */
    get(name: string, url?: string): string | null;
    /**
     * 指定 URL に送る Cookie ヘッダーを構築する
     */
    getCookieHeader(url: string): string;
    /**
     * レスポンスの Set-Cookie を保存する
     */
    storeFromResponse(response: Response, requestUrl: string): void;
    /**
     * Set-Cookie をパースして内部保存する
     * Domain Path Expires Max-Age だけを見れば今回の用途では十分
     */
    private store;
    /**
     * Set-Cookie に Path がないときの既定値を返す
     */
    private defaultPath;
    /**
     * URL に対して Cookie が送信可能かを判定する
     * hostOnly と domain 属性の差をここで吸収している
     */
    private matches;
}
