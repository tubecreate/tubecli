import { Router } from 'express';
import { get } from './get';
import { post } from './post';

const synthesizeRouter = Router();

synthesizeRouter.get('/', get);
synthesizeRouter.post('/', post);

export default synthesizeRouter;
