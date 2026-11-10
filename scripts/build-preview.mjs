import { readFile, writeFile } from 'node:fs/promises';

const args = process.argv.slice(2);
if (args.length > 1 || (args.length === 1 && args[0] !== '--check')) {
  console.error('Usage: node scripts/build-preview.mjs [--check]');
  process.exit(2);
}

const sourcePath = new URL('../design/observatory.fragment.html', import.meta.url);
const outputPath = new URL('../design/index.html', import.meta.url);
const fragmentPath = new URL('../design/preview.fragment.html', import.meta.url);
const scenePath = new URL('../design/scene/lab-scene.js', import.meta.url);
const prefix = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>Interspace — Observatory design study</title><style>body{margin:0;padding:24px;background:light-dark(#e7e9e6,#10151a)}#ispace{max-width:1200px;margin:auto}button{cursor:pointer}@media(max-width:580px){body{padding:0}}</style></head><body>
`;

try {
  const source = await readFile(sourcePath, 'utf8');
  const scene = await readFile(scenePath, 'utf8');
  const marker = '<!-- INTERSPACE_LAB_SCENE -->';
  if (source.split(marker).length !== 2) throw new Error('Expected exactly one laboratory scene marker.');
  const fragment = source.replace(marker, `<script>\n${scene}\n</script>`);
  const expected = `${prefix}${fragment}</body></html>\n`;
  if (args[0] === '--check') {
    let actual;
    try {
      actual = await readFile(outputPath, 'utf8');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    let actualFragment;
    try { actualFragment = await readFile(fragmentPath, 'utf8'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (actual !== expected || actualFragment !== fragment) {
      console.error('Preview is missing or out of date. Run: node scripts/build-preview.mjs');
      process.exitCode = 1;
    } else {
      console.log('Preview matches its source.');
    }
  } else {
    await writeFile(outputPath, expected, 'utf8');
    await writeFile(fragmentPath, fragment, 'utf8');
    console.log('Generated design/index.html and design/preview.fragment.html.');
  }
} catch (error) {
  console.error(`Preview build failed: ${error.message}`);
  process.exitCode = 1;
}
