import type { SpeakerFilter, SpeakerInfo, Speaker } from '../../types/capcut';
/**
 * CapCut の voice item から内部 Speaker へ変換する
 * extra と biz_extra の両方を見て title description speaker を拾う
 *
 * @param item - CapCut の effect_item
 * @param categoryKey - 取得元カテゴリの category_key
 */
export declare const parseSpeaker: (item: unknown, categoryKey?: string) => Speaker | null;
/**
 * 言語コードか国コードを言語コードへ正規化する
 * vn jp のような国コードでも引けるようにしておく
 */
export declare const normalizeLanguageCode: (value: string) => string;
/**
 * 話者一覧を言語 カテゴリで絞り込む
 */
export declare const filterSpeakerInfoList: (speakers: SpeakerInfo[], filter: SpeakerFilter) => SpeakerInfo[];
/**
 * 利用可能話者一覧向けに重複を除去して整形する
 */
export declare const toSpeakerInfoList: (speakers: Speaker[]) => SpeakerInfo[];
/**
 * speaker と type 指定から使う Speaker を解決する
 */
export declare const resolveSpeaker: (type: number | string, speakers: Speaker[], requestedSpeaker?: string, requestedPlatform?: string) => Speaker;
