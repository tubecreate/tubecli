/**
 * 音声カテゴリの最終手段フォールバック
 *
 * CapCut 側でカテゴリ ID は入れ替わるため、通常は
 * /artist/v1/panel/get_panel_info から実行時に取得する
 * ここの値はその取得が失敗したときだけ使う
 */
export declare const capCutVoiceCategoryIds: readonly [30313, 2037708788, 21695, 21926, 36152, 23648, 33087, 30546, 33074, 33076, 33077, 41169];
/**
 * カテゴリキーから言語コードへの対応
 * CapCut は言語カテゴリを英語名や現地名の混在で持つのでここで正規化する
 */
export declare const capCutCategoryLanguages: Record<string, string>;
/**
 * CapCut の tag_list に出る言語タグから言語コードへの対応
 *
 * 実際のカタログでは言語情報がタグにしか出ない話者が多いため
 * ここが言語判定の主力になる 中国語表記と英語表記が混在する
 */
export declare const capCutTagLanguages: Record<string, string>;
/**
 * 言語コードから代表的な国コードへの対応
 * 国名で絞り込みたいとき用の補助
 */
export declare const capCutLanguageCountries: Record<string, string[]>;
/**
 * 国コードから言語コードを引く逆引き表
 */
export declare const capCutCountryLanguages: Record<string, string>;
