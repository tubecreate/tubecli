/**
 * CapCut のログイン応答
 */
export interface LoginResponse {
  sec_user_id?: string;
  screen_name?: string;
  user_id?: string | number;
  user_id_str?: string | number;
}

/**
 * CapCut のアカウント情報
 */
export interface AccountInfo {
  user_id?: string | number;
  screen_name?: string;
}

/**
 * CapCut のワークスペース情報
 */
export interface WorkspaceInfo {
  workspace_id: string;
  role?: string;
}

/**
 * ワークスペース一覧応答
 */
export interface WorkspaceListResponse {
  workspace_infos?: WorkspaceInfo[];
}

/**
 * 音声モデル一覧応答
 * サーバー側でページサイズが抑えられるため has_more next_offset で追従する
 */
export interface VoiceListResponse {
  effect_item_list?: unknown[];
  has_more?: boolean;
  next_offset?: number;
}

/**
 * 音声パネルのカテゴリ
 */
export interface VoicePanelCategory {
  category_id?: number;
  category_key?: string;
  category_name?: string;
}

/**
 * 音声パネル情報応答
 */
export interface VoicePanelInfoResponse {
  categories?: VoicePanelCategory[];
}

/**
 * TTS タスク作成応答
 */
export interface TtsTaskResponse {
  task_id?: string;
}

/**
 * TTS タスク詳細
 */
export interface TtsTaskDetail {
  url?: string;
  transcode_audio_info?: Array<{
    url?: string;
  }>;
}

/**
 * TTS タスク照会応答
 */
export interface TtsQueryResponse {
  status?: number;
  task_detail?: TtsTaskDetail[];
}

/**
 * リージョン解決応答
 */
export interface RegionResponse {
  country_code?: string;
  domain?: string;
}

/**
 * multi_platform TTS 応答
 */
export interface MultiPlatformTtsResponse {
  tts_materials?: Array<{
    meta_data?: {
      url?: string;
    };
  }>;
}
