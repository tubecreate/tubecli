import { CapCutWebApiClient } from '@/api/capcut-web/apiClient';
import type { ApiRequester } from '@/types/api';

interface GetLoginPageParams {
  requester: ApiRequester;
  path: string;
  headers: HeadersInit;
}

/**
 * login ページを取得して初期 Cookie を得る
 */
export const getLoginPage = ({ requester, path, headers }: GetLoginPageParams) =>
  CapCutWebApiClient.request({
    requester,
    path,
    method: 'GET',
    headers,
  });
