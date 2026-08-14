/**
 * 管理 UI が預かる資格情報の暗号化
 *
 * D1 に平文で置かないための最小限の箱
 * 鍵は Worker secret の ADMIN_ENC_KEY から SHA-256 で導く
 * WebCrypto は Workers にも Node 22 にもあるので実装は 1 本で足りる
 */
/**
 * 暗号化して `iv.ciphertext` の base64 文字列にする
 */
export declare const sealSecret: (plaintext: string, secret: string) => Promise<string>;
/**
 * sealSecret で作った文字列を戻す 壊れていれば null
 */
export declare const openSecret: (sealed: string, secret: string) => Promise<string | null>;
/**
 * 長さを揃えて比較する 早期 return でトークンを推測されないため
 */
export declare const safeEqual: (left: string, right: string) => boolean;
