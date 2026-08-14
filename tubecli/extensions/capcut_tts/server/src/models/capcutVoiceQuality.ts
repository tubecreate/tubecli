/**
 * 実測で読み上げ品質が破綻している組み合わせ
 *
 * faster-whisper に言語自動判定させ、書き起こしを入力文と突き合わせて確認した。
 * ここに載せた組み合わせだけカタログから除外する。
 *
 * 計測 2026-08-03 faster-whisper medium 言語自動判定
 *   ja  sami    ja p=1.000  一致 94.4%   OK
 *   vi  sami    vi p=0.996  一致 88-94%  OK
 *   es  sami    es p=0.998  一致 86%     OK
 *   es  11labs  es p=0.946  一致 86%     OK
 *   en  sami    en p=0.986  一致 79%     OK  ※残りは固有名詞と数字表記の差
 *   en  11labs  en p=0.979  一致 79%     OK
 *   zh  sami    zh p=0.989  内容一致     OK  ※書き起こしが繁体字になるだけ
 *   id  sami    id p=0.987  一致 67%     OK
 *   th  sami    th p=0.967  一致 77%     OK
 *   vi  11labs  si p=0.314  一致 0%      破綻 ベトナム語をマレー語等として読む
 */
export interface BrokenVoiceCombo {
  language: string;
  platform: string;
  reason: string;
}

export const brokenVoiceCombos: BrokenVoiceCombo[] = [
  {
    language: 'vi',
    platform: '11labs',
    reason:
      'Reads Vietnamese text in the wrong language (detected as Malay/Sinhala, 0% word match)',
  },
];

/**
 * カタログから除外すべき話者かを判定する
 */
export const isBrokenVoice = (
  language: string | undefined,
  platform: string | undefined
): BrokenVoiceCombo | undefined =>
  brokenVoiceCombos.find(
    (combo) =>
      combo.language === (language ?? '').toLowerCase() &&
      combo.platform === (platform ?? '').toLowerCase()
  );
