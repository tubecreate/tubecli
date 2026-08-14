import { z } from 'zod';

const singleQueryValue = <T extends z.ZodTypeAny>(schema: T) =>
  z.preprocess((value) => {
    if (Array.isArray(value)) {
      return value[0];
    }

    return value;
  }, schema);

const numericQuery = (defaultValue: number) =>
  singleQueryValue(z.coerce.number().int()).default(defaultValue);

export const LegacySynthesizeQuerySchema = z.object({
  text: singleQueryValue(z.string().trim().min(1, 'text is required')),
  type: numericQuery(0),
  pitch: numericQuery(10),
  speed: numericQuery(10),
  volume: numericQuery(10),
  method: singleQueryValue(z.enum(['buffer', 'stream'])).default('buffer'),
});

export type LegacySynthesizeQuery = z.infer<typeof LegacySynthesizeQuerySchema>;
