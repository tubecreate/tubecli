import type { Speaker } from '../types/capcut';
/**
 * HAR から確認できた代表的な音声のフォールバック一覧
 * 基本は取得してきたものを利用する
 */
export declare const fallbackSpeakers: Speaker[];
/**
 * ユーザー向け別名から resourceId へ解決する辞書
 */
export declare const speakerAliases: Record<string, string>;
