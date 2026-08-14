"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.NodeBlobStorage = void 0;
const promises_1 = __importDefault(require("node:fs/promises"));
const node_path_1 = __importDefault(require("node:path"));
const isNotFound = (error) => error instanceof Error &&
    'code' in error &&
    error.code === 'ENOENT';
/**
 * ローカルファイルシステム上の BlobStorage
 * key はそのまま cwd 起点の相対パスとして扱う
 */
class NodeBlobStorage {
    baseDir;
    constructor(baseDir = process.cwd()) {
        this.baseDir = baseDir;
    }
    resolve(key) {
        return node_path_1.default.resolve(this.baseDir, key);
    }
    async ensureParent(filePath) {
        await promises_1.default.mkdir(node_path_1.default.dirname(filePath), { recursive: true });
    }
    async readText(key) {
        try {
            return await promises_1.default.readFile(this.resolve(key), 'utf8');
        }
        catch (error) {
            if (isNotFound(error)) {
                return null;
            }
            throw error;
        }
    }
    async writeText(key, value) {
        const filePath = this.resolve(key);
        await this.ensureParent(filePath);
        await promises_1.default.writeFile(filePath, value, 'utf8');
    }
    async readBlob(key) {
        const filePath = this.resolve(key);
        try {
            const [body, stats] = await Promise.all([
                promises_1.default.readFile(filePath),
                promises_1.default.stat(filePath),
            ]);
            return { body: new Uint8Array(body), uploadedAt: stats.mtimeMs };
        }
        catch (error) {
            if (isNotFound(error)) {
                return null;
            }
            throw error;
        }
    }
    async writeBlob(key, body) {
        const filePath = this.resolve(key);
        await this.ensureParent(filePath);
        await promises_1.default.writeFile(filePath, body);
    }
}
exports.NodeBlobStorage = NodeBlobStorage;
//# sourceMappingURL=nodeStorage.js.map