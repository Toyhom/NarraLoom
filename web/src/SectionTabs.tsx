import { ReactNode } from 'react';

export function SectionTabs<T extends string>({name, label, value, items, onChange}: {
  name: string; label: string; value: T; items: {id: T; label: ReactNode}[]; onChange: (value: T) => void;
}) {
  return <div className="section-tabs" role="tablist" aria-label={label}>
    {items.map((item, index) => <button key={item.id} type="button" role="tab"
      id={`${name}-tab-${item.id}`} aria-controls={`${name}-panel-${item.id}`}
      aria-selected={value === item.id} tabIndex={value === item.id ? 0 : -1}
      onClick={() => onChange(item.id)} onKeyDown={event => {
        let next = index;
        if (event.key === 'ArrowRight') next = (index + 1) % items.length;
        else if (event.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = items.length - 1;
        else return;
        event.preventDefault(); onChange(items[next].id);
        document.getElementById(`${name}-tab-${items[next].id}`)?.focus();
      }}>{item.label}</button>)}
  </div>;
}

export function TabPanel({name, id, active, children}: {
  name: string; id: string; active: string; children: ReactNode;
}) {
  return <div id={`${name}-panel-${id}`} role="tabpanel" aria-labelledby={`${name}-tab-${id}`}
    hidden={active !== id} tabIndex={0}>{children}</div>;
}
