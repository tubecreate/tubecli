import { Router } from 'express';
import speakerIdRouter from './[speakerId]';
import { get } from './get';

const speakersRouter = Router();

speakersRouter.get('/', get);
speakersRouter.use('/:speakerId', speakerIdRouter);

export default speakersRouter;
