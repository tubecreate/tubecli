"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const _speakerId_1 = __importDefault(require("./[speakerId]"));
const get_1 = require("./get");
const speakersRouter = (0, express_1.Router)();
speakersRouter.get('/', get_1.get);
speakersRouter.use('/:speakerId', _speakerId_1.default);
exports.default = speakersRouter;
//# sourceMappingURL=index.js.map