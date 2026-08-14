import crypto from 'node:crypto';
import type { D1Like } from '@/lib/storage/sessionStore';
import { openSecret, sealSecret } from '@/lib/admin/secretBox';

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

interface AccountRow {
  email: string;
  password_enc: string;
  label: string;
  enabled: number;
  created_at: number;
  last_used_at: number;
  last_error: string;
}

interface JoinedRow extends AccountRow {
  version: number | null;
  bytes: number | null;
  expires_at: number | null;
  lock_until: number | null;
  fail_until: number | null;
}

/**
 * CapCutService が使うセッションキーと同じ規則
 * 変えると既存セッションと紐付かなくなる
 */
export const sessionKeyFor = (email: string, basePath: string): string => {
  const suffix = crypto
    .createHash('sha256')
    .update(email.trim().toLowerCase())
    .digest('hex')
    .slice(0, 16);

  return basePath.replace(/(\.json)?$/i, `.${suffix}$1`);
};

/**
 * 管理 UI 用のアカウント台帳
 */
export class AccountStore {
  private readonly db: D1Like;

  private readonly encKey: string;

  private readonly sessionBasePath: string;

  constructor(db: D1Like, encKey: string, sessionBasePath: string) {
    this.db = db;
    this.encKey = encKey;
    this.sessionBasePath = sessionBasePath;
  }

  /**
   * セッション状態を突き合わせて一覧を返す
   */
  async list(): Promise<AccountSummary[]> {
    const rows = await this.db
      .prepare(
        `SELECT a.email, a.password_enc, a.label, a.enabled, a.created_at,
                a.last_used_at, a.last_error,
                s.version, length(s.payload) AS bytes, s.expires_at,
                s.lock_until, s.fail_until
           FROM capcut_account a
           LEFT JOIN capcut_session s
             ON s.account_key = a.session_key_cache
          ORDER BY a.created_at ASC`
      )
      .bind()
      .all<JoinedRow>();

    return (rows?.results ?? []).map((row) => this.toSummary(row));
  }

  private toSummary(row: JoinedRow): AccountSummary {
    return {
      email: row.email,
      label: row.label,
      enabled: row.enabled === 1,
      createdAt: row.created_at,
      lastUsedAt: row.last_used_at,
      lastError: row.last_error,
      session:
        row.version === null
          ? null
          : {
              version: row.version,
              bytes: row.bytes ?? 0,
              expiresAt: row.expires_at ?? 0,
              lockedUntil: row.lock_until ?? 0,
              failUntil: row.fail_until ?? 0,
            },
    };
  }

  async add(email: string, password: string, label: string): Promise<void> {
    const now = Date.now();
    const sealed = await sealSecret(password, this.encKey);

    await this.db
      .prepare(
        `INSERT INTO capcut_account
           (email, password_enc, label, enabled, created_at, last_used_at, last_error, session_key_cache)
         VALUES (?, ?, ?, 1, ?, 0, '', ?)
         ON CONFLICT(email) DO UPDATE
           SET password_enc = excluded.password_enc,
               label = excluded.label`
      )
      .bind(
        email.trim().toLowerCase(),
        sealed,
        label,
        now,
        sessionKeyFor(email, this.sessionBasePath)
      )
      .run();
  }

  async remove(email: string): Promise<void> {
    const key = sessionKeyFor(email, this.sessionBasePath);

    await this.db
      .prepare('DELETE FROM capcut_account WHERE email = ?')
      .bind(email.trim().toLowerCase())
      .run();
    await this.db
      .prepare('DELETE FROM capcut_session WHERE account_key = ?')
      .bind(key)
      .run();
  }

  async setEnabled(email: string, enabled: boolean): Promise<void> {
    await this.db
      .prepare('UPDATE capcut_account SET enabled = ? WHERE email = ?')
      .bind(enabled ? 1 : 0, email.trim().toLowerCase())
      .run();
  }

  /**
   * セッションを捨てて次回ログインし直させる
   * backoff も解除するので、様子見待ちを飛ばせる
   */
  async resetSession(email: string): Promise<void> {
    await this.db
      .prepare('DELETE FROM capcut_session WHERE account_key = ?')
      .bind(sessionKeyFor(email, this.sessionBasePath))
      .run();
  }

  async clearBackoff(email: string): Promise<void> {
    await this.db
      .prepare(
        'UPDATE capcut_session SET fail_until = 0, lock_until = 0 WHERE account_key = ?'
      )
      .bind(sessionKeyFor(email, this.sessionBasePath))
      .run();
  }

  /**
   * 資格情報を取り出す 合成を実行するときだけ使う
   */
  async credentialsFor(
    email: string
  ): Promise<{ email: string; password: string } | null> {
    const row = await this.db
      .prepare(
        'SELECT email, password_enc FROM capcut_account WHERE email = ? AND enabled = 1'
      )
      .bind(email.trim().toLowerCase())
      .first<AccountRow>();

    if (!row) {
      return null;
    }

    const password = await openSecret(row.password_enc, this.encKey);

    return password ? { email: row.email, password } : null;
  }

  async recordUsage(email: string, error: string): Promise<void> {
    await this.db
      .prepare(
        'UPDATE capcut_account SET last_used_at = ?, last_error = ? WHERE email = ?'
      )
      .bind(Date.now(), error.slice(0, 300), email.trim().toLowerCase())
      .run();
  }
}
