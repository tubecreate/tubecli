export interface CapCutLegacySpeaker {
  id: string;
  title: string;
  description: string;
  language: string;
  type: number;
}

export const capCutLegacySpeakers: CapCutLegacySpeaker[] = [
  {
    id: 'BV525_streaming',
    title: '謎1 男子1',
    description: '男性ボイス',
    language: 'ja',
    type: 0,
  },
  {
    id: 'BV528_streaming',
    title: '謎2 坊や',
    description: '少年風ボイス',
    language: 'ja',
    type: 1,
  },
  {
    id: 'BV017_streaming',
    title: 'カワボ',
    description: 'かわいい女性ボイス',
    language: 'ja',
    type: 2,
  },
  {
    id: 'BV016_streaming',
    title: 'お姉さん',
    description: '女性ボイス',
    language: 'ja',
    type: 3,
  },
  {
    id: 'BV023_streaming',
    title: '少女',
    description: '少女風ボイス',
    language: 'ja',
    type: 4,
  },
  {
    id: 'BV024_streaming',
    title: '女子',
    description: '女性ボイス',
    language: 'ja',
    type: 5,
  },
  {
    id: 'BV018_streaming',
    title: '男子2',
    description: '男性ボイス',
    language: 'ja',
    type: 6,
  },
  {
    id: 'BV523_streaming',
    title: '坊ちゃん',
    description: '少年風ボイス',
    language: 'ja',
    type: 7,
  },
  {
    id: 'BV521_streaming',
    title: '女子"',
    description: '女性ボイス',
    language: 'ja',
    type: 8,
  },
  {
    id: 'BV522_streaming',
    title: '女子アナ',
    description: '女性アナウンサーボイス',
    language: 'ja',
    type: 9,
  },
  {
    id: 'BV524_streaming',
    title: '男性アナ',
    description: '男性アナウンサーボイス',
    language: 'ja',
    type: 10,
  },
  {
    id: 'BV520_streaming',
    title: '元気ロリ',
    description: '元気な少女風ボイス',
    language: 'ja',
    type: 11,
  },
  {
    id: 'VOV401_bytesing3_kangkangwuqu',
    title: '明るいハニー',
    description: '明るい女性ボイス',
    language: 'ja',
    type: 12,
  },
  {
    id: 'VOV402_bytesing3_oh',
    title: '優しいレディー',
    description: '優しい女性ボイス',
    language: 'ja',
    type: 13,
  },
  {
    id: 'VOV402_bytesing3_aidelizan',
    title: '風雅メゾソプラノ',
    description: 'メゾソプラノ風ボイス',
    language: 'ja',
    type: 14,
  },
  {
    id: 'jp_005',
    title: 'Sakura',
    description: 'Sakura ボイス',
    language: 'ja',
    type: 15,
  },
];

export const legacySpeakers = capCutLegacySpeakers.map((model) => model.id) as [
  string,
  ...string[],
];
