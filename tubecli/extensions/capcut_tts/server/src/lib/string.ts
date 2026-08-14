/**
 * ### splitTtsText
 * TTS の文字数上限に合わせてテキストを分割する
 *
 * @param text - 分割対象のテキスト
 * @param maxLength - 1 チャンクあたりの最大文字数
 * @param boundarySearchRatio - 区切り文字を探し始める割合
 * @returns 分割済みテキスト
 */
export const splitTtsText = (
  text: string,
  maxLength: number,
  boundarySearchRatio: number
): string[] => {
  const normalizedText = text.trim();
  const textCharacters = Array.from(normalizedText);

  if (textCharacters.length <= maxLength) {
    return [normalizedText];
  }

  const chunks: string[] = [];
  let startIndex = 0;

  while (startIndex < textCharacters.length) {
    const remainingLength = textCharacters.length - startIndex;
    if (remainingLength <= maxLength) {
      const tailChunk = textCharacters.slice(startIndex).join('').trim();
      if (tailChunk) {
        chunks.push(tailChunk);
      }
      break;
    }

    const splitLength = resolveTtsChunkLength(
      textCharacters,
      startIndex,
      maxLength,
      boundarySearchRatio
    );
    const chunk = textCharacters
      .slice(startIndex, startIndex + splitLength)
      .join('')
      .trim();
    if (chunk) {
      chunks.push(chunk);
    }

    startIndex += splitLength;
    while (
      startIndex < textCharacters.length &&
      isTtsChunkSeparator(textCharacters[startIndex])
    ) {
      startIndex += 1;
    }
  }

  return chunks.length > 0 ? chunks : [normalizedText];
};

/**
 * ### resolveTtsChunkLength
 * 境界らしい箇所を優先して切り出し長を決める
 *
 * @param textCharacters - 文字単位に分割済みのテキスト
 * @param startIndex - 切り出し開始位置
 * @param maxLength - 1 チャンクあたりの最大文字数
 * @param boundarySearchRatio - 区切り文字を探し始める割合
 * @returns 切り出す文字数
 */
const resolveTtsChunkLength = (
  textCharacters: string[],
  startIndex: number,
  maxLength: number,
  boundarySearchRatio: number
): number => {
  const endIndex = Math.min(textCharacters.length, startIndex + maxLength);
  const preferredBoundaryIndex = Math.max(
    startIndex + 1,
    startIndex + Math.floor(maxLength * boundarySearchRatio)
  );

  for (let cursor = endIndex - 1; cursor >= preferredBoundaryIndex; cursor -= 1) {
    if (isStrongTtsChunkBoundary(textCharacters[cursor])) {
      return cursor - startIndex + 1;
    }
  }

  for (let cursor = endIndex - 1; cursor >= preferredBoundaryIndex; cursor -= 1) {
    if (isWeakTtsChunkBoundary(textCharacters[cursor])) {
      return cursor - startIndex + 1;
    }
  }

  return endIndex - startIndex;
};

const isTtsChunkSeparator = (value: string) =>
  value === '\n' ||
  value === '\r' ||
  value === ' ' ||
  value === '\t' ||
  value === '\u3000';

const isStrongTtsChunkBoundary = (value: string) =>
  value === '\n' ||
  value === '\r' ||
  value === '。' ||
  value === '！' ||
  value === '？' ||
  value === '!' ||
  value === '?' ||
  value === '．' ||
  value === '.';

const isWeakTtsChunkBoundary = (value: string) =>
  isTtsChunkSeparator(value) ||
  value === '、' ||
  value === ',' ||
  value === '，' ||
  value === '；' ||
  value === ';' ||
  value === '：' ||
  value === ':';
