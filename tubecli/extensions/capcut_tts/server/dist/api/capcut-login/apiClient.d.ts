import type { ApiRequester } from '../../types/api';
interface CapCutLoginRequestOptions {
    requester: ApiRequester;
    host: string;
    path: string;
    searchParams?: Record<string, string>;
    method?: 'GET' | 'POST';
    headers?: HeadersInit;
    body?: BodyInit | null;
}
export declare const CapCutLoginApiClient: {
    resolveUrl: (host: string, path: string, searchParams?: Record<string, string>) => string;
    request: ({ requester, host, path, searchParams, method, headers, body, }: CapCutLoginRequestOptions) => Promise<Response>;
};
export {};
