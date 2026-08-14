import { z } from 'zod';
export declare const SynthesizeQuerySchema: z.ZodObject<{
    text: z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodString>;
    type: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodUnion<readonly [z.ZodCoercedNumber<unknown>, z.ZodString]>>>;
    speaker: z.ZodOptional<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodString>>;
    pitch: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    speed: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    volume: z.ZodDefault<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodCoercedNumber<unknown>>>;
    method: z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodDefault<z.ZodEnum<{
        buffer: "buffer";
        stream: "stream";
    }>>>;
    platform: z.ZodOptional<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodString>>;
    timestamps: z.ZodOptional<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodPipe<z.ZodEnum<{
        true: "true";
        0: "0";
        false: "false";
        1: "1";
    }>, z.ZodTransform<boolean, "true" | "0" | "false" | "1">>>>;
    phonemes: z.ZodOptional<z.ZodPipe<z.ZodTransform<any, unknown>, z.ZodPipe<z.ZodEnum<{
        true: "true";
        0: "0";
        false: "false";
        1: "1";
    }>, z.ZodTransform<boolean, "true" | "0" | "false" | "1">>>>;
}, z.core.$strip>;
export declare const SynthesizeBodySchema: z.ZodObject<{
    text: z.ZodString;
    type: z.ZodDefault<z.ZodUnion<readonly [z.ZodCoercedNumber<unknown>, z.ZodString]>>;
    speaker: z.ZodOptional<z.ZodString>;
    pitch: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    speed: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    volume: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    method: z.ZodDefault<z.ZodEnum<{
        buffer: "buffer";
        stream: "stream";
    }>>;
    platform: z.ZodOptional<z.ZodString>;
    timestamps: z.ZodOptional<z.ZodCoercedBoolean<unknown>>;
    phonemes: z.ZodOptional<z.ZodCoercedBoolean<unknown>>;
}, z.core.$strip>;
export type SynthesizeQuery = z.infer<typeof SynthesizeQuerySchema>;
export type SynthesizeBody = z.infer<typeof SynthesizeBodySchema>;
