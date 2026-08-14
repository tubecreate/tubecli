"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getEnv = exports.setEnvSource = void 0;
const zod_1 = require("zod");
const defaultUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36';
const booleanFlag = zod_1.z.preprocess((value) => {
    if (value === undefined) {
        return 'true';
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false';
    }
    return String(value).toLowerCase();
}, zod_1.z.enum(['true', 'false']).transform((value) => value === 'true'));
const logLevelSchema = zod_1.z
    .enum(['silly', 'trace', 'debug', 'info', 'warn', 'error', 'fatal'])
    .default('info');
const envSchema = zod_1.z
    .object({
    HOST: zod_1.z.string().default('0.0.0.0'),
    PORT: zod_1.z.coerce.number().int().positive().default(8080),
    CORS_POLICY_ORIGIN: zod_1.z.string().optional(),
    ORIGIN: zod_1.z.string().optional(),
    CAPCUT_WEB_URL: zod_1.z.string().url().default('https://www.capcut.com'),
    CAPCUT_EDIT_API_URL: zod_1.z
        .string()
        .url()
        .default('https://edit-api-sg.capcut.com'),
    CAPCUT_LOGIN_HOST: zod_1.z
        .string()
        .url()
        .default('https://login-row.www.capcut.com'),
    CAPCUT_FALLBACK_LOGIN_HOST: zod_1.z
        .string()
        .url()
        .default('https://login.us.capcut.com'),
    CAPCUT_EMAIL: zod_1.z.string().email('CAPCUT_EMAIL must be a valid email'),
    CAPCUT_PASSWORD: zod_1.z.string().min(1, 'CAPCUT_PASSWORD is required'),
    CAPCUT_LOCALE: zod_1.z.string().min(1).default('ja-JP'),
    CAPCUT_PAGE_LOCALE: zod_1.z.string().min(1).default('ja-jp'),
    CAPCUT_REGION: zod_1.z.string().min(1).default('JP'),
    CAPCUT_STORE_COUNTRY_CODE: zod_1.z.string().min(1).default('jp'),
    CAPCUT_DEVICE_ID: zod_1.z.string().min(1).optional(),
    CAPCUT_TDID: zod_1.z.string().min(1).optional(),
    CAPCUT_VERIFY_FP: zod_1.z.string().min(1).optional(),
    CAPCUT_BUNDLE_CONFIG_PATH: zod_1.z
        .string()
        .min(1)
        .default('capcut-bundle-config.json'),
    CAPCUT_VOICE_CATEGORY_ID: zod_1.z.coerce.number().int().positive().default(21699),
    CAPCUT_SESSION_STORE_PATH: zod_1.z.string().min(1).default('capcut-session.json'),
    CAPCUT_SPEAKER_PREVIEW_TEMP_DIR: zod_1.z
        .string()
        .min(1)
        .default('speaker-preview-temp'),
    CAPCUT_SPEAKER_PREVIEW_TEXT: zod_1.z
        .string()
        .min(1)
        .default('こんにちは、これは話者プレビューです。'),
    CAPCUT_SPEAKER_PREVIEW_MAX_AGE_DAYS: zod_1.z.coerce
        .number()
        .positive()
        .default(14),
    CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH: zod_1.z.coerce
        .number()
        .int()
        .positive()
        .default(100),
    CAPCUT_TTS_TEXT_CHUNK_BOUNDARY_SEARCH_RATIO: zod_1.z.coerce
        .number()
        .positive()
        .max(1)
        .default(0.6),
    LEGACY_CAPCUT_API_URL: zod_1.z
        .string()
        .url()
        .default('https://edit-api-sg.capcut.com/lv/v1'),
    LEGACY_BYTEINTL_API_URL: zod_1.z
        .string()
        .url()
        .default('wss://sami-sg1.byteintlapi.com/internal/api/v1'),
    LEGACY_DEVICE_TIME: zod_1.z.string().min(1).optional(),
    LEGACY_SIGN: zod_1.z.string().min(1).optional(),
    LEGACY_TOKEN_INTERVAL: zod_1.z.coerce.number().positive().default(6),
    USER_AGENT: zod_1.z.string().min(1).default(defaultUserAgent),
    LOG_LEVEL: logLevelSchema,
    ERROR_HANDLE: booleanFlag,
    SESSION_REFRESH_INTERVAL_MINUTES: zod_1.z.coerce.number().positive().default(10),
    /** 実測で読み上げが破綻している話者をカタログから除外するか */
    CAPCUT_EXCLUDE_BROKEN_VOICES: booleanFlag,
    /** リクエストごとの CapCut 資格情報の受け入れを許可するか */
    CAPCUT_ALLOW_REQUEST_CREDENTIALS: booleanFlag,
})
    .superRefine((value, ctx) => {
    const hasLegacyDeviceTime = Boolean(value.LEGACY_DEVICE_TIME);
    const hasLegacySign = Boolean(value.LEGACY_SIGN);
    if (hasLegacyDeviceTime !== hasLegacySign) {
        if (!hasLegacyDeviceTime) {
            ctx.addIssue({
                code: zod_1.z.ZodIssueCode.custom,
                path: ['LEGACY_DEVICE_TIME'],
                message: 'LEGACY_DEVICE_TIME is required when LEGACY_SIGN is provided',
            });
        }
        if (!hasLegacySign) {
            ctx.addIssue({
                code: zod_1.z.ZodIssueCode.custom,
                path: ['LEGACY_SIGN'],
                message: 'LEGACY_SIGN is required when LEGACY_DEVICE_TIME is provided',
            });
        }
    }
});
const resolve = (source) => {
    const parsedEnv = envSchema.safeParse(source);
    if (!parsedEnv.success) {
        const errorMessages = parsedEnv.error.issues
            .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
            .join(', ');
        throw new Error(`Invalid environment variables: ${errorMessages}`);
    }
    return {
        ...parsedEnv.data,
        CORS_POLICY_ORIGIN: parsedEnv.data.CORS_POLICY_ORIGIN ?? parsedEnv.data.ORIGIN ?? '*',
    };
};
let envSource = null;
let resolvedEnv = null;
/**
 * 環境変数の供給元を差し替える
 *
 * Cloudflare Workers には process.env が無く、値は fetch ハンドラの
 * bindings 経由で届く そのため実際の解決を初回アクセスまで遅らせ、
 * Worker 側から先に注入できるようにしている
 */
const setEnvSource = (source) => {
    envSource = source;
    resolvedEnv = null;
};
exports.setEnvSource = setEnvSource;
/**
 * 解決済みの環境変数を返す 未解決ならここで解決する
 */
const getEnv = () => {
    if (!resolvedEnv) {
        resolvedEnv = resolve(envSource ?? (typeof process !== 'undefined' ? process.env : {}));
    }
    return resolvedEnv;
};
exports.getEnv = getEnv;
// 既存の `env.X` という書き方をそのまま残すため Proxy で遅延解決する
const env = new Proxy({}, {
    get: (_target, property) => (0, exports.getEnv)()[property],
    has: (_target, property) => property in (0, exports.getEnv)(),
    ownKeys: () => Reflect.ownKeys((0, exports.getEnv)()),
    getOwnPropertyDescriptor: (_target, property) => Object.getOwnPropertyDescriptor((0, exports.getEnv)(), property),
});
exports.default = env;
//# sourceMappingURL=env.js.map