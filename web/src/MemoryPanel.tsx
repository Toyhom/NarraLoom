import { uiText, useLocale } from './i18n';
import { useEffect, useState } from 'react';
import { NotebookPen, Search, Check } from 'lucide-react';

export type NoteRecord={id:string;text:string;kind:'note'|'commitment';status:'open'|'done'|'archived';source_event_ids:string[]};
type Memory={source_id:string;kind:string;text:string;source_event_ids:string[];world_version?:number;game_time_s?:number;certainty:string;origin_story?:string};
const names:Record<string,string>={get known_fact() { return uiText("MemoryPanel.026"); },get utterance() { return uiText("MemoryPanel.025"); },get outcome() { return uiText("MemoryPanel.024"); },get historical_record() { return uiText("MemoryPanel.023"); },get note() { return uiText("MemoryPanel.010"); },get commitment() { return uiText("MemoryPanel.011"); }};
export function MemoryPanel({api,campaign,branch,version,notes,busy,onRecord,memoryPath}:{api:(path:string,opts?:RequestInit)=>Promise<any>;campaign:string;branch:string;version:number;notes:NoteRecord[];busy:boolean;onRecord:(note:NoteRecord)=>void;memoryPath?:string}){
  useLocale();
  const [query,setQuery]=useState('');const [rows,setRows]=useState<Memory[]>([]);const [error,setError]=useState('');
  const [text,setText]=useState('');const [kind,setKind]=useState<'note'|'commitment'>('note');const [sources,setSources]=useState<string[]>([]);
  useEffect(()=>{setRows([]);setQuery('');setError('');setSources([]);setText('');},[campaign,branch]);
  async function search(){try{setError('');const result=await api((memoryPath||`/api/campaigns/${campaign}/branches/${branch}/memories`)+`?q=${encodeURIComponent(query)}`);setRows(result.records);}catch(e){setError(String(e));}}
  function save(){if(!text.trim())return;onRecord({id:'note_'+crypto.randomUUID().replaceAll('-',''),text:text.trim(),kind,status:'open',source_event_ids:sources});setText('');setSources([]);}
  return <section className="sidebar-section memory-panel"><h3><NotebookPen size={16}/>{uiText("MemoryPanel.001")}</h3>
    <details><summary>{uiText("MemoryPanel.002")}</summary><div className="memory-search"><input aria-label={uiText("MemoryPanel.022")} maxLength={240} value={query} placeholder={uiText("MemoryPanel.021")} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();void search();}}}/><button aria-label={uiText("MemoryPanel.020")} onClick={()=>void search()}><Search size={15}/></button></div>
      <p className="tiny-muted">{uiText("MemoryPanel.003")}</p>
      {rows.map(row=><article className="memory-result" key={row.source_id}><small>{names[row.kind]||row.kind}{row.origin_story?uiText("MemoryPanel.019", {p0: (row.origin_story)}):''}{row.world_version?uiText("MemoryPanel.018", {p0: (row.world_version)}):''}</small><p>{row.text}</p><details><summary>{uiText("MemoryPanel.004")}</summary><code>{row.source_id}</code>{row.source_event_ids.filter(id=>id!==row.source_id).map(id=><code key={id}>{id}</code>)}</details><button className="text-button" onClick={()=>{setText(row.text.slice(0,1800));setSources([row.source_id]);}}>{uiText("MemoryPanel.005")}</button></article>)}
      {error&&<p className="notice error" role="alert">{error}</p>}
    </details>
    <div className="note-list">{notes.filter(n=>n.status!=='archived').map(n=><article key={n.id} className={'personal-note '+n.status}><span>{names[n.kind]}</span><p>{n.text}</p>{n.status==='open'?<button disabled={busy} className="text-button" onClick={()=>onRecord({...n,status:'done'})}><Check size={13}/>{uiText("MemoryPanel.006")}</button>:<button disabled={busy} className="text-button" onClick={()=>onRecord({...n,status:'open'})}>{uiText("MemoryPanel.007")}</button>}<button disabled={busy} className="text-button" onClick={()=>onRecord({...n,status:'archived'})}>{uiText("MemoryPanel.008")}</button></article>)}</div>
    <details className="note-editor"><summary>{uiText("MemoryPanel.009")}</summary><select aria-label={uiText("MemoryPanel.017")} value={kind} onChange={e=>setKind(e.target.value as 'note'|'commitment')}><option value="note">{uiText("MemoryPanel.010")}</option><option value="commitment">{uiText("MemoryPanel.011")}</option></select><textarea aria-label={uiText("MemoryPanel.016")} maxLength={1800} value={text} onChange={e=>setText(e.target.value)} placeholder={uiText("MemoryPanel.015")}/>{sources.length>0&&<p className="tiny-muted">{uiText("MemoryPanel.012", {p0: (sources.length)})}</p>}<button className="secondary" disabled={busy||!text.trim()} onClick={save}>{uiText("MemoryPanel.013")}</button><p className="tiny-muted">{uiText("MemoryPanel.014", {p0: (version)})}</p></details>
  </section>;
}
