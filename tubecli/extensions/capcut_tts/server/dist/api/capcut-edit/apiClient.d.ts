import type { ApiRequester } from '../../types/api';
interface CapCutEditRequestOptions {
    requester: ApiRequester;
    path: string;
    searchParams?: Record<string, string>;
    method?: 'GET' | 'POST';
    headers?: HeadersInit;
    body?: BodyInit | null;
}
export declare const createEditApiSignature: (requestUrl: string, platformId: string, appVersion: string, tdid?: string, recipe?: Partial<{
    prefix: string;
    suffix: string;
    pathTailLength: number;
}>) => {
    sign: string;
    deviceTime: string;
};
export declare const CapCutEditApiClient: {
    resolveUrl: (path: string, searchParams?: Record<string, string>) => string;
    request: ({ requester, path, searchParams, method, headers, body, }: CapCutEditRequestOptions) => Promise<Response>;
};
export {};
