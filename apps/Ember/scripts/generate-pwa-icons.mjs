// Regenerate both app icon sets from their existing SVG logos (requires local Chrome).
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
const require = createRequire(new URL('../ember_web/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const page = await browser.newPage();
  for (const app of ['ember_web', 'ember_admin']) {
    const folder = new URL(`../${app}/public/`, import.meta.url);
    const svg = await readFile(new URL('favicon.svg', folder), 'utf8');
    await mkdir(new URL('icons/', folder), { recursive: true });
    for (const [filename, size] of [['icon-192.png', 192], ['icon-512.png', 512], ['icon-maskable-512.png', 512], ['apple-touch-icon.png', 180]]) {
      const encoded = await page.evaluate(async ({ svg, size, admin }) => {
        const image = new Image();
        image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = size;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#17171a';
        ctx.fillRect(0, 0, size, size);
        // Keep the whole mark inside the maskable safe area.
        ctx.drawImage(image, size * .16, size * .16, size * .68, size * .68);
        if (admin) {
          ctx.fillStyle = '#e8590c';
          ctx.font = `bold ${size * .13}px system-ui`;
          ctx.textAlign = 'center';
          ctx.fillText('A', size * .75, size * .75);
        }
        return canvas.toDataURL('image/png').split(',')[1];
      }, { svg, size, admin: app === 'ember_admin' });
      await writeFile(new URL(`icons/${filename}`, folder), Buffer.from(encoded, 'base64'));
    }
  }
} finally { await browser.close(); }
