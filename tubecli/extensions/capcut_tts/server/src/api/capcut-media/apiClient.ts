import type { ApiRequester } from '@/types/api';

interface CapCutMediaRequestOptions {
  requester: ApiRequester;
  url: string;
  method?: 'GET' | 'POST';
  headers?: HeadersInit;
  body?: BodyInit | null;
}

/**
 * 音声ダウンロード向けの共通リクエスト
 */
const request = async ({
  requester,
  url,
  method = 'GET',
  headers,
  body,
}: CapCutMediaRequestOptions) =>
  requester(url, {
    method,
    headers,
    body,
  });

export const CapCutMediaApiClient = {
  request,
};
