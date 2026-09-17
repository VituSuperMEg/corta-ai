const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
async function check(supported) {
  const elements = new Map();
  const el = (selector) => {
    if (!elements.has(selector)) elements.set(selector, {value: '30', checked: true, textContent: '', style: {}, classList: {add(){},remove(){}}, addEventListener(type, fn){this[type] = fn}, querySelector: el});
    return elements.get(selector);
  };
  let posts = 0;
  const context = {document: {querySelector: el}, setTimeout(){},clearTimeout(){},fetch: async(url, options) => {
    if (url === '/openapi.json') return {ok:true,json:async()=>({components:{schemas:{CreateJobRequest:{properties:supported?{stylish_captions:{type:'boolean'}}:{}}}}})};
    if (options?.method === 'POST') {posts++;return {ok:true,json:async()=>({id:'test',stylish_captions:supported})};}
    return {ok:true,json:async()=>({status:'processing',progress:0,message:''})};
  }};
  vm.runInNewContext(fs.readFileSync('corta_ai/static/app.js','utf8'),context);
  await el('#job-form').submit({preventDefault(){}});
  assert.equal(posts, supported ? 1 : 0, 'Servidor antigo não pode receber trabalho com estilo que não suporta');
  if (!supported) assert.match(el('#error-box').textContent,/reinici|atualiz/i);
}
(async()=>{await check(false);await check(true);console.log('OK: servidor antigo bloqueado; servidor atualizado aceito')})().catch(e=>{console.error(e);process.exitCode=1});
