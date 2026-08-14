import { Router } from 'express';
import { get } from './get';

const modelsRouter = Router();

modelsRouter.get('/', get);

export default modelsRouter;
