import { uiText, useLocale } from './i18n';
import { useEffect, useState } from 'react';

type Item = {item_id:string;quantity:number;name?:string};
type Bundle = {items:Item[];coins:number};
type Offer = {id:string;sender:string;recipient:string;sender_name:string;recipient_name:string;
  give:Bundle;receive:Bundle;status:string;unavailable:string|null};
export type TradeCommand = {kind:'propose'|'counter'|'accept'|'decline'|'withdraw';target_id?:string;offer_id?:string;
  items?:Item[];coins?:number;request_coins?:number};
const describe=(bundle:Bundle)=>[...bundle.items.map(i=>`${i.name} ×${i.quantity}`),...(bundle.coins?[uiText("TradePanel.035", {p0: (bundle.coins)})]:[])].join('、')||uiText("TradePanel.034");
const labels:Record<string,string>={get pending() { return uiText("TradePanel.033"); },get accepted() { return uiText("TradePanel.032"); },get declined() { return uiText("TradePanel.031"); },get withdrawn() { return uiText("TradePanel.030"); },get countered() { return uiText("TradePanel.029"); }};

export function TradePanel({view,busy,onTrade}:{view:any;busy:boolean;onTrade:(trade:TradeCommand)=>Promise<boolean>}) {
  useLocale();
  const actors=view.present_actors.filter((a:any)=>a.control==='player'&&a.id!==view.player_actor_id);
  const offers:Offer[]=view.trades||[];
  const pending=offers.filter(o=>o.status==='pending');
  const [target,setTarget]=useState(''); const [editing,setEditing]=useState(false);
  const [counter,setCounter]=useState<string|null>(null); const [coins,setCoins]=useState(0);
  const [requested,setRequested]=useState(0); const [quantities,setQuantities]=useState<Record<string,number>>({});
  const [sending,setSending]=useState(false);
  const original=offers.find(o=>o.id===counter);
  const other=original?.sender||target||actors[0]?.id||'';
  const selected=view.inventory.filter((i:any)=>quantities[i.id]>0).map((i:any)=>({item_id:i.id,quantity:quantities[i.id]}));
  const invalid=selected.length>6||selected.some((i:Item)=>i.quantity>view.inventory.find((x:any)=>x.id===i.item_id).quantity)||
    !Number.isInteger(coins)||coins<0||coins>(view.resources.coins||0)||!Number.isInteger(requested)||requested<0||requested>999999||
    selected.some((i:Item)=>!Number.isInteger(i.quantity))||
    (!selected.length&&!coins&&!requested&&!original?.give.items.length&&!original?.give.coins);
  const disabled=busy||sending;
  useEffect(()=>{if(target&&!actors.some((a:any)=>a.id===target))setTarget('');},[view.world_version]);
  function open(offer?:Offer) {
    setCounter(offer?.id||null);setCoins(0);setRequested(0);setQuantities({});setEditing(true);
  }
  async function submit(command:TradeCommand) {
    setSending(true);
    try {if(await onTrade(command)){setEditing(false);setCounter(null);setQuantities({});}}
    finally {setSending(false);}
  }
  return <section className="trade-panel" aria-label={uiText("RoomPanel.059")}>
    <div className="section-heading"><h3>{uiText("TradePanel.001")}{pending.length>0&&<small>{uiText("TradePanel.002", {p0: (pending.length)})}</small>}</h3>
      <button className="secondary" disabled={disabled||!actors.length} onClick={()=>open()}>{uiText("TradePanel.003")}</button></div>
    <p className="tiny-muted">{uiText("TradePanel.004")}</p>
    {editing&&<form className="trade-editor" onSubmit={e=>{e.preventDefault();void submit(counter?
      {kind:'counter',offer_id:counter,items:selected,coins}:{kind:'propose',target_id:other,items:selected,coins,request_coins:requested});}}>
      <h4>{counter?uiText("TradePanel.028"):uiText("TradePanel.027")}</h4>
      {original?<p>{uiText("TradePanel.005", {p0: (original.sender_name), p1: (describe(original.give))})}</p>:
        <label className="studio-field">{uiText("TradePanel.006")}<select aria-label={uiText("TradePanel.006")} value={other} disabled={disabled} onChange={e=>setTarget(e.target.value)}>
          {actors.map((a:any)=><option key={a.id} value={a.id}>{a.name}</option>)}
        </select></label>}
      <fieldset disabled={disabled}><legend>{uiText("TradePanel.007")}</legend>
        {view.inventory.length?view.inventory.map((i:any)=><label className="trade-item" key={i.id}><span>{uiText("TradePanel.008", {p0: (i.name), p1: (i.quantity)})}</span>
          <input aria-label={uiText("TradePanel.026", {p0: (i.name)})} type="number" min="0" max={i.quantity} step="1" value={quantities[i.id]||0} onChange={e=>setQuantities({...quantities,[i.id]:Number(e.target.value)})}/>
        </label>):<p className="tiny-muted">{uiText("TradePanel.009")}</p>}
      </fieldset>
      <div className="trade-money"><label className="studio-field">{uiText("TradePanel.010")}<input aria-label={uiText("TradePanel.025")} disabled={disabled} type="number" min="0" max={view.resources.coins||0} step="1" value={coins} onChange={e=>setCoins(Number(e.target.value))}/></label>
        {!counter&&<label className="studio-field">{uiText("TradePanel.011")}<input aria-label={uiText("TradePanel.024")} disabled={disabled} type="number" min="0" max="999999" step="1" value={requested} onChange={e=>setRequested(Number(e.target.value))}/></label>}
      </div>
      <p className="tiny-muted">{uiText("TradePanel.012")}</p>
      <button className="primary" type="submit" disabled={disabled||invalid||!other||(!!original&&original.status!=='pending')}>{counter?uiText("TradePanel.023"):uiText("TradePanel.022")}</button>
      <button className="quiet-button" type="button" disabled={sending} onClick={()=>setEditing(false)}>{uiText("TradePanel.013")}</button>
    </form>}
    {pending.map(o=><article className="trade-offer" data-offer={o.id} key={o.id}>
      <h4>{o.sender_name} → {o.recipient_name} <small>{uiText("TradePanel.014")}</small></h4>
      <p>{uiText("TradePanel.015", {p0: (o.sender_name), p1: (describe(o.give))})}</p><p>{uiText("TradePanel.015", {p0: (o.recipient_name), p1: (describe(o.receive))})}</p>
      {o.unavailable&&<p className="notice">{uiText("TradePanel.016", {p0: (o.unavailable)})}</p>}
      {o.recipient===view.player_actor_id?<div className="trade-buttons">
        <button className="primary" disabled={disabled||!!o.unavailable} onClick={()=>void submit({kind:'accept',offer_id:o.id})}>{uiText("TradePanel.017")}</button>
        <button className="secondary" disabled={disabled||!actors.some((a:any)=>a.id===o.sender)} onClick={()=>open(o)}>{uiText("TradePanel.018")}</button>
        <button className="quiet-button" disabled={disabled} onClick={()=>void submit({kind:'decline',offer_id:o.id})}>{uiText("TradePanel.019")}</button>
      </div>:<button className="quiet-button" disabled={disabled} onClick={()=>void submit({kind:'withdraw',offer_id:o.id})}>{uiText("TradePanel.020")}</button>}
    </article>)}
    {offers.some(o=>o.status!=='pending')&&<details className="trade-history"><summary>{uiText("TradePanel.021")}</summary>
      {offers.filter(o=>o.status!=='pending').map(o=><p key={o.id}>{o.sender_name} → {o.recipient_name} · {labels[o.status]}<br/>{describe(o.give)} ⇄ {describe(o.receive)}</p>)}
    </details>}
  </section>;
}
