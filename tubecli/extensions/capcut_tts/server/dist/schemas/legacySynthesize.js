"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LegacySynthesizeQuerySchema = void 0;
const zod_1 = require("zod");
const singleQueryValue = (schema) => zod_1.z.preprocess((value) => {
    if (Array.isArray(value)) {
        return value[0];
    }
    return value;
}, schema);
const numericQuery = (defaultValue) => singleQueryValue(zod_1.z.coerce.number().int()).default(defaultValue);
exports.LegacySynthesizeQuerySchema = zod_1.z.object({
    text: singleQueryValue(zod_1.z.string().trim().min(1, 'text is required')),
    type: numericQuery(0),
    pitch: numericQuery(10),
    speed: numericQuery(10),
    volume: numericQuery(10),
    method: singleQueryValue(zod_1.z.enum(['buffer', 'stream'])).default('buffer'),
});
//# sourceMappingURL=legacySynthesize.js.map