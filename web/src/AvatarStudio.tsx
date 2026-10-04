import { uiText, useLocale } from './i18n';
import { useEffect, useState } from 'react';
import { ImagePlus, RotateCcw } from 'lucide-react';
export type AvatarRecord={id:string;description:string;name?:string;state:string;stage:string;progress:number;error?:string};
export type Api=(path:string,opts?:RequestInit)=>Promise<any>;
const stages:Record<string,string>={get queued() { return uiText("AvatarStudio.029"); },get understanding() { return uiText("AvatarStudio.028"); },get illustrating() { return uiText("AvatarStudio.027"); },get landmarking() { return uiText("AvatarStudio.026"); },get voicing() { return uiText("AvatarStudio.025"); },get packaging() { return uiText("AvatarStudio.024"); },get mouth_design() { return uiText("AvatarStudio.023"); },get mouth_binding() { return uiText("AvatarStudio.022"); },get complete() { return uiText("AvatarStudio.021"); }};
export async function createAvatar(api:Api,file:File,description:string,requestId:string){
  if(file.size>10_000_000)throw Error(uiText("AvatarStudio.020"));
  const image=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error(uiText("AvatarStudio.019")));reader.readAsDataURL(file);});
  return await api('/api/avatars',{method:'POST',body:JSON.stringify({request_id:requestId,description,image_base64:image})}) as AvatarRecord;
}
export function AvatarStudio({api,onSelect}:{api:Api;onSelect?:(id:string)=>void}){
  useLocale();
  const [items,setItems]=useState<AvatarRecord[]>([]);const [available,setAvailable]=useState(false);const [error,setError]=useState('');
  const [file,setFile]=useState<File|null>(null);const [brief,setBrief]=useState('');const [saving,setSaving]=useState(false);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID().replaceAll('-',''));
  async function refresh(){setItems(await api('/api/avatars'));}
  useEffect(()=>{let mounted=true;void api('/api/avatars/capabilities').then(c=>{if(mounted)setAvailable(c.available);}).catch(e=>{if(mounted){setAvailable(false);setError(String(e));}});const update=()=>void api('/api/avatars').then(rows=>{if(mounted)setItems(rows);}).catch(e=>{if(mounted)setError(String(e));});update();const timer=setInterval(update,7000);return()=>{mounted=false;clearInterval(timer);};},[]);
  async function create(){if(!file)return;setSaving(true);setError('');try{const avatar=await createAvatar(api,file,brief,requestId);setRequestId(crypto.randomUUID().replaceAll('-',''));onSelect?.(avatar.id);await refresh();}catch(e){setError(String(e));}finally{setSaving(false);}}
  async function control(id:string,op:string){try{setError('');await api(`/api/avatars/${id}/${op}`,{method:'POST'});await refresh();}catch(e){setError(String(e));}}
  return <section className="avatar-studio"><div className="section-heading"><h2><ImagePlus size={20}/>{uiText("AvatarStudio.001")}</h2><span>{uiText("AvatarStudio.002")}</span></div><p>{uiText("AvatarStudio.003")}</p>
    <details><summary>{uiText("AvatarStudio.004")}</summary><div className="form-grid"><label className="studio-field">{uiText("AvatarStudio.005")}<input type="file" aria-label={uiText("AvatarStudio.018")} accept="image/png,image/jpeg,image/webp" onChange={e=>{setFile(e.target.files?.[0]||null);setRequestId(crypto.randomUUID().replaceAll('-',''));}}/></label><label className="studio-field">{uiText("AvatarStudio.006")}<textarea aria-label={uiText("AvatarStudio.017")} maxLength={1500} value={brief} onChange={e=>{setBrief(e.target.value);setRequestId(crypto.randomUUID().replaceAll('-',''));}}/></label></div><button className="secondary" disabled={!available||saving||!file||brief.trim().length<2} onClick={()=>void create()}>{saving?uiText("AvatarStudio.016"):uiText("AvatarStudio.015")}</button>{!available&&<p className="tiny-muted">{uiText("AvatarStudio.007")}</p>}</details>
    {error&&<p role="alert" className="notice error">{error}</p>}<div className="avatar-library">{items.map(a=><article key={a.id} className="avatar-job"><div>{a.state==='ready'?<img src={`/api/avatars/${a.id}/files/puppet/portrait.png`} alt={a.name||uiText("AvatarStudio.014")}/>:<ImagePlus size={35}/>}</div><section><h4>{a.name||a.description.slice(0,32)}</h4><p>{stages[a.stage]||a.stage} · {a.progress}%</p>{a.error&&<small>{a.error}</small>}{['queued','running','submitting','submission_error'].includes(a.state)&&<button className="text-button" onClick={()=>void control(a.id,'cancel')}>{uiText("AvatarStudio.008")}</button>}{['failed','cancelled'].includes(a.state)&&<button className="text-button" onClick={()=>void control(a.id,'retry')}><RotateCcw size={13}/>{uiText("AvatarStudio.009")}</button>}</section></article>)}</div>
  </section>;
}

export function AvatarPicker({api,value,onChange}:{api:Api;value?:string|null;onChange:(id:string|null)=>void}){
  useLocale();
  const [items,setItems]=useState<AvatarRecord[]>([]);
  useEffect(()=>{void api('/api/avatars').then(setItems).catch(()=>setItems([]));},[]);
  return <label className="studio-field">{uiText("AvatarStudio.010")}<select aria-label={uiText("AvatarStudio.013")} value={value||''} onChange={e=>onChange(e.target.value||null)}><option value="">{uiText("AvatarStudio.011")}</option>{items.map(a=><option value={a.id} key={a.id}>{a.name||a.description.slice(0,32)} · {a.state==='ready'?uiText("AvatarStudio.012"):stages[a.stage]||a.state}</option>)}</select></label>;
}
