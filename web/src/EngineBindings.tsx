import { MessageKey, uiMessage, useUiMessage, uiText, useLocale } from './i18n';
import { useState } from 'react';
import { Api } from './AvatarStudio';

export type NamedProvider={backend:string;url:string;api_key?:string;has_key?:boolean;clear_key?:boolean;json_mode:string;thinking_disabled:boolean;context_chars:number;timeout_s:number;query_prefix?:string;document_prefix?:string};
export type TaskBinding={provider:string;model:string;revision:string};
export type MemoryPolicy={mode:'lexical'|'hybrid';failure:'lexical'|'error';max_calls:number;max_chunks:number;min_similarity:number};
export type EngineConfig={providers:Record<string,NamedProvider>;bindings:Record<string,TaskBinding>;decision_policy:{mode:string;min_probability:number;min_margin:number};memory_policy:MemoryPolicy};
const compatible=(role:string,backend:string)=>!['openai','systemone','openai_embedding'].includes(backend)||backend===(role==='memory_embedding'?'openai_embedding':role==='action_router'?'systemone':'openai');
const guide:Record<string,[MessageKey,MessageKey]>={
 world_builder:["engine.world_builder","engine.world_builder.hint"],
 story_builder:["engine.story_builder","engine.story_builder.hint"],
 rules_builder:["engine.rules_builder","engine.rules_builder.hint"],
 simulation_builder:["engine.simulation_builder","engine.simulation_builder.hint"],
 state_builder:["engine.state_builder","engine.state_builder.hint"],
 content_reviewer:["engine.content_reviewer","engine.content_reviewer.hint"],
 import_builder:["engine.import_builder","engine.import_builder.hint"],
 game_master:["engine.game_master","engine.game_master.hint"],
 character_actor:["engine.character_actor","engine.character_actor.hint"],
 narrator:["engine.narrator","engine.narrator.hint"],
 world_actor:["engine.world_actor","engine.world_actor.hint"],
 memory_embedding:["engine.memory_embedding","engine.memory_embedding.hint"],
 action_router:["engine.action_router","engine.action_router.hint"],
};
export function EngineBindings({value,onChange,api}:{value:EngineConfig;onChange:(p:Partial<EngineConfig>)=>void;api:Api}){
 useLocale();
 const [result,setResult]=useUiMessage();const [testing,setTesting]=useState('');

 function patch(id:string,p:Partial<NamedProvider>){
  const providers={...value.providers,[id]:{...value.providers[id],...p}};
  if(p.backend&&p.backend!==value.providers[id].backend){
   const bindings=Object.fromEntries(Object.entries(value.bindings).filter(([role,b])=>b.provider!==id||compatible(role,p.backend!)));
   onChange({providers,bindings,...(!bindings.action_router?{decision_policy:{...value.decision_policy,mode:'off'}}:{}),...(!bindings.memory_embedding?{memory_policy:{...value.memory_policy,mode:'lexical'}}:{})});
  }else onChange({providers});
 }
 function add(){let n=1;while(value.providers['provider_'+n])n++;onChange({providers:{...value.providers,['provider_'+n]:{backend:'openai',url:'http://127.0.0.1:8000/v1',json_mode:'object',thinking_disabled:false,context_chars:120000,timeout_s:90}}});}
 function remove(id:string){const providers={...value.providers};delete providers[id];const bindings=Object.fromEntries(Object.entries(value.bindings).filter(([,b])=>b.provider!==id));onChange({providers,bindings,...(!bindings.action_router?{decision_policy:{...value.decision_policy,mode:'off'}}:{}),...(!bindings.memory_embedding?{memory_policy:{...value.memory_policy,mode:'lexical'}}:{})});}
 function bind(role:string,provider:string){const bindings={...value.bindings};if(provider)bindings[role]={provider,model:'',revision:''};else delete bindings[role];onChange({bindings,...(role==='action_router'&&!provider?{decision_policy:{...value.decision_policy,mode:'off'}}:{}),...(role==='memory_embedding'&&!provider?{memory_policy:{...value.memory_policy,mode:'lexical'}}:{})});}
 async function check(role:string){setTesting(role);setResult('');try{const r=await api('/api/engines/'+role+'/check',{method:'POST'});setResult(uiMessage("engine.protocolResult", {p0: JSON.stringify(r.answers||r.sample)}));}catch(e){setResult(String(e));}finally{setTesting('');}}
 return <details className="engine-bindings"><summary>{uiText("EngineBindings.028")}</summary>
 <p>{uiText("EngineBindings.027")}</p>
 {Object.entries(value.providers).map(([id,p])=><fieldset key={id}><legend>{id}</legend>
 <label className="studio-field">{uiText("EngineBindings.026")}<select aria-label={id+' backend'} value={p.backend} onChange={e=>patch(id,{backend:e.target.value,timeout_s:e.target.value==='systemone'?15:90})}><option value="openai">{uiText("engine.openai")}</option><option value="systemone">{uiText("engine.systemone")}</option><option value="openai_embedding">{uiText("engine.openai_embedding")}</option></select></label>
 <label className="studio-field">{uiText("EngineBindings.025")}<input aria-label={id+' URL'} value={p.url} onChange={e=>patch(id,{url:e.target.value})}/></label>
 <label className="studio-field">API key<input aria-label={id+' API key'} type="password" autoComplete="new-password" value={p.api_key||''} placeholder={p.has_key?uiText("EngineBindings.024"):uiText("EngineBindings.023")} onChange={e=>patch(id,{api_key:e.target.value,clear_key:false})}/></label>
 <label className="checkboxes"><input type="checkbox" checked={p.clear_key||false} onChange={e=>patch(id,{clear_key:e.target.checked,api_key:''})}/>{uiText("EngineBindings.022")}</label>
 <div className="form-grid"><label className="studio-field">{uiText("EngineBindings.021")}<input type="number" min={1} max={120} value={p.timeout_s} onChange={e=>patch(id,{timeout_s:Number(e.target.value)})}/></label><label className="studio-field">{uiText("EngineBindings.020")}<input type="number" min={1000} max={1000000} value={p.context_chars} onChange={e=>patch(id,{context_chars:Number(e.target.value)})}/></label></div>
 {p.backend==='openai'&&<><label className="studio-field">JSON<select value={p.json_mode} onChange={e=>patch(id,{json_mode:e.target.value})}><option value="object">JSON Object</option><option value="schema">JSON Schema</option><option value="prompt">{uiText("engine.prompt")}</option></select></label><label className="checkboxes"><input type="checkbox" checked={p.thinking_disabled} onChange={e=>patch(id,{thinking_disabled:e.target.checked})}/>{uiText("EngineBindings.019")}</label></>}
 {p.backend==='openai_embedding'&&(['query_prefix','document_prefix'] as const).map(k=><label className="studio-field" key={k}>{uiText(k==='query_prefix'?'memory.query_prefix':'memory.document_prefix')}<input value={p[k]||''} onChange={e=>patch(id,{[k]:e.target.value})}/></label>)}
 <button className="text-button" onClick={()=>remove(id)}>{uiText("EngineBindings.018")}</button></fieldset>)}
 <button className="secondary" onClick={add}>{uiText("EngineBindings.017")}</button>
 {Object.entries(guide).map(([role,names])=>{const b=value.bindings[role];return <fieldset key={role}><legend>{uiText(names[0])}</legend><p className="tiny-muted">{uiText(names[1])}</p><label className="studio-field">{uiText("EngineBindings.016")}<select aria-label={role+' provider'} value={b?.provider||''} onChange={e=>bind(role,e.target.value)}><option value="">{(role==='action_router'||role==='memory_embedding')?uiText("EngineBindings.015"):uiText("EngineBindings.014")}</option>{Object.entries(value.providers).filter(([,p])=>compatible(role,p.backend!)).map(([id])=><option key={id}>{id}</option>)}</select></label>{b&&<><label className="studio-field">{uiText("EngineBindings.013")}<input aria-label={role+' model'} value={b.model} onChange={e=>onChange({bindings:{...value.bindings,[role]:{...b,model:e.target.value}}})}/></label><label className="studio-field">{uiText("EngineBindings.012")}<input aria-label={role+' revision'} value={b.revision} onChange={e=>onChange({bindings:{...value.bindings,[role]:{...b,revision:e.target.value}}})}/></label><button className="secondary" disabled={!!testing} onClick={()=>void check(role)}>{testing===role?uiText("EngineBindings.011"):uiText("EngineBindings.010")}</button></>}</fieldset>;})}
 {value.bindings.action_router&&<fieldset><legend>{uiText("EngineBindings.009")}</legend><p>{uiText("EngineBindings.008")}</p><label className="studio-field">{uiText("EngineBindings.007")}<select aria-label="Decision routing mode" value={value.decision_policy.mode} onChange={e=>onChange({decision_policy:{...value.decision_policy,mode:e.target.value}})}><option value="off">{uiText("EngineBindings.006")}</option><option value="shadow">{uiText("EngineBindings.005")}</option><option value="auto">{uiText("EngineBindings.004")}</option></select></label>{(['min_probability','min_margin'] as const).map(k=><label className="studio-field" key={k}>{k==='min_probability'?uiText("EngineBindings.003"):uiText("EngineBindings.002")}<input type="number" min={k==='min_probability'?0.5:0} max={1} step={0.01} value={value.decision_policy[k]} onChange={e=>onChange({decision_policy:{...value.decision_policy,[k]:Number(e.target.value)}})}/></label>)}</fieldset>}
 {value.bindings.memory_embedding&&<fieldset><legend>{uiText("memory.policy")}</legend><p className="tiny-muted">{uiText("memory.policy.hint")}</p><label className="studio-field">{uiText("memory.mode")}<select aria-label="Memory retrieval mode" value={value.memory_policy.mode} onChange={e=>onChange({memory_policy:{...value.memory_policy,mode:e.target.value as MemoryPolicy['mode']}})}><option value="lexical">{uiText("memory.lexical")}</option><option value="hybrid">{uiText("memory.hybrid")}</option></select></label><label className="studio-field">{uiText("memory.failure")}<select value={value.memory_policy.failure} onChange={e=>onChange({memory_policy:{...value.memory_policy,failure:e.target.value as MemoryPolicy['failure']}})}><option value="lexical">{uiText("memory.fallback")}</option><option value="error">{uiText("memory.error")}</option></select></label></fieldset>}
 <p className="tiny-muted">{uiText("EngineBindings.001")}</p>{result&&<p role="status" className="notice">{result}</p>}
 </details>;
}
