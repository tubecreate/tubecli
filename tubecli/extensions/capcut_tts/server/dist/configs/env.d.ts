import { z } from 'zod';
declare const envSchema: z.ZodObject<{
    HOST: z.ZodDefault<z.ZodString>;
    PORT: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    CORS_POLICY_ORIGIN: z.ZodOptional<z.ZodString>;
    ORIGIN: z.ZodOptional<z.ZodString>;
    CAPCUT_WEB_URL: z.ZodDefault<z.ZodString>;
    CAPCUT_EDIT_API_URL: z.ZodDefault<z.ZodString>;
    CAPCUT_LOGIN_HOST: z.ZodDefault<z.ZodString>;
    CAPCUT_FALLBACK_LOGIN_HOST: z.ZodDefault<z.ZodString>;
    CAPCUT_EMAIL: z.ZodString;
    CAPCUT_PASSWORD: z.ZodString;
    CAPCUT_LOCALE: z.ZodDefault<z.ZodString>;
    CAPCUT_PAGE_LOCALE: z.ZodDefault<z.ZodString>;
    CAPCUT_REGION: z.ZodDefault<z.ZodString>;
    CAPCUT_STORE_COUNTRY_CODE: z.ZodDefault<z.ZodString>;
    CAPCUT_DEVICE_ID: z.ZodOptional<z.ZodString>;
    CAPCUT_TDID: z.ZodOptional<z.ZodString>;
    CAPCUT_VERIFY_FP: z.ZodOptional<z.ZodString>;
    CAPCUT_BUNDLE_CONFIG_PATH: z.ZodDefault<z.ZodString>;
    CAPCUT_VOICE_CATEGORY_ID: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    CAPCUT_SESSION_STORE_PATH: z.ZodDefault<z.ZodString>;
    CAPCUT_SPEAKER_PREVIEW_TEMP_DIR: z.ZodDefault<z.ZodString>;
    CAPCUT_SPEAKER_PREVIEW_TEXT: z.ZodDefault<z.ZodString>;
    CAPCUT_SPEAKER_PREVIEW_MAX_AGE_DAYS: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    CAPCUT_TTS_TEXT_CHUNK_BOUNDARY_SEARCH_RATIO: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    LEGACY_CAPCUT_API_URL: z.ZodDefault<z.ZodString>;
    LEGACY_BYTEINTL_API_URL: z.ZodDefault<z.ZodString>;
    LEGACY_DEVICE_TIME: z.ZodOptional<z.ZodString>;
    LEGACY_SIGN: z.ZodOptional<z.ZodString>;
    LEGACY_TOKEN_INTERVAL: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    USER_AGENT: z.ZodDefault<z.ZodString>;
    LOG_LEVEL: z.ZodDefault<z.ZodEnum<{
        silly: "silly";
        trace: "trace";
        debug: "debug";
        info: "info";
        warn: "warn";
        error: "error";
        fatal: "fatal";
    }>>;
    ERROR_HANDLE: z.ZodPipe<z.ZodTransform<string, unknown>, z.ZodPipe<z.ZodEnum<{
        true: "true";
        false: "false";
    }>, z.ZodTransform<boolean, "true" | "false">>>;
    SESSION_REFRESH_INTERVAL_MINUTES: z.ZodDefault<z.ZodCoercedNumber<unknown>>;
    CAPCUT_EXCLUDE_BROKEN_VOICES: z.ZodPipe<z.ZodTransform<string, unknown>, z.ZodPipe<z.ZodEnum<{
        true: "true";
        false: "false";
    }>, z.ZodTransform<boolean, "true" | "false">>>;
    CAPCUT_ALLOW_REQUEST_CREDENTIALS: z.ZodPipe<z.ZodTransform<string, unknown>, z.ZodPipe<z.ZodEnum<{
        true: "true";
        false: "false";
    }>, z.ZodTransform<boolean, "true" | "false">>>;
}, z.core.$strip>;
type ParsedEnv = z.infer<typeof envSchema>;
export type AppEnv = ParsedEnv & {
    CORS_POLICY_ORIGIN: string;
};
/**
 * 環境変数の供給元を差し替える
 *
 * Cloudflare Workers には process.env が無く、値は fetch ハンドラの
 * bindings 経由で届く そのため実際の解決を初回アクセスまで遅らせ、
 * Worker 側から先に注入できるようにしている
 */
export declare const setEnvSource: (source: Record<string, unknown>) => void;
/**
 * 解決済みの環境変数を返す 未解決ならここで解決する
 */
export declare const getEnv: () => AppEnv;
declare const env: AppEnv;
export default env;
