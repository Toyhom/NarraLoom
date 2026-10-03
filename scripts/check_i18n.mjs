/** Catalog contracts and locale behavior. Run with node --test scripts/check_i18n.mjs. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
const root=path.resolve('web/src');
const zh=JSON.parse(fs.readFileSync(root+'/locales/zh-CN.json','utf8'));
const en=JSON.parse(fs.readFileSync(root+'/locales/en.json','utf8'));
const ja=JSON.parse(fs.readFileSync(root+'/locales/ja.json','utf8'));
const placeholders=s=>[...s.matchAll(/\{(p\d+)\}/g)].map(m=>m[1]).sort();

test('catalog keys and interpolation contracts match across languages',()=>{
 for(const catalog of [en,ja]){
  assert.deepEqual(Object.keys(catalog).sort(),Object.keys(zh).sort());
  for(const [key,text] of Object.entries(zh)){
   assert.equal(typeof catalog[key],'string',key);assert.ok(catalog[key].trim(),key);
   assert.deepEqual(placeholders(catalog[key]),placeholders(text),key);
  }
 }
});

test('UI calls use existing keys and supply the exact placeholder names',()=>{
 let calls=0;
 for(const filename of fs.readdirSync(root).filter(f=>f.endsWith('.tsx'))){
  const sf=ts.createSourceFile(filename,fs.readFileSync(root+'/'+filename,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  assert.equal(sf.parseDiagnostics.length,0,filename);
  function walk(node){
   if(ts.isCallExpression(node)&&['uiText','uiMessage'].includes(node.expression.getText(sf))&&ts.isStringLiteral(node.arguments[0])){
    const key=node.arguments[0].text;assert.ok(key in zh,`${filename}: ${key}`);calls++;
    const params=node.arguments[1];const expected=[...new Set(placeholders(zh[key]))];
    assert.ok(!params||ts.isObjectLiteralExpression(params),`${filename}: static params required`);
    const supplied=params?params.properties.map(p=>p.name.getText(sf)).sort():[];
    assert.deepEqual(supplied,expected,`${filename}: ${key}`);
    let parent=node.parent,insideFunction=false;
    while(parent){if(ts.isFunctionLike(parent))insideFunction=true;parent=parent.parent;}
    assert.ok(insideFunction,`${filename}: ${key} freezes locale at module load`);
   }
   ts.forEachChild(node,walk);
  }
  walk(sf);
 }
 assert.ok(calls>800);
});

function runtime({language='en-US',stored={},brokenStorage=false}={}){
 const local=new Map(Object.entries(stored)),events={};
 const source=fs.readFileSync(root+'/i18n.ts','utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
 const exports={},document={documentElement:{lang:''},title:''};
 const context={exports,require:createRequire(root+'/i18n.ts'),document,navigator:{language},window:{addEventListener:(name,cb)=>{events[name]=cb;}},localStorage:{
  getItem:key=>{if(brokenStorage)throw Error('denied');return local.get(key)??null;},
  setItem:(key,value)=>{if(brokenStorage)throw Error('denied');local.set(key,value);},
 }};
 vm.runInNewContext(compiled,context);
 return {api:exports,document,local,events};
}

test('browser preference, legacy migration, persistence and cross-tab changes',()=>{
 assert.equal(runtime({language:'zh-TW'}).api.getLocale(),'zh-CN');
 assert.equal(runtime({language:'ja-JP'}).api.getLocale(),'ja');
 const japanese=runtime({stored:{'narraloom.locale':'ja'}});
 assert.equal(japanese.api.getLocale(),'ja');
 assert.equal(japanese.document.documentElement.lang,'ja');
 assert.equal(japanese.document.title,'NarraLoom · 物語の世界');
 const r=runtime({stored:{'narraloom.engineLanguage':'en'},language:'zh-CN'});
 assert.equal(r.api.getLocale(),'en');assert.equal(r.local.get('narraloom.locale'),'en');
 r.api.setLocale('zh-CN');assert.equal(r.document.documentElement.lang,'zh-CN');
 assert.equal(r.local.get('narraloom.locale'),'zh-CN');
 r.events.storage({key:'narraloom.locale',newValue:'en'});assert.equal(r.api.getLocale(),'en');
 assert.equal(r.document.title,'NarraLoom · Story worlds');
 assert.equal(runtime({stored:{'narraloom.locale':'zh-CN','narraloom.engineLanguage':'en'}}).api.getLocale(),'zh-CN');
 const denied=runtime({brokenStorage:true});denied.api.setLocale('zh-CN');assert.equal(denied.api.getLocale(),'zh-CN');
});

test('interpolation preserves authored strings and never recursively expands them',()=>{
 const {api}=runtime();
 const payload='<script>{p1}</script> 日本語';
 assert.equal(api.uiText('main.037',{p0:payload}),`I say to ${payload}: “`);
 assert.equal(api.uiText('main.039',{p0:0}),'Story saved · Turn 0');
 api.setLocale('zh-CN');assert.equal(api.uiText('main.037',{p0:payload}),`我对${payload}说：“`);
});
