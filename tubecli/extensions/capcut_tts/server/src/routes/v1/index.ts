import { Router } from 'express';
import modelsRouter from '@/routes/v1/models';
import synthesizeRouter from '@/routes/v1/synthesize';

const v1Router = Router();

v1Router.use('/models', modelsRouter);
v1Router.use('/synthesize', synthesizeRouter);

export default v1Router;
