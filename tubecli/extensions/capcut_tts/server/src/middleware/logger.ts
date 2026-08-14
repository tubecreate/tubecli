import type { NextFunction, Request, Response } from 'express';
import logger from '@/services/logger';

const decodeUrlForLog = (value: string) => {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
};

/**
 * リクエストとレスポンス時間をログへ出す
 */
export const loggerMiddleware = (
  req: Request,
  res: Response,
  next: NextFunction
): void => {
  const startedAt = Date.now();
  const forwardedFor = req.headers['x-forwarded-for'];
  const realIp = req.headers['x-real-ip'];
  const xForwardedFor = Array.isArray(forwardedFor)
    ? forwardedFor.join(', ')
    : (forwardedFor ?? '');
  const remoteAddress =
    req.socket.remoteAddress ??
    req.connection.remoteAddress ??
    '';
  const requestIp =
    (Array.isArray(forwardedFor) ? forwardedFor[0] : forwardedFor) ??
    (Array.isArray(realIp) ? realIp[0] : realIp) ??
    req.ip ??
    '';
  const requestUrl = decodeUrlForLog(req.originalUrl);

  logger.info(
    `Incoming request: ${req.method} ${requestUrl} ip=${requestIp} remote=${remoteAddress} xff=${xForwardedFor || '-'}`
  );

  res.on('finish', () => {
    logger.info(
      `Completed request: ${req.method} ${requestUrl} status=${res.statusCode} durationMs=${Date.now() - startedAt} ip=${requestIp} remote=${remoteAddress} xff=${xForwardedFor || '-'}`
    );
  });

  next();
};
