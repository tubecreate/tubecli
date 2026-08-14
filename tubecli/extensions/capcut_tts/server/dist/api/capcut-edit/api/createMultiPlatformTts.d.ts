import type { ApiRequester } from '../../../types/api';
interface CreateMultiPlatformTtsParams {
    requester: ApiRequester;
    path?: string;
    headers: HeadersInit;
    body: BodyInit;
}
/**
 * multi_platform TTS を実行する
 */
export declare const createMultiPlatformTts: ({ requester, path, headers, body, }: CreateMultiPlatformTtsParams) => Promise<Response>;
export {};
