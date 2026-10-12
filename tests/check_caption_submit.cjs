const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const names = ['stylish_captions','varied_fonts','smooth_zoom','clip_progress','opening_title','sound_effects','hook_start','end_cta','camera_cuts','caption_emoji','censor','background_music','energy_score','suggestions','floating_captions','sfx_hook','sfx_whoosh','sfx_riser','fx_hook','fx_shake','fx_flash','fx_keyword','fx_vignette','ncs_credit','speed_ramp','freeze_climax'];
async function check(supported, mask) {
  const elements = new Map();
  const el = selector => {
    if (!elements.has(selector)) elements.set(selector, {value:'30',checked:false,textContent:'',disabled:false,style:{},classList:{add(){},remove(){}},addEventListener(type,fn){this[type]=fn},querySelector:el,append(){}});
    return elements.get(selector);
  };
  const expected = Object.fromEntries(names.map((name,i) => [name,Boolean(mask & (1 << i))]));
  for (const name of names) el('#'+name.replaceAll('_','-')).checked = expected[name];
  el('#title-text').value = 'Título com ação';
  let posts=0;
  const properties = Object.fromEntries([...(supported?names:names.slice(0,2)).map(name=>[name,{type:'boolean'}]),
    ...(supported?[['director',{type:'string'}],['music_track',{type:'string'}],['music_volume',{type:'integer'}]]:[])]);
  const context={document:{querySelector:el,createElement:()=>el('option-'+Math.random())},setTimeout(){},clearTimeout(){},fetch:async(url,options)=>{
    if (url==='/openapi.json') return {ok:true,json:async()=>({components:{schemas:{CreateJobRequest:{properties}}}})};
    if(options?.method==='POST') {
      posts++;
      const body=JSON.parse(options.body);
      for(const name of names) assert.equal(body[name],expected[name]);
      assert.equal(body.title_text,expected.opening_title?'Título com ação':'');
      assert.equal(body.music_track,el('#music-track').value);
      assert.equal(body.music_volume,Number(el('#music-volume').value));
      assert.equal(body.caption_position,'30');assert.equal(body.director,'30');
      return {ok:true,json:async()=>({id:'test',...body})};
    }
    return {ok:true,json:async()=>({status:'processing',progress:0,message:''})};
  }};
  vm.runInNewContext(fs.readFileSync('corta_ai/static/app.js','utf8'),context);
  assert.equal(el('#title-text').disabled,!expected.opening_title);
  await el('#job-form').submit({preventDefault(){}});
  assert.equal(posts,supported?1:0);
  if(!supported) assert.match(el('#error-box').textContent,/atualiz/i);
}
(async()=>{
  await check(false,0);await check(false,63);
  // cada bit isolado e o complemento: prova que nenhuma opção liga outra no corpo do POST
  for(let bit=0;bit<names.length;bit++){await check(true,1<<bit);await check(true,~(1<<bit)&((1<<names.length)-1));}
  // amostra com passo ímpar cobrindo combinações arbitrárias de 26 bits
  const full = (1 << names.length) - 1;
  for(let i = 0, mask = 0; i < 600; i++) { await check(true, mask); mask = (mask + 32749) & full; }
  console.log(`OK: ${names.length} opções independentes; servidor antigo bloqueado`);
})().catch(error=>{console.error(error);process.exitCode=1});
