/**
 * 保存済みバイナリと、その最終更新時刻
 */
export interface StoredBlob {
  body: Uint8Array;
  /** epoch ms 期限判定に使う */
  uploadedAt: number;
}

/**
 * セッションやプレビュー音声の永続化先を抽象化する
 *
 * Node ではローカルファイル、Cloudflare Workers では R2 が実体になる
 * Workers にファイルシステムが無いため、この境界だけを差し替える
 */
export interface BlobStorage {
  readText(key: string): Promise<string | null>;
  writeText(key: string, value: string): Promise<void>;
  readBlob(key: string): Promise<StoredBlob | null>;
  writeBlob(key: string, body: Uint8Array, contentType?: string): Promise<void>;
}
