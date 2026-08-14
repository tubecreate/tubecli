"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const models_1 = __importDefault(require("../../routes/v1/models"));
const synthesize_1 = __importDefault(require("../../routes/v1/synthesize"));
const v1Router = (0, express_1.Router)();
v1Router.use('/models', models_1.default);
v1Router.use('/synthesize', synthesize_1.default);
exports.default = v1Router;
//# sourceMappingURL=index.js.map