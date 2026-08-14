import type { ApiRequester } from '../../types/api';
interface CapCutWebRequestOptions {
    requester: ApiRequester;
    path: string;
    searchParams?: Record<string, string>;
    method?: 'GET' | 'POST';
    headers?: HeadersInit;
    body?: BodyInit | null;
}
export declare const CapCutWebApiClient: {
    resolveUrl: (path: string, searchParams?: Record<string, string>) => string;
    request: ({ requester, path, searchParams, method, headers, body, }: CapCutWebRequestOptions) => Promise<Response>;
};
export {};
