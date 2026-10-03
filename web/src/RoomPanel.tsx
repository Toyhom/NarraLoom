import { LocaleSwitcher } from './LocaleSwitcher';
import { uiText, useLocale } from './i18n';
import { useEffect, useRef, useState } from 'react';
import { Users, ArrowLeft, X, Download, LockKeyhole } from 'lucide-react';
import { Api } from './AvatarStudio';
import { GamePanel, RuleAction } from './GamePanel';
import { MemoryPanel, NoteRecord } from './MemoryPanel';
import { StatePanel } from './StateEditor';
import { NPCStage } from './NPCStage';
import { TradePanel, TradeCommand } from './TradePanel';

type Member = {id:string; name:string; actor_id?:string|null};
type Room = {id:string; revision:number; closed:boolean; turn:string; me:string; host:boolean;
  title:string; world_version:number; mode:'shared_character'|'independent_characters';
  members:Member[]; characters:{id:string;name:string}[]; invite_code:string|null;
  state:any; pending:any[]; recoverable:any[]};
const active = (status:string) => ['accepted','planning','characters','narrating'].includes(status);

export function RoomEntry({api,campaign,onOpen,onClose}:{api:Api;campaign?:{cid:string;bid:string};onOpen:(id:string)=>void;onClose:()=>void}) {
  useLocale();
  const [name,setName]=useState(uiText("RoomPanel.079")); const [code,setCode]=useState('');
  const [mode,setMode]=useState('shared_character'); const [role,setRole]=useState(uiText("RoomPanel.090"));
  const [createCharacter,setCreateCharacter]=useState(true); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  async function submit(create=false) {
    setBusy(true);setError('');
    try {
      const room=await api(create?'/api/rooms':'/api/rooms/join',{method:'POST',body:JSON.stringify(create?
        {campaign_id:campaign!.cid,branch_id:campaign!.bid,name:name.trim(),mode}:
        {code:code.trim(),name:name.trim(),role:role.trim(),create_character:createCharacter})});
      onOpen(room.id);onClose();
    } catch(e) {setError(String(e));} finally {setBusy(false);}
  }
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-label={uiText("RoomPanel.089")}><LocaleSwitcher/>
    <button className="modal-close icon-button" aria-label={uiText("RoomPanel.088")} onClick={onClose}><X size={18}/></button>
    <h2><Users size={20}/>{uiText("RoomPanel.001")}</h2><p>{uiText("RoomPanel.002")}</p>
    <label className="studio-field">{uiText("RoomPanel.003")}<input aria-label={uiText("RoomPanel.087")} value={name} maxLength={32} onChange={e=>setName(e.target.value)}/></label>
    {campaign&&<><label className="studio-field">{uiText("RoomPanel.004")}<select aria-label={uiText("RoomPanel.004")} value={mode} onChange={e=>setMode(e.target.value)}>
      <option value="shared_character">{uiText("RoomPanel.005")}</option><option value="independent_characters">{uiText("RoomPanel.006")}</option>
    </select></label><p className="tiny-muted">{uiText("RoomPanel.007")}</p>
    <button className="primary" disabled={busy||!name.trim()} onClick={()=>void submit(true)}>{uiText("RoomPanel.008")}</button></>}
    <label className="studio-field">{uiText("RoomPanel.009")}<input aria-label={uiText("RoomPanel.009")} value={code} maxLength={160} onChange={e=>setCode(e.target.value)}/></label>
    <label className="studio-field">{uiText("RoomPanel.010")}<input aria-label={uiText("RoomPanel.086")} value={role} maxLength={80} onChange={e=>setRole(e.target.value)}/></label>
    <label className="checkboxes"><input type="checkbox" checked={createCharacter} onChange={e=>setCreateCharacter(e.target.checked)}/>{uiText("RoomPanel.011")}</label>
    <p className="tiny-muted">{uiText("RoomPanel.012")}</p>
    <button className="secondary" disabled={busy||!name.trim()||!code.trim()||!role.trim()} onClick={()=>void submit()}>{uiText("RoomPanel.013")}</button>
    {error&&<p className="notice error" role="alert">{error}</p>}
  </section></div>;
}

export function RoomPanel({api,id,onClose}:{api:Api;id:string;onClose:()=>void}) {
  useLocale();
  const [room,setRoom]=useState<Room|null>(null); const [error,setError]=useState('');
  const [connectionError,setConnectionError]=useState('');
  const [draft,setDraft]=useState(''); const [busy,setBusy]=useState(false);
  const [mode,setMode]=useState('act'); const [whisper,setWhisper]=useState('');
  const [assignment,setAssignment]=useState<Record<string,string>>({});
  const [showTools,setShowTools]=useState(false);
  const mounted=useRef(true);
  function update(value:Room) {if(mounted.current)setRoom(old=>old&&old.id===value.id&&
    (old.revision>value.revision||old.world_version>value.world_version)?old:value);}
  async function refresh() {const value=await api('/api/rooms/'+id);update(value);return value as Room;}
  useEffect(()=>{
    mounted.current=true;
    const poll=()=>void refresh().then(()=>{if(mounted.current)setConnectionError('');})
      .catch(e=>{if(mounted.current)setConnectionError(String(e));});
    poll();const timer=setInterval(poll,1500);
    return()=>{mounted.current=false;clearInterval(timer);};
  },[id]);
  const state=room?.state;
  const actor=state?.player_actor_id;
  const targets=state?.present_actors.filter((a:any)=>a.id!==actor)||[];
  const targetKey=targets.map((a:any)=>a.id).join(',');
  useEffect(()=>{setDraft('');setWhisper('');setAssignment({});},[actor,id]);
  useEffect(()=>{if(whisper&&!targets.some((a:any)=>a.id===whisper))setWhisper('');},[targetKey]);
  async function control(operation:string,member_id?:string,actor_id?:string) {
    if(!room)return;setBusy(true);setError('');
    try {const latest=await refresh();update(await api(`/api/rooms/${id}/control`,{method:'POST',body:JSON.stringify({expected_revision:latest.revision,operation,member_id,actor_id})}));}
    catch(e) {setError(String(e));await refresh().catch(()=>{});} finally {setBusy(false);}
  }
  async function monitor(action:any) {
    await refresh();
    while(active(action.status)&&mounted.current) {
      await new Promise(r=>setTimeout(r,750));
      action=await api(`/api/rooms/${id}/actions/${action.id}`);
    }
    if(mounted.current) {
      if(action.error)setError(action.error);
      await refresh();
    }
    return action.status==='committed';
  }
  async function send(text=draft,sendMode=mode,operation?:RuleAction,note?:NoteRecord,trade?:TradeCommand) {
    if(!room?.state)return false;setBusy(true);setError('');
    try {
      const latest=await refresh();
      if(latest.state?.player_actor_id!==room.state.player_actor_id)throw new Error(uiText("RoomPanel.085"));
      const command={action_id:'room_'+crypto.randomUUID().replaceAll('-',''),expected_world_version:room.state.world_version,
        text,mode:sendMode,...(sendMode==='say'&&whisper?{whisper_to:whisper}:{}),
        ...(operation?{selected_operation:operation}:{}),...(note?{note_record:note}:{}),...(trade?{trade}:{})};
      const action=await api(`/api/rooms/${id}/actions`,{method:'POST',body:JSON.stringify({expected_revision:latest.revision,command})});
      if(text===draft)setDraft('');return await monitor(action);
    } catch(e) {if(mounted.current)setError(String(e));return false;} finally {if(mounted.current)setBusy(false);}
  }
  async function actionControl(aid:string,operation:string) {
    setError('');
    try {const action=await api(`/api/rooms/${id}/actions/${aid}/${operation}`,{method:'POST'});if(operation==='retry')setBusy(true);await monitor(action);}
    catch(e) {setError(String(e));} finally {if(operation==='retry')setBusy(false);}
  }
  if(!room)return <main className="room-shell"><p role={error||connectionError?'alert':'status'}>{error||connectionError||uiText("RoomPanel.084")}</p><button onClick={onClose}>{uiText("RoomPanel.014")}</button></main>;
  const independent=room.mode==='independent_characters';
  const mine=room.turn===room.me&&!room.closed&&!!state;
  const pending=room.pending.length>0; const disabled=!mine||pending||busy;
  const current=room.members.find(m=>m.id===room.turn);
  return <main className="room-shell">
    <div className="section-heading"><h2><Users size={22}/> {room.title}</h2><button className="quiet-button" onClick={onClose}><ArrowLeft size={15}/>{uiText("RoomPanel.014")}</button></div>
    <p>{uiText("RoomPanel.015", {p0: (independent?uiText("RoomPanel.083"):uiText("RoomPanel.082")), p1: (room.closed?uiText("RoomPanel.081"):uiText("RoomPanel.080", {p0: (current?.name||uiText("RoomPanel.079"))})), p2: (room.world_version)})}</p>
    <button className="secondary room-tools-toggle" aria-expanded={showTools} onClick={()=>setShowTools(!showTools)}>{showTools?uiText("RoomPanel.078"):uiText("RoomPanel.077")}</button>
    {(error||connectionError)&&<p className="notice error" role="alert">{error||connectionError}</p>}
    <div className="room-layout"><aside className={'room-seats '+(showTools?'mobile-open':'')}><h3>{uiText("RoomPanel.016")}</h3>
      {room.members.map(m=>{
        const available=room.characters.filter(a=>a.id!==room.members.find(s=>s.id===room.me)?.actor_id&&
          !room.members.some(s=>s.id!==m.id&&s.actor_id===a.id));
        const selected=assignment[m.id]||available.find(a=>a.id===m.actor_id)?.id||available[0]?.id||'';
        return <div className="room-member" key={m.id}>
          <span>{m.name}{m.id===room.me?uiText("RoomPanel.076"):''}{m.id===room.turn?uiText("RoomPanel.075"):''}</span>
          {independent&&<small>{room.characters.find(a=>a.id===m.actor_id)?.name||uiText("RoomPanel.074")}</small>}
          {mine&&m.id!==room.me&&<button disabled={busy||pending||(independent&&!m.actor_id)} onClick={()=>void control('pass',m.id)}>{uiText("RoomPanel.017", {p0: (m.name)})}</button>}
          {room.host&&m.id!==room.me&&<>
            <button disabled={busy||pending||room.closed} onClick={()=>void control('kick',m.id)}>{uiText("RoomPanel.018", {p0: (m.name)})}</button>
            {independent&&!!available.length&&<details><summary>{uiText("RoomPanel.019")}</summary>
              <label className="studio-field">{uiText("RoomPanel.020", {p0: (m.name)})}<select aria-label={uiText("RoomPanel.073", {p0: (m.name)})} value={selected} onChange={e=>setAssignment({...assignment,[m.id]:e.target.value})}>{available.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
              <button disabled={busy||pending||room.closed||!selected||selected===m.actor_id} onClick={()=>void control('assign',m.id,selected)}>{uiText("RoomPanel.021", {p0: (m.name)})}</button>
            </details>}
          </>}
        </div>;
      })}
      {room.host&&!room.closed&&<>
        <label className="studio-field">{uiText("RoomPanel.009")}<input aria-label={uiText("RoomPanel.072")} readOnly value={room.invite_code||''} onFocus={e=>e.target.select()}/></label>
        <button className="text-button" disabled={busy} onClick={()=>void control('rotate')}>{uiText("RoomPanel.022")}</button>
        <button className="text-button" disabled={busy||pending} onClick={()=>void control('reclaim')}>{uiText("RoomPanel.023")}</button>
        <button className="text-button" disabled={busy||pending} onClick={()=>void control('close')}>{uiText("RoomPanel.024")}</button>
      </>}
      {state&&<div key={actor} className="room-personal" data-player={actor}>
        <h3>{independent?uiText("RoomPanel.071"):uiText("RoomPanel.070")}「{state.player_name}」</h3><p>{state.player_role}</p>
        <h3>{state.location.name}</h3><p>{state.location.description}</p>
        {state.exits.map((p:any)=><button className="opportunity-button" key={p.id} disabled={disabled} onClick={()=>void send(uiText("RoomPanel.069", {p0: (p.name)}),'act',{kind:'move',target_id:p.id})}>{p.name}</button>)}
        <p>{uiText("RoomPanel.025")}{targets.map((a:any)=>a.name+(a.control==='player'?uiText("RoomPanel.068"):'')).join('、')||uiText("RoomPanel.067")}</p>
        <StatePanel value={state.custom_state} busy={disabled} onAction={(text,target_id)=>void send(text,'act',{kind:'state_action',target_id})}/>
        <details className="room-character-details"><summary>{uiText("RoomPanel.026")}</summary>
          <GamePanel view={state} busy={disabled} onAction={(text,op)=>void send(text,'act',op)}/>
          {!state.rule_system&&<p>{Object.entries(state.resources).map(([key,v])=>`${({vitality:uiText("RoomPanel.066"),coins:uiText("RoomPanel.065")} as Record<string,string>)[key]||key} ${v}`).join(' · ')}</p>}
          <h4>{uiText("RoomPanel.027")}</h4><ul>{state.inventory.map((i:any)=><li key={i.id}>{i.name} ×{i.quantity}</li>)}</ul>{!state.inventory.length&&<p>{uiText("RoomPanel.028")}</p>}
          <h4>{uiText("RoomPanel.029")}</h4>{state.known_facts.map((f:any)=> <p key={f.id}>{f.text}</p>)}
          <h4>{uiText("RoomPanel.030")}</h4>{state.quests.map((q:any)=><p key={q.id}>{q.name} · {q.status==='completed'?uiText("RoomPanel.064"):uiText("RoomPanel.063")}</p>)}
          {state.opportunities.map((o:any)=><button className="opportunity-button" key={o.id} disabled={disabled||!o.ready} onClick={()=>void send(uiText("RoomPanel.062", {p0: (o.name)}),'act',{kind:'challenge',target_id:o.id})}>{o.name}</button>)}
        </details>
        <MemoryPanel key={actor} api={api} campaign={id} branch={actor} memoryPath={`/api/rooms/${id}/memories`} version={state.world_version} notes={state.notes||[]} busy={disabled} onRecord={note=>void send(note.text,'ooc',undefined,note)}/>
        <a className="text-button" href={`/api/rooms/${id}/export`} download><Download size={14}/>{uiText("RoomPanel.031")}</a>
      </div>}
      <p className="tiny-muted">{uiText("RoomPanel.032", {p0: (independent?uiText("RoomPanel.061"):uiText("RoomPanel.060"))})}</p>
    </aside><section className="room-story">
      {!state?<p className="notice" role="status">{uiText("RoomPanel.033")}</p>:<>
        <NPCStage api={api} base={`/api/rooms/${id}/avatars`} actors={state.present_actors} history={state.history} busy={pending}/>
        {independent&&<TradePanel key={actor} view={state} busy={disabled} onTrade={trade=>send(uiText("RoomPanel.059"),'act',undefined,undefined,trade)}/>}
        <article className="opening narrative"><p>{state.opening}</p></article>
        {state.history.map((c:any)=><article className="turn" data-version={c.version} key={c.id}>
          <div className="turn-divider">{uiText("RoomPanel.034", {p0: (c.version), p1: (independent&&c.actor_name?' · '+c.actor_name:'')})}</div>
          {c.player_text&&<p className="room-player-text">{c.private?uiText("RoomPanel.058"):''}{c.actor_name||state.player_name}：{c.player_text}</p>}
          {c.segments.map((s:any,i:number)=><div key={i} className={s.kind==='dialogue'?'dialogue':'narrative'}><p>{s.private?uiText("RoomPanel.058"):''}{s.speaker_name&&<strong>{s.speaker_name}：</strong>}{s.text}</p></div>)}
          {!!c.effects?.length&&<ul className="room-effects">{c.effects.map((effect:string,i:number)=><li key={i}>{effect}</li>)}</ul>}
        </article>)}
        {pending&&<div role="status" className="notice">{uiText("RoomPanel.035")}{room.pending.filter(a=>a.can_cancel).map(a=><button key={a.id} onClick={()=>void actionControl(a.id,'cancel')}>{uiText("RoomPanel.036")}</button>)}</div>}
        {room.recoverable?.map(a=><div className="notice" key={a.id}>{a.error||uiText("RoomPanel.057")}
          {a.can_retry?<button disabled={busy} onClick={()=>void actionControl(a.id,'retry')}>{uiText("RoomPanel.037")}</button>:<span>{uiText("RoomPanel.038")}</span>}
        </div>)}
        <form className="room-composer" onSubmit={e=>{e.preventDefault();void send();}}>
          <div className="room-mode-row"><label className="studio-field">{uiText("RoomPanel.039")}<select aria-label={uiText("RoomPanel.056")} value={mode} disabled={disabled} onChange={e=>setMode(e.target.value)}>
            <option value="act">{uiText("RoomPanel.040")}</option><option value="say">{uiText("RoomPanel.041")}</option><option value="wait">{uiText("RoomPanel.042")}</option><option value="ooc">{uiText("RoomPanel.043")}</option>
          </select></label>{mode==='say'&&<label className="studio-field">{uiText("RoomPanel.044")}<select aria-label={uiText("RoomPanel.044")} value={whisper} disabled={disabled} onChange={e=>setWhisper(e.target.value)}>
            <option value="">{uiText("RoomPanel.045")}</option>{targets.map((a:any)=><option key={a.id} value={a.id}>{uiText("RoomPanel.046", {p0: (a.name)})}</option>)}
          </select></label>}</div>
          {mode==='say'&&whisper&&<p className="tiny-muted"><LockKeyhole size={13}/>{uiText("RoomPanel.047")}</p>}
          <label className="studio-field">{independent?uiText("RoomPanel.055"):uiText("RoomPanel.054")}<textarea aria-label={uiText("RoomPanel.053")} disabled={disabled} maxLength={1800} value={draft} onChange={e=>setDraft(e.target.value)} placeholder={mine?uiText("RoomPanel.052"):uiText("RoomPanel.051")}/></label>
          <button className="primary" type="submit" disabled={disabled||!draft.trim()}>{independent?uiText("RoomPanel.050"):uiText("RoomPanel.049")}</button>
          {mine&&independent&&<p className="tiny-muted">{uiText("RoomPanel.048")}</p>}
        </form>
      </>}
    </section></div>
  </main>;
}
