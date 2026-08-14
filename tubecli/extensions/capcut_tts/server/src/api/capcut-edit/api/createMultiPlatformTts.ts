import { CapCutEditApiClient } from '@/api/capcut-edit/apiClient';
import type { ApiRequester } from '@/types/api';

interface CreateMultiPlatformTtsParams {
  requester: ApiRequester;
  path?: string;
  headers: HeadersInit;
  body: BodyInit;
}

/**
 * multi_platform TTS を実行する
 */
export const createMultiPlatformTts = ({
  requester,
  path,
  headers,
  body,
}: CreateMultiPlatformTtsParams) =>
  CapCutEditApiClient.request({
    requester,
    path: path ?? '/storyboard/v1/tts/multi_platform',
    method: 'POST',
    headers,
    body,
  });
