"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getSessionStore = exports.setSessionStore = exports.D1SessionStore = void 0;
/**
 * D1 上のセッションストア
 *
 * 1 アカウント 1 行 同時実行は version と lock_until で捌く
 */
class D1SessionStore {
    db;
    constructor(db) {
        this.db = db;
    }
    async read(accountKey) {
        const row = await this.db
            .prepare('SELECT payload, version, expires_at, lock_until, fail_until FROM capcut_session WHERE account_key = ?')
            .bind(accountKey)
            .first();
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
    async write(accountKey, payload, expiresAt, expectedVersion) {
        const now = Date.now();
        // 手元に version が無い = まだ何も読めていない初回
        //
        // acquireLock が payload 空の行を先に作るため、単純な DO NOTHING では
        // その空行に阻まれて永久に書けなくなる 空のときだけ埋める
        if (expectedVersion === null) {
            const inserted = await this.db
                .prepare(`INSERT INTO capcut_session
             (account_key, payload, version, expires_at, lock_until, updated_at)
           VALUES (?, ?, 1, ?, 0, ?)
           ON CONFLICT(account_key) DO UPDATE
             SET payload = excluded.payload,
                 version = capcut_session.version + 1,
                 expires_at = excluded.expires_at,
                 updated_at = excluded.updated_at
             WHERE capcut_session.payload = ''`)
                .bind(accountKey, payload, expiresAt, now)
                .run();
            return (inserted.meta?.changes ?? 0) > 0;
        }
        const updated = await this.db
            .prepare(`UPDATE capcut_session
            SET payload = ?, version = version + 1, expires_at = ?, updated_at = ?
          WHERE account_key = ? AND version = ?`)
            .bind(payload, expiresAt, now, accountKey, expectedVersion)
            .run();
        return (updated.meta?.changes ?? 0) > 0;
    }
    /**
     * ログイン権を取る
     *
     * 行が無ければ作ってから取る 期限切れの lock は奪ってよい
     */
    async acquireLock(accountKey, lockMs) {
        const now = Date.now();
        await this.db
            .prepare(`INSERT INTO capcut_session
           (account_key, payload, version, expires_at, lock_until, updated_at)
         VALUES (?, '', 0, 0, 0, ?)
         ON CONFLICT(account_key) DO NOTHING`)
            .bind(accountKey, now)
            .run();
        // backoff 中は誰にもログインさせない
        const locked = await this.db
            .prepare(`UPDATE capcut_session
            SET lock_until = ?, updated_at = ?
          WHERE account_key = ? AND lock_until < ? AND fail_until < ?`)
            .bind(now + lockMs, now, accountKey, now, now)
            .run();
        return (locked.meta?.changes ?? 0) > 0;
    }
    async markLoginFailure(accountKey, backoffMs) {
        const now = Date.now();
        await this.db
            .prepare(`UPDATE capcut_session
            SET fail_until = ?, lock_until = 0, updated_at = ?
          WHERE account_key = ?`)
            .bind(now + backoffMs, now, accountKey)
            .run();
    }
    async releaseLock(accountKey) {
        await this.db
            .prepare('UPDATE capcut_session SET lock_until = 0, updated_at = ? WHERE account_key = ?')
            .bind(Date.now(), accountKey)
            .run();
    }
}
exports.D1SessionStore = D1SessionStore;
let store = null;
const setSessionStore = (next) => {
    store = next;
};
exports.setSessionStore = setSessionStore;
/**
 * セッションストアを返す 未設定なら null
 * null のときは従来どおり BlobStorage へ保存する
 */
const getSessionStore = () => store;
exports.getSessionStore = getSessionStore;
//# sourceMappingURL=sessionStore.js.map