import { NodeBlobStorage } from '@/lib/storage/nodeStorage';
import type { BlobStorage } from '@/lib/storage/types';

let storage: BlobStorage | null = null;

/**
 * 永続化先を差し替える
 * Worker 起動時に R2BlobStorage を注入するために使う
 */
export const setBlobStorage = (next: BlobStorage) => {
  storage = next;
};

/**
 * 現在の永続化先を返す
 * 未設定なら Node のファイルシステムへ倒す
 */
export const getBlobStorage = (): BlobStorage => {
  if (!storage) {
    storage = new NodeBlobStorage();
  }

  return storage;
};

export type { BlobStorage, StoredBlob } from '@/lib/storage/types';
export { NodeBlobStorage } from '@/lib/storage/nodeStorage';
export { R2BlobStorage } from '@/lib/storage/r2Storage';
export type { R2BucketLike } from '@/lib/storage/r2Storage';
