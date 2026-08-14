import type { ApiRequester } from '../../../types/api';
interface DownloadAudioParams {
    requester: ApiRequester;
    url: string;
    headers: HeadersInit;
}
/**
 * 音声ファイルを直接ダウンロードする
 */
export declare const downloadAudio: ({ requester, url, headers }: DownloadAudioParams) => Promise<Response>;
export {};
