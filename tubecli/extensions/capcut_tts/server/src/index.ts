// Workers には dotenv もファイルシステムも無いため、Node エントリ側でだけ読む
import 'dotenv/config';
import app from '@/app';
import env from '@/configs/env';
import logger from '@/services/logger';
import { startCapCutSessionTask } from '@/services/CapCutService';
import { startLegacyTokenTask } from '@/services/LegacyCapCutService';

/**
 * サーバー起動エントリポイント
 */
if (env.ERROR_HANDLE) {
  process.on('uncaughtException', (error) => {
    logger.error('Uncaught exception', error);
  });

  process.on('unhandledRejection', (error) => {
    logger.error('Unhandled rejection', error);
  });
}

const server = app.listen(env.PORT, env.HOST);

// listen コールバックは bind 失敗時でも発火しうるので listening を待って告知する
server.on('listening', () => {
  logger.info(`Server is running on: http://${env.HOST}:${env.PORT}`);
});

server.on('error', (error) => {
  logger.error('Server failed to start.', error);
  process.exit(1);
});

void startCapCutSessionTask();
void startLegacyTokenTask();
