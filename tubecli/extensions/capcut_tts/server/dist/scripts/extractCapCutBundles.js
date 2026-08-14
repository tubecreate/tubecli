"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const promises_1 = __importDefault(require("node:fs/promises"));
const node_path_1 = __importDefault(require("node:path"));
const harBundleUtils_1 = require("../lib/capcutBundle/harBundleUtils");
/**
 * CLI 引数を読む
 */
const parseArgs = (argv) => {
    const harPaths = [];
    let outputPath = 'capcut-bundle-config.json';
    for (let index = 0; index < argv.length; index += 1) {
        const arg = argv[index];
        if (arg === '--har' && argv[index + 1]) {
            harPaths.push(argv[index + 1]);
            index += 1;
            continue;
        }
        if (arg === '--out' && argv[index + 1]) {
            outputPath = argv[index + 1];
            index += 1;
        }
    }
    return {
        harPaths: harPaths.length > 0
            ? harPaths
            : [
                'tmp/www.capcut.com-create-account.har',
                'tmp/www.capcut.com-generate-audio.har',
                'tmp/www.capcut.com-audio-category-all.har',
            ],
        outputPath,
    };
};
const mergeBundleConfig = (current, next) => ({
    discoveredAt: Math.max(current.discoveredAt, next.discoveredAt),
    login: {
        ...current.login,
        ...next.login,
    },
    editor: {
        ...current.editor,
        ...next.editor,
        sourceUrls: Array.from(new Set([
            ...(current.editor.sourceUrls ?? []),
            ...(next.editor.sourceUrls ?? []),
        ])),
        signRecipe: {
            ...current.editor.signRecipe,
            ...next.editor.signRecipe,
        },
        voiceCategoryIds: next.editor.voiceCategoryIds && next.editor.voiceCategoryIds.length > 0
            ? Array.from(new Set([
                ...(current.editor.voiceCategoryIds ?? []),
                ...next.editor.voiceCategoryIds,
            ])).sort((left, right) => left - right)
            : current.editor.voiceCategoryIds,
    },
});
const run = async () => {
    const { harPaths, outputPath } = parseArgs(process.argv.slice(2));
    let mergedConfig = {
        discoveredAt: 0,
        login: {},
        editor: {
            sourceUrls: [],
        },
    };
    for (const harPath of harPaths) {
        const absolutePath = node_path_1.default.resolve(process.cwd(), harPath);
        const stat = await promises_1.default.stat(absolutePath);
        if (!stat.isFile()) {
            continue;
        }
        const extracted = await (0, harBundleUtils_1.extractCapCutBundleConfigFromHarFile)(absolutePath);
        mergedConfig = mergeBundleConfig(mergedConfig, extracted);
    }
    const absoluteOutputPath = node_path_1.default.resolve(process.cwd(), outputPath);
    await promises_1.default.mkdir(node_path_1.default.dirname(absoluteOutputPath), { recursive: true });
    await promises_1.default.writeFile(absoluteOutputPath, JSON.stringify(mergedConfig, null, 2), 'utf8');
    process.stdout.write(`${JSON.stringify(mergedConfig, null, 2)}\n`);
};
void run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
//# sourceMappingURL=extractCapCutBundles.js.map