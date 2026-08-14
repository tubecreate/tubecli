"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const get_1 = require("./get");
const synthesizeRouter = (0, express_1.Router)();
synthesizeRouter.get('/', get_1.get);
exports.default = synthesizeRouter;
//# sourceMappingURL=index.js.map