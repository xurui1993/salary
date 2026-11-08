import React,{useEffect,useRef,useState} from 'react';
import {RefreshCw,Search} from 'lucide-react';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {useStationDirectory,stationCountText} from '../lib/useStationDirectory';
import {filterStations,requestStationCatalog,stationCityOptions,stationCitySelection,stationIdentity,type DeductionStation,type StationCatalog,type StationFetch,type StationPlatform} from '../lib/deductionStations';

export function DeductionStationPicker({apiFetch,platform:initialPlatform='fengshen',current,disabled=false,onSelect,onManual,onClose,onPlatformChange}:{
  apiFetch:StationFetch;platform?:StationPlatform;current?:{city:string;name:string;id:string};disabled?:boolean;
  onSelect:(station:DeductionStation)=>void;onManual:()=>void;onClose:()=>void;onPlatformChange?:(platform:StationPlatform)=>void;
}){
  const [platform,setPlatform]=useState<StationPlatform>(initialPlatform),[city,setCity]=useState('');
  const stationDirectory=useStationDirectory(platform,apiFetch);
  const [catalog,setCatalog]=useState<StationCatalog|null>(null),[cityOptions,setCityOptions]=useState<{id:string;name:string}[]>([]);
  const [search,setSearch]=useState(''),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const controller=useRef<AbortController|null>(null),sequence=useRef(0),alive=useRef(true);
  const fetchRef=useRef(apiFetch);fetchRef.current=apiFetch;
  const cancel=()=>{sequence.current++;controller.current?.abort();controller.current=null;setLoading(false);};
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;sequence.current++;controller.current?.abort();};},[]);
  useEffect(()=>{
    const changed=(event:Event)=>{
      if((event as CustomEvent).detail?.source!==platform)return;
      cancel();setCatalog(null);setCityOptions([]);setCity('');setSearch('');setError('平台会话已变化，请重新获取站点；配置草稿仍保留。');
    };
    window.addEventListener('workbench:platform-session-changed',changed);
    return()=>window.removeEventListener('workbench:platform-session-changed',changed);
  },[platform]);
  async function load(refresh=false){
    controller.current?.abort();const request=++sequence.current;
    const abort=new AbortController();controller.current=abort;
    setLoading(true);setError('');setCatalog(null);
    try{
      const result=await requestStationCatalog(fetchRef.current,platform,city,refresh,AbortSignal.any([abort.signal,AbortSignal.timeout(60000)]));
      if(!alive.current||request!==sequence.current||abort.signal.aborted)return;
      const resolvedCity=stationCitySelection(city,result.cities);
      setCityOptions(result.cities);setCity(resolvedCity);
      if(city&&!resolvedCity){setCatalog({...result,stations:[]});setError('后台存在同名城市，请按编号选择城市后重新获取站点。');}
      else setCatalog(result);
    }catch(problem){
      if(!alive.current||request!==sequence.current||abort.signal.aborted)return;
      setError(problem instanceof Error?problem.message:'获取站点未完成，请重试。');
    }finally{if(alive.current&&request===sequence.current)setLoading(false);}
  }
  const choices=stationCityOptions(cityOptions);
  const stations=catalog?filterStations(catalog.stations,search):[];
  const fetched=catalog?.fetched_at;
  const fetchedDate=fetched?new Date(typeof fetched==='number'&&fetched<1e12?fetched*1000:fetched):null;
  const fetchedTime=fetchedDate&&Number.isFinite(fetchedDate.getTime())?fetchedDate.toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):'';
  return <WorkbenchDrawer title="从平台选择站点" wide onClose={onClose}>
    <section className="wb-station-picker" aria-label="后台站点目录">
      {current&&<div className="wb-station-picker-current"><strong>当前配置：{current.city||'未填城市'} · {current.name||'未填站点'}</strong><p className="wb-muted">编号 {current.id||'未填'}。选择候选站点后才修改草稿；目录中未出现不代表历史配置已失效。</p></div>}
      <div className="wb-station-picker-controls">
        <label><span>来源平台</span><select className="wb-select" aria-label="站点来源平台" value={platform} disabled={disabled} onChange={event=>{cancel();const next=event.target.value as StationPlatform;setPlatform(next);onPlatformChange?.(next);setCity('');setCityOptions([]);setCatalog(null);setSearch('');setError('');}}><option value="fengshen">风神</option><option value="xiaoxiang">灯塔</option></select></label>
        <label><span>城市</span><select className="wb-select" aria-label="后台站点城市" value={city} disabled={disabled||!cityOptions.length} onChange={event=>{cancel();setCity(event.target.value);setCatalog(null);setSearch('');setError('');}}><option value="">{platform==='fengshen'?'先获取后台城市':'全部可查询城市'}</option>{choices.map(option=><option key={JSON.stringify([option.value,option.name])} value={option.value}>{option.label} · {stationCountText(stationDirectory.data,option.value)}</option>)}</select></label>
        <button type="button" className="wb-primary" disabled={disabled||loading} onClick={()=>void load()}>{loading?'正在获取…':platform==='fengshen'&&!city?'获取城市列表':'获取站点'}</button>
        <button type="button" className="wb-button" disabled={disabled||loading||!catalog} onClick={()=>void load(true)}><RefreshCw size={14}/>刷新目录</button>
        <button type="button" className="wb-button" onClick={()=>window.dispatchEvent(new CustomEvent('workbench:connections',{detail:{source:platform}}))}>平台登录</button>
      </div>
      <p className="wb-muted">获取只读取平台目录，选中后仍需保存扣款配置。登录完成后可返回这里重新获取，原草稿保留。</p>
      {error&&<p className="wb-error" role="alert">{error}</p>}
      {catalog&&<><p className="wb-notice">{catalog.scope_note}</p>{catalog.warnings.map((warning,index)=><p key={index} className="wb-notice">{warning}</p>)}{fetchedTime&&<p className="wb-muted">{catalog.cached?'目录缓存':'本次获取'} · {fetchedTime}</p>}</>}
      {loading&&<p role="status" className="wb-muted">正在读取授权范围内的目录，请稍候；不会修改现有扣款。</p>}
      {catalog&&catalog.stations.length>0&&<label className="wb-station-picker-search"><Search size={15}/><input className="wb-input" aria-label="搜索后台站点" placeholder="搜索站点名称、编号或城市" value={search} onChange={event=>setSearch(event.target.value)}/></label>}
      <div className="wb-station-picker-results" aria-label="后台候选站点">
        {stations.map(station=><div className="wb-station-picker-item" key={stationIdentity(station)}><div><strong>{station.name}</strong><p className="wb-muted">{station.city||'平台未提供城市归属'} · 编号 {station.id}</p></div><button type="button" className="wb-button" disabled={disabled||loading||!station.city} aria-label={`选择站点 ${station.name} ${station.id}`} onClick={()=>{try{onSelect(station);}catch(problem){setError(problem instanceof Error?problem.message:'选择未完成，请检查配置。');}}}>选择</button></div>)}
        {!loading&&catalog&&!stations.length&&<p className="wb-empty">{search?'没有匹配的站点。':platform==='fengshen'&&!city&&catalog.cities.length?'已取得城市目录，请选择城市后获取站点。':'本次查询未返回可选择的站点，请确认城市、权限和目录范围。现有配置保留。'}</p>}
        {!loading&&!catalog&&!error&&<p className="wb-muted">先获取平台目录，再按城市选择站点。</p>}
      </div>
      <footer className="wb-row wb-space"><span className="wb-muted">历史站点或暂时无法查询的站点可继续手动维护。</span><button type="button" className="wb-button" disabled={disabled} onClick={onManual}>手动填写</button></footer>
    </section>
  </WorkbenchDrawer>;
}
