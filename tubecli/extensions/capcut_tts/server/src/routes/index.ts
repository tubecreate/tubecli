import { Router } from 'express';
import { fallback } from '@/routes/fallback';
import v1Router from '@/routes/v1';
import v2Router from '@/routes/v2';

/**
 * ルートルーター
 */
const router = Router();

router.use('/v1', v1Router);
router.use('/v2', v2Router);
router.use(fallback);

export default router;
