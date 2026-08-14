import { Router } from 'express';
import { get } from './get';

const languagesRouter = Router();

languagesRouter.get('/', get);

export default languagesRouter;
