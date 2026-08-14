import type { ApiRequester } from '../../../types/api';
interface GetUserWorkspacesParams {
    requester: ApiRequester;
    path?: string;
    headers: HeadersInit;
    body: BodyInit;
}
/**
 * ワークスペース一覧を取得する
 */
export declare const getUserWorkspaces: ({ requester, path, headers, body, }: GetUserWorkspacesParams) => Promise<Response>;
export {};
