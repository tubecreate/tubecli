"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const get_1 = require("./get");
const languagesRouter = (0, express_1.Router)();
languagesRouter.get('/', get_1.get);
exports.default = languagesRouter;
//# sourceMappingURL=index.js.map