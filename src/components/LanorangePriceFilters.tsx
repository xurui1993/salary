import React,{useEffect,useRef,useState} from 'react';
import {KeyRound, RefreshCw} from 'lucide-react';
import {platformAuthRequest} from '../lib/platformAuthApi';
import {stationFilterChoices} from '../lib/stationFilterChoices';
import {usePlatformAuthSnapshot} from '../lib/platformAuthStore';
type Fetcher=(url:string,init?:RequestInit)=>Promise<Response>;
export type LanorangeFilterOptions={cities:string[];stations:{id:string;name:string;city:string}[];months:string[];session_version:string};
export function LanorangePriceFilters({apiFetch,workspaceId,city,station,month,onChange,disabled=false,requiredMonth=false,lanorangeConnected}:{apiFetch:Fetcher;workspaceId:string;city:string;station:string;month:string;onChange:(value:{city:string;station:string;month:string})=>void;disabled?:boolean;requiredMonth?:boolean;lanorangeConnected?:boolean}){
  const fetchRef=useRef(apiFetch);fetchRef.current=apiFetch;
  const changeRef=useRef(onChange);changeRef.current=onChange;
  const disabledRef=useRef(disabled);disabledRef.current=disabled;
  const [options,setOptions]=useState<LanorangeFilterOptions|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[reload,setReload]=useState(0);
  const auth=usePlatformAuthSnapshot();
  const isLoggedIn=Boolean(lanorangeConnected || auth.isLoggedIn('lanorange'));
  useEffect(()=>{
    const changed=(event:Event)=>{if((event as CustomEvent).detail?.source==='lanorange'){setOptions(null);if(!disabledRef.current)changeRef.current({city:'',station:'',month:''});setReload(v=>v+1);}};
    window.addEventListener('workbench:platform-session-changed',changed);return()=>window.removeEventListener('workbench:platform-session-changed',changed);
  },[]);
  useEffect(()=>{
    if(!isLoggedIn && reload===0){
      setOptions(null);
      setBusy(false);
      setError('');
      return;
    }
    let disposed=false;const controller=new AbortController();setOptions(null);setBusy(true);setError('');
    const fetcher=(url:string,init?:RequestInit)=>fetchRef.current(url,{...init,signal:init?.signal?AbortSignal.any([controller.signal,init.signal]):controller.signal});
    void platformAuthRequest<LanorangeFilterOptions>(fetcher,'/api/fengshen-downloads/lanorange-approvals/filter-options'+(reload?'?refresh=true':''),undefined,60000).then(value=>{if(!disposed)setOptions(value);}).catch(err=>{if(!disposed)setError(err instanceof Error?err.message:'筛选条件读取失败');}).finally(()=>{if(!disposed)setBusy(false);});
    return()=>{disposed=true;controller.abort();};
  },[workspaceId,reload,isLoggedIn]);
  const stations=stationFilterChoices(options?.stations||[],city);
  const chosen=stations.filter(s=>s.name===station);
  const selectedId=chosen.length===1?chosen[0].id:station?'legacy':'';
  const waiting=disabled || busy || !options;
  const isLoginErr=error.includes('登录');
  const showDisconnectedHint=!options && !busy && (!isLoggedIn || isLoginErr);
  return <>
    <label className="wbx-ap-field">
      <span className="wbx-ap-field__label">城市</span>
      <select className="wbx-ap-select" aria-label="城市" disabled={waiting} value={city} onChange={e=>changeRef.current({city:e.target.value,station:'',month})}>
        <option value="">全部城市</option>
        {city && !options?.cities.includes(city) && <option value={city} disabled>{city}（原选择，请重新选择）</option>}
        {options?.cities.map(c=><option key={c} value={c}>{c} · {new Set(options?.stations.filter(s=>s.city===c).map(s=>s.id)).size}站</option>)}
      </select>
    </label>
    <label className="wbx-ap-field">
      <span className="wbx-ap-field__label">站点</span>
      <select className="wbx-ap-select" aria-label="站点" disabled={waiting} value={selectedId} onChange={e=>{const selected=stations.find(s=>s.id===e.target.value);if(selected?.ambiguous)return;changeRef.current({city,station:selected?.name||'',month});}}>
        <option value="">全部站点</option>
        {selectedId==='legacy'&&<option value="legacy" disabled>{station}（请重新选择）</option>}
        {stations.map(s=><option key={s.id} value={s.id} disabled={s.ambiguous}>{s.label}{s.ambiguous?'（同名，请限定城市或核对）':''}</option>)}
      </select>
    </label>
    <label className="wbx-ap-field">
      <span className="wbx-ap-field__label">结算月份{requiredMonth && <em className="wbx-ap-field__req">*</em>}</span>
      <select className="wbx-ap-select" aria-label="结算月份" required={requiredMonth} disabled={waiting} value={month} onChange={e=>changeRef.current({city,station,month:e.target.value})}>
        <option value="">{requiredMonth?'请选择结算月份':'全部月份'}</option>
        {month && !options?.months.includes(month) && <option value={month} disabled>{month}（原选择，请重新选择）</option>}
        {options?.months.map(m=><option key={m} value={m}>{m}</option>)}
      </select>
    </label>
    {(showDisconnectedHint || error) && (
      <div className={`wbx-ap-notice col-span-full ${showDisconnectedHint ? 'is-auth' : 'is-danger'}`} role="alert">
        <div className="wbx-ap-notice__body">
          <KeyRound size={15} className="wbx-ap-notice__icon" aria-hidden="true" />
          <div className="wbx-ap-notice__copy">
            <strong>{showDisconnectedHint ? '当前未连接蓝橙账号，请点击页面顶部「去登录」后读取实时权限城市与站点目录' : '筛选项读取提示'}</strong>
            {!showDisconnectedHint && <span>{error}</span>}
          </div>
        </div>
        <div className="wbx-ap-notice__actions">
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={busy}
            onClick={() => setReload(v => v + 1)}
          >
            <RefreshCw size={12.5} className={busy ? 'wbx-spin' : ''} />
            <span>{busy ? '读取中…' : '重新读取'}</span>
          </button>
        </div>
      </div>
    )}
  </>;
}

