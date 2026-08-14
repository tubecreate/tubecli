"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.R2BlobStorage = void 0;
/**
 * Cloudflare R2 上の BlobStorage
 *
 * Workers にはファイルシステムが無いため、セッション JSON と
 * プレビュー音声の保存先をまるごと R2 に置き換える
 */
class R2BlobStorage {
    bucket;
    prefix;
    constructor(bucket, prefix = '') {
        this.bucket = bucket;
        this.prefix = prefix;
    }
    toKey(key) {
        return this.prefix ? `${this.prefix.replace(/\/+$/, '')}/${key}` : key;
    }
    async readText(key) {
        const object = await this.bucket.get(this.toKey(key));
        return object ? object.text() : null;
    }
    async writeText(key, value) {
        await this.bucket.put(this.toKey(key), value, {
            httpMetadata: { contentType: 'application/json; charset=utf-8' },
        });
    }
    async readBlob(key) {
        const object = await this.bucket.get(this.toKey(key));
        if (!object) {
            return null;
        }
        return {
            body: new Uint8Array(await object.arrayBuffer()),
            // uploaded が無い実装でも期限判定が壊れないよう現在時刻へ倒す
            uploadedAt: object.uploaded ? object.uploaded.getTime() : Date.now(),
        };
    }
    async writeBlob(key, body, contentType = 'audio/mpeg') {
        // Uint8Array の view をそのまま渡すと副次的な参照ズレが出るため ArrayBuffer 化する
        const buffer = body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength);
        await this.bucket.put(this.toKey(key), buffer, {
            httpMetadata: { contentType },
        });
    }
}
exports.R2BlobStorage = R2BlobStorage;
//# sourceMappingURL=r2Storage.js.map