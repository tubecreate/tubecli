import type { Request, Response } from 'express';
import { capCutLegacySpeakers } from '@/models/capcutLegacySpeakers';

/**
 * ### get
 * `/v1/models` を処理する
 *
 * @param req - Express リクエスト
 * @param res - Express レスポンス
 */
export const get = async (req: Request, res: Response): Promise<void> => {
  void req;

  res.status(200).json(
    capCutLegacySpeakers.map((model) => ({
      id: model.id,
      name: model.title,
      description: model.description,
      language: model.language,
      type: model.type,
    }))
  );
};
