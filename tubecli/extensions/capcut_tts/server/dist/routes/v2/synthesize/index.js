"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const get_1 = require("./get");
const post_1 = require("./post");
const synthesizeRouter = (0, express_1.Router)();
synthesizeRouter.get('/', get_1.get);
synthesizeRouter.post('/', post_1.post);
exports.default = synthesizeRouter;
//# sourceMappingURL=index.js.map