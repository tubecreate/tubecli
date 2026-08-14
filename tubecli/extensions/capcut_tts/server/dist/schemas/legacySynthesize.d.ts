import { z } from 'zod';
export declare const LegacySynthesizeQuerySchema: z.ZodObject<{
    text: z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodString>;
    type: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    pitch: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    speed: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    volume: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    method: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodEnum<{
        buffer: "buffer";
        stream: "stream";
    }>>>;
}, z.core.$strip>;
export type LegacySynthesizeQuery = z.infer<typeof LegacySynthesizeQuerySchema>;
