"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const tslog_1 = require("tslog");
const env_1 = __importDefault(require("../configs/env"));
const logLevelToMinLevel = {
    silly: 0,
    trace: 1,
    debug: 2,
    info: 3,
    warn: 4,
    error: 5,
    fatal: 6,
};
let instance = null;
/**
 * ロガー本体を返す 初回参照時に生成する
 *
 * モジュール評価時に env へ触れると、bindings がまだ無い
 * Cloudflare Workers の起動チェックで失敗するため遅延させる
 */
const getLogger = () => {
    if (!instance) {
        instance = new tslog_1.Logger({ minLevel: logLevelToMinLevel[env_1.default.LOG_LEVEL] });
    }
    return instance;
};
/**
 * アプリ全体で共有するロガー
 */
const logger = {
    silly: (...args) => getLogger().silly(...args),
    trace: (...args) => getLogger().trace(...args),
    debug: (...args) => getLogger().debug(...args),
    info: (...args) => getLogger().info(...args),
    warn: (...args) => getLogger().warn(...args),
    error: (...args) => getLogger().error(...args),
    fatal: (...args) => getLogger().fatal(...args),
};
exports.default = logger;
//# sourceMappingURL=logger.js.map