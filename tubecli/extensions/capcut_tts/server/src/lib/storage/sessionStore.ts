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
  write(
    accountKey: string,
    payload: string,
    expiresAt: number,
    expectedVersion: number | null
  ): Promise<boolean>;
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
      all<T = unknown>(): Promise<{ results?: T[] }>;
      run(): Promise<{ meta?: { changes?: number } }>;
    };
  };
}

interface SessionRow {
  payload: string;
  version: number;
  expires_at: number;
  lock_until: number;
  fail_until: number;
}

/**
 * D1 上のセッションストア
 *
 * 1 アカウント 1 行 同時実行は version と lock_until で捌く
 */
export class D1SessionStore implements SessionStore {
  private readonly db: D1Like;

  constructor(db: D1Like) {
    this.db = db;
  }

  async read(accountKey: string): Promise<SessionRecord | null> {
    const row = await this.db
      .prepare(
        'SELECT payload, version, expires_at, lock_until, fail_until FROM capcut_session WHERE account_key = ?'
      )
      .bind(accountKey)
      .first<SessionRow>();

    if (!row) {
      return null;
    }

    return {
      payload: row.payload,
      version: row.version,
      expiresAt: row.expires_at,
      lockUntil: row.lock_until,
      failUntil: row.fail_until ?? 0,
    };
  }

  async write(
    accountKey: string,
    payload: string,
    expiresAt: number,
    expectedVersion: number | null
  ): Promise<boolean> {
    const now = Date.now();

    // 手元に version が無い = まだ何も読めていない初回
    //
    // acquireLock が payload 空の行を先に作るため、単純な DO NOTHING では
    // その空行に阻まれて永久に書けなくなる 空のときだけ埋める
    if (expectedVersion === null) {
      const inserted = await this.db
        .prepare(
          `INSERT INTO capcut_session
             (account_key, payload, version, expires_at, lock_until, updated_at)
           VALUES (?, ?, 1, ?, 0, ?)
           ON CONFLICT(account_key) DO UPDATE
             SET payload = excluded.payload,
                 version = capcut_session.version + 1,
                 expires_at = excluded.expires_at,
                 updated_at = excluded.updated_at
             WHERE capcut_session.payload = ''`
        )
        .bind(accountKey, payload, expiresAt, now)
        .run();

      return (inserted.meta?.changes ?? 0) > 0;
    }

    const updated = await this.db
      .prepare(
        `UPDATE capcut_session
            SET payload = ?, version = version + 1, expires_at = ?, updated_at = ?
          WHERE account_key = ? AND version = ?`
      )
      .bind(payload, expiresAt, now, accountKey, expectedVersion)
      .run();

    return (updated.meta?.changes ?? 0) > 0;
  }

  /**
   * ログイン権を取る
   *
   * 行が無ければ作ってから取る 期限切れの lock は奪ってよい
   */
  async acquireLock(accountKey: string, lockMs: number): Promise<boolean> {
    const now = Date.now();

    await this.db
      .prepare(
        `INSERT INTO capcut_session
           (account_key, payload, version, expires_at, lock_until, updated_at)
         VALUES (?, '', 0, 0, 0, ?)
         ON CONFLICT(account_key) DO NOTHING`
      )
      .bind(accountKey, now)
      .run();

    // backoff 中は誰にもログインさせない
    const locked = await this.db
      .prepare(
        `UPDATE capcut_session
            SET lock_until = ?, updated_at = ?
          WHERE account_key = ? AND lock_until < ? AND fail_until < ?`
      )
      .bind(now + lockMs, now, accountKey, now, now)
      .run();

    return (locked.meta?.changes ?? 0) > 0;
  }

  async markLoginFailure(accountKey: string, backoffMs: number): Promise<void> {
    const now = Date.now();

    await this.db
      .prepare(
        `UPDATE capcut_session
            SET fail_until = ?, lock_until = 0, updated_at = ?
          WHERE account_key = ?`
      )
      .bind(now + backoffMs, now, accountKey)
      .run();
  }

  async releaseLock(accountKey: string): Promise<void> {
    await this.db
      .prepare(
        'UPDATE capcut_session SET lock_until = 0, updated_at = ? WHERE account_key = ?'
      )
      .bind(Date.now(), accountKey)
      .run();
  }
}

let store: SessionStore | null = null;

export const setSessionStore = (next: SessionStore | null) => {
  store = next;
};

/**
 * セッションストアを返す 未設定なら null
 * null のときは従来どおり BlobStorage へ保存する
 */
export const getSessionStore = (): SessionStore | null => store;
