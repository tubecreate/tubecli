import type { BlobStorage, StoredBlob } from '../../lib/storage/types';
/**
 * ローカルファイルシステム上の BlobStorage
 * key はそのまま cwd 起点の相対パスとして扱う
 */
export declare class NodeBlobStorage implements BlobStorage {
    private readonly baseDir;
    constructor(baseDir?: string);
    private resolve;
    private ensureParent;
    readText(key: string): Promise<string | null>;
    writeText(key: string, value: string): Promise<void>;
    readBlob(key: string): Promise<StoredBlob | null>;
    writeBlob(key: string, body: Uint8Array): Promise<void>;
}
