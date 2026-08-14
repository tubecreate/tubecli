"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const get_1 = require("./get");
const modelsRouter = (0, express_1.Router)();
modelsRouter.get('/', get_1.get);
exports.default = modelsRouter;
//# sourceMappingURL=index.js.map