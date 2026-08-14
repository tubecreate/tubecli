"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const fallback_1 = require("../routes/fallback");
const v1_1 = __importDefault(require("../routes/v1"));
const v2_1 = __importDefault(require("../routes/v2"));
/**
 * ルートルーター
 */
const router = (0, express_1.Router)();
router.use('/v1', v1_1.default);
router.use('/v2', v2_1.default);
router.use(fallback_1.fallback);
exports.default = router;
//# sourceMappingURL=index.js.map