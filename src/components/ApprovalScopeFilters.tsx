import React from 'react';
type Row={cityName?:string;siteName?:string;settle_month?:string;period_start?:string};
export function ApprovalScopeFilters({rows,cities,months,site,busy,onChange,onRefresh}:{rows:Row[];cities:string[];months:string[];site:string;busy:boolean;onChange:(cities:string[],months:string[],site:string)=>void;onRefresh:()=>void}){
  const month=(r:Row)=>(r.settle_month||r.period_start||'').slice(0,7);
  const cityChoices=[...new Set(rows.map(r=>r.cityName||'').filter(Boolean))].sort();
  const monthChoices=[...new Set(rows.filter(r=>!cities.length||cities.includes(r.cityName||'')).map(month).filter(Boolean))].sort().reverse();
  const sites=new Map(rows.filter(r=>(!cities.length||cities.includes(r.cityName||''))&&(!months.length||months.includes(month(r)))).map(r=>[JSON.stringify([r.cityName,r.siteName]),r]));
  const toggle=(values:string[],v:string)=>values.includes(v)?values.filter(x=>x!==v):[...values,v];
  return <section className="approval-scope" aria-label="本人待审批范围">
    <header><div><h3>本人待审批</h3><p>按城市、月份多选组合，勾选后预览审批。</p></div><button className="wb-button" disabled={busy} onClick={onRefresh}>{busy?'正在读取…':'刷新待办'}</button></header>
    <fieldset disabled={busy}><legend>城市 <small>未勾选时显示全部待办城市</small></legend><div className="approval-chips">{cityChoices.map(c=><label key={c} className={cities.includes(c)?'is-selected':''}><input type="checkbox" checked={cities.includes(c)} onChange={()=>onChange(toggle(cities,c),[], '')}/>{c}<span>{rows.filter(r=>r.cityName===c).length}条</span></label>)}</div></fieldset>
    <fieldset disabled={busy}><legend>结算月份</legend><div className="approval-chips">{monthChoices.map(m=><label key={m} className={months.includes(m)?'is-selected':''}><input type="checkbox" checked={months.includes(m)} onChange={()=>onChange(cities,toggle(months,m),'')}/>{m}<span>{rows.filter(r=>(!cities.length||cities.includes(r.cityName||''))&&month(r)===m).length}条</span></label>)}</div></fieldset>
    <div className="wb-row"><label>站点 <select className="wb-select" aria-label="待审批站点" disabled={busy} value={site} onChange={e=>onChange(cities,months,e.target.value)}><option value="">当前范围全部站点</option>{[...sites].map(([key,r])=><option value={key} key={key}>{r.cityName} · {r.siteName||'待办未提供站点'}</option>)}</select></label>{(cities.length>0||months.length>0||site)&&<button className="wb-link" onClick={()=>onChange([],[],'')}>清除范围</button>}</div>
    {!busy&&!rows.length&&<p className="wb-muted">当前账号暂无可审批待办。</p>}
  </section>;
}
