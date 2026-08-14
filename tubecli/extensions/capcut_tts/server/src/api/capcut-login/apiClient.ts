import type { ApiRequester } from '@/types/api';

interface CapCutLoginRequestOptions {
  requester: ApiRequester;
  host: string;
  path: string;
  searchParams?: Record<string, string>;
  method?: 'GET' | 'POST';
  headers?: HeadersInit;
  body?: BodyInit | null;
}

const resolveUrl = (
  host: string,
  path: string,
  searchParams: Record<string, string> = {}
) => {
  const url = new URL(path, host);

  for (const [key, value] of Object.entries(searchParams)) {
    url.searchParams.set(key, value);
  }

  return url.toString();
};

/**
 * login ドメイン向けの共通リクエスト
 */
const request = async ({
  requester,
  host,
  path,
  searchParams = {},
  method = 'GET',
  headers,
  body,
}: CapCutLoginRequestOptions) =>
  requester(resolveUrl(host, path, searchParams), {
    method,
    headers,
    body,
  });

export const CapCutLoginApiClient = {
  resolveUrl,
  request,
};
