import { CapCutLoginApiClient } from '@/api/capcut-login/apiClient';
import type { ApiRequester } from '@/types/api';

interface EmailLoginParams {
  requester: ApiRequester;
  host: string;
  path?: string;
  searchParams: Record<string, string>;
  headers: HeadersInit;
  body: BodyInit;
}

/**
 * email/password ログイン API を呼ぶ
 */
export const emailLogin = (params: EmailLoginParams) =>
  CapCutLoginApiClient.request({
    ...params,
    path: params.path ?? '/passport/web/email/login/',
    method: 'POST',
  });
