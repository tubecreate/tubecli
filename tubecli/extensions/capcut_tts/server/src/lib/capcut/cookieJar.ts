import type { StoredCookie } from '@/types/capcutSession';

const getSetCookieHeaders = (response: Response): string[] => {
  const headers = response.headers as Headers & {
    getSetCookie?: () => string[];
  };

  if (typeof headers.getSetCookie === 'function') {
    return headers.getSetCookie();
  }

  const header = response.headers.get('set-cookie');
  return header ? [header] : [];
};

/**
 * CapCut 用の最小 CookieJar
 * fetch ベースでログインセッションを維持するために使う
 */
export class CookieJar {
  private readonly cookies = new Map<string, StoredCookie>();

  /**
   * すべての Cookie を破棄する
   */
  clear() {
    this.cookies.clear();
  }

  /**
   * 永続化済み Cookie を復元する
   */
  hydrate(cookies: StoredCookie[]) {
    this.cookies.clear();

    for (const cookie of cookies) {
      const cookieKey = `${cookie.domain};${cookie.path};${cookie.name}`;
      this.cookies.set(cookieKey, cookie);
    }
  }

  /**
   * 永続化用の Cookie 一覧を返す
   */
  serialize() {
    return Array.from(this.cookies.values());
  }

  /**
   * Cookie を手動で投入する
   */
  set(
    name: string,
    value: string,
    domain: string,
    path = '/',
    hostOnly = false
  ) {
    this.cookies.set(`${domain};${path};${name}`, {
      name,
      value,
      domain,
      path,
      hostOnly,
      secure: true,
    });
  }

  /**
   * 条件に合う Cookie 値を取得する
   */
  get(name: string, url?: string): string | null {
    const now = Date.now();

    for (const cookie of this.cookies.values()) {
      if (cookie.name !== name) {
        continue;
      }

      if (cookie.expiresAt !== undefined && cookie.expiresAt <= now) {
        continue;
      }

      if (!url || this.matches(cookie, new URL(url), now)) {
        return cookie.value;
      }
    }

    return null;
  }

  /**
   * 指定 URL に送る Cookie ヘッダーを構築する
   */
  getCookieHeader(url: string): string {
    const requestUrl = new URL(url);
    const now = Date.now();

    return Array.from(this.cookies.values())
      .filter((cookie) => this.matches(cookie, requestUrl, now))
      .sort((left, right) => right.path.length - left.path.length)
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join('; ');
  }

  /**
   * レスポンスの Set-Cookie を保存する
   */
  storeFromResponse(response: Response, requestUrl: string) {
    for (const setCookieHeader of getSetCookieHeaders(response)) {
      this.store(setCookieHeader, requestUrl);
    }
  }

  /**
   * Set-Cookie をパースして内部保存する
   * Domain Path Expires Max-Age だけを見れば今回の用途では十分
   */
  private store(setCookieHeader: string, requestUrl: string) {
    const request = new URL(requestUrl);
    const parts = setCookieHeader
      .split(';')
      .map((part) => part.trim())
      .filter(Boolean);

    if (parts.length === 0) {
      return;
    }

    const [nameValue, ...attributes] = parts;
    const equalsIndex = nameValue.indexOf('=');

    if (equalsIndex <= 0) {
      return;
    }

    const name = nameValue.slice(0, equalsIndex).trim();
    const value = nameValue.slice(equalsIndex + 1).trim();

    let domain = request.hostname.toLowerCase();
    let path = this.defaultPath(request.pathname);
    let expiresAt: number | undefined;
    let secure = false;
    let hostOnly = true;

    for (const attribute of attributes) {
      const [rawKey, ...rawValueParts] = attribute.split('=');
      const key = rawKey.toLowerCase();
      const attributeValue = rawValueParts.join('=').trim();

      if (key === 'domain' && attributeValue) {
        domain = attributeValue.replace(/^\./, '').toLowerCase();
        hostOnly = false;
      } else if (key === 'path' && attributeValue) {
        path = attributeValue;
      } else if (key === 'max-age') {
        const seconds = Number(attributeValue);

        if (Number.isFinite(seconds)) {
          expiresAt = Date.now() + seconds * 1000;
        }
      } else if (key === 'expires') {
        const parsed = Date.parse(attributeValue);

        if (!Number.isNaN(parsed)) {
          expiresAt = parsed;
        }
      } else if (key === 'secure') {
        secure = true;
      }
    }

    const cookieKey = `${domain};${path};${name}`;

    if (expiresAt !== undefined && expiresAt <= Date.now()) {
      this.cookies.delete(cookieKey);
      return;
    }

    this.cookies.set(cookieKey, {
      name,
      value,
      domain,
      path,
      expiresAt,
      hostOnly,
      secure,
    });
  }

  /**
   * Set-Cookie に Path がないときの既定値を返す
   */
  private defaultPath(pathname: string) {
    if (!pathname || pathname === '/') {
      return '/';
    }

    const lastSlash = pathname.lastIndexOf('/');
    return lastSlash <= 0 ? '/' : pathname.slice(0, lastSlash);
  }

  /**
   * URL に対して Cookie が送信可能かを判定する
   * hostOnly と domain 属性の差をここで吸収している
   */
  private matches(cookie: StoredCookie, requestUrl: URL, now: number) {
    if (cookie.expiresAt !== undefined && cookie.expiresAt <= now) {
      return false;
    }

    if (cookie.secure && requestUrl.protocol !== 'https:') {
      return false;
    }

    const hostname = requestUrl.hostname.toLowerCase();
    const domainMatches = cookie.hostOnly
      ? hostname === cookie.domain
      : hostname === cookie.domain || hostname.endsWith(`.${cookie.domain}`);

    if (!domainMatches) {
      return false;
    }

    const pathname = requestUrl.pathname || '/';
    return pathname.startsWith(cookie.path);
  }
}
