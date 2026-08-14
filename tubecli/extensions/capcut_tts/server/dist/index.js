"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// Workers には dotenv もファイルシステムも無いため、Node エントリ側でだけ読む
require("dotenv/config");
const app_1 = __importDefault(require("./app"));
const env_1 = __importDefault(require("./configs/env"));
const logger_1 = __importDefault(require("./services/logger"));
const CapCutService_1 = require("./services/CapCutService");
const LegacyCapCutService_1 = require("./services/LegacyCapCutService");
/**
 * サーバー起動エントリポイント
 */
if (env_1.default.ERROR_HANDLE) {
    process.on('uncaughtException', (error) => {
        logger_1.default.error('Uncaught exception', error);
    });
    process.on('unhandledRejection', (error) => {
        logger_1.default.error('Unhandled rejection', error);
    });
}
const server = app_1.default.listen(env_1.default.PORT, env_1.default.HOST);
// listen コールバックは bind 失敗時でも発火しうるので listening を待って告知する
server.on('listening', () => {
    logger_1.default.info(`Server is running on: http://${env_1.default.HOST}:${env_1.default.PORT}`);
});
server.on('error', (error) => {
    logger_1.default.error('Server failed to start.', error);
    process.exit(1);
});
void (0, CapCutService_1.startCapCutSessionTask)();
void (0, LegacyCapCutService_1.startLegacyTokenTask)();
//# sourceMappingURL=index.js.map