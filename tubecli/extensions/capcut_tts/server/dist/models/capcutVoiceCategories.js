"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.capCutCountryLanguages = exports.capCutLanguageCountries = exports.capCutTagLanguages = exports.capCutCategoryLanguages = exports.capCutVoiceCategoryIds = void 0;
/**
 * 音声カテゴリの最終手段フォールバック
 *
 * CapCut 側でカテゴリ ID は入れ替わるため、通常は
 * /artist/v1/panel/get_panel_info から実行時に取得する
 * ここの値はその取得が失敗したときだけ使う
 */
exports.capCutVoiceCategoryIds = [
    30313, 2037708788, 21695, 21926, 36152, 23648, 33087, 30546, 33074, 33076,
    33077, 41169,
];
/**
 * カテゴリキーから言語コードへの対応
 * CapCut は言語カテゴリを英語名や現地名の混在で持つのでここで正規化する
 */
exports.capCutCategoryLanguages = {
    english: 'en',
    japanese: 'ja',
    riyu: 'ja',
    korean: 'ko',
    hanyu: 'ko',
    zhongwen: 'zh',
    chinese: 'zh',
    vietnamese: 'vi',
    yuenan: 'vi',
    indonesian: 'id',
    yinni: 'id',
    thai: 'th',
    taiyu: 'th',
    spanish: 'es',
    xibanya: 'es',
    portuguese: 'pt',
    putaoya: 'pt',
    french: 'fr',
    fayu: 'fr',
    german: 'de',
    deyu: 'de',
    italian: 'it',
    russian: 'ru',
    arabic: 'ar',
    hindi: 'hi',
    turkish: 'tr',
    malay: 'ms',
    filipino: 'fil',
};
/**
 * CapCut の tag_list に出る言語タグから言語コードへの対応
 *
 * 実際のカタログでは言語情報がタグにしか出ない話者が多いため
 * ここが言語判定の主力になる 中国語表記と英語表記が混在する
 */
exports.capCutTagLanguages = {
    英语: 'en',
    美式口音: 'en',
    英式口音: 'en',
    english: 'en',
    西班牙语: 'es',
    spanish: 'es',
    葡萄牙语: 'pt',
    portuguese: 'pt',
    印尼语: 'id',
    indonesian: 'id',
    越南语: 'vi',
    vietnamese: 'vi',
    泰语: 'th',
    thai: 'th',
    中文: 'zh',
    中国语: 'zh',
    chinese: 'zh',
    日语: 'ja',
    japanese: 'ja',
    韩语: 'ko',
    korean: 'ko',
    法语: 'fr',
    french: 'fr',
    德语: 'de',
    german: 'de',
    意大利语: 'it',
    italian: 'it',
    俄语: 'ru',
    russian: 'ru',
    阿拉伯语: 'ar',
    arabic: 'ar',
    印地语: 'hi',
    hindi: 'hi',
    土耳其语: 'tr',
    turkish: 'tr',
    马来语: 'ms',
    malay: 'ms',
};
/**
 * 言語コードから代表的な国コードへの対応
 * 国名で絞り込みたいとき用の補助
 */
exports.capCutLanguageCountries = {
    en: ['us', 'gb', 'au'],
    ja: ['jp'],
    ko: ['kr'],
    zh: ['cn', 'tw'],
    vi: ['vn'],
    id: ['id'],
    th: ['th'],
    es: ['es', 'mx'],
    pt: ['pt', 'br'],
    fr: ['fr'],
    de: ['de'],
    it: ['it'],
    ru: ['ru'],
    ar: ['sa'],
    hi: ['in'],
    tr: ['tr'],
    ms: ['my'],
    fil: ['ph'],
};
/**
 * 国コードから言語コードを引く逆引き表
 */
exports.capCutCountryLanguages = Object.entries(exports.capCutLanguageCountries).reduce((acc, [language, countries]) => {
    for (const country of countries) {
        acc[country] = language;
    }
    return acc;
}, {});
//# sourceMappingURL=capcutVoiceCategories.js.map