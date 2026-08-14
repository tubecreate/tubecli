import { CapCutEditApiClient } from '@/api/capcut-edit/apiClient';
import type { ApiRequester } from '@/types/api';

interface GetUserWorkspacesParams {
  requester: ApiRequester;
  path?: string;
  headers: HeadersInit;
  body: BodyInit;
}

/**
 * ワークスペース一覧を取得する
 */
export const getUserWorkspaces = ({
  requester,
  path,
  headers,
  body,
}: GetUserWorkspacesParams) =>
  CapCutEditApiClient.request({
    requester,
    path: path ?? '/cc/v1/workspace/get_user_workspaces',
    method: 'POST',
    headers,
    body,
  });
