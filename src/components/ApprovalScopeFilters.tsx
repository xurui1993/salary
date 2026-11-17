import React from 'react';
import {RotateCcw} from 'lucide-react';

type Row={cityName?:string;siteName?:string;settle_month?:string;period_start?:string};

export function ApprovalScopeFilters({rows,cities,months,site,busy,onChange}:{rows:Row[];cities:string[];months:string[];site:string;busy:boolean;onChange:(cities:string[],months:string[],site:string)=>void;onRefresh?:()=>void}){
  const month=(r:Row)=>(r.settle_month||r.period_start||'').slice(0,7);
  const cityChoices=[...new Set(rows.map(r=>r.cityName||'').filter(Boolean))].sort();
  const monthChoices=[...new Set(rows.filter(r=>!cities.length||cities.includes(r.cityName||'')).map(month).filter(Boolean))].sort().reverse();
  const sites=new Map(rows.filter(r=>(!cities.length||cities.includes(r.cityName||''))&&(!months.length||months.includes(month(r)))).map(r=>[JSON.stringify([r.cityName,r.siteName]),r]));
  const toggle=(values:string[],v:string)=>values.includes(v)?values.filter(x=>x!==v):[...values,v];
  const hasActiveFilter=cities.length>0||months.length>0||Boolean(site);
  const isEmptyRows=rows.length===0;

  return (
    <section className="approval-scope wbx-approval__scope-compact" aria-label="本人待审批范围">
      <div className="wbx-approval__scope-row">
        <span className="wbx-approval__scope-label">城市</span>
        <div className="wbx-approval__scope-chips">
          {cityChoices.length > 0 ? (
            <div className="approval-chips">
              {cityChoices.map(c => (
                <label key={c} className={cities.includes(c) ? 'is-selected' : ''}>
                  <input
                    type="checkbox"
                    disabled={busy || isEmptyRows}
                    checked={cities.includes(c)}
                    onChange={() => onChange(toggle(cities, c), [], '')}
                  />
                  {c}
                  <span>{rows.filter(r => r.cityName === c).length}</span>
                </label>
              ))}
            </div>
          ) : (
            <span className="wbx-approval__scope-empty">全部城市（同步本人待办后生成）</span>
          )}
        </div>
        {hasActiveFilter && (
          <button
            type="button"
            className="wb-link wbx-approval__scope-reset"
            onClick={() => onChange([], [], '')}
          >
            <RotateCcw size={12} />
            清除筛选
          </button>
        )}
      </div>

      <div className="wbx-approval__scope-row wbx-approval__scope-row--secondary">
        <span className="wbx-approval__scope-label">月份</span>
        <div className="wbx-approval__scope-chips">
          {monthChoices.length > 0 ? (
            <div className="approval-chips">
              {monthChoices.map(m => (
                <label key={m} className={months.includes(m) ? 'is-selected' : ''}>
                  <input
                    type="checkbox"
                    disabled={busy || isEmptyRows}
                    checked={months.includes(m)}
                    onChange={() => onChange(cities, toggle(months, m), '')}
                  />
                  {m}
                  <span>
                    {rows.filter(r => (!cities.length || cities.includes(r.cityName || '')) && month(r) === m).length}
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <span className="wbx-approval__scope-empty">全部结算月份</span>
          )}
        </div>
        <label className="wbx-approval__station-inline">
          <span>站点</span>
          <select
            className="wb-select"
            aria-label="待审批站点"
            disabled={busy || isEmptyRows}
            value={site}
            onChange={e => onChange(cities, months, e.target.value)}
          >
            <option value="">
              {isEmptyRows ? '全部站点（待同步）' : `全部站点 (${sites.size})`}
            </option>
            {[...sites].map(([key, r]) => (
              <option value={key} key={key}>
                {r.cityName} · {r.siteName || '未命名站点'}
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
}

