import fs from 'node:fs/promises';
import path from 'node:path';
import type { BlobStorage, StoredBlob } from '@/lib/storage/types';

const isNotFound = (error: unknown) =>
  error instanceof Error &&
  'code' in error &&
  (error as NodeJS.ErrnoException).code === 'ENOENT';

/**
 * ローカルファイルシステム上の BlobStorage
 * key はそのまま cwd 起点の相対パスとして扱う
 */
export class NodeBlobStorage implements BlobStorage {
  private readonly baseDir: string;

  constructor(baseDir: string = process.cwd()) {
    this.baseDir = baseDir;
  }

  private resolve(key: string) {
    return path.resolve(this.baseDir, key);
  }

  private async ensureParent(filePath: string) {
    await fs.mkdir(path.dirname(filePath), { recursive: true });
  }

  async readText(key: string): Promise<string | null> {
    try {
      return await fs.readFile(this.resolve(key), 'utf8');
    } catch (error) {
      if (isNotFound(error)) {
        return null;
      }

      throw error;
    }
  }

  async writeText(key: string, value: string): Promise<void> {
    const filePath = this.resolve(key);
    await this.ensureParent(filePath);
    await fs.writeFile(filePath, value, 'utf8');
  }

  async readBlob(key: string): Promise<StoredBlob | null> {
    const filePath = this.resolve(key);

    try {
      const [body, stats] = await Promise.all([
        fs.readFile(filePath),
        fs.stat(filePath),
      ]);

      return { body: new Uint8Array(body), uploadedAt: stats.mtimeMs };
    } catch (error) {
      if (isNotFound(error)) {
        return null;
      }

      throw error;
    }
  }

  async writeBlob(key: string, body: Uint8Array): Promise<void> {
    const filePath = this.resolve(key);
    await this.ensureParent(filePath);
    await fs.writeFile(filePath, body);
  }
}
