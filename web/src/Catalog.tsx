import { uiText, useLocale } from './i18n';
import { useEffect, useState } from 'react';
import { ArrowDownToLine, BookOpen, ExternalLink } from 'lucide-react';

type Source = { author: string; license: string; url: string };
type Pack = {
  id: string; title: string; summary: string; genre: string; locations: number; characters: number;
  source: Source;
  adaptation: { scope: string; retained: string[]; adapted: string[]; unsupported: string[] };
};
type Api = (path: string, options?: RequestInit) => Promise<any>;

export function Catalog({ api, ready, onInstalled }: {
  api: Api; ready: boolean | null; onInstalled: (worldId: string) => Promise<void>;
}) {
  useLocale();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let mounted = true;
    api('/api/catalog').then(value => { if (mounted) setPacks(value); })
      .catch(e => { if (mounted) setError(String(e)); });
    return () => { mounted = false; };
  }, []);

  async function install(pack: Pack) {
    setPending(pack.id); setError('');
    try {
      const job = await api(`/api/studio/catalog/${pack.id}/install`, { method: 'POST' });
      await onInstalled(job.world_id);
    } catch (e) { setError(String(e)); }
    finally { setPending(''); }
  }

  return <section className="catalog-section">
    <div className="section-heading"><h2><BookOpen size={20}/>{uiText("Catalog.001")}</h2><span>{uiText("Catalog.002")}</span></div>
    <p className="tiny-muted">{uiText("Catalog.003")}</p>
    {error && <p role="alert" className="notice error">{error}</p>}
    <div className="catalog-grid">{packs.map(pack => <article className="catalog-card" key={pack.id} data-catalog-id={pack.id}>
      <span className="eyebrow">{uiText("Catalog.004", {p0: (pack.genre), p1: (pack.locations), p2: (pack.characters)})}</span>
      <h3>{pack.title}</h3><p>{pack.summary}</p>
      <details><summary>{uiText("Catalog.005")}</summary>
        <p>{pack.adaptation.scope}</p>
        <p>{uiText("Catalog.006", {p0: (pack.adaptation.retained.join('；'))})}</p>
        <p>{uiText("Catalog.007", {p0: (pack.adaptation.adapted.join('；'))})}</p>
        <p>{uiText("Catalog.008", {p0: (pack.adaptation.unsupported.join('；'))})}</p>
      </details>
      <div className="catalog-credit"><a href={pack.source.url} target="_blank" rel="noreferrer">{uiText("Catalog.009", {p0: (pack.source.author)})}<ExternalLink size={12}/></a><small>{pack.source.license}</small></div>
      <button className="primary" disabled={!ready || !!pending} onClick={() => install(pack)}>
        <ArrowDownToLine size={15}/>{pending === pack.id ? uiText("Catalog.011") : uiText("Catalog.010")}
      </button>
    </article>)}</div>
  </section>;
}
