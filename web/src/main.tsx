import { getLocale, uiText, useLocale } from './i18n';
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, ArrowRight, Backpack, BookOpen, Check, ChevronDown, Compass, Download,
  Feather, Flag, GitBranch, MapPin, Menu, MessageCircle, Send, Sparkles, Square, Waves, X,
  Clock3, RotateCcw, Anchor, Footprints, Dices, NotebookPen, Plus, Settings2, Users } from 'lucide-react';
import './style.css';
import { LocaleSwitcher } from './LocaleSwitcher';
import { Studio } from './Studio';
import { StatePanel, CustomState } from './StateEditor';
import { GamePanel, GameView, RuleAction } from './GamePanel';
import { MemoryPanel, NoteRecord } from './MemoryPanel';
import { WorldPanel, WorldMap, WorldSimulation } from './WorldPanel';
import { BackupLink } from './BackupStudio';
import { RoomEntry, RoomPanel } from './RoomPanel';
import { ProviderPanel } from './ProviderPanel';
import { NPCStage } from './NPCStage';

type Actor = { avatar_id?:string; id: string; name: string; control: string; description: string; initial: string };
type Segment = { emotion?:string;gesture?:string; kind: string; text: string; speaker_id?: string; speaker_name?: string };
type Roll = { dice?:string; comparison?:string; roll: number; modifier: number; total: number; difficulty: number; purpose: string; passed: boolean };
type Commit = { id: string; action_id: string; version: number; segments: Segment[]; effects: string[];
  suggestions: string[]; player_text: string; mode: string; game_time_s: number; roll?: Roll };
type Action = { id: string; status: string; error?: string; result?: Commit };
type View = Omit<GameView, 'present_actors'> & {custom_state?:CustomState; notes:NoteRecord[]; map:WorldMap; simulation?:WorldSimulation; campaign_id: string; branch_id: string; branch_title: string; fork_version: number; world_version: number;
  content_language?:string;creation_preset?:string;title: string; world_title: string; player_role: string; player_name: string; player_actor_id: string; game_time_s: number; opening: string;
  opening_suggestions: string[]; location: { id: string; name: string; description: string };
  exits: { id: string; name: string; travel_time_s: number }[]; present_actors: Actor[];
  inventory: { id: string; name: string; quantity: number }[]; resources: Record<string, number>;
  known_facts: { id: string; text: string }[]; visible_clocks: { id: string; name: string; value: number; threshold: number }[];
  opportunities?: { id: string; name: string; description: string; ready: boolean }[];
  quests: { id: string; name: string; status: string; description?: string }[]; history: Commit[]; active_actions: Action[] };
type Campaign = { id: string; title: string; world_title: string; player_role: string; player_name: string; main_branch: string; created_at: number; world_ref?:{id:string;revision:number};world_version?:number };
type Branch = { id: string; title: string; version: number; parent_id: string | null; fork_version: number };
type World = { id: string; title: string; premise: string; opening: string; locations: number; characters: number };
const active = (a: Action | null) => !!a && ['accepted', 'planning', 'characters', 'narrating'].includes(a.status);
const phases: Record<string, string> = { get accepted() { return uiText("main.072"); }, get planning() { return uiText("main.071"); }, get characters() { return uiText("main.070"); }, get narrating() { return uiText("main.069"); } };
const timeLabel = (seconds: number) => {
  const minutes = 17 * 60 + Math.floor(seconds / 60);
  return `${String(Math.floor(minutes / 60) % 24).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
};

function Harbor({ compact = false }: { compact?: boolean }) {
  useLocale();
  return <svg className={`harbor-art ${compact ? 'compact' : ''}`} viewBox="0 0 1000 520" preserveAspectRatio="xMidYMid slice" role="img" aria-label={uiText("main.068")}>
    <defs>
      <linearGradient id="sky" x2="0" y2="1"><stop stopColor="#28424a"/><stop offset=".65" stopColor="#82918a"/><stop offset="1" stopColor="#c7b595"/></linearGradient>
      <linearGradient id="sea" x2="0" y2="1"><stop stopColor="#657c7b"/><stop offset="1" stopColor="#172e35"/></linearGradient>
      <linearGradient id="fog" x2="1" y2="0"><stop stopColor="#d1d9cc" stopOpacity="0"/><stop offset=".5" stopColor="#d1d9cc" stopOpacity=".18"/><stop offset="1" stopColor="#d1d9cc" stopOpacity="0"/></linearGradient>
      <radialGradient id="glow"><stop stopColor="#f4dc9a" stopOpacity=".4"/><stop offset="1" stopColor="#ead899" stopOpacity="0"/></radialGradient>
    </defs>
    <path fill="url(#sky)" d="M0 0h1000v520H0z"/><circle cx="667" cy="153" r="48" fill="#ddcfab" opacity=".72"/>
    <path d="M0 256l95-26 75 14 105-50 66 25 80-23 97 72 79-26 47 24 120-80 62 6 75 67 99-29v290H0z" fill="#466366" opacity=".45"/>
    <path d="M0 306l117-39 135 38 71-20 146 41 177-47 189 48 165-28v221H0z" fill="#3d5b60" opacity=".6"/>
    <path fill="url(#sea)" d="M0 324h1000v196H0z"/>
    <g fill="#1f383e"><path d="M797 326l22-144h24l21 144z"/><path d="M816 182h31v-23h-31z"/><path d="M809 160l22-22 22 22z"/><path d="M783 327l42-19 56 6 62 35H754z"/></g>
    <path d="M820 163h21v15h-21z" fill="#f3d594"/><circle cx="831" cy="171" r="118" fill="url(#glow)"/>
    <path d="M839 171l161-39v68z" fill="#e8d8a9" opacity=".07"/>
    <g stroke="#acb7a9" strokeWidth="1" opacity=".24"><path d="M100 357h247m139 7h134m74-22h111M29 410h151m460 9h246M230 456h177m314 26h144M493 383h100"/></g>
    <g fill="#14292f"><path d="M0 419l204-15 196 24-21 17-198-17L0 444z"/><path d="M66 430h11v90H66zm127-8h12v98h-12zm119 15h12v83h-12z"/><path d="M393 374q56 31 157 4l-26 30h-101z"/><path d="M463 226h5v156h-5z"/></g>
    <path d="M461 237l-54 126h54z" fill="#c7bfa7" opacity=".67"/><path d="M473 267l54 92-54 9z" fill="#b0b4a6" opacity=".5"/>
    <path d="M0 291h1000v39H0zm120 68h880v31H120z" fill="url(#fog)"/>
    <g fill="none" stroke="#263f45" strokeWidth="2"><path d="M503 123q9-6 18 0 9-6 18 0m-159 54q6-4 12 0 6-4 12 0"/></g>
  </svg>;
}

function App() {
  useLocale();
  const [settingsOpen,setSettingsOpen]=useState(false);
  const [roomEntry,setRoomEntry]=useState(false);const [roomId,setRoomId]=useState(()=>new URLSearchParams(location.search).has('package')?'':localStorage.getItem('rpw-room')||'');
  function openRoom(id:string){setRoomId(id);localStorage.setItem('rpw-room',id);}
  function closeRoom(){setRoomId('');localStorage.removeItem('rpw-room');if(current.current)void openCampaign(current.current.campaign_id,current.current.branch_id);}
  const [csrf, setCsrf] = useState('');
  const [world, setWorld] = useState<World | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [view, setView] = useState<View | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [name, setName] = useState(uiText("Studio.159"));
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState('act');
  const [action, setAction] = useState<Action | null>(null);
  const [pendingText, setPendingText] = useState('');
  const [error, setError] = useState('');
  const [ready, setReady] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [panel, setPanel] = useState<'world' | 'player' | null>(null);
  const [forkAt, setForkAt] = useState<number | null>(null);
  const [forkName, setForkName] = useState(uiText("main.065"));
  const stream = useRef<EventSource | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const current = useRef<View | null>(null);
  const busy = active(action) || creating;

  async function api(path: string, options: RequestInit = {}, token = csrf) {
    const r = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token, ...options.headers } });
    const data = await r.json();
    if (!r.ok) {
      const detail = data.message || data.detail?.[0]?.msg || uiText("main.067");
      // Keep provider/content diagnostics verbatim; never machine-translate user data.
      throw new Error(data.message === '会话已过期，请刷新页面' ? uiText('request.expired') : getLocale() !== 'zh-CN'
        ? uiText('request.failed', {p0: data.error || r.status, p1: detail}) : detail);
    }
    return data;
  }
  function scroll() { setTimeout(() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 70); }
  async function openCampaign(cid: string, bid: string) {
    stream.current?.close(); stream.current = null; setError(''); setAction(null); setPendingText(''); setPanel(null);
    const [v, bs] = await Promise.all([api(`/api/campaigns/${cid}/branches/${bid}/view`), api(`/api/campaigns/${cid}/branches`)]);
    current.current = v; setView(v); setBranches(bs);
    localStorage.setItem('rpw-active', JSON.stringify({ cid, bid }));
    if(new URLSearchParams(location.search).has('package')){const url=new URL(location.href);url.searchParams.delete('package');history.replaceState(null,'',url);}
    const a = v.active_actions.at(-1);
    if (a) { setAction(a); if (a.error) setError(a.error); if (active(a)) watch(a.id, cid, bid); }
  }
  function watch(aid: string, cid: string, bid: string) {
    stream.current?.close();
    const es = new EventSource(`/api/actions/${aid}/events`); stream.current = es;
    es.addEventListener('state', async (event) => {
      const a = JSON.parse((event as MessageEvent).data) as Action;
      if (stream.current !== es || current.current?.branch_id !== bid) { es.close(); return; }
      setAction(a);
      if (!active(a)) {
        es.close();
        if (a.status === 'committed') {
          try { await openCampaign(cid, bid); setPendingText(''); scroll(); } catch (e) { setError(String(e)); }
        } else if (a.error) setError(a.error);
      }
    });
    es.onerror = () => { if (es.readyState === EventSource.CLOSED) setError(uiText("main.066")); };
  }
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const session = await api('/api/session', { method: 'POST' }, '');
        if (!mounted) return; setCsrf(session.csrf_token);
        const [ws, cs, status] = await Promise.all([api('/api/worlds'), api('/api/campaigns'), api('/api/status')]);
        if (!mounted) return; setWorld(ws[0]); setCampaigns(cs); setReady(status.ready);
        const saved = localStorage.getItem('rpw-active');
        if (saved && !new URLSearchParams(location.search).has('package')) {
          const { cid, bid } = JSON.parse(saved);
          if (cs.some((c: Campaign) => c.id === cid)) await openCampaign(cid, bid);
          else localStorage.removeItem('rpw-active');
        }
      } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
      finally { if (mounted) setLoading(false); }
    })();
    return () => { mounted = false; stream.current?.close(); };
  }, []);

  async function create() {
    setCreating(true); setError('');
    try {
      const c = await api('/api/campaigns', { method: 'POST', body: JSON.stringify({ template_id: world?.id, player_name: name || uiText("Studio.159") }) });
      setCampaigns(await api('/api/campaigns')); await openCampaign(c.id, c.branch_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setCreating(false); }
  }
  async function send(text = draft, explicitMode = mode, selectedOperation?:RuleAction, noteRecord?:NoteRecord, simulationControl?:'pause'|'resume') {
    if (!view || !text.trim() || busy) return;
    setError(''); setAction(null); setCreating(true); setPendingText(text.trim());
    try {
      const a = await api(`/api/campaigns/${view.campaign_id}/branches/${view.branch_id}/actions`, { method: 'POST', body: JSON.stringify({ action_id: 'action_' + crypto.randomUUID().replaceAll('-', ''), expected_world_version: view.world_version, text: text.trim(), mode: explicitMode, ...(selectedOperation?{selected_operation:selectedOperation}:{}), ...(noteRecord?{note_record:noteRecord}:{}), ...(simulationControl?{simulation_control:simulationControl}:{}) }) });
      setDraft(''); setAction(a); watch(a.id, view.campaign_id, view.branch_id); scroll();
    } catch (e) { setPendingText(''); setError(e instanceof Error ? e.message : String(e)); }
    finally { setCreating(false); }
  }
  async function cancel() {
    if (!action) return;
    try { const cancelled = await api(`/api/actions/${action.id}/cancel`, { method: 'POST' }); stream.current?.close(); stream.current = null; setAction(cancelled); setPendingText(''); }
    catch (e) { if (view) await openCampaign(view.campaign_id, view.branch_id); setError(e instanceof Error ? e.message : String(e)); }
  }
  async function retry() {
    if (!action || !view) return;
    try { setError(''); const a = await api(`/api/actions/${action.id}/retry`, { method: 'POST' }); setAction(a); watch(a.id, view.campaign_id, view.branch_id); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function fork() {
    if (!view || forkAt === null) return;
    setCreating(true);
    try {
      const b = await api(`/api/campaigns/${view.campaign_id}/branches`, { method: 'POST', body: JSON.stringify({ source_branch_id: view.branch_id, world_version: forkAt, title: forkName || uiText("main.065") }) });
      setForkAt(null); await openCampaign(view.campaign_id, b.id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setCreating(false); }
  }
  function library() { setRoomId('');localStorage.removeItem('rpw-room');void api('/api/campaigns').then(setCampaigns).catch(e=>setError(String(e))); stream.current?.close(); current.current = null; setView(null); setAction(null); localStorage.removeItem('rpw-active'); setError(''); }

  return <div className="app-shell">
    <header className="topbar"><LocaleSwitcher/>
      <button className="brand" onClick={library} aria-label={uiText("main.064")}><Compass size={27}/><span>{uiText("main.001")}<small>{uiText("brand.subtitle")}</small></span></button>
      <div className="top-title">{view ? <><span className="muted">{uiText("main.002")}</span><span className="slash">/</span>{view.title}</> : uiText("main.063")}</div>
      <div className={`connection ${ready ? 'online' : ''}`}><i/>{ready === null ? uiText("main.062") : ready ? uiText("main.061") : uiText("main.060")}</div>
      <button className="icon-button" aria-label={uiText("RoomPanel.089")} disabled={!csrf} onClick={()=>setRoomEntry(true)}><Users size={19}/></button>
      <button className="icon-button" aria-label={uiText("ProviderPanel.032")} disabled={!csrf} onClick={()=>setSettingsOpen(true)}><Settings2 size={19}/></button>
      {view && <button className="icon-button mobile-only" onClick={() => setPanel(panel ? null : 'world')} aria-label={uiText("main.059")}><Menu size={20}/></button>}
    </header>

    {roomEntry&&<RoomEntry api={api} campaign={view?{cid:view.campaign_id,bid:view.branch_id}:undefined} onOpen={openRoom} onClose={()=>setRoomEntry(false)}/>}
    {settingsOpen&&<ProviderPanel api={api} onClose={()=>setSettingsOpen(false)} onChanged={()=>void api("/api/status").then(s=>setReady(s.ready))}/>}
    {!view && error && <div className="notice error" role="alert">{error}</div>}
    {roomId&&!loading?<RoomPanel api={api} id={roomId} onClose={closeRoom}/>:loading ? <div className="loading-screen"><Compass className="spin-slow" size={40}/><p>{uiText("main.003")}</p></div> : !view ?
    <Studio api={api} ready={ready} campaigns={campaigns} onOpen={(cid,bid) => { void openCampaign(cid,bid).catch(e=>setError(String(e))); }} onDemo={create} onStart={async (sid,playerName,source)=>{
      const c = await api('/api/campaigns', {method:'POST', body:JSON.stringify({story_id:sid,player_name:playerName||uiText("Studio.159"),...(source?{source_campaign_id:source.id,source_branch_id:source.main_branch,source_world_version:source.world_version}:{})})});
      setCampaigns(await api('/api/campaigns')); await openCampaign(c.id,c.branch_id);
    }}/> : <main className="adventure">
      {panel && <button className="panel-backdrop" onClick={() => setPanel(null)} aria-label={uiText("main.058")}/>}
      <aside className={`sidebar world-sidebar ${panel === 'world' ? 'opened' : ''}`}>
        <div className="sidebar-heading"><span className="eyebrow">{uiText("brand.world")}</span><button className="icon-button mobile-only" onClick={() => setPanel(null)} aria-label={uiText("main.057")}><X size={18}/></button></div>
        <div className="mini-scene">{view.world_title.includes("雾港") ? <Harbor compact/> : <div className="generic-scene"><Compass size={58} strokeWidth={1}/><span>{view.world_title}</span></div>}<span><MapPin size={13}/>{view.location.name}</span></div>
        <div className="location-heading"><h2>{view.location.name}</h2><span><Clock3 size={13}/>{timeLabel(view.game_time_s)}</span></div><p className="location-description">{view.location.description}</p>
        {view.exits.length>0&&<section className="sidebar-section"><h3><Footprints size={15}/>{uiText("main.004")}</h3><div className="route-list">{view.exits.map(x => <button key={x.id} disabled={busy || !ready} onClick={() => { void send(uiText("RoomPanel.069", {p0: (x.name)}), 'act'); setPanel(null); }}><MapPin size={14}/><span>{x.name}<small>{uiText("main.005", {p0: (Math.ceil(x.travel_time_s / 60))})}</small></span><ArrowRight size={15}/></button>)}</div></section>}
        {view.visible_clocks.length>0&&<section className="sidebar-section"><h3><Waves size={15}/>{uiText("main.006")}</h3>{view.visible_clocks.map(c => <div className="clock-meter" key={c.id}><div><span>{c.name}</span><small>{c.value} / {c.threshold}</small></div><div className={`clock-segments ${c.value === c.threshold ? 'full' : ''}`}>{Array.from({ length: c.threshold }, (_, i) => <i key={i} className={i < c.value ? 'filled' : ''}/>)}</div></div>)}<p className="tiny-muted">{uiText("main.007")}</p></section>}
        {view.quests.length>0&&<section className="sidebar-section"><h3><Flag size={15}/>{uiText("main.008")}</h3>{view.quests.map(q => <div className={`quest ${q.status === 'completed' ? 'complete' : ''}`} key={q.id}>{q.status === 'completed' ? <Check size={15}/> : <span className="quest-dot"/>}<span>{q.name}<small>{q.status === 'completed' ? uiText("main.056") : q.description || uiText("main.055")}</small></span></div>)}</section>}
        {!!view.opportunities?.length && <section className="sidebar-section"><h3><Sparkles size={15}/>{uiText("main.009")}</h3>{view.opportunities.map(o=><button key={o.id} className="opportunity-button" disabled={busy||!ready||!o.ready} onClick={()=>void send(uiText("main.054", {p0: (o.name), p1: (o.description)}),'act')}><strong>{o.name}</strong><small>{o.ready?uiText("main.053"):uiText("main.052")}</small></button>)}</section>}
        <WorldPanel map={view.map||[]} location={view.location.id} simulation={view.simulation} busy={busy} onMove={(text,op)=>void send(text,'act',op)} onControl={control=>void send(control==='pause'?uiText("WorldPanel.005"):uiText("WorldPanel.006"),'ooc',undefined,undefined,control)}/><button className="quiet-button back-library" onClick={library}><ArrowLeft size={15}/>{uiText("main.010")}</button>
      </aside>

      <section className="story-column">
        <div className="story-toolbar"><div><Feather size={17}/><span>{uiText("main.002")}</span><span className="turn-count">{uiText("main.011", {p0: (view.history.length)})}</span></div><div className="toolbar-actions"><div className="branch-select"><GitBranch size={15}/><select aria-label={uiText("main.051")} value={view.branch_id} disabled={busy} onChange={e => openCampaign(view.campaign_id, e.target.value).catch(e => setError(String(e)))}>{branches.map(b => <option key={b.id} value={b.id}>{b.title} · {b.version}</option>)}</select><ChevronDown size={12}/></div><a className="icon-button" href={`/api/campaigns/${view.campaign_id}/branches/${view.branch_id}/export`} title={uiText("main.050")} aria-label={uiText("main.050")}><Download size={17}/></a><BackupLink cid={view.campaign_id}/></div></div>
        <NPCStage api={api} actors={view.present_actors} history={view.history} busy={busy}/><div className="story-scroll" aria-live="polite">
          <div className="chapter-heading"><span className="eyebrow">{uiText("brand.chapter")}</span><h2>{view.title}</h2><div><span/>{view.world_title}<span/></div></div>
          <article className="opening narrative"><span className="narrator-label"><Feather size={13}/>{uiText("main.012")}</span><p>{view.opening}</p>{view.fork_version === 0 && <button className="fork-link" onClick={() => setForkAt(0)} disabled={busy}><GitBranch size={13}/>{uiText("main.013")}</button>}</article>
          {view.history.map(c => <article key={c.id} className="turn" data-version={c.version}>
            <div className="turn-divider"><span>{uiText("turn.label", {p0: (c.version)})}</span><i/><time>{timeLabel(c.game_time_s)}</time><button aria-label={uiText("main.049", {p0: (c.version)})} disabled={busy || c.version < view.fork_version} onClick={() => setForkAt(c.version)} title={uiText("main.048")}><GitBranch size={14}/></button></div>
            <div className="player-action"><span className="player-monogram">{view.player_name[0]}</span><div><span>{view.player_name}<small>{c.mode === 'say' ? uiText("RoomPanel.041") : c.mode === 'ooc' ? uiText("main.045") : uiText("RoomPanel.040")}</small></span><p>{c.player_text}</p></div></div>
            {c.roll && <div className={`roll-result ${c.roll.passed ? 'passed' : 'missed'}`}><Dices size={23}/><div><span>{c.roll.purpose}</span><small>{c.roll.dice||'d20'} {c.roll.roll} + {c.roll.modifier} = <b>{c.roll.total}</b>{uiText("main.014", {p0: (c.roll.comparison||'>='), p1: (c.roll.difficulty)})}</small></div><strong>{c.roll.passed ? uiText("main.047") : uiText("main.046")}</strong></div>}
            {c.segments.map((s, i) => s.kind === 'dialogue' ? <div className="dialogue" key={i}><div className={`avatar ${s.speaker_id}`}><span>{s.speaker_name?.[0]}</span></div><div><span className="speaker-name">{s.speaker_name}</span><p>{s.text}</p></div></div> : <div className="narrative" key={i}><p>{s.text}</p></div>)}
            {c.effects.length > 0 && <div className="consequences"><span><Sparkles size={12}/>{uiText("main.015")}</span>{c.effects.map((x, i) => <p key={i}>{x}</p>)}</div>}
          </article>)}
          {pendingText && active(action) && <div className="player-action pending"><span className="player-monogram">{view.player_name[0]}</span><div><span>{view.player_name}</span><p>{pendingText}</p></div></div>}
          {active(action) && <div className="thinking"><span className="thinking-dots"><i/><i/><i/></span>{phases[action!.status]}</div>}
          {action?.status === 'cancelled' && <div className="notice subtle">{uiText("main.016")}</div>}
          {error && <div className="notice error" role="alert">{error}<button onClick={() => setError('')} aria-label={uiText("Studio.158")}><X size={15}/></button></div>}
          {action && ['failed', 'interrupted'].includes(action.status) && <button className="retry-button" onClick={retry}><RotateCcw size={15}/>{uiText("main.017")}</button>}
          <div ref={bottom}/>
        </div>
        <div className="composer-wrap">
          {!busy && <div className="suggestions">{(view.history.at(-1)?.suggestions || view.opening_suggestions).map((s, i) => <button key={i} onClick={() => void send(s, 'act')} disabled={!ready}>{s}<ArrowRight size={12}/></button>)}</div>}
          <form className={`composer ${busy ? 'is-busy' : ''}`} onSubmit={e => { e.preventDefault(); void send(); }}>
            <div className="composer-tabs">{[{ id: 'act', text: uiText("RoomPanel.040"), icon: Footprints }, { id: 'say', text: uiText("RoomPanel.041"), icon: MessageCircle }, { id: 'ooc', text: uiText("main.045"), icon: BookOpen }].map(m => <button key={m.id} type="button" className={mode === m.id ? 'selected' : ''} onClick={() => setMode(m.id)}><m.icon size={13}/>{m.text}</button>)}<span>{uiText("main.018")}</span></div>
            <textarea ref={textarea} aria-label={uiText("main.044")} value={draft} onChange={e => setDraft(e.target.value)} placeholder={busy ? uiText("main.043") : mode === 'say' ? uiText("main.042") : uiText("main.041")} maxLength={1800} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }}/>
            <div className="composer-bottom"><span><Check size={12}/> {busy ? uiText("main.040") : uiText("main.039", {p0: (view.world_version)})}<small>{uiText("main.019")}</small></span>{busy ? <button className="stop-button" type="button" onClick={cancel} disabled={!action}><Square size={13}/>{uiText("main.020")}</button> : <button className="send-button" type="submit" disabled={!draft.trim() || !ready}><span>{uiText("main.021")}</span><Send size={17}/></button>}</div>
          </form>
          <div className="mobile-panel-buttons"><button onClick={() => setPanel('world')}><MapPin size={14}/>{uiText("main.022")}</button><button onClick={() => setPanel('player')}><Backpack size={14}/>{uiText("main.023")}</button></div>
        </div>
      </section>

      <aside className={`sidebar player-sidebar ${panel === 'player' ? 'opened' : ''}`}>
        <div className="sidebar-heading"><span className="eyebrow">{uiText("brand.story")}</span><button className="icon-button mobile-only" onClick={() => setPanel(null)} aria-label={uiText("main.038")}><X size={18}/></button></div>
        <div className="player-profile"><div className="profile-seal"><Compass size={30}/></div><h2>{view.player_name}</h2><span>{view.player_role}</span></div>
        {('vitality' in view.resources||'coins' in view.resources)&&<div className="resources"><div><span>{uiText("RoomPanel.066")}</span><strong>{view.resources.vitality}</strong></div><i/><div><span>{uiText("RoomPanel.065")}</span><strong>{view.resources.coins}</strong></div></div>}
        <StatePanel value={view.custom_state} busy={busy||!ready} onAction={(text,id)=>void send(text,'act',{kind:'state_action',target_id:id})}/><GamePanel view={view} busy={busy||!ready} onAction={(text,op)=>void send(text,'act',op)}/>{(view.creation_preset!=='scene'||view.inventory.length>0)&&<section className="sidebar-section"><h3><Backpack size={15}/>{uiText("main.024")}<span>{view.inventory.length}</span></h3>{view.inventory.length ? view.inventory.map(i => <div className="inventory-item" key={i.id}><div><Anchor size={17}/></div><span>{i.name}</span><small>×{i.quantity}</small></div>) : <div className="empty-inventory"><Backpack size={24}/><p>{uiText("main.025")}</p><small>{uiText("main.026")}</small></div>}</section>}
        <section className="sidebar-section"><h3><MessageCircle size={15}/>{uiText("main.027")}</h3>{view.present_actors.filter(a => a.control !== 'player').map(a => <button className="npc-card" key={a.id} onClick={() => { setDraft(uiText("main.037", {p0: (a.name)})); setMode('say'); setPanel(null); textarea.current?.focus(); }}><div className={`avatar ${a.id}`}><span>{a.initial}</span></div><div><strong>{a.name}</strong><small>{a.description}</small></div></button>)}{view.present_actors.length === 1 && <p className="tiny-muted">{uiText("main.028")}</p>}</section>
        <section className="sidebar-section knowledge"><h3><BookOpen size={15}/>{uiText("main.029")}</h3>{view.known_facts.map(f => <p key={f.id}><span/>{f.text}</p>)}</section>
        <MemoryPanel api={api} campaign={view.campaign_id} branch={view.branch_id} version={view.world_version} notes={view.notes||[]} busy={busy} onRecord={note=>void send(note.text,'ooc',undefined,note)}/><div className="sidebar-note"><Feather size={17}/><p>{uiText("main.030")}<br/>{uiText("main.031")}</p></div>
      </aside>
    </main>}

    {forkAt !== null && <div className="modal-backdrop" onClick={() => setForkAt(null)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="fork-title" onClick={e => e.stopPropagation()}><LocaleSwitcher/><button className="modal-close icon-button" onClick={() => setForkAt(null)} aria-label={uiText("main.036")}><X size={20}/></button><div className="modal-emblem"><GitBranch size={29}/></div><span className="eyebrow">{uiText("brand.branch")}</span><h2 id="fork-title">{uiText("main.032")}</h2><p>{uiText("main.033", {p0: (forkAt)})}</p><label htmlFor="branch-name">{uiText("main.034")}</label><input id="branch-name" value={forkName} onChange={e => setForkName(e.target.value)} maxLength={40}/><button className="primary" onClick={fork} disabled={creating}><Plus size={17}/>{uiText("main.035")}</button></section></div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
