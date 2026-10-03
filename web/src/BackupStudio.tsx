import { uiText, useLocale } from './i18n';
import { useState } from 'react';
import { ArchiveRestore, Download } from 'lucide-react';
import { Api } from './AvatarStudio';
type Preview={title:string;player_name:string;branches:{title:string;version:number}[];missing_avatars:string[];includes:string};
export function BackupStudio({api,onRestored}:{api:Api;onRestored:(cid:string,bid:string)=>void}){
  useLocale();
  const [raw,setRaw]=useState('');const [preview,setPreview]=useState<Preview|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  async function read(file?:File){setPreview(null);setRaw('');setError('');if(!file)return;setBusy(true);try{if(file.size>6000000)throw Error(uiText("BackupStudio.009"));const text=await file.text();const value=await api('/api/backups/preview',{method:'POST',body:text});setRaw(text);setPreview(value);}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function restore(){setBusy(true);setError('');try{const c=await api('/api/backups/restore',{method:'POST',body:raw});setPreview(null);onRestored(c.id,c.branch_id);}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <section className="backup-studio"><details><summary><ArchiveRestore size={18}/>{uiText("BackupStudio.001")}</summary><p>{uiText("BackupStudio.002")}</p><label className="studio-field">{uiText("BackupStudio.003")}<input aria-label={uiText("BackupStudio.003")} type="file" accept="application/json,.json" disabled={busy} onChange={e=>void read(e.target.files?.[0])}/></label>{error&&<p className="notice error" role="alert">{error}</p>}{preview&&<div className="backup-preview"><h3>{preview.title} · {preview.player_name}</h3><p>{preview.includes}</p>{preview.branches.map((b,i)=><p key={i}>{uiText("BackupStudio.004", {p0: (b.title), p1: (b.version)})}</p>)}{preview.missing_avatars.length>0&&<p>{uiText("BackupStudio.005", {p0: (preview.missing_avatars.length)})}</p>}<button className="primary" disabled={busy} onClick={()=>void restore()}>{uiText("BackupStudio.006")}</button></div>}</details></section>;
}
export function BackupLink({cid}:{cid:string}){
  useLocale();return <a className="text-button" title={uiText("BackupStudio.008")} href={`/api/campaigns/${cid}/backup`} download><Download size={14}/>{uiText("BackupStudio.007")}</a>;}
