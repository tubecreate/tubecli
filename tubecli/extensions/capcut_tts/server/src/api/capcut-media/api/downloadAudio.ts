import { CapCutMediaApiClient } from '@/api/capcut-media/apiClient';
import type { ApiRequester } from '@/types/api';

interface DownloadAudioParams {
  requester: ApiRequester;
  url: string;
  headers: HeadersInit;
}

/**
 * 音声ファイルを直接ダウンロードする
 */
export const downloadAudio = ({ requester, url, headers }: DownloadAudioParams) =>
  CapCutMediaApiClient.request({
    requester,
    url,
    method: 'GET',
    headers,
  });
