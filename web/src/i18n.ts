import { useState, useSyncExternalStore } from 'react';
import zh from './locales/zh-CN.json';
import en from './locales/en.json';
import ja from './locales/ja.json';

export type Locale = 'zh-CN' | 'en' | 'ja';
export type MessageKey = keyof typeof zh;
const catalogs: Record<Locale, Record<MessageKey, string>> = { 'zh-CN': zh, en, ja };
const preference = 'narraloom.locale';
const listeners = new Set<() => void>();
const normalize = (value: string | null): Locale | null =>
  value === 'zh' || value === 'zh-CN' ? 'zh-CN' : value === 'en' ? 'en' : value === 'ja' ? 'ja' : null;

function initialLocale(): Locale {
  try {
    const saved = normalize(localStorage.getItem(preference));
    if (saved) return saved;
    // Migrate the former module-panel preference once, without touching content.
    const legacy = normalize(localStorage.getItem('narraloom.engineLanguage'));
    if (legacy) { localStorage.setItem(preference, legacy); return legacy; }
  } catch { /* Storage can be unavailable in embedded/private browsers. */ }
  const language = typeof navigator !== 'undefined' ? navigator.language.toLowerCase() : 'en';
  return language.startsWith('zh') ? 'zh-CN' : language.startsWith('ja') ? 'ja' : 'en';
}

let locale = initialLocale();
export const getLocale = () => locale;
function publish(next: Locale) {
  locale = next;
  if (typeof document !== 'undefined') {
    document.documentElement.lang = next;
    document.title = { en: 'NarraLoom · Story worlds', 'zh-CN': '叙织 · NarraLoom', ja: 'NarraLoom · 物語の世界' }[next];
  }
  listeners.forEach(listener => listener());
}
export function setLocale(next: Locale) {
  const canonical = normalize(next);
  if (!canonical) return;
  try { localStorage.setItem(preference, canonical); } catch { /* In-memory choice still works. */ }
  publish(canonical);
}
if (typeof window !== 'undefined') {
  publish(locale);
  window.addEventListener('storage', event => {
    if (event.key === preference) publish(normalize(event.newValue) || initialLocale());
  });
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function useLocale() { return useSyncExternalStore(subscribe, getLocale, () => 'zh-CN' as const); }

/** Text interpolation only. Never accepts HTML or modifies authored world data. */
export function uiText(key: MessageKey, params: Record<string, string | number | boolean | null | undefined> = {}): string {
  const template = catalogs[locale][key] ?? en[key];
  return template.replace(/\{(p\d+)\}/g, (placeholder, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name] ?? '') : placeholder);
}

export type UiMessage = { key: MessageKey; params: Parameters<typeof uiText>[1] };
export const uiMessage = (key: MessageKey, params: Parameters<typeof uiText>[1] = {}): UiMessage => ({ key, params });
/** Keep notifications as keys so an open status updates without repeating its action. */
export function useUiMessage(initial: string | UiMessage = '') {
  useLocale();
  const [value, setValue] = useState(initial);
  return [typeof value === 'string' ? value : uiText(value.key, value.params), setValue] as const;
}
