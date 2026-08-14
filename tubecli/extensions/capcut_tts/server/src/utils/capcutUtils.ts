import crypto from 'node:crypto';

const defaultCapCutEmailHashSalt = 'aDy0TUhtql92P7hScCs97YWMT-jub2q9';

/**
 * CapCut の verifyFp 形式に寄せた識別子を生成する
 */
export const createVerifyFp = () => {
  const random = (length: number) =>
    crypto
      .randomBytes(length * 2)
      .toString('base64url')
      .replace(/[^a-zA-Z0-9]/g, '')
      .slice(0, length);

  const prefix = Date.now().toString(36).slice(-8).padStart(8, '0');
  return `verify_${prefix}_${random(8)}_${random(4)}_${random(4)}_${random(
    4
  )}_${random(12)}`;
};

/**
 * CapCut の did として使うデバイス ID を生成する
 */
export const createDeviceId = () =>
  `${Date.now()}${Array.from(crypto.randomBytes(12), (value) =>
    String(value % 10)
  ).join('')}`.slice(0, 19);

/**
 * CapCut の tdid として使うトラッキング ID を生成する
 */
export const createTrackingId = () =>
  `${Date.now()}${Array.from(crypto.randomBytes(8), (value) =>
    String(value % 10)
  ).join('')}`.slice(0, 17);

/**
 * speed パラメータを CapCut の再生速度に変換する
 */
export const toPlaybackRate = (speed: number) =>
  Number((Math.min(Math.max(speed, 1), 20) / 10).toFixed(2));

/**
 * volume パラメータを CapCut の音量レベルに変換する
 */
export const toVolumeLevel = (volume: number) =>
  Math.min(Math.max(volume, 0), 20) * 10;

/**
 * CapCut login SDK が使う XOR5 + hex 変換
 */
export const xorFiveHexEncode = (value: string) =>
  Array.from(Buffer.from(value, 'utf8'), (charCode) =>
    (charCode ^ 5).toString(16).padStart(2, '0')
  ).join('');

/**
 * SHA-256 の hex 文字列を返す
 */
export const sha256Hex = (value: string) =>
  crypto.createHash('sha256').update(value).digest('hex').toLowerCase();

/**
 * email をリージョン解決用の正規化形式へ揃える
 */
export const normalizeEmailForRegion = (email: string) =>
  email.trim().toLowerCase();

/**
 * region 解決用の hashed_id を生成する
 */
export const createEmailRegionHash = (email: string) =>
  sha256Hex(`${normalizeEmailForRegion(email)}${defaultCapCutEmailHashSalt}`);

/**
 * region 解決用の hashed_id を任意 salt で生成する
 */
export const createEmailRegionHashWithSalt = (
  email: string,
  salt = defaultCapCutEmailHashSalt
) => sha256Hex(`${normalizeEmailForRegion(email)}${salt}`);

/**
 * 秘匿項目だけ XOR5 + hex で包んだ form body を作る
 */
export const buildSensitiveFormBody = (
  values: Record<string, string>,
  keys: string[]
): string => {
  const payload = new URLSearchParams();
  let mixMode = 0;
  let fixedMixMode = 0;

  for (const [key, value] of Object.entries(values)) {
    if (keys.includes(key)) {
      mixMode |= 1;
      fixedMixMode |= 1;
      payload.set(key, xorFiveHexEncode(value));
      continue;
    }

    payload.set(key, value);
  }

  payload.set('mix_mode', String(mixMode));
  payload.set('fixed_mix_mode', String(fixedMixMode));

  return payload.toString();
};

/**
 * CapCut がログイン試行回数の上限を返したかを判定する
 *
 * この状態で別 host を試しても通らず、残り試行を減らすだけになる
 * errorCode 7 のほか、文言でも拾えるようにしておく
 */
export const isLoginAttemptLimitError = (error: unknown): boolean => {
  if (!(error instanceof Error)) {
    return false;
  }

  if (
    'errorCode' in error &&
    (error as { errorCode?: number }).errorCode === 7
  ) {
    return true;
  }

  return /số lần thử tối đa|試行回数の上限|maximum.*attempts|too many attempts/i.test(
    error.message
  );
};

/**
 * セッション失効らしいエラーかを判定する
 */
export const isSessionExpiredError = (error: unknown) =>
  error instanceof Error &&
  /check login error|account info failed|workspace list was empty/i.test(
    error.message
  );
