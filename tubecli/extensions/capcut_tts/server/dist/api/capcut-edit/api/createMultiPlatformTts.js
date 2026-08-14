"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createMultiPlatformTts = void 0;
const apiClient_1 = require("../../../api/capcut-edit/apiClient");
/**
 * multi_platform TTS を実行する
 */
const createMultiPlatformTts = ({ requester, path, headers, body, }) => apiClient_1.CapCutEditApiClient.request({
    requester,
    path: path ?? '/storyboard/v1/tts/multi_platform',
    method: 'POST',
    headers,
    body,
});
exports.createMultiPlatformTts = createMultiPlatformTts;
//# sourceMappingURL=createMultiPlatformTts.js.map