import React from 'react';

export interface PayrollReview {
  version: number;
  status: 'pending_review';
  batch_id: string;
  city?: string;
  start?: string;
  end?: string;
  metrics: {key:string;label:string;value:number|null;unit:string;note:string}[];
  issues: {code:string;label:string;count?:number;location?:string;rows?:{row:number;same_as:number}[]}[];
  sources: {kind:string;label:string;status:string;files:{name:string;sha256?:string}[]}[];
  template: {name:string;sha256?:string};
  deduction_version?: string;
  input_check: string;
  money_check: string;
  export_error?: string;
}

export function PayrollReviewSummary({review}: {review?:PayrollReview}) {
  if(!review)return <section className="wb-review-summary" aria-label="核算业务复核"><h3>待人工复核</h3><p className="wb-muted">本批次未保存统一复核摘要，请查看原工作簿与资料清单。未统计不代表零异常。</p></section>;
  const primary=new Set(['applicants','no_price','unbound','intercepted']);
  return <section className="wb-review-summary" aria-label="核算业务复核">
    <header><h3>已生成 · 待人工复核</h3><span>{review.issues.length?`${review.issues.length} 项需核对`:'仍需核对金额与业务范围'}</span></header>
    {review.city&&<p className="wb-muted">{review.city} · {review.start} 至 {review.end} · 批次 {review.batch_id.slice(0,8).toUpperCase()}</p>}
    <dl className="wb-review-metrics">{review.metrics.filter(metric=>primary.has(metric.key)).map(metric=><div key={metric.key}><dt>{metric.label}</dt><dd>{metric.value==null?'未统计':`${metric.value.toLocaleString()} ${metric.unit}`}</dd></div>)}</dl>
    {review.issues.length>0&&<ul className="wb-review-issues">{review.issues.map(issue=><li key={issue.code}><strong>{issue.label}{issue.count!=null?`（${issue.count}）`:''}</strong>{issue.location&&<span>{issue.location}</span>}{issue.rows&&<details><summary>查看重复行位置</summary><ul>{issue.rows.map(row=><li key={row.row}>第 {row.row} 行与第 {row.same_as} 行相同</li>)}</ul></details>}</li>)}</ul>}
    <p className="wb-muted">{review.money_check}</p>
    {review.export_error&&<p className="wb-error" role="alert">{review.export_error}</p>}
    <details className="wb-advanced"><summary>统计口径与来源凭据</summary>
      <dl className="wb-review-definitions">{review.metrics.map(metric=><div key={metric.key}><dt>{metric.label}：{metric.value==null?'未统计':`${metric.value.toLocaleString()} ${metric.unit}`}</dt><dd>{metric.note}</dd></div>)}</dl>
      <p className="wb-muted">{review.input_check}</p>
      <p>申请表：{review.template.name} · 内容标识 {review.template.sha256?.slice(0,12)||'未保存'}</p>
      <p>扣款配置内容标识：{review.deduction_version?.slice(0,12)||'未保存'}</p>
      <ul>{review.sources.map(source=><li key={source.kind}>{source.label} · {source.status==='ready'?'已准备':source.status==='omitted'?'本批次不提供':'状态需核对'}{source.files.map(file=><p key={file.name} className="wb-muted">{file.name} · {file.sha256?.slice(0,12)||'未保存校验值'}</p>)}</li>)}</ul>
    </details>
  </section>;
}
