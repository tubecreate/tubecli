import type { ApiRequester } from '../../types/api';
interface CapCutMediaRequestOptions {
    requester: ApiRequester;
    url: string;
    method?: 'GET' | 'POST';
    headers?: HeadersInit;
    body?: BodyInit | null;
}
export declare const CapCutMediaApiClient: {
    request: ({ requester, url, method, headers, body, }: CapCutMediaRequestOptions) => Promise<Response>;
};
export {};
