import { uiText, useLocale } from './i18n';
import { useState } from 'react';
import { Swords, Heart, Coins, Users } from 'lucide-react';

export type RuleAction={kind:string;target_id:string;item_id?:string;quantity?:number;action_id?:string;parameters?:Record<string,unknown>};
export type GameView={rule_system?:string;resources:Record<string,number>;resource_limits?:Record<string,number>;
  rule_actions?:RuleAction[];inventory:{id:string;name:string;quantity:number}[];equipment?:Record<string,string|null>;
  present_actors:{id:string;name:string}[];ground_items?:{id:string;name:string;quantity:number}[];
  enemies?:{id:string;name:string;hp:number;max_hp:number}[];party?:{id:string;name:string}[];
  shops?:{id:string;name:string;stock:{item_id:string;quantity:number}[];catalog:{id:string;name:string;price:number}[]}[]};
const names:Record<string,string>={get take() { return uiText("GamePanel.022"); },get use() { return uiText("GamePanel.021"); },get equip() { return uiText("GamePanel.020"); },get unequip() { return uiText("GamePanel.019"); },get buy() { return uiText("GamePanel.018"); },get sell() { return uiText("GamePanel.017"); },get attack() { return uiText("GamePanel.016"); },get rest() { return uiText("GamePanel.015"); },get recover() { return uiText("GamePanel.014"); },get recruit() { return uiText("GamePanel.013"); },get dismiss() { return uiText("GamePanel.012"); }};

export function GamePanel({view,busy,onAction}:{view:GameView;busy:boolean;onAction:(text:string,op:RuleAction)=>void}){
  useLocale();
  const [count,setCount]=useState(1);
  if(!view.rule_system)return null;
  const label=(op:RuleAction)=>{
    const item=[...view.inventory,...view.ground_items||[],...view.shops?.flatMap(s=>s.catalog)||[]].find(i=>i.id===op.item_id);
    const target=[...view.present_actors,...view.enemies||[],...view.party||[]].find(a=>a.id===op.target_id);
    return names[op.kind]+(item?' '+item.name:target&&['attack','recruit','dismiss'].includes(op.kind)?' '+target.name:'');
  };
  return <section className="sidebar-section game-panel"><h3><Swords size={16}/>{uiText("GamePanel.001")}<span>{view.rule_system}</span></h3>
    <div className="game-resources"><span><Heart size={14}/>{uiText("GamePanel.002")}<b>{view.resources.hp}/{view.resource_limits?.hp}</b></span><span><Coins size={14}/>{uiText("GamePanel.003")}<b>{view.resources.coins}</b></span><span>{uiText("GamePanel.004")}<b>{view.resources.xp}</b></span></div>
    {!!view.enemies?.length&&<div className="enemy-list">{view.enemies.map(e=><div key={e.id}><strong>{e.name}</strong><span>{e.hp>0?`${e.hp}/${e.max_hp}`:uiText("GamePanel.011")}</span><progress value={e.hp} max={e.max_hp}/></div>)}</div>}
    {!!view.party?.length&&<p className="party-list"><Users size={14}/>{view.party.map(a=>a.name).join(' · ')}</p>}
    {view.shops?.map(shop=><details key={shop.id}><summary>{shop.name}</summary>{shop.stock.map(stock=>{const item=shop.catalog.find(i=>i.id===stock.item_id);return <p key={stock.item_id}>{uiText("GamePanel.005", {p0: (item?.name), p1: (item?.price), p2: (stock.quantity)})}</p>;})}</details>)}
    <label className="trade-quantity">{uiText("GamePanel.006")}<input type="number" aria-label={uiText("GamePanel.010")} value={count} min={1} max={99} onChange={e=>setCount(Math.max(1,Math.min(99,Number(e.target.value)||1)))}/></label>
    <div className="rule-actions">{view.rule_actions?.map((op,i)=><button key={i} className={'rule-action '+(op.kind==='attack'?'combat-action':'')} disabled={busy} onClick={()=>{const n=['buy','sell','take'].includes(op.kind)?count:1;onAction(uiText("GamePanel.009", {p0: (label(op)), p1: ((n>1?uiText("GamePanel.008", {p0: (n)}):''))}),{...op,quantity:n});}}>{label(op)}</button>)}</div>
    {view.resources.hp===0&&<p className="notice">{uiText("GamePanel.007")}</p>}
  </section>;
}
