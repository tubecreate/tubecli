/**
 * ### splitTtsText
 * TTS の文字数上限に合わせてテキストを分割する
 *
 * @param text - 分割対象のテキスト
 * @param maxLength - 1 チャンクあたりの最大文字数
 * @param boundarySearchRatio - 区切り文字を探し始める割合
 * @returns 分割済みテキスト
 */
export declare const splitTtsText: (text: string, maxLength: number, boundarySearchRatio: number) => string[];
