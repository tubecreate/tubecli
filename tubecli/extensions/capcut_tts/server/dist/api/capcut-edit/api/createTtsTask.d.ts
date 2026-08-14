import type { ApiRequester } from '../../../types/api';
interface CreateTtsTaskParams {
    requester: ApiRequester;
    path?: string;
    searchParams: Record<string, string>;
    headers: HeadersInit;
    body: BodyInit;
}
/**
 * editor intelligence TTS タスクを作成する
 */
export declare const createTtsTask: ({ requester, path, searchParams, headers, body, }: CreateTtsTaskParams) => Promise<Response>;
export {};
