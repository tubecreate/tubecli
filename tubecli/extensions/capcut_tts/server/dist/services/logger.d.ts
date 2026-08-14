/**
 * アプリ全体で共有するロガー
 */
declare const logger: {
    silly: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
    trace: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
    debug: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
    info: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
    warn: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
    error: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
    fatal: (...args: unknown[]) => import("tslog").ILogObjMeta | undefined;
};
export default logger;
