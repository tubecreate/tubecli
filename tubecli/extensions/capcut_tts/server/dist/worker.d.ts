import { Hono } from 'hono';
import type { D1Like } from './lib/storage/sessionStore';
import type { R2BucketLike } from './lib/storage';
import { getCapCutService } from './services/CapCutService';
/**
 * wrangler.toml で宣言する bindings
 */
export interface WorkerBindings extends Record<string, unknown> {
    /** プレビュー音声の置き場 */
    CAPCUT_BUCKET: R2BucketLike;
    /** セッションを 1 行で共有する 全 isolate で 1 セッションにするため */
    CAPCUT_DB?: D1Like;
    /** 管理 UI のアクセストークン 無ければ管理 UI は動かない */
    ADMIN_TOKEN?: string;
    /** 資格情報の暗号化キー */
    ADMIN_ENC_KEY?: string;
}
type Vars = {
    capcutService?: ReturnType<typeof getCapCutService>;
};
declare const app: Hono<{
    Bindings: WorkerBindings;
    Variables: Vars;
}, import("hono/types").BlankSchema, "/">;
export default app;
