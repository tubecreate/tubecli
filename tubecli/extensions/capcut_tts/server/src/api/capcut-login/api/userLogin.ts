import { CapCutLoginApiClient } from '@/api/capcut-login/apiClient';
import type { ApiRequester } from '@/types/api';

interface UserLoginParams {
  requester: ApiRequester;
  host: string;
  path?: string;
  searchParams: Record<string, string>;
  headers: HeadersInit;
  body: BodyInit;
}

/**
 * user/login 互換 API を呼ぶ
 */
export const userLogin = (params: UserLoginParams) =>
  CapCutLoginApiClient.request({
    ...params,
    path: params.path ?? '/passport/web/user/login/',
    method: 'POST',
  });
