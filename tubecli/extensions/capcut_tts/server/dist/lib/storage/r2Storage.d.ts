import type { BlobStorage, StoredBlob } from '../../lib/storage/types';
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
        httpMetadata?: {
            contentType?: string;
        };
    } | null>;
    put(key: string, value: ArrayBuffer | ArrayBufferView | string, options?: {
        httpMetadata?: {
            contentType?: string;
        };
        customMetadata?: Record<string, string>;
    }): Promise<unknown>;
    list?(options?: {
        prefix?: string;
        limit?: number;
    }): Promise<{
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
export declare class R2BlobStorage implements BlobStorage {
    private readonly bucket;
    private readonly prefix;
    constructor(bucket: R2BucketLike, prefix?: string);
    private toKey;
    readText(key: string): Promise<string | null>;
    writeText(key: string, value: string): Promise<void>;
    readBlob(key: string): Promise<StoredBlob | null>;
    writeBlob(key: string, body: Uint8Array, contentType?: string): Promise<void>;
}
