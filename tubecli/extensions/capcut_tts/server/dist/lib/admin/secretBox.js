"use strict";
/**
 * 管理 UI が預かる資格情報の暗号化
 *
 * D1 に平文で置かないための最小限の箱
 * 鍵は Worker secret の ADMIN_ENC_KEY から SHA-256 で導く
 * WebCrypto は Workers にも Node 22 にもあるので実装は 1 本で足りる
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.safeEqual = exports.openSecret = exports.sealSecret = void 0;
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const toBase64 = (bytes) => {
    let binary = '';
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
};
// ArrayBuffer 固定で返す SharedArrayBuffer 混じりだと WebCrypto の型に通らない
const fromBase64 = (value) => {
    const binary = atob(value);
    const bytes = new Uint8Array(new ArrayBuffer(binary.length));
    for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
};
const importKey = async (secret) => {
    const digest = await crypto.subtle.digest('SHA-256', encoder.encode(secret));
    return crypto.subtle.importKey('raw', digest, { name: 'AES-GCM' }, false, [
        'encrypt',
        'decrypt',
    ]);
};
/**
 * 暗号化して `iv.ciphertext` の base64 文字列にする
 */
const sealSecret = async (plaintext, secret) => {
    const key = await importKey(secret);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const sealed = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoder.encode(plaintext));
    return `${toBase64(iv)}.${toBase64(new Uint8Array(sealed))}`;
};
exports.sealSecret = sealSecret;
/**
 * sealSecret で作った文字列を戻す 壊れていれば null
 */
const openSecret = async (sealed, secret) => {
    const [ivPart, dataPart] = sealed.split('.');
    if (!ivPart || !dataPart) {
        return null;
    }
    try {
        const key = await importKey(secret);
        const opened = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromBase64(ivPart) }, key, fromBase64(dataPart));
        return decoder.decode(opened);
    }
    catch {
        return null;
    }
};
exports.openSecret = openSecret;
/**
 * 長さを揃えて比較する 早期 return でトークンを推測されないため
 */
const safeEqual = (left, right) => {
    if (left.length !== right.length) {
        return false;
    }
    let diff = 0;
    for (let index = 0; index < left.length; index += 1) {
        diff |= left.charCodeAt(index) ^ right.charCodeAt(index);
    }
    return diff === 0;
};
exports.safeEqual = safeEqual;
//# sourceMappingURL=secretBox.js.map