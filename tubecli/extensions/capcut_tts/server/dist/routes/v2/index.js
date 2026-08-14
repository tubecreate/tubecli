"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const fallback_1 = require("../../routes/v2/fallback");
const languages_1 = __importDefault(require("../../routes/v2/languages"));
const speakers_1 = __importDefault(require("../../routes/v2/speakers"));
const synthesize_1 = __importDefault(require("../../routes/v2/synthesize"));
const v2Router = (0, express_1.Router)();
v2Router.use('/languages', languages_1.default);
v2Router.use('/speakers', speakers_1.default);
v2Router.use('/synthesize', synthesize_1.default);
v2Router.use(fallback_1.fallback);
exports.default = v2Router;
//# sourceMappingURL=index.js.map