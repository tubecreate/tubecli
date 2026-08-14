import { Logger } from 'tslog';
import env from '@/configs/env';

const logLevelToMinLevel = {
  silly: 0,
  trace: 1,
  debug: 2,
  info: 3,
  warn: 4,
  error: 5,
  fatal: 6,
} as const;

type LogMethod = 'silly' | 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'fatal';

let instance: Logger<unknown> | null = null;

/**
 * ロガー本体を返す 初回参照時に生成する
 *
 * モジュール評価時に env へ触れると、bindings がまだ無い
 * Cloudflare Workers の起動チェックで失敗するため遅延させる
 */
const getLogger = (): Logger<unknown> => {
  if (!instance) {
    instance = new Logger({ minLevel: logLevelToMinLevel[env.LOG_LEVEL] });
  }

  return instance;
};

/**
 * アプリ全体で共有するロガー
 */
const logger = {
  silly: (...args: unknown[]) => getLogger().silly(...args),
  trace: (...args: unknown[]) => getLogger().trace(...args),
  debug: (...args: unknown[]) => getLogger().debug(...args),
  info: (...args: unknown[]) => getLogger().info(...args),
  warn: (...args: unknown[]) => getLogger().warn(...args),
  error: (...args: unknown[]) => getLogger().error(...args),
  fatal: (...args: unknown[]) => getLogger().fatal(...args),
} satisfies Record<LogMethod, (...args: unknown[]) => unknown>;

export default logger;
