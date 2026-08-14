import type { ApiRequester } from '../../../types/api';
interface GetVoiceModelsParams {
    requester: ApiRequester;
    path?: string;
    searchParams: Record<string, string>;
    headers: HeadersInit;
    body: BodyInit;
}
/**
 * 音声モデル一覧を取得する
 */
export declare const getVoiceModels: ({ requester, path, searchParams, headers, body, }: GetVoiceModelsParams) => Promise<Response>;
export {};
