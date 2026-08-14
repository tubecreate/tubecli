import type { CapCutSessionState } from '@/types/capcut';

/**
 * 永続化可能な Cookie 情報
 */
export interface StoredCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  expiresAt?: number;
  hostOnly: boolean;
  secure: boolean;
}

/**
 * 保存済み CapCut セッション情報
 */
export interface PersistedSessionState {
  session: CapCutSessionState | null;
  cookies: StoredCookie[];
  verifyFp: string;
  deviceId: string;
  tdid?: string;
}
