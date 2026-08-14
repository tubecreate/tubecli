import type { BlobStorage, StoredBlob } from '@/lib/storage/types';

/**
 * Workers ランタイムが渡してくる R2 バケットの最小インターフェース
 * @cloudflare/workers-types に依存せずに済むよう、使う分だけ宣言する
 */
export interface R2BucketLike {
  get(key: string): Promise<{
    arrayBuffer(): Promise<ArrayBuffer>;
    text(): Promise<string>;
    uploaded?: Date;
    size?: number;
    httpMetadata?: { contentType?: string };
  } | null>;
  put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: {
      httpMetadata?: { contentType?: string };
      customMetadata?: Record<string, string>;
    }
  ): Promise<unknown>;
  list?(options?: { prefix?: string; limit?: number }): Promise<{
    objects: Array<{
      key: string;
      size: number;
      uploaded: Date;
      customMetadata?: Record<string, string>;
    }>;
  }>;
  delete?(key: string): Promise<void>;
}

/**
 * Cloudflare R2 上の BlobStorage
 *
 * Workers にはファイルシステムが無いため、セッション JSON と
 * プレビュー音声の保存先をまるごと R2 に置き換える
 */
export class R2BlobStorage implements BlobStorage {
  private readonly bucket: R2BucketLike;

  private readonly prefix: string;

  constructor(bucket: R2BucketLike, prefix = '') {
    this.bucket = bucket;
    this.prefix = prefix;
  }

  private toKey(key: string) {
    return this.prefix ? `${this.prefix.replace(/\/+$/, '')}/${key}` : key;
  }

  async readText(key: string): Promise<string | null> {
    const object = await this.bucket.get(this.toKey(key));
    return object ? object.text() : null;
  }

  async writeText(key: string, value: string): Promise<void> {
    await this.bucket.put(this.toKey(key), value, {
      httpMetadata: { contentType: 'application/json; charset=utf-8' },
    });
  }

  async readBlob(key: string): Promise<StoredBlob | null> {
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

  async writeBlob(
    key: string,
    body: Uint8Array,
    contentType = 'audio/mpeg'
  ): Promise<void> {
    // Uint8Array の view をそのまま渡すと副次的な参照ズレが出るため ArrayBuffer 化する
    const buffer = body.buffer.slice(
      body.byteOffset,
      body.byteOffset + body.byteLength
    ) as ArrayBuffer;

    await this.bucket.put(this.toKey(key), buffer, {
      httpMetadata: { contentType },
    });
  }
}
