import React,{useEffect,useRef,useState} from 'react';
import {platformAuthRequest} from '../lib/platformAuthApi';
import {stationFilterChoices} from '../lib/stationFilterChoices';
type Fetcher=(url:string,init?:RequestInit)=>Promise<Response>;
type Options={cities:string[];stations:{id:string;name:string;city:string}[];months:string[];session_version:string};
export function LanorangePriceFilters({apiFetch,workspaceId,city,station,month,onChange,disabled=false,requiredMonth=false}:{apiFetch:Fetcher;workspaceId:string;city:string;station:string;month:string;onChange:(value:{city:string;station:string;month:string})=>void;disabled?:boolean;requiredMonth?:boolean}){
  const fetchRef=useRef(apiFetch);fetchRef.current=apiFetch;
  const changeRef=useRef(onChange);changeRef.current=onChange;
  const disabledRef=useRef(disabled);disabledRef.current=disabled;
  const [options,setOptions]=useState<Options|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[reload,setReload]=useState(0);
  useEffect(()=>{
    const changed=(event:Event)=>{if((event as CustomEvent).detail?.source==='lanorange'){setOptions(null);if(!disabledRef.current)changeRef.current({city:'',station:'',month:''});setReload(v=>v+1);}};
    window.addEventListener('workbench:platform-session-changed',changed);return()=>window.removeEventListener('workbench:platform-session-changed',changed);
  },[]);
  useEffect(()=>{
    let disposed=false;const controller=new AbortController();setOptions(null);setBusy(true);setError('');
    const fetcher=(url:string,init?:RequestInit)=>fetchRef.current(url,{...init,signal:init?.signal?AbortSignal.any([controller.signal,init.signal]):controller.signal});
    void platformAuthRequest<Options>(fetcher,'/api/fengshen-downloads/lanorange-approvals/filter-options'+(reload?'?refresh=true':''),undefined,60000).then(value=>{if(!disposed)setOptions(value);}).catch(err=>{if(!disposed)setError(err instanceof Error?err.message:'筛选条件读取失败');}).finally(()=>{if(!disposed)setBusy(false);});
    return()=>{disposed=true;controller.abort();};
  },[workspaceId,reload]);
  const stations=stationFilterChoices(options?.stations||[],city);
  const chosen=stations.filter(s=>s.name===station);
  const selectedId=chosen.length===1?chosen[0].id:station?'legacy':'';
  const waiting=disabled || busy || !options;
  return <>
    <label>城市<select className="wb-select" aria-label="城市" disabled={waiting} value={city} onChange={e=>changeRef.current({city:e.target.value,station:'',month})}><option value="">全部城市</option>{city && !options?.cities.includes(city) && <option value={city} disabled>{city}（原选择，请重新选择）</option>}{options?.cities.map(c=><option key={c} value={c}>{c} · {new Set(options?.stations.filter(s=>s.city===c).map(s=>s.id)).size}站</option>)}</select></label>
    <label>站点<select className="wb-select" aria-label="站点" disabled={waiting} value={selectedId} onChange={e=>{const selected=stations.find(s=>s.id===e.target.value);if(selected?.ambiguous)return;changeRef.current({city,station:selected?.name||'',month});}}><option value="">全部站点</option>{selectedId==='legacy'&&<option value="legacy" disabled>{station}（请重新选择）</option>}{stations.map(s=><option key={s.id} value={s.id} disabled={s.ambiguous}>{s.label}{s.ambiguous?'（同名，请限定城市或核对）':''}</option>)}</select></label>
    <label>结算月份<select className="wb-select" aria-label="结算月份" required={requiredMonth} disabled={disabled || busy || !options} value={month} onChange={e=>changeRef.current({city,station,month:e.target.value})}><option value="">{requiredMonth?'请选择结算月份':'全部月份'}</option>{month && !options?.months.includes(month) && <option value={month} disabled>{month}（原选择，请重新选择）</option>}{options?.months.map(m=><option key={m} value={m}>{m}</option>)}</select></label>
    {error && <p className="wb-error" role="alert">{error}</p>}
  </>;
}
