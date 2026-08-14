import cors from 'cors';
import express from 'express';
import env from '@/configs/env';
import { errorHandler } from '@/middleware/errorHandler';
import { loggerMiddleware } from '@/middleware/logger';
import router from '@/routes';
import { capCutService } from '@/services/CapCutService';

/**
 * Express アプリ本体
 */
const app = express();

// cors 設定
app.use(cors({ origin: env.CORS_POLICY_ORIGIN }));

// ミドルウェア設定
app.use(express.json());
app.use(loggerMiddleware);

// Cookie の変更はリクエスト終端で 1 回だけ保存する
// 各サブリクエストごとに書くとポーリング中に何十回も書き込みが走る
app.use((req, res, next) => {
  res.on('finish', () => {
    void capCutService.flushSession();
  });
  next();
});

// ルーティング設定
app.use('/', router);
app.use(errorHandler);

export default app;
