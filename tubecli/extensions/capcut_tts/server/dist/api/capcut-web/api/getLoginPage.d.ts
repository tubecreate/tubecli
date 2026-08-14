import type { ApiRequester } from '../../../types/api';
interface GetLoginPageParams {
    requester: ApiRequester;
    path: string;
    headers: HeadersInit;
}
/**
 * login ページを取得して初期 Cookie を得る
 */
export declare const getLoginPage: ({ requester, path, headers }: GetLoginPageParams) => Promise<Response>;
export {};
