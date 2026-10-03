import { useEffect, useState } from 'react';
import { BookOpen, Download, FileUp, Share2, X } from 'lucide-react';
import { LocaleSwitcher } from './LocaleSwitcher';
import { uiText, useLocale, useUiMessage, uiMessage } from './i18n';

type Api=(path:string,options?:RequestInit)=>Promise<any>;
type Meta={slug:string;release:string;title:string;summary:string;author:string;license:string;license_text:string;tags:string[];model_notes:string;known_limits:string[]};
type Pack={id?:string;revision?:number;visibility?:string;sha256:string;metadata:Meta;genre:string;locations:number;characters:number;assets:{id:string;name:string}[];capabilities:string[];omissions:string[];stories:{key:string;title:string;language:string;preset:string}[]};
type ShareStory={id:string;revision:number;world_revision:number;world_id:string;world_content:{title:string;premise:string};content:{title:string};test_report:{status:string;revision?:number}};
const blank=():Meta=>({slug:'my-world',release:'1.0.0',title:'',summary:'',author:'',license:'',license_text:'',tags:[],model_notes:'',known_limits:[]});
const visibilityLabel=(value:string)=>({private:uiText('community.private'),unlisted:uiText('community.unlisted'),listed:uiText('community.listed'),withdrawn:uiText('community.withdrawn')}[value]||value);
function Metadata({pack}:{pack:Pack}){
 useLocale();
 return <><h3>{pack.metadata.title} <small>{pack.metadata.release}</small></h3><p>{pack.metadata.summary}</p>
  <p className="tiny-muted">{uiText('community.credit',{p0:pack.metadata.author,p1:pack.metadata.license})}</p>
  <p className="tiny-muted">{uiText('community.counts',{p0:pack.locations,p1:pack.characters,p2:pack.stories.length,p3:pack.assets.length})}</p>
  <details><summary>{uiText('community.details')}</summary><p>{uiText('community.modelRequirement')}</p><p>{pack.metadata.model_notes}</p>
   <p>{pack.metadata.tags.join(' · ')}</p><p>{pack.capabilities.join(' · ')}</p>
   {pack.metadata.known_limits.map((text,i)=><p key={i}>{text}</p>)}{pack.omissions.map((text,i)=><p key={i}>{text}</p>)}
   <pre className="package-license">{pack.metadata.license_text}</pre><small>{uiText('community.attribution')}</small>
  </details></>;
}
function InstallCard({pack,ready,pending,onInstall}:{pack:Pack;ready:boolean|null;pending:boolean;onInstall:(keys:string[])=>void}){
 useLocale();const [keys,setKeys]=useState(pack.stories.map(s=>s.key));
 return <article className="community-card" data-package-id={pack.id||pack.sha256}><Metadata pack={pack}/>
  <fieldset><legend>{uiText('community.chooseStories')}</legend>{pack.stories.map(s=><label className="package-choice" key={s.key}>
   <input type="checkbox" checked={keys.includes(s.key)} onChange={e=>setKeys(e.target.checked?[...keys,s.key]:keys.filter(k=>k!==s.key))}/><span>{s.title}<small>{s.language} · {s.preset}</small></span></label>)}</fieldset>
  <p className="tiny-muted">{uiText('community.retest')}</p><div className="story-card-actions"><button className="primary" disabled={!ready||pending||!keys.length} onClick={()=>onInstall(keys)}>{uiText(pending?'community.installing':'community.install')}</button>
  {pack.id&&<a className="secondary" href={`/api/community/${pack.id}/download`}><Download size={15}/>{uiText('community.download')}</a>}</div>
 </article>;
}
export function PackagePublisher({api,stories,onCreated}:{api:Api;stories:ShareStory[];onCreated:()=>void}){
 useLocale();const [open,setOpen]=useState(false),[snapshot,setSnapshot]=useState<ShareStory[]>([]),[revision,setRevision]=useState(1),[selected,setSelected]=useState<string[]>([]);
 const [meta,setMeta]=useState<Meta>(blank),[assets,setAssets]=useState(true),[pending,setPending]=useState(false),[error,setError]=useState('');const [tagText,setTagText]=useState('');
 function begin(){const available=structuredClone(stories);setSnapshot(available);const rev=Math.max(...available.map(s=>s.world_revision),1);setRevision(rev);setSelected(available.filter(s=>s.world_revision===rev&&s.test_report.status==='passed'&&s.test_report.revision===s.revision).slice(0,8).map(s=>s.id));setMeta({...blank(),title:available[0]?.world_content.title||'',summary:available[0]?.world_content.premise||''});setTagText('');setError('');setOpen(true);}
 function field(key:keyof Meta,value:string){if(key==='tags'){setTagText(value);return;}setMeta(m=>({...m,[key]:key==='known_limits'?value.split('\n'):value}));}
 async function build(e:React.FormEvent){e.preventDefault();setPending(true);setError('');try{await api('/api/studio/packages',{method:'POST',body:JSON.stringify({metadata:{...meta,tags:tagText.split(',').map(t=>t.trim()).filter(Boolean)},stories:snapshot.filter(s=>selected.includes(s.id)).map(s=>({id:s.id,revision:s.revision})),include_avatars:assets})});setOpen(false);onCreated();document.querySelector('.community-section')?.scrollIntoView({behavior:'smooth'});}catch(e){setError(String(e));}finally{setPending(false);}}
 return <><button className="secondary" disabled={!stories.length} onClick={begin}><Share2 size={16}/>{uiText('community.create')}</button>
 {open&&<div className="modal-backdrop"><section className="modal package-modal" role="dialog" aria-modal="true" aria-labelledby="package-title"><LocaleSwitcher/><button className="icon-button modal-close" disabled={pending} onClick={()=>setOpen(false)} aria-label={uiText('community.close')}><X size={18}/></button>
 <h2 id="package-title">{uiText('community.create')}</h2><p>{uiText('community.snapshot')}</p><form onSubmit={build}>
 <label className="studio-field">{uiText('community.worldRevision')}<select aria-label={uiText('community.worldRevision')} value={revision} onChange={e=>{setRevision(Number(e.target.value));setSelected([]);}}>{[...new Set(snapshot.map(s=>s.world_revision))].sort((a,b)=>b-a).map(r=><option key={r} value={r}>{r}</option>)}</select></label>
 <fieldset><legend>{uiText('community.chooseTested')}</legend>{snapshot.filter(s=>s.world_revision===revision).map(s=><label className="package-choice" key={s.id}><input type="checkbox" disabled={s.test_report.status!=='passed'||s.test_report.revision!==s.revision||(!selected.includes(s.id)&&selected.length>=8)} checked={selected.includes(s.id)} onChange={e=>setSelected(e.target.checked?[...selected,s.id]:selected.filter(id=>id!==s.id))}/><span>{s.content.title}<small>{uiText('community.storyRevision',{p0:s.revision})}</small></span></label>)}</fieldset>
 {(['title','slug','release','summary','author','license','license_text','tags','model_notes','known_limits'] as const).map(key=><label key={key} className="studio-field"><span>{uiText(`community.field.${key}`)}</span>{['summary','license_text','model_notes','known_limits'].includes(key)?<textarea aria-label={uiText(`community.field.${key}`)} required={key==='summary'} value={Array.isArray(meta[key])?(meta[key] as string[]).join('\n'):meta[key] as string} maxLength={key==='license_text'?12000:800} onChange={e=>field(key,e.target.value)}/>:<input aria-label={uiText(`community.field.${key}`)} required={key!=='tags'} value={key==='tags'?tagText:Array.isArray(meta[key])?(meta[key] as string[]).join(', '):meta[key] as string} maxLength={key==='tags'?260:key==='release'?20:120} pattern={key==='slug'?'[a-z0-9][a-z0-9\\-]{0,59}':key==='release'?'[0-9]+\\.[0-9]+\\.[0-9]+':undefined} onChange={e=>field(key,e.target.value)}/>}</label>)}
 <label className="package-choice"><input type="checkbox" checked={assets} onChange={e=>setAssets(e.target.checked)}/><span>{uiText('community.includeAssets')}</span></label><p className="tiny-muted">{uiText('community.scope')}</p>
 {error&&<p className="notice error" role="alert">{error}</p>}<button className="primary" disabled={pending||!selected.length}>{uiText(pending?'community.building':'community.build')}</button>
 </form></section></div>}</>;
}
export function Community({api,ready,refreshKey,onInstalled}:{api:Api;ready:boolean|null;refreshKey:number;onInstalled:(wid:string)=>Promise<void>}){
 useLocale();const [packs,setPacks]=useState<Pack[]>([]),[own,setOwn]=useState<Pack[]>([]),[shared,setShared]=useState<Pack|null>(null),[total,setTotal]=useState(0),[offset,setOffset]=useState(0);
 const [q,setQ]=useState(''),[language,setLanguage]=useState(''),[tag,setTag]=useState(''),[pending,setPending]=useState(''),[error,setError]=useState(''),[message,setMessage]=useUiMessage('');
 const [file,setFile]=useState<File|null>(null),[preview,setPreview]=useState<Pack|null>(null);
 const sharedId=new URLSearchParams(location.search).get('package');
 async function refresh(start=offset){const [s,m]=await Promise.all([api(`/api/community?${new URLSearchParams({q,language,tag,offset:String(start),limit:'12'})}`),api('/api/studio/packages')]);setPacks(s.items);setTotal(s.total);setOwn(m);setOffset(start);}
 useEffect(()=>{void refresh(0).catch(e=>setError(String(e)));},[refreshKey]);
 useEffect(()=>{if(sharedId)void api('/api/community/'+encodeURIComponent(sharedId)).then(v=>{setShared(v);setTimeout(()=>document.querySelector('#shared-package')?.scrollIntoView({behavior:'smooth'}),100);}).catch(e=>setError(String(e)));},[sharedId]);
 async function visibility(pack:Pack,value:string){setPending(pack.id!);setError('');try{await api(`/api/studio/packages/${pack.id}/visibility`,{method:'PUT',body:JSON.stringify({expected_revision:pack.revision,visibility:value})});await refresh();}catch(e){setError(String(e));}finally{setPending('');}}
 async function inspect(value?:File){if(!value)return;setFile(value);setPreview(null);setPending('upload');setError('');try{if(value.size>32*1024*1024)throw Error(uiText('community.size'));setPreview(await api('/api/studio/packages/preview',{method:'POST',headers:{'Content-Type':'application/zip'},body:value}));}catch(e){setError(String(e));}finally{setPending('');}}
 async function install(pack:Pack,keys:string[],local=false){setPending(pack.id||'upload');setError('');try{const job=await api(local?'/api/studio/packages/import?'+new URLSearchParams(keys.map(k=>['story_keys',k])):`/api/community/${pack.id}/install`,local?{method:'POST',headers:{'Content-Type':'application/zip'},body:file}:{method:'POST',body:JSON.stringify({story_keys:keys})});setMessage(uiMessage('community.installed'));await onInstalled(job.world_id);}catch(e){setError(String(e));}finally{setPending('');}}
 async function copyLink(pack:Pack){const url=new URL(location.origin+location.pathname);url.searchParams.set('package',pack.id!);try{await navigator.clipboard.writeText(url.toString());setMessage(uiMessage('community.copied'));}catch{setMessage(url.toString());}}
 return <section className="community-section"><div className="section-heading"><h2><BookOpen size={20}/>{uiText('community.title')}</h2><span>{uiText('community.local')}</span></div><p>{uiText('community.intro')}</p>
 {error&&<p role="alert" className="notice error">{error}</p>}{message&&<p role="status" className="notice">{message}</p>}
 {shared&&<div id="shared-package"><h3>{uiText('community.shared')}</h3><InstallCard pack={shared} ready={ready} pending={!!pending} onInstall={keys=>void install(shared,keys)}/></div>}
 <form className="community-search" onSubmit={e=>{e.preventDefault();void refresh(0).catch(e=>setError(String(e)));}}><input aria-label={uiText('community.search')} placeholder={uiText('community.search')} value={q} maxLength={100} onChange={e=>setQ(e.target.value)}/><input aria-label={uiText('community.language')} placeholder={uiText('community.language')} value={language} maxLength={40} onChange={e=>setLanguage(e.target.value)}/><input aria-label={uiText('community.tag')} placeholder={uiText('community.tag')} value={tag} maxLength={32} onChange={e=>setTag(e.target.value)}/><button className="secondary">{uiText('community.find')}</button></form>
 <div className="community-grid">{packs.map(pack=><InstallCard key={pack.id} pack={pack} ready={ready} pending={!!pending} onInstall={keys=>void install(pack,keys)}/>)}</div>{!total&&<p className="tiny-muted">{uiText('community.empty')}</p>}
 {total>12&&<div className="story-card-actions"><button disabled={!offset} onClick={()=>void refresh(Math.max(0,offset-12)).catch(e=>setError(String(e)))}>{uiText('community.previous')}</button><span>{offset+1}–{Math.min(offset+12,total)} / {total}</span><button disabled={offset+12>=total} onClick={()=>void refresh(offset+12).catch(e=>setError(String(e)))}>{uiText('community.next')}</button></div>}
 <details className="package-own" open={own.length>0}><summary>{uiText('community.mine')}</summary><p>{uiText('community.publicationScope')}</p><div className="community-grid">{own.map(pack=><article key={pack.id} className="community-card" data-owned-package={pack.id}><Metadata pack={pack}/><label className="studio-field">{uiText('community.visibility')}<select aria-label={uiText('community.visibility')} value={pack.visibility} disabled={!!pending} onChange={e=>void visibility(pack,e.target.value)}>{['private','unlisted','listed','withdrawn'].map(v=><option key={v} value={v}>{visibilityLabel(v)}</option>)}</select></label><div className="story-card-actions"><a className="secondary" href={`/api/community/${pack.id}/download`}><Download size={15}/>{uiText('community.download')}</a>{['listed','unlisted'].includes(pack.visibility||'')&&<><button className="secondary" onClick={()=>void copyLink(pack)}><Share2 size={15}/>{uiText('community.link')}</button><a href={`?package=${encodeURIComponent(pack.id!)}`}>{uiText('community.view')}</a></>}</div></article>)}</div></details>
 <h3><FileUp size={18}/>{uiText('community.uploadTitle')}</h3><label className="studio-field"><span>{uiText('community.upload')}</span><input aria-label={uiText('community.upload')} type="file" accept=".zip" disabled={!!pending} onChange={e=>void inspect(e.target.files?.[0])}/></label><p className="tiny-muted">{uiText('community.oldImports')}</p>
 {preview&&<InstallCard key={preview.sha256} pack={preview} ready={ready} pending={!!pending} onInstall={keys=>void install(preview,keys,true)}/>}
 </section>;
}
