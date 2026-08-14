"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.resolveSpeaker = exports.toSpeakerInfoList = exports.filterSpeakerInfoList = exports.normalizeLanguageCode = exports.parseSpeaker = void 0;
const capcutSpeakers_1 = require("../../models/capcutSpeakers");
const responseUtils_1 = require("../../lib/capcut/responseUtils");
const capcutVoiceCategories_1 = require("../../models/capcutVoiceCategories");
const isRecord = (value) => typeof value === 'object' && value !== null;
const asString = (value) => {
    if (typeof value === 'string') {
        return value;
    }
    if (typeof value === 'number' || typeof value === 'bigint') {
        return String(value);
    }
    return null;
};
/**
 * tonetype.name 例 id-female から言語コードを拾う
 * 空文字のことが多いので補助扱い
 */
const languageFromToneTypeName = (name) => {
    const match = name?.match(/^([a-z]{2,3})[-_]/i);
    return match?.[1]?.toLowerCase() ?? null;
};
/**
 * tag_list から言語コードを拾う
 * 実カタログでは言語がタグにしか出ない話者が多い
 */
const languageFromTagList = (tagList) => {
    if (!Array.isArray(tagList)) {
        return null;
    }
    for (const tag of tagList) {
        const name = isRecord(tag) ? asString(tag.name) : null;
        const matched = name
            ? capcutVoiceCategories_1.capCutTagLanguages[name.trim().toLowerCase()] ??
                capcutVoiceCategories_1.capCutTagLanguages[name.trim()]
            : null;
        if (matched) {
            return matched;
        }
    }
    return null;
};
/**
 * CapCut の voice item から内部 Speaker へ変換する
 * extra と biz_extra の両方を見て title description speaker を拾う
 *
 * @param item - CapCut の effect_item
 * @param categoryKey - 取得元カテゴリの category_key
 */
const parseSpeaker = (item, categoryKey) => {
    if (!isRecord(item)) {
        return null;
    }
    const commonAttr = isRecord(item.common_attr) ? item.common_attr : null;
    if (!commonAttr) {
        return null;
    }
    // extra biz_extra は common_attr 配下にある 念のため item 直下も見る
    const extra = (0, responseUtils_1.parseNestedJsonRecord)(commonAttr.extra) ?? (0, responseUtils_1.parseNestedJsonRecord)(item.extra);
    const bizExtra = (0, responseUtils_1.parseNestedJsonRecord)(commonAttr.biz_extra) ??
        (0, responseUtils_1.parseNestedJsonRecord)(item.biz_extra);
    const toneType = (0, responseUtils_1.parseNestedJsonRecord)(extra?.tonetype);
    const voiceAlias = asString(extra?.voice_alias_name) ?? asString(bizExtra?.voice_alias_name);
    const title = asString(commonAttr.title);
    const speaker = asString(toneType?.voice_type) ??
        JSON.stringify(item).match(/ICL_[A-Za-z0-9_]+|BV\d+_streaming|jp_\d+/)?.[0] ??
        null;
    const description = asString(commonAttr.description) ??
        voiceAlias ??
        speaker ??
        'CapCut voice preset';
    const effectId = asString(commonAttr.effect_id) ?? asString(commonAttr.id) ?? null;
    const resourceId = asString(commonAttr.third_resource_id_str) ??
        asString(commonAttr.third_resource_id) ??
        effectId;
    if (!title || !effectId || !resourceId || !speaker) {
        return null;
    }
    const resolvedLanguage = languageFromToneTypeName(asString(toneType?.name)) ??
        languageFromSpeakerId(speaker) ??
        languageFromTagList(commonAttr.tag_list) ??
        (categoryKey ? (capcutVoiceCategories_1.capCutCategoryLanguages[categoryKey] ?? null) : null);
    const language = resolvedLanguage
        ? (0, exports.normalizeLanguageCode)(resolvedLanguage)
        : 'unknown';
    return {
        title,
        description,
        speaker,
        effectId,
        resourceId,
        style: '',
        language,
        categories: categoryKey ? [categoryKey] : [],
        platform: asString(toneType?.platform) ?? undefined,
    };
};
exports.parseSpeaker = parseSpeaker;
/**
 * speaker ID から言語コードを拾う 拾えなければ null
 */
const languageFromSpeakerId = (speaker) => {
    const match = speaker.match(/^(?:ICL_)?([a-z]{2})[_-]/i);
    return match?.[1]?.toLowerCase() ?? null;
};
const envLanguageFromSpeaker = (speaker) => languageFromSpeakerId(speaker) ?? 'unknown';
/**
 * 言語コードか国コードを言語コードへ正規化する
 * vn jp のような国コードでも引けるようにしておく
 */
const normalizeLanguageCode = (value) => {
    const normalized = value.trim().toLowerCase().replace(/_/g, '-');
    const base = normalized.split('-')[0] ?? normalized;
    return capcutVoiceCategories_1.capCutCountryLanguages[normalized] ?? capcutVoiceCategories_1.capCutCountryLanguages[base] ?? base;
};
exports.normalizeLanguageCode = normalizeLanguageCode;
/**
 * 話者一覧を言語 カテゴリで絞り込む
 */
const filterSpeakerInfoList = (speakers, filter) => {
    const language = filter.language
        ? (0, exports.normalizeLanguageCode)(filter.language)
        : null;
    const category = filter.category?.trim().toLowerCase() ?? null;
    return speakers.filter((speaker) => {
        if (language && (0, exports.normalizeLanguageCode)(speaker.language) !== language) {
            return false;
        }
        if (category &&
            !speaker.categories.some((key) => key.toLowerCase() === category)) {
            return false;
        }
        return true;
    });
};
exports.filterSpeakerInfoList = filterSpeakerInfoList;
/**
 * 利用可能話者一覧向けに重複を除去して整形する
 */
const toSpeakerInfoList = (speakers) => {
    const seen = new Set();
    return speakers
        .filter((resolvedSpeaker) => {
        if (seen.has(resolvedSpeaker.resourceId)) {
            return false;
        }
        seen.add(resolvedSpeaker.resourceId);
        return true;
    })
        .map((resolvedSpeaker) => ({
        id: resolvedSpeaker.speaker,
        resourceId: resolvedSpeaker.resourceId,
        effectId: resolvedSpeaker.effectId,
        name: resolvedSpeaker.title,
        description: resolvedSpeaker.description,
        style: resolvedSpeaker.style || '',
        language: resolvedSpeaker.language ||
            envLanguageFromSpeaker(resolvedSpeaker.speaker),
        categories: resolvedSpeaker.categories ?? [],
        platform: resolvedSpeaker.platform ?? '',
    }));
};
exports.toSpeakerInfoList = toSpeakerInfoList;
const findSpeaker = (targetSpeaker, speakers) => {
    const normalizedTarget = targetSpeaker.toLowerCase();
    return speakers.find((resolvedSpeaker) => resolvedSpeaker.effectId.toLowerCase() === normalizedTarget ||
        resolvedSpeaker.resourceId.toLowerCase() === normalizedTarget ||
        resolvedSpeaker.speaker.toLowerCase() === normalizedTarget ||
        resolvedSpeaker.title.toLowerCase() === normalizedTarget);
};
/**
 * speaker と type 指定から使う Speaker を解決する
 */
const resolveSpeaker = (type, speakers, requestedSpeaker, requestedPlatform) => {
    if (requestedSpeaker) {
        const normalizedSpeaker = requestedSpeaker.trim().toLowerCase();
        const targetSpeaker = capcutSpeakers_1.speakerAliases[normalizedSpeaker] ?? normalizedSpeaker;
        const matchedSpeaker = findSpeaker(targetSpeaker, speakers) ??
            findSpeaker(targetSpeaker, capcutSpeakers_1.fallbackSpeakers);
        if (matchedSpeaker) {
            return requestedPlatform
                ? { ...matchedSpeaker, platform: requestedPlatform }
                : matchedSpeaker;
        }
        // platform を明示されたらカタログ外の voice ID もそのまま通す
        // CapCut の 11labs 系 voice_type は ElevenLabs の voice ID そのものなので
        // 自前の ID を試せるようにしておく
        if (requestedPlatform) {
            const rawSpeaker = requestedSpeaker.trim();
            return {
                title: rawSpeaker,
                description: `Passthrough voice on ${requestedPlatform}`,
                speaker: rawSpeaker,
                effectId: rawSpeaker,
                resourceId: rawSpeaker,
                style: '',
                language: 'unknown',
                categories: [],
                platform: requestedPlatform,
            };
        }
    }
    if (typeof type === 'string') {
        const normalizedType = type.trim();
        if (/^\d+$/.test(normalizedType)) {
            const legacyIndex = Number(normalizedType);
            return (capcutSpeakers_1.fallbackSpeakers[legacyIndex] ??
                speakers[legacyIndex] ??
                capcutSpeakers_1.fallbackSpeakers[0]);
        }
        const targetSpeaker = capcutSpeakers_1.speakerAliases[normalizedType.toLowerCase()] ?? normalizedType;
        const matchedSpeaker = findSpeaker(targetSpeaker, speakers) ??
            findSpeaker(targetSpeaker, capcutSpeakers_1.fallbackSpeakers);
        if (matchedSpeaker) {
            return matchedSpeaker;
        }
    }
    const legacyIndex = typeof type === 'number' ? type : 0;
    return (capcutSpeakers_1.fallbackSpeakers[legacyIndex] ??
        speakers[legacyIndex] ??
        capcutSpeakers_1.fallbackSpeakers[0]);
};
exports.resolveSpeaker = resolveSpeaker;
//# sourceMappingURL=voiceUtils.js.map