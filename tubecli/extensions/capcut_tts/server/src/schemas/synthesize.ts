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

const numericBody = (defaultValue: number) =>
  z.coerce.number().int().default(defaultValue);

const legacyTypeQuery = singleQueryValue(
  z.union([z.coerce.number().int(), z.string().trim().min(1)])
).default(0);

const legacyTypeBody = z
  .union([z.coerce.number().int(), z.string().trim().min(1)])
  .default(0);

const methodSchema = z.enum(['buffer', 'stream']).default('buffer');

export const SynthesizeQuerySchema = z.object({
  text: singleQueryValue(z.string().trim().min(1, 'text is required')),
  type: legacyTypeQuery,
  speaker: singleQueryValue(z.string().trim().min(1)).optional(),
  pitch: numericQuery(10),
  speed: numericQuery(10),
  volume: numericQuery(10),
  method: singleQueryValue(methodSchema),
  platform: singleQueryValue(z.string().trim().min(1)).optional(),
  timestamps: singleQueryValue(
    z.enum(['true', 'false', '1', '0']).transform((v) => v === 'true' || v === '1')
  ).optional(),
  phonemes: singleQueryValue(
    z.enum(['true', 'false', '1', '0']).transform((v) => v === 'true' || v === '1')
  ).optional(),
});

export const SynthesizeBodySchema = z.object({
  text: z.string().trim().min(1, 'text is required'),
  type: legacyTypeBody,
  speaker: z.string().trim().min(1).optional(),
  pitch: numericBody(10),
  speed: numericBody(10),
  volume: numericBody(10),
  method: methodSchema,
  platform: z.string().trim().min(1).optional(),
  timestamps: z.coerce.boolean().optional(),
  phonemes: z.coerce.boolean().optional(),
});

export type SynthesizeQuery = z.infer<typeof SynthesizeQuerySchema>;
export type SynthesizeBody = z.infer<typeof SynthesizeBodySchema>;
