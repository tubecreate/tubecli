"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.isSessionExpiredError = exports.isLoginAttemptLimitError = exports.buildSensitiveFormBody = exports.createEmailRegionHashWithSalt = exports.createEmailRegionHash = exports.normalizeEmailForRegion = exports.sha256Hex = exports.xorFiveHexEncode = exports.toVolumeLevel = exports.toPlaybackRate = exports.createTrackingId = exports.createDeviceId = exports.createVerifyFp = void 0;
const node_crypto_1 = __importDefault(require("node:crypto"));
const defaultCapCutEmailHashSalt = 'aDy0TUhtql92P7hScCs97YWMT-jub2q9';
/**
 * CapCut の verifyFp 形式に寄せた識別子を生成する
 */
const createVerifyFp = () => {
    const random = (length) => node_crypto_1.default
        .randomBytes(length * 2)
        .toString('base64url')
        .replace(/[^a-zA-Z0-9]/g, '')
        .slice(0, length);
    const prefix = Date.now().toString(36).slice(-8).padStart(8, '0');
    return `verify_${prefix}_${random(8)}_${random(4)}_${random(4)}_${random(4)}_${random(12)}`;
};
exports.createVerifyFp = createVerifyFp;
/**
 * CapCut の did として使うデバイス ID を生成する
 */
const createDeviceId = () => `${Date.now()}${Array.from(node_crypto_1.default.randomBytes(12), (value) => String(value % 10)).join('')}`.slice(0, 19);
exports.createDeviceId = createDeviceId;
/**
 * CapCut の tdid として使うトラッキング ID を生成する
 */
const createTrackingId = () => `${Date.now()}${Array.from(node_crypto_1.default.randomBytes(8), (value) => String(value % 10)).join('')}`.slice(0, 17);
exports.createTrackingId = createTrackingId;
/**
 * speed パラメータを CapCut の再生速度に変換する
 */
const toPlaybackRate = (speed) => Number((Math.min(Math.max(speed, 1), 20) / 10).toFixed(2));
exports.toPlaybackRate = toPlaybackRate;
/**
 * volume パラメータを CapCut の音量レベルに変換する
 */
const toVolumeLevel = (volume) => Math.min(Math.max(volume, 0), 20) * 10;
exports.toVolumeLevel = toVolumeLevel;
/**
 * CapCut login SDK が使う XOR5 + hex 変換
 */
const xorFiveHexEncode = (value) => Array.from(Buffer.from(value, 'utf8'), (charCode) => (charCode ^ 5).toString(16).padStart(2, '0')).join('');
exports.xorFiveHexEncode = xorFiveHexEncode;
/**
 * SHA-256 の hex 文字列を返す
 */
const sha256Hex = (value) => node_crypto_1.default.createHash('sha256').update(value).digest('hex').toLowerCase();
exports.sha256Hex = sha256Hex;
/**
 * email をリージョン解決用の正規化形式へ揃える
 */
const normalizeEmailForRegion = (email) => email.trim().toLowerCase();
exports.normalizeEmailForRegion = normalizeEmailForRegion;
/**
 * region 解決用の hashed_id を生成する
 */
const createEmailRegionHash = (email) => (0, exports.sha256Hex)(`${(0, exports.normalizeEmailForRegion)(email)}${defaultCapCutEmailHashSalt}`);
exports.createEmailRegionHash = createEmailRegionHash;
/**
 * region 解決用の hashed_id を任意 salt で生成する
 */
const createEmailRegionHashWithSalt = (email, salt = defaultCapCutEmailHashSalt) => (0, exports.sha256Hex)(`${(0, exports.normalizeEmailForRegion)(email)}${salt}`);
exports.createEmailRegionHashWithSalt = createEmailRegionHashWithSalt;
/**
 * 秘匿項目だけ XOR5 + hex で包んだ form body を作る
 */
const buildSensitiveFormBody = (values, keys) => {
    const payload = new URLSearchParams();
    let mixMode = 0;
    let fixedMixMode = 0;
    for (const [key, value] of Object.entries(values)) {
        if (keys.includes(key)) {
            mixMode |= 1;
            fixedMixMode |= 1;
            payload.set(key, (0, exports.xorFiveHexEncode)(value));
            continue;
        }
        payload.set(key, value);
    }
    payload.set('mix_mode', String(mixMode));
    payload.set('fixed_mix_mode', String(fixedMixMode));
    return payload.toString();
};
exports.buildSensitiveFormBody = buildSensitiveFormBody;
/**
 * CapCut がログイン試行回数の上限を返したかを判定する
 *
 * この状態で別 host を試しても通らず、残り試行を減らすだけになる
 * errorCode 7 のほか、文言でも拾えるようにしておく
 */
const isLoginAttemptLimitError = (error) => {
    if (!(error instanceof Error)) {
        return false;
    }
    if ('errorCode' in error &&
        error.errorCode === 7) {
        return true;
    }
    return /số lần thử tối đa|試行回数の上限|maximum.*attempts|too many attempts/i.test(error.message);
};
exports.isLoginAttemptLimitError = isLoginAttemptLimitError;
/**
 * セッション失効らしいエラーかを判定する
 */
const isSessionExpiredError = (error) => error instanceof Error &&
    /check login error|account info failed|workspace list was empty/i.test(error.message);
exports.isSessionExpiredError = isSessionExpiredError;
//# sourceMappingURL=capcutUtils.js.map