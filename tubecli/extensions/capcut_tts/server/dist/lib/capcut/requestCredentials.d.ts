import type { CapCutCredentials } from '../../services/CapCutService';
/**
 * リクエスト由来の CapCut 資格情報を取り出す
 *
 * ヘッダ x-capcut-email / x-capcut-password を優先し、
 * 無ければ body や query の capcutEmail / capcutPassword を見る。
 * 片方だけ来た場合は不完全なので無視して既定アカウントへ倒す。
 *
 * CAPCUT_ALLOW_REQUEST_CREDENTIALS=false のときは常に既定アカウントを使う。
 */
export declare const extractRequestCredentials: (sources: {
    headers?: Record<string, unknown> | undefined;
    body?: Record<string, unknown> | undefined;
    query?: Record<string, unknown> | undefined;
}) => CapCutCredentials | null;
