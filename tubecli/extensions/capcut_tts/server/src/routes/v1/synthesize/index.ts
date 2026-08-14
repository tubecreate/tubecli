import { Router } from 'express';
import { get } from './get';

const synthesizeRouter = Router();

synthesizeRouter.get('/', get);

export default synthesizeRouter;
