import env from '@/configs/env';
import type { ApiRequester } from '@/types/api';

interface CapCutWebRequestOptions {
  requester: ApiRequester;
  path: string;
  searchParams?: Record<string, string>;
  method?: 'GET' | 'POST';
  headers?: HeadersInit;
  body?: BodyInit | null;
}

const resolveUrl = (
  path: string,
  searchParams: Record<string, string> = {}
) => {
  const url = new URL(path, env.CAPCUT_WEB_URL);

  for (const [key, value] of Object.entries(searchParams)) {
    url.searchParams.set(key, value);
  }

  return url.toString();
};

/**
 * web ドメイン向けの共通リクエスト
 */
const request = async ({
  requester,
  path,
  searchParams = {},
  method = 'GET',
  headers,
  body,
}: CapCutWebRequestOptions) =>
  requester(resolveUrl(path, searchParams), {
    method,
    headers,
    body,
  });

export const CapCutWebApiClient = {
  resolveUrl,
  request,
};
