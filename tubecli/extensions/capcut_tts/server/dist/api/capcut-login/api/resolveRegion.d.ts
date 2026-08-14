import type { ApiRequester } from '../../../types/api';
interface ResolveRegionParams {
    requester: ApiRequester;
    host: string;
    path?: string;
    searchParams: Record<string, string>;
    headers: HeadersInit;
    body: BodyInit;
}
/**
 * email から login host を解決する API を呼ぶ
 */
export declare const resolveRegion: (params: ResolveRegionParams) => Promise<Response>;
export {};
