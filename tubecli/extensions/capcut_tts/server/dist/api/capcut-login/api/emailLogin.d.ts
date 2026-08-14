import type { ApiRequester } from '../../../types/api';
interface EmailLoginParams {
    requester: ApiRequester;
    host: string;
    path?: string;
    searchParams: Record<string, string>;
    headers: HeadersInit;
    body: BodyInit;
}
/**
 * email/password ログイン API を呼ぶ
 */
export declare const emailLogin: (params: EmailLoginParams) => Promise<Response>;
export {};
