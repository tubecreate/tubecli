"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.R2BlobStorage = exports.NodeBlobStorage = exports.getBlobStorage = exports.setBlobStorage = void 0;
const nodeStorage_1 = require("../../lib/storage/nodeStorage");
let storage = null;
/**
 * 永続化先を差し替える
 * Worker 起動時に R2BlobStorage を注入するために使う
 */
const setBlobStorage = (next) => {
    storage = next;
};
exports.setBlobStorage = setBlobStorage;
/**
 * 現在の永続化先を返す
 * 未設定なら Node のファイルシステムへ倒す
 */
const getBlobStorage = () => {
    if (!storage) {
        storage = new nodeStorage_1.NodeBlobStorage();
    }
    return storage;
};
exports.getBlobStorage = getBlobStorage;
var nodeStorage_2 = require("../../lib/storage/nodeStorage");
Object.defineProperty(exports, "NodeBlobStorage", { enumerable: true, get: function () { return nodeStorage_2.NodeBlobStorage; } });
var r2Storage_1 = require("../../lib/storage/r2Storage");
Object.defineProperty(exports, "R2BlobStorage", { enumerable: true, get: function () { return r2Storage_1.R2BlobStorage; } });
//# sourceMappingURL=index.js.map