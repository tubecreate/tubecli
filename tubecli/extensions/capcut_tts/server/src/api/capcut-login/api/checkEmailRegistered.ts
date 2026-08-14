import { CapCutLoginApiClient } from '@/api/capcut-login/apiClient';
import type { ApiRequester } from '@/types/api';

interface CheckEmailRegisteredParams {
  requester: ApiRequester;
  host: string;
  searchParams: Record<string, string>;
  headers: HeadersInit;
  body: BodyInit;
}

/**
 * email 登録状態確認 API を呼ぶ
 */
export const checkEmailRegistered = ({
  requester,
  host,
  searchParams,
  headers,
  body,
}: CheckEmailRegisteredParams) =>
  CapCutLoginApiClient.request({
    requester,
    host,
    path: '/passport/web/user/check_email_registered',
    searchParams,
    method: 'POST',
    headers,
    body,
  });
