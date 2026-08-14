"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.AccountStore = exports.sessionKeyFor = void 0;
const node_crypto_1 = __importDefault(require("node:crypto"));
const secretBox_1 = require("../../lib/admin/secretBox");
/**
 * CapCutService が使うセッションキーと同じ規則
 * 変えると既存セッションと紐付かなくなる
 */
const sessionKeyFor = (email, basePath) => {
    const suffix = node_crypto_1.default
        .createHash('sha256')
        .update(email.trim().toLowerCase())
        .digest('hex')
        .slice(0, 16);
    return basePath.replace(/(\.json)?$/i, `.${suffix}$1`);
};
exports.sessionKeyFor = sessionKeyFor;
/**
 * 管理 UI 用のアカウント台帳
 */
class AccountStore {
    db;
    encKey;
    sessionBasePath;
    constructor(db, encKey, sessionBasePath) {
        this.db = db;
        this.encKey = encKey;
        this.sessionBasePath = sessionBasePath;
    }
    /**
     * セッション状態を突き合わせて一覧を返す
     */
    async list() {
        const rows = await this.db
            .prepare(`SELECT a.email, a.password_enc, a.label, a.enabled, a.created_at,
                a.last_used_at, a.last_error,
                s.version, length(s.payload) AS bytes, s.expires_at,
                s.lock_until, s.fail_until
           FROM capcut_account a
           LEFT JOIN capcut_session s
             ON s.account_key = a.session_key_cache
          ORDER BY a.created_at ASC`)
            .bind()
            .all();
        return (rows?.results ?? []).map((row) => this.toSummary(row));
    }
    toSummary(row) {
        return {
            email: row.email,
            label: row.label,
            enabled: row.enabled === 1,
            createdAt: row.created_at,
            lastUsedAt: row.last_used_at,
            lastError: row.last_error,
            session: row.version === null
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
    async add(email, password, label) {
        const now = Date.now();
        const sealed = await (0, secretBox_1.sealSecret)(password, this.encKey);
        await this.db
            .prepare(`INSERT INTO capcut_account
           (email, password_enc, label, enabled, created_at, last_used_at, last_error, session_key_cache)
         VALUES (?, ?, ?, 1, ?, 0, '', ?)
         ON CONFLICT(email) DO UPDATE
           SET password_enc = excluded.password_enc,
               label = excluded.label`)
            .bind(email.trim().toLowerCase(), sealed, label, now, (0, exports.sessionKeyFor)(email, this.sessionBasePath))
            .run();
    }
    async remove(email) {
        const key = (0, exports.sessionKeyFor)(email, this.sessionBasePath);
        await this.db
            .prepare('DELETE FROM capcut_account WHERE email = ?')
            .bind(email.trim().toLowerCase())
            .run();
        await this.db
            .prepare('DELETE FROM capcut_session WHERE account_key = ?')
            .bind(key)
            .run();
    }
    async setEnabled(email, enabled) {
        await this.db
            .prepare('UPDATE capcut_account SET enabled = ? WHERE email = ?')
            .bind(enabled ? 1 : 0, email.trim().toLowerCase())
            .run();
    }
    /**
     * セッションを捨てて次回ログインし直させる
     * backoff も解除するので、様子見待ちを飛ばせる
     */
    async resetSession(email) {
        await this.db
            .prepare('DELETE FROM capcut_session WHERE account_key = ?')
            .bind((0, exports.sessionKeyFor)(email, this.sessionBasePath))
            .run();
    }
    async clearBackoff(email) {
        await this.db
            .prepare('UPDATE capcut_session SET fail_until = 0, lock_until = 0 WHERE account_key = ?')
            .bind((0, exports.sessionKeyFor)(email, this.sessionBasePath))
            .run();
    }
    /**
     * 資格情報を取り出す 合成を実行するときだけ使う
     */
    async credentialsFor(email) {
        const row = await this.db
            .prepare('SELECT email, password_enc FROM capcut_account WHERE email = ? AND enabled = 1')
            .bind(email.trim().toLowerCase())
            .first();
        if (!row) {
            return null;
        }
        const password = await (0, secretBox_1.openSecret)(row.password_enc, this.encKey);
        return password ? { email: row.email, password } : null;
    }
    async recordUsage(email, error) {
        await this.db
            .prepare('UPDATE capcut_account SET last_used_at = ?, last_error = ? WHERE email = ?')
            .bind(Date.now(), error.slice(0, 300), email.trim().toLowerCase())
            .run();
    }
}
exports.AccountStore = AccountStore;
//# sourceMappingURL=accountStore.js.map