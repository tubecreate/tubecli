import type { Speaker } from '@/types/capcut';

/**
 * HAR から確認できた代表的な音声のフォールバック一覧
 * 基本は取得してきたものを利用する
 */
export const fallbackSpeakers: Speaker[] = [
  {
    title: 'ラベベさん',
    description: '英語の明るい女性ボイス',
    speaker: 'ICL_en_female_jiaoao',
    effectId: '7530105822785899777',
    resourceId: '7530105822785899777',
  },
  {
    title: '冷静なレディ',
    description: '英語の落ち着いた女性ボイス',
    speaker: 'ICL_en_female_guanggao',
    effectId: '7530107275239869713',
    resourceId: '7530107275239869713',
  },
  {
    title: 'ハッピーディノ',
    description: 'スペイン語の陽気な男性ボイス',
    speaker: 'ICL_es_male_barney',
    effectId: '7527795878967446801',
    resourceId: '7527795878967446801',
  },
  {
    title: 'おかしなあやつり人形',
    description: 'スペイン語のコミカルな男性ボイス',
    speaker: 'ICL_es_male_elmo',
    effectId: '7527814111502044433',
    resourceId: '7527814111502044433',
  },
  {
    title: 'モテ男',
    description: 'スペイン語の低めな男性ボイス',
    speaker: 'ICL_es_male_cixing',
    effectId: '7527779392769002769',
    resourceId: '7527779392769002769',
  },
  {
    title: '生意気な魔女',
    description: 'スペイン語のクセのある女性ボイス',
    speaker: 'ICL_es_female_dianpo',
    effectId: '7527846655475928336',
    resourceId: '7527846655475928336',
  },
  {
    title: 'ゲームホスト',
    description: 'スペイン語の軽快な男性ボイス',
    speaker: 'ICL_es_male_dorado',
    effectId: '7527778973296774416',
    resourceId: '7527778973296774416',
  },
  {
    title: '穏やかな吹き替え',
    description: 'スペイン語の穏やかな女性ボイス',
    speaker: 'ICL_es_female_dianyingpeiyin',
    effectId: '7527793325328452881',
    resourceId: '7527793325328452881',
  },
  {
    title: '濁声おじさん',
    description: '低く濁った男性ボイス',
    speaker: 'ICL_es_male_taici',
    effectId: '7522965008020507920',
    resourceId: '7522965008020507920',
  },
  {
    title: '魔婆',
    description: '年配女性風の日本語ボイス',
    speaker: 'ICL_ja_female_laopopo',
    effectId: '7522976550736710913',
    resourceId: '7522976550736710913',
  },
  {
    title: 'マネージャー',
    description: '早口で張りのある日本語ボイス',
    speaker: 'ICL_ja_female_kuaizui02',
    effectId: '7522976550736678145',
    resourceId: '7522976550736678145',
  },
  {
    title: '妹系',
    description: '若い女性寄りの日本語ボイス',
    speaker: 'ICL_ja_female_shuanglang',
    effectId: '7522987643752303889',
    resourceId: '7522987643752303889',
  },
  {
    title: '幼い女の子',
    description: '幼い少女風の日本語ボイス',
    speaker: 'ICL_jp_female_jidongshaonv',
    effectId: '7522965008020475152',
    resourceId: '7522965008020475152',
  },
  {
    title: '高テンション',
    description: '勢いのある日本語男性ボイス',
    speaker: 'ICL_ja_male_gaoxiao',
    effectId: '7522976550736661761',
    resourceId: '7522976550736661761',
  },
  {
    title: '真面目男',
    description: '落ち着いた日本語男性ボイス',
    speaker: 'ICL_ja_male_gaoxiao02',
    effectId: '7522987643752271121',
    resourceId: '7522987643752271121',
  },
];

/**
 * ユーザー向け別名から resourceId へ解決する辞書
 */
export const speakerAliases: Record<string, string> = {
  labebe: '7530105822785899777',
  cool_lady: '7530107275239869713',
  happy_dino: '7527795878967446801',
  puppet: '7527814111502044433',
  popular_guy: '7527779392769002769',
  bratty_witch: '7527846655475928336',
  game_host: '7527778973296774416',
  calm_dubbing: '7527793325328452881',
  gruff_uncle: '7522965008020507920',
  witch_granny: '7522976550736710913',
  high_tension: '7522976550736661761',
  serious_man: '7522987643752271121',
  manager: '7522976550736678145',
  little_sister: '7522987643752303889',
  young_girl: '7522965008020475152',
  peaceful_woman: '7114563483257016833',
};
