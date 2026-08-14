import env from '@/configs/env';
import type { CapCutCredentials } from '@/services/CapCutService';

const asTrimmedString = (value: unknown): string | undefined => {
  const raw = Array.isArray(value) ? value[0] : value;

  if (typeof raw !== 'string') {
    return undefined;
  }

  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

/**
 * リクエスト由来の CapCut 資格情報を取り出す
 *
 * ヘッダ x-capcut-email / x-capcut-password を優先し、
 * 無ければ body や query の capcutEmail / capcutPassword を見る。
 * 片方だけ来た場合は不完全なので無視して既定アカウントへ倒す。
 *
 * CAPCUT_ALLOW_REQUEST_CREDENTIALS=false のときは常に既定アカウントを使う。
 */
export const extractRequestCredentials = (sources: {
  headers?: Record<string, unknown> | undefined;
  body?: Record<string, unknown> | undefined;
  query?: Record<string, unknown> | undefined;
}): CapCutCredentials | null => {
  if (!env.CAPCUT_ALLOW_REQUEST_CREDENTIALS) {
    return null;
  }

  const email =
    asTrimmedString(sources.headers?.['x-capcut-email']) ??
    asTrimmedString(sources.body?.capcutEmail) ??
    asTrimmedString(sources.query?.capcutEmail);
  const password =
    asTrimmedString(sources.headers?.['x-capcut-password']) ??
    asTrimmedString(sources.body?.capcutPassword) ??
    asTrimmedString(sources.query?.capcutPassword);

  if (!email || !password) {
    return null;
  }

  return { email, password };
};
