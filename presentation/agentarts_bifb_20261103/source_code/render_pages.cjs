const fs = require('fs');
const path = require('path');
const sharp = require(process.env.SHARP_MODULE || 'C:/Users/AHin0/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'validation', 'page-previews');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const plan = JSON.parse(fs.readFileSync(path.join(root, 'page_plan.json'), 'utf8')).pages;
  const thumbs = [];
  for (let i=0; i<plan.length; i++) {
    const p = plan[i];
    const src = path.join(root, 'authoring-svg-flat', p.svg || `slide_${String(p.source_slide).padStart(2,'0')}.svg`);
    let svg = fs.readFileSync(src, 'utf8');
    // Embed referenced raster assets for standalone preview only; authoring SVG stays untouched.
    svg = svg.replace(/href="(\.\.\/images\/[^\"]+)"/g, (m, ref) => {
      const abs = path.resolve(path.dirname(src), ref);
      if (!fs.existsSync(abs)) return m;
      const ext = path.extname(abs).slice(1).toLowerCase();
      const mime = ({png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',svg:'image/svg+xml'})[ext];
      return mime ? `href="data:${mime};base64,${fs.readFileSync(abs).toString('base64')}"` : m;
    });
    const png = path.join(out, `P${String(i+1).padStart(2,'0')}.png`);
    await sharp(Buffer.from(svg)).resize(1600,900).png().toFile(png);
    const label = Buffer.from(`<svg width="480" height="30"><rect width="480" height="30" fill="#EFEFEF"/><text x="12" y="21" font-size="18" font-family="Arial" fill="#333333">P${String(i+1).padStart(2,'0')}</text></svg>`);
    const thumb = await sharp(png).resize(480,270).extend({ top:0, bottom:30,left:0,right:0,background:'#EFEFEF' }).composite([{input:label,left:0,top:270}]).png().toBuffer();
    thumbs.push({input:thumb,left:(i%4)*500+10,top:Math.floor(i/4)*320+10});
  }
  await sharp({create:{width:2000,height:Math.ceil(plan.length/4)*320,channels:3,background:'#D8D8D8'}}).composite(thumbs).png().toFile(path.join(out,'contact-sheet.png'));
  console.log(`Rendered ${plan.length} slides to ${out}`);
})();
