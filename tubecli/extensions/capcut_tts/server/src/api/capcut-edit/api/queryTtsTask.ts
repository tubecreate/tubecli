import { CapCutEditApiClient } from '@/api/capcut-edit/apiClient';
import type { ApiRequester } from '@/types/api';

interface QueryTtsTaskParams {
  requester: ApiRequester;
  path?: string;
  searchParams: Record<string, string>;
  headers: HeadersInit;
  body: BodyInit;
}

/**
 * editor intelligence TTS タスク状態を照会する
 */
export const queryTtsTask = ({
  requester,
  path,
  searchParams,
  headers,
  body,
}: QueryTtsTaskParams) =>
  CapCutEditApiClient.request({
    requester,
    path: path ?? '/lv/v2/intelligence/query',
    searchParams,
    method: 'POST',
    headers,
    body,
  });
