"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.loggerMiddleware = void 0;
const logger_1 = __importDefault(require("../services/logger"));
const decodeUrlForLog = (value) => {
    try {
        return decodeURIComponent(value);
    }
    catch {
        return value;
    }
};
/**
 * リクエストとレスポンス時間をログへ出す
 */
const loggerMiddleware = (req, res, next) => {
    const startedAt = Date.now();
    const forwardedFor = req.headers['x-forwarded-for'];
    const realIp = req.headers['x-real-ip'];
    const xForwardedFor = Array.isArray(forwardedFor)
        ? forwardedFor.join(', ')
        : (forwardedFor ?? '');
    const remoteAddress = req.socket.remoteAddress ??
        req.connection.remoteAddress ??
        '';
    const requestIp = (Array.isArray(forwardedFor) ? forwardedFor[0] : forwardedFor) ??
        (Array.isArray(realIp) ? realIp[0] : realIp) ??
        req.ip ??
        '';
    const requestUrl = decodeUrlForLog(req.originalUrl);
    logger_1.default.info(`Incoming request: ${req.method} ${requestUrl} ip=${requestIp} remote=${remoteAddress} xff=${xForwardedFor || '-'}`);
    res.on('finish', () => {
        logger_1.default.info(`Completed request: ${req.method} ${requestUrl} status=${res.statusCode} durationMs=${Date.now() - startedAt} ip=${requestIp} remote=${remoteAddress} xff=${xForwardedFor || '-'}`);
    });
    next();
};
exports.loggerMiddleware = loggerMiddleware;
//# sourceMappingURL=logger.js.map