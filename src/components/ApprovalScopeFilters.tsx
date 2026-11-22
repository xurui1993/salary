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

  if (isEmptyRows) {
    return (
      <div className="wbx-ap-scope is-empty" aria-label="本人待审批范围">
        <div className="wbx-ap-scope__item">
          <span className="wbx-ap-scope__label">城市</span>
          <span className="wbx-ap-scope__placeholder">同步本人待办后生成</span>
        </div>
        <div className="wbx-ap-scope__item">
          <span className="wbx-ap-scope__label">结算月份</span>
          <span className="wbx-ap-scope__placeholder">全部月份</span>
        </div>
        <label className="wbx-ap-scope__station">
          <span className="wbx-ap-scope__label">站点</span>
          <select
            className="wbx-ap-select"
            aria-label="待审批站点"
            disabled
            value=""
            onChange={() => {}}
          >
            <option value="">全部站点（待同步）</option>
          </select>
        </label>
      </div>
    );
  }

  return (
    <div className="wbx-ap-scope" aria-label="本人待审批范围">
      <div className="wbx-ap-scope__row">
        <span className="wbx-ap-scope__label">城市</span>
        <div className="wbx-ap-scope__chips">
          <div className="approval-chips">
            {cityChoices.map(c => (
              <label key={c} className={cities.includes(c) ? 'is-selected' : ''}>
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={cities.includes(c)}
                  onChange={() => onChange(toggle(cities, c), [], '')}
                />
                {c}
                <span>{rows.filter(r => r.cityName === c).length}</span>
              </label>
            ))}
          </div>
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

      <div className="wbx-ap-scope__row wbx-ap-scope__row--secondary">
        <span className="wbx-ap-scope__label">月份</span>
        <div className="wbx-ap-scope__chips">
          {monthChoices.length > 0 ? (
            <div className="approval-chips">
              {monthChoices.map(m => (
                <label key={m} className={months.includes(m) ? 'is-selected' : ''}>
                  <input
                    type="checkbox"
                    disabled={busy}
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
            <span className="wbx-ap-scope__placeholder">全部结算月份</span>
          )}
        </div>
        <label className="wbx-ap-scope__station">
          <span className="wbx-ap-scope__label">站点</span>
          <select
            className="wbx-ap-select"
            aria-label="待审批站点"
            disabled={busy}
            value={site}
            onChange={e => onChange(cities, months, e.target.value)}
          >
            <option value="">全部站点 ({sites.size})</option>
            {[...sites].map(([key, r]) => (
              <option value={key} key={key}>
                {r.cityName} · {r.siteName || '未命名站点'}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

