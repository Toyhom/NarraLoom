import { uiText, useLocale } from './i18n';

export type TextChange = {round?:number; path:string; before:string; after:string};
export type SemanticReview = {
  status:string; changes_applied:boolean; repair_rounds:number; changes:TextChange[];
  issues:{kind:string; path:string; quote:string; explanation:string;
    scene_claim?:{kind:string; actor_id?:string|null; location_id?:string|null}|null}[];
};
export type TextRevision = {revision:number; changes:TextChange[]};

function Changes({changes}:{changes:TextChange[]}) {
  return <>{changes.map((change,i)=><article className="review-change" key={i}>
    <code>{change.path}</code>
    <div className="review-comparison"><div><strong>{uiText('review.before')}</strong><p>{change.before}</p></div>
      <div><strong>{uiText('review.after')}</strong><p>{change.after}</p></div></div>
  </article>)}</>;
}

export function ContentReview({report}:{report?:SemanticReview|null}) {
  useLocale();
  if(!report)return null;
  return <section className="semantic-review" data-review-status={report.status}>
    <h4>{uiText('review.title')}</h4><p className="tiny-muted">{uiText('review.scope')}</p>
    {report.issues?.map((issue,i)=><article className="review-issue" key={i}>
      <strong>{issue.explanation}</strong><code>{issue.path}</code><blockquote>{issue.quote}</blockquote>
      {issue.scene_claim&&<small>{uiText('review.claim')}: <code>{issue.scene_claim.kind}</code>
        {issue.scene_claim.actor_id&&<> · <code>{issue.scene_claim.actor_id}</code></>}
        {issue.scene_claim.location_id&&<> · <code>{issue.scene_claim.location_id}</code></>}</small>}
    </article>)}
    {!!report.changes?.length&&<><p className={report.changes_applied?'review-applied':'notice error'}>
      {uiText(report.changes_applied?'review.applied':'review.unapplied')}</p><Changes changes={report.changes}/></>}
  </section>;
}

export function RevisionHistory({revisions}:{revisions?:TextRevision[]}) {
  useLocale();
  if(!Array.isArray(revisions)||!revisions.length)return null;
  return <details className="review-history"><summary>{uiText('review.history')}</summary>
    {revisions.filter(r=>r&&typeof r.revision==='number'&&Array.isArray(r.changes)
      &&r.changes.every(c=>c&&['path','before','after'].every(k=>typeof c[k as keyof TextChange]==='string'))).map((revision,i)=><section key={i}>
      <h4>{uiText('review.revision',{p0:revision.revision})}</h4><Changes changes={revision.changes}/>
    </section>)}
  </details>;
}
