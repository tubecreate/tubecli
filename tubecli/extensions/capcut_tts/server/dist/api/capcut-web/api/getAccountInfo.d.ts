import type { ApiRequester } from '../../../types/api';
interface GetAccountInfoParams {
    requester: ApiRequester;
    path?: string;
    searchParams: Record<string, string>;
    headers: HeadersInit;
}
/**
 * ログイン済みアカウント情報を取得する
 */
export declare const getAccountInfo: ({ requester, path, searchParams, headers, }: GetAccountInfoParams) => Promise<Response>;
export {};
