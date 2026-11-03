const fs=require('fs');const path=require('path');
const sharp=require(process.env.SHARP_MODULE || 'C:/Users/AHin0/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root=path.resolve(process.argv[2]);
(async()=>{
  const files=fs.readdirSync(root).filter(n=>/^P\d{2}\.png$/.test(n)).sort();const layers=[];
  for(let i=0;i<files.length;i++){
    const label=Buffer.from(`<svg width="480" height="30"><rect width="480" height="30" fill="#EFEFEF"/><text x="12" y="22" font-size="18" font-family="Arial" fill="#333333">${files[i].slice(0,3)}</text></svg>`);
    const thumb=await sharp(path.join(root,files[i])).resize(480,270).extend({top:0,bottom:30,left:0,right:0,background:'#EFEFEF'}).composite([{input:label,left:0,top:270}]).png().toBuffer();
    layers.push({input:thumb,left:(i%4)*500+10,top:Math.floor(i/4)*320+10});
  }
  await sharp({create:{width:2000,height:Math.ceil(files.length/4)*320,channels:3,background:'#D8D8D8'}}).composite(layers).png().toFile(path.join(root,'contact-sheet.png'));
  console.log(`${files.length} previews composed`);
})();
