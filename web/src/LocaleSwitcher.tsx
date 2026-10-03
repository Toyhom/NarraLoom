import { Languages } from 'lucide-react';
import { Locale, setLocale, useLocale } from './i18n';

export function LocaleSwitcher() {
  const locale = useLocale();
  return <label className="locale-switcher" title={{ en: 'Interface language', 'zh-CN': '界面语言', ja: '表示言語' }[locale]}>
    <Languages size={17} aria-hidden="true"/>
    <select aria-label="界面语言 / Interface language" value={locale} onChange={event => setLocale(event.target.value as Locale)}>
      <option value="zh-CN">简体中文</option><option value="en">English</option><option value="ja">日本語</option>
    </select>
  </label>;
}
