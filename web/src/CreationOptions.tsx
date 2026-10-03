import { uiText, useLocale } from './i18n';
import { useState } from 'react';

export type Preset = 'scene' | 'story' | 'adventure';
export const presetNames: Record<Preset, string> = {
  get scene() { return uiText("CreationOptions.020"); },
  get story() { return uiText("CreationOptions.019"); },
  get adventure() { return uiText("CreationOptions.018"); },
};

export function ContentLanguage({value,onChange,inherit=false,source=false,resolved=false}: {
  value:string;onChange:(value:string)=>void;inherit?:boolean;source?:boolean;resolved?:boolean;
}) {
  useLocale();
  const choices = ['auto','zh-CN','en','ja','ko','fr','de','es','pt','ru','ar'];
  const [custom,setCustom] = useState(!choices.includes(value) && !!value);
  return <label className="studio-field"><span>{uiText("CreationOptions.001")}</span>
    <select aria-label={uiText("CreationOptions.017")} value={custom?'custom':value} onChange={e=>{
      setCustom(e.target.value==='custom');
      onChange(e.target.value==='custom'?'':e.target.value);
    }}>
      {inherit&&<option value="">{uiText("CreationOptions.002")}</option>}
      {!resolved&&<option value="auto">{source?uiText("CreationOptions.016"):uiText("CreationOptions.015")}</option>}
      <option value="zh-CN">{uiText("CreationOptions.003")}</option><option value="en">English</option>
      <option value="ja">{uiText("CreationOptions.004")}</option><option value="ko">한국어</option>
      <option value="fr">Français</option><option value="de">Deutsch</option>
      <option value="es">Español</option><option value="pt">Português</option>
      <option value="ru">Русский</option><option value="ar">العربية</option>
      <option value="custom">{uiText("CreationOptions.005")}</option>
    </select>
    {custom&&<input aria-label={uiText("CreationOptions.014")} value={value} placeholder={uiText("CreationOptions.013")} required pattern="[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}" maxLength={35} onChange={e=>onChange(e.target.value)}/>}
    <small>{uiText("CreationOptions.006")}</small>
  </label>;
}

export function CreationPreset({value,onChange,existingWorld=false}: {
  value:Preset;onChange:(value:Preset)=>void;existingWorld?:boolean;
}) {
  useLocale();
  return <label className="studio-field"><span>{uiText("CreationOptions.007")}</span>
    <select aria-label={uiText("CreationOptions.007")} value={value} onChange={e=>onChange(e.target.value as Preset)}>
      {Object.entries(presetNames).map(([key,name])=><option key={key} value={key}>{existingWorld?({scene:uiText("CreationOptions.012"),story:uiText("CreationOptions.011"),adventure:uiText("CreationOptions.010")} as Record<string,string>)[key]:name}</option>)}
    </select>
    <small>{existingWorld?uiText("CreationOptions.009"):uiText("CreationOptions.008")}</small>
  </label>;
}
