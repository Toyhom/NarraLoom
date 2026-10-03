import { uiMessage, useUiMessage, uiText, useLocale } from './i18n';
import { useEffect, useRef, useState } from 'react';
import { Image, Play, ChevronDown, ChevronUp } from 'lucide-react';
import { PuppetStage } from './avatar/puppet';
import { Api, AvatarRecord } from './AvatarStudio';
type Actor={id:string;name:string;avatar_id?:string};
type Dialogue={speaker_id?:string;text:string;emotion?:string;gesture?:string};
type History={id:string;segments:Dialogue[]}[];
export function NPCStage({api,actors,history,busy,base='/api/avatars'}:{api:Api;actors:Actor[];history:History;busy:boolean;base?:string}){
  useLocale();
  const available=actors.filter(a=>a.avatar_id);const latest=history.at(-1);
  const [chosen,setChosen]=useState('');const [collapsed,setCollapsed]=useState(false);const [loaded,setLoaded]=useState(false);const [status,setStatus]=useUiMessage(uiMessage("NPCStage.014"));const [replay,setReplay]=useState(0);
  const canvas=useRef<HTMLCanvasElement>(null);const stage=useRef<PuppetStage|null>(null);const animation=useRef(0);
  const actor=available.find(a=>a.id===chosen)||available.find(a=>latest?.segments.some(s=>s.speaker_id===a.id))||available[0];
  const dialogue=latest?.segments.find(s=>s.speaker_id===actor?.id);
  useEffect(()=>{
    let cancelled=false;let timer:ReturnType<typeof setTimeout>;setLoaded(false);
    if(!actor?.avatar_id||collapsed||!canvas.current)return;
    let renderer:PuppetStage;
    try{renderer=new PuppetStage(canvas.current, text => setStatus(text === "正在准备 2D 立绘…" ? uiMessage("avatar.preparing") : text === "准备好了" ? uiMessage("avatar.ready") : text));stage.current=renderer;renderer.active=true;renderer.closeup=true;}catch(e){setStatus(uiMessage("NPCStage.013", {p0: (String(e))}));return;}
    const load=async()=>{try{const value:AvatarRecord=await api(base+'/'+actor.avatar_id);if(cancelled)return;
      if(value.state!=='ready'){setStatus(value.state==='failed'?value.error||uiMessage("NPCStage.012"):uiMessage("NPCStage.011", {p0: (value.progress)}));timer=setTimeout(load,8000);return;}
      const profile=await api(`${base}/${actor.avatar_id}/files/profile.json`);if(cancelled)return;
      await renderer.load({profile,asset_base:`${base}/${actor.avatar_id}/files/puppet/`});if(!cancelled)setLoaded(true);
    }catch(e){if(!cancelled)setStatus(uiMessage("NPCStage.010", {p0: (String(e))}));}};void load();
    return()=>{cancelled=true;clearTimeout(timer);cancelAnimationFrame(animation.current);renderer.dispose();stage.current=null;};
  },[actor?.avatar_id,collapsed,base]);
  useEffect(()=>{
    cancelAnimationFrame(animation.current);const renderer=stage.current;if(!renderer||!loaded)return;
    if(busy||!dialogue){renderer.setMode(busy?'thinking':'listening');return;}
    const start=performance.now();const duration=Math.max(3,Math.min(16,dialogue.text.length/7));renderer.setMode('speaking');
    const run=()=>{const time=(performance.now()-start)/1000;if(time>=duration){renderer.setMode('listening');return;}
      const emotion=dialogue.emotion||'neutral';const gesture=dialogue.gesture||'none';
      renderer.setPerformance({action_time_s:time,actions:gesture==='none'?[]:[{name:gesture,start_s:0,duration_s:Math.min(3,duration),strength:.65}]},
        {values:{jaw_open:.12+.42*Math.abs(Math.sin(time*11))*Math.abs(Math.sin(time*3)),mouth_round:.15*Math.max(0,Math.sin(time*7)),[emotion]:.6}});
      if(canvas.current){canvas.current.dataset.frames=String(renderer.motionEvidence?.speechFrames||0);canvas.current.dataset.mouth=String(renderer.motionEvidence?.maxMouth||0);canvas.current.dataset.joint=String(renderer.motionEvidence?.maxJointDelta||0);canvas.current.dataset.actions=JSON.stringify(renderer.motionEvidence?.actionFrames||{});canvas.current.dataset.body=String(renderer.motionEvidence?.maxBodyDelta||0);canvas.current.dataset.commit=latest?.id||'';}
      animation.current=requestAnimationFrame(run);
    };animation.current=requestAnimationFrame(run);return()=>cancelAnimationFrame(animation.current);
  },[loaded,latest?.id,actor?.id,busy,replay]);
  if(!actor)return null;
  return <section className={'npc-theater '+(collapsed?'collapsed':'')} aria-label={uiText("NPCStage.009")}><div className="npc-stage-header"><strong><Image size={15}/>{actor.name}</strong>{available.length>1&&<select aria-label={uiText("NPCStage.008")} value={actor.id} onChange={e=>setChosen(e.target.value)}>{available.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select>}<span>{uiText("NPCStage.001")}</span><button className="icon-button" aria-label={collapsed?uiText("NPCStage.007"):uiText("NPCStage.006")} onClick={()=>setCollapsed(!collapsed)}>{collapsed?<ChevronDown size={15}/>:<ChevronUp size={15}/>}</button></div>{!collapsed&&<div className="npc-stage-body"><canvas ref={canvas} aria-label={uiText("NPCStage.005", {p0: (actor.name)})} data-ready={loaded}/><div className="npc-stage-caption"><small>{loaded?(busy?uiText("NPCStage.004"):uiText("NPCStage.003")):status}</small>{dialogue&&<p>{dialogue.text}</p>}{loaded&&dialogue&&!busy&&<button className="text-button" onClick={()=>setReplay(v=>v+1)}><Play size={13}/>{uiText("NPCStage.002")}</button>}</div></div>}</section>;
}
