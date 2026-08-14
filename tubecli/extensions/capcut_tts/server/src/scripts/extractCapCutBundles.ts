import fs from 'node:fs/promises';
import path from 'node:path';
import { extractCapCutBundleConfigFromHarFile } from '../lib/capcutBundle/harBundleUtils';
import type { CapCutBundleConfig } from '../types/capcutBundle';

/**
 * CLI 引数を読む
 */
const parseArgs = (argv: string[]) => {
  const harPaths: string[] = [];
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
    harPaths:
      harPaths.length > 0
        ? harPaths
        : [
            'tmp/www.capcut.com-create-account.har',
            'tmp/www.capcut.com-generate-audio.har',
            'tmp/www.capcut.com-audio-category-all.har',
          ],
    outputPath,
  };
};

const mergeBundleConfig = (
  current: CapCutBundleConfig,
  next: CapCutBundleConfig
): CapCutBundleConfig => ({
  discoveredAt: Math.max(current.discoveredAt, next.discoveredAt),
  login: {
    ...current.login,
    ...next.login,
  },
  editor: {
    ...current.editor,
    ...next.editor,
    sourceUrls: Array.from(
      new Set([
        ...(current.editor.sourceUrls ?? []),
        ...(next.editor.sourceUrls ?? []),
      ])
    ),
    signRecipe: {
      ...current.editor.signRecipe,
      ...next.editor.signRecipe,
    },
    voiceCategoryIds:
      next.editor.voiceCategoryIds && next.editor.voiceCategoryIds.length > 0
        ? Array.from(
            new Set([
              ...(current.editor.voiceCategoryIds ?? []),
              ...next.editor.voiceCategoryIds,
            ])
          ).sort((left, right) => left - right)
        : current.editor.voiceCategoryIds,
  },
});

const run = async () => {
  const { harPaths, outputPath } = parseArgs(process.argv.slice(2));

  let mergedConfig: CapCutBundleConfig = {
    discoveredAt: 0,
    login: {},
    editor: {
      sourceUrls: [],
    },
  };

  for (const harPath of harPaths) {
    const absolutePath = path.resolve(process.cwd(), harPath);
    const stat = await fs.stat(absolutePath);

    if (!stat.isFile()) {
      continue;
    }

    const extracted = await extractCapCutBundleConfigFromHarFile(absolutePath);
    mergedConfig = mergeBundleConfig(mergedConfig, extracted);
  }

  const absoluteOutputPath = path.resolve(process.cwd(), outputPath);
  await fs.mkdir(path.dirname(absoluteOutputPath), { recursive: true });
  await fs.writeFile(
    absoluteOutputPath,
    JSON.stringify(mergedConfig, null, 2),
    'utf8'
  );

  process.stdout.write(`${JSON.stringify(mergedConfig, null, 2)}\n`);
};

void run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
