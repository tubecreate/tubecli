import { Hono } from 'hono';
import type { D1Like } from '../../lib/storage/sessionStore';
import type { R2BucketLike } from '../../lib/storage';
export interface AdminDeps {
    db?: D1Like;
    adminToken?: string;
    encKey?: string;
    sessionBasePath: string;
    /** 試聴した音声を貯めておくバケット */
    bucket?: R2BucketLike;
    /** 合成を 1 回試して疎通を見る */
    probe: (email: string, password: string) => Promise<{
        ok: boolean;
        detail: string;
    }>;
    /** 管理画面の試聴用 話者一覧 */
    listVoices: (email: string, password: string, language?: string) => Promise<unknown[]>;
    /** 管理画面の試聴用 合成 資格情報はサーバー側だけで扱う */
    synthesize: (email: string, password: string, options: {
        text: string;
        speaker: string;
        speed: number;
        volume: number;
        timestamps: boolean;
    }) => Promise<{
        audio: string;
        contentType: string;
        words?: Array<{
            word: string;
            start: number;
            end: number;
        }>;
        duration?: number | null;
    }>;
}
/**
 * 管理 UI と管理 API
 *
 * 公開 URL に置く以上、トークン無しでは何も返さない
 * トークンは Authorization: Bearer か admin_token クッキーで受ける
 */
export declare const createAdminRoutes: (getDeps: () => AdminDeps) => Hono<import("hono/types").BlankEnv, import("hono/types").BlankSchema, "/">;
