"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const get_1 = require("./get");
const speakerIdRouter = (0, express_1.Router)({ mergeParams: true });
speakerIdRouter.get('/preview', get_1.get);
exports.default = speakerIdRouter;
//# sourceMappingURL=index.js.map