import { Router } from 'express';
import { get } from './get';

const speakerIdRouter = Router({ mergeParams: true });

speakerIdRouter.get('/preview', get);

export default speakerIdRouter;
