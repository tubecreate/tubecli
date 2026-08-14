export interface LegacySynthesizeOptions {
  text: string;
  type: number;
  pitch: number;
  speed: number;
  volume: number;
}

export interface LegacySynthesizePayload {
  text: string;
  speaker: string;
  pitch: number;
  speed: number;
  volume: number;
  rate: number;
  appid: string;
}

export interface LegacySynthesizeTaskMessage {
  token: string;
  appkey: string;
  namespace: 'TTS';
  event: 'StartTask';
  payload: string;
}

export interface LegacyTaskStatus {
  task_id: string;
  message_id: string;
  namespace: string;
  event: string;
  status_code: number;
  status_text: string;
}

export interface LegacyTokenState {
  token: string;
  appKey: string;
  refreshedAt: number;
}

export interface LegacyGetTokenResponse {
  ret: string;
  errmsg: string;
  svr_time: number;
  log_id: string;
  data: {
    token: string;
    app_key: string;
  };
}
