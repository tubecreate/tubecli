/**
 * API 層で使う共通 requester
 */
export type ApiRequester = (
  url: string,
  init: RequestInit
) => Promise<Response>;
