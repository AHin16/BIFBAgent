const fs = require('fs');
const path = require('path');
const sharp = require('C:/Users/AHin0/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root = path.resolve(__dirname, '..');
const out = path.join(__dirname, 'template-preview');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const thumbs = [];
  for (let n = 1; n <= 14; n++) {
    const id = String(n).padStart(2, '0');
    const src = path.join(root, 'authoring-svg-flat', `slide_${id}.svg`);
    const png = path.join(out, `slide_${id}.png`);
    await sharp(src).resize(1280, 720).png().toFile(png);
    const thumb = await sharp(png).resize(480, 270).extend({ top: 0, bottom: 30, left: 0, right: 0, background: '#eeeeee' }).png().toBuffer();
    thumbs.push({ input: thumb, left: ((n - 1) % 3) * 500 + 10, top: Math.floor((n - 1) / 3) * 320 + 10 });
  }
  await sharp({ create: { width: 1500, height: 1600, channels: 3, background: '#dddddd' } }).composite(thumbs).png().toFile(path.join(out, 'contact-sheet.png'));
  console.log(path.join(out, 'contact-sheet.png'));
})();
