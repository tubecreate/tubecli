"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.isBrokenVoice = exports.brokenVoiceCombos = void 0;
exports.brokenVoiceCombos = [
    {
        language: 'vi',
        platform: '11labs',
        reason: 'Reads Vietnamese text in the wrong language (detected as Malay/Sinhala, 0% word match)',
    },
];
/**
 * カタログから除外すべき話者かを判定する
 */
const isBrokenVoice = (language, platform) => exports.brokenVoiceCombos.find((combo) => combo.language === (language ?? '').toLowerCase() &&
    combo.platform === (platform ?? '').toLowerCase());
exports.isBrokenVoice = isBrokenVoice;
//# sourceMappingURL=capcutVoiceQuality.js.map