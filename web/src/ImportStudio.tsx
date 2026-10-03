import { uiText, useLocale } from './i18n';
import { ContentLanguage } from './CreationOptions';
import { useEffect, useState } from 'react';
import { FileUp, Download, ArrowRight } from 'lucide-react';

type Entry = {source: string; status: string; note?: string; target?: string; targets?: string[]};
type Source = {id: string; filename: string; name: string; format: string; report: Entry[]; sha256: string};
type Api = (path: string, options?: RequestInit) => Promise<any>;
const statusNames: Record<string, string> = {get candidate() { return uiText("ImportStudio.023"); }, get mapped() { return uiText("ImportStudio.022"); }, get partial() { return uiText("ImportStudio.021"); }, get unmapped() { return uiText("ImportStudio.020"); }, get preserved() { return uiText("ImportStudio.019"); }, get unsupported() { return uiText("ImportStudio.018"); }};

export function ConversionReport({rows}: {rows: Entry[]}) {
  useLocale();
  return <details className="conversion-report"><summary>{uiText("ImportStudio.001", {p0: (rows.length)})}</summary>
    <p className="tiny-muted">{uiText("ImportStudio.002")}</p>
    {rows.map((r,i)=><div className="conversion-row" key={i}><code>{r.source}</code><strong>{statusNames[r.status]||r.status}</strong><p>{r.note}</p>{r.targets?.length ? <small>{r.targets.join('、')}</small>:null}</div>)}
  </details>;
}

export function ImportStudio({api,ready,onJob}: {api: Api; ready: boolean|null; onJob: () => Promise<void>}) {
  useLocale();
  const [sources,setSources]=useState<Source[]>([]);
  const [contentLanguage,setContentLanguage]=useState('auto');
  const [selected,setSelected]=useState('');
  const [additional,setAdditional]=useState<string[]>([]);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [brief,setBrief]=useState('');
  async function refresh(){setSources(await api('/api/studio/imports'));}
  useEffect(()=>{void refresh().catch(e=>setError(String(e)));},[]);
  const source=sources.find(s=>s.id===selected)||sources.at(-1);
  async function upload(file?:File){
    if(!file)return;
    setError('');setBusy(true);
    try{
      if(file.size>8*1024*1024)throw new Error(uiText("ImportStudio.017"));
      const value=await api('/api/studio/imports?filename='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
      await refresh();setSelected(value.id);
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function convert(){
    if(!source)return;
    setBusy(true);setError('');
    try{await api(`/api/studio/imports/${source.id}/convert`,{method:'POST',body:JSON.stringify({brief,content_language:contentLanguage,additional_ids:source.format==='roleplay-world'?[]:additional.filter(id=>id!==source.id)})});await onJob();}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <section className="import-studio">
    <div className="section-heading"><h2><FileUp size={20}/>{uiText("ImportStudio.003")}</h2><span>{uiText("ImportStudio.004")}</span></div>
    <p className="tiny-muted">{uiText("ImportStudio.005")}</p>
    <label className="secondary import-upload"><FileUp size={16}/>{busy?uiText("ImportStudio.016"):uiText("ImportStudio.015")}<input aria-label={uiText("ImportStudio.014")} type="file" accept=".json,.png,.charx,.zip" disabled={busy} onChange={e=>void upload(e.target.files?.[0])}/></label>
    {error&&<p className="notice error" role="alert">{error}</p>}
    {source&&<div className="import-preview">
      <label className="studio-field">{uiText("ImportStudio.006")}<select aria-label={uiText("ImportStudio.006")} value={source.id} onChange={e=>setSelected(e.target.value)}>{sources.map(s=><option key={s.id} value={s.id}>{s.name} · {s.filename}</option>)}</select></label>
      <p>{source.name} <span className="status-pill">{source.format}</span> <a href={`/api/studio/imports/${source.id}/original`} className="quiet-button"><Download size={14}/>{uiText("ImportStudio.007")}</a></p>
      <ConversionReport rows={source.report}/>
      {source.format!=='roleplay-world'&&sources.length>1&&<fieldset className="import-bundle"><legend>{uiText("ImportStudio.008")}</legend>{sources.filter(s=>s.id!==source.id&&s.format!=='roleplay-world').map(s=><label key={s.id}><input type="checkbox" checked={additional.includes(s.id)} onChange={e=>setAdditional(e.target.checked?[...additional,s.id]:additional.filter(id=>id!==s.id))}/>{s.name} · {s.filename}</label>)}</fieldset>}
      <label className="studio-field">{uiText("ImportStudio.009")}<textarea aria-label={uiText("ImportStudio.013")} maxLength={2500} value={brief} onChange={e=>setBrief(e.target.value)} placeholder={uiText("ImportStudio.012")}/></label>
      {source.format!=='roleplay-world'&&<ContentLanguage source value={contentLanguage} onChange={setContentLanguage}/>}
      <button className="primary" disabled={!ready||busy||!contentLanguage} onClick={()=>void convert()}>{source.format==='roleplay-world'?uiText("ImportStudio.011"):uiText("ImportStudio.010")}<ArrowRight size={16}/></button>
    </div>}
  </section>;
}
