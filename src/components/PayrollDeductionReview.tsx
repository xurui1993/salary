import React,{useCallback,useEffect,useRef,useState} from 'react';
import {CityDeductionAmounts} from './CityDeductionAmounts';
import {StationAssociations,type AssociationSubmission} from './StationAssociations';
import {associationRows} from '../lib/stationAssociations';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {DeductionAmounts,type DeductionEntry,type DeductionDraft,type Fetcher} from './DeductionAmounts';
import {useStationDirectory,stationCountText} from '../lib/useStationDirectory';
import {applyCityAmounts,deductionIssues,nextReviewAction} from '../lib/payrollReviewActions';
function ReviewContainer({inline,onClose,children}:{inline:boolean;onClose:()=>void;children:React.ReactNode}){
  const ref=useRef<HTMLElement>(null);
  useEffect(()=>{if(inline)ref.current?.scrollIntoView({block:'start',behavior:'smooth'});},[]);
  return inline?<section ref={ref} className="payroll-inline-review" aria-label="确认本次扣款清单"><header className="wb-row wb-space"><h3>确认本次扣款清单</h3><button className="wb-link" onClick={onClose}>收起清单</button></header>{children}</section>:<WorkbenchDrawer title="确认本次扣款清单" wide onClose={onClose}>{children}</WorkbenchDrawer>;
}
function preserve(next:DeductionEntry[],previous:DeductionEntry[]){
  return next.map(entry=>{const old=previous.find(e=>e.key===entry.key);return old?.edited&&old.station.id===entry.station.id&&old.station.city_id===entry.station.city_id&&old.station.name===entry.station.name?{...entry,row:old.row,edited:true,zero_confirmed:old.zero_confirmed}:entry;});
}
export function PayrollDeductionReview({apiFetch,batchId,platform='fengshen',inline=false,plan,onOpenConnections,onClose,onConfirmed}:{apiFetch:Fetcher;batchId:string;platform?:'fengshen'|'xiaoxiang';inline?:boolean;plan?:{city:string;start:string;end:string;applicants:number};onOpenConnections?:()=>void;onClose:()=>void;onConfirmed:(value:any,version:string)=>void}){
  const directory=useStationDirectory(platform,apiFetch);
  const [cityId,setCityId]=useState(''),[data,setData]=useState<DeductionDraft|null>(null);
  const [entries,setEntries]=useState<DeductionEntry[]>([]),[cities,setCities]=useState<DeductionEntry[]>([]);
  const [accepted,setAccepted]=useState<string[]>([]),[saveDefaults,setSaveDefaults]=useState(true);
  const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState(''),[reload,setReload]=useState(0);
  const [linksOpen,setLinksOpen]=useState(false),[sitesOpen,setSitesOpen]=useState(false);
  const [linkEdits,setLinkEdits]=useState(0);
  const [linkSelection,setLinkSelection]=useState({selected:0,ready:0});
  const linkSubmission=useRef<AssociationSubmission|null>(null);
  const updateLinkSubmission=useCallback((value:AssociationSubmission)=>{linkSubmission.current=value;setLinkSelection(previous=>previous.selected===value.selected&&previous.ready===value.ready?previous:{selected:value.selected,ready:value.ready});},[]);
  const forceDirectory=useRef(false);
  const entriesRef=useRef(entries),citiesRef=useRef(cities),guard=useRef(false);
  entriesRef.current=entries;citiesRef.current=cities;
  const linksRef=useRef<HTMLElement>(null),amountsRef=useRef<HTMLElement>(null),differencesRef=useRef<HTMLElement>(null);
  function install(d:DeductionDraft){
    const cityIds=new Set([...d.entries,...(d.station_choices||[])].map(e=>e.station.city_id));
    const nextCities=preserve((d.cities||[]).filter(c=>cityIds.has(c.station.city_id)),citiesRef.current);
    setCities(nextCities);setEntries(applyCityAmounts(preserve(d.entries,entriesRef.current),nextCities,d.columns));setData(d);
    setAccepted([]);if(d.unresolved?.length)setLinksOpen(true);
  }
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;setLoading(true);setError('');
    async function read(attempt=0){
      try{
        const response=await apiFetch(`/api/workbench/batches/${batchId}/deduction-review?city_id=${encodeURIComponent(cityId)}${forceDirectory.current?'&refresh=true':''}`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(30000)])});
        const value=await response.json();
        if(!response.ok){
          const message=value.detail||'本次城市资料暂未读取完成';
          if([409,503].includes(response.status)&&!/登录|映射|修改|编号/.test(message)&&attempt<5){
            if(!controller.signal.aborted){setNotice('正在获取本次城市资料，系统会自动继续；已填金额保留。');timer=setTimeout(()=>void read(attempt+1),Math.min(2000*(attempt+1),6000));}return;
          }
          throw Error(message);
        }
        if(!controller.signal.aborted){forceDirectory.current=false;install(value);setLoading(false);setNotice(previous=>previous.startsWith('正在')?'':previous);}
      }catch(error){if(!controller.signal.aborted){setLoading(false);setNotice('');setError(error instanceof Error?error.message:'连接暂未恢复，请重试本次城市');}}
    }
    void read();return()=>{controller.abort();clearTimeout(timer);};
  },[batchId,reload,cityId]);
  const refreshedDirectory=useRef('');
  useEffect(()=>{
    const city=directory.data?.cities.find(c=>c.id===cityId||c.name===(plan?.city||''));
    const token=`${directory.data?.session_version}/${directory.data?.fetched_at}/${city?.id}`;
    if(!data&&error&&city?.status==='ready'&&refreshedDirectory.current!==token){refreshedDirectory.current=token;setReload(v=>v+1);}
  },[directory.data?.fetched_at,directory.data?.status,error,cityId,plan?.city]);
  async function perform(work:()=>Promise<void>){if(guard.current)return;guard.current=true;setBusy(true);setError('');try{await work();}catch(e){setError(e instanceof Error?e.message:'操作失败，请重试');}finally{guard.current=false;setBusy(false);}}
  async function post(path:string,payload:unknown){const response=await apiFetch(`/api/workbench/batches/${batchId}/${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const value=await response.json();if(!response.ok)throw Error(value.detail||'操作失败');return value;}
  const sync=()=>perform(async()=>{await post('separation',{enabled:true});setNotice('取分离目录已同步，已填金额保留。请确认剩余站点关联。');setReload(v=>v+1);setLinksOpen(true);});
  const disabled=busy||loading;
  const cityInvalid=data?cities.filter(c=>{const issue=deductionIssues(c,data.columns);return c.edited&&(issue.fields.length||issue.zero);}):[];
  const baseAction=data?nextReviewAction(data,entries,accepted,platform):{kind:'reload',label:'重试读取本次城市',hint:'本次城市资料尚未就绪，已填金额保留。'};
  const action=baseAction.kind!=='separation'&&linkSelection.selected>0&&linkSelection.selected===linkSelection.ready?{kind:'saveLinks',label:`确认所选关联（${linkSelection.ready}）`,hint:`已勾选 ${linkSelection.ready} 个站点，请核对后台归属后确认。`}:linkEdits&&baseAction.kind==='execute'?{kind:'links',label:'确认站点关联修改',hint:'站点归属有未保存修改，请先确认或撤销。'}:cityInvalid.length&&['execute','amounts'].includes(baseAction.kind)?{kind:'amounts',label:'完善城市默认金额',hint:'城市金额尚未完整，请补齐空白项或明确确认零扣款。'}:baseAction;
  function focus(ref:React.RefObject<HTMLElement|null>){requestAnimationFrame(()=>{ref.current?.scrollIntoView({block:'center',behavior:'smooth'});ref.current?.querySelector<HTMLElement>('select,input')?.focus({preventScroll:true});});}
  async function next(){
    if(disabled)return;
    if(action.kind==='saveLinks'){await linkSubmission.current?.submit();return;}
    if(action.kind==='reload'){setReload(v=>v+1);return;}
    if(action.kind==='separation'){await sync();return;}
    if(action.kind==='links'){setLinksOpen(true);setNotice(action.hint);focus(linksRef);return;}
    if(action.kind==='amounts'){setSitesOpen(true);setNotice(action.hint);focus(amountsRef);return;}
    if(action.kind==='differences'){setNotice(action.hint);focus(differencesRef);return;}
    if(!data)return;
    await perform(async()=>{const value=await post('deduction-review',{city_id:cityId,cities:cities.filter(c=>c.edited),review_version:data.review_version,entries,accepted_differences:accepted,confirmed:true,save_defaults:saveDefaults});onConfirmed(value,value.deduction_version);});
  }
  const invalid=data?entries.filter(e=>{const issue=deductionIssues(e,data.columns);return issue.fields.length||issue.zero;}):[];
  const unresolved=data?.unresolved||[],linkRows=data?associationRows(data):[];
  return <ReviewContainer inline={inline} onClose={onClose}>
    <div className="review-scope-summary">{plan&&<span>{plan.city} · {plan.start} 至 {plan.end} · {plan.applicants} 条申请</span>}</div>
    <div className={`review-readiness ${action.kind==='execute'?'is-ready':''}`} role="status"><strong>{loading?'正在读取本次城市资料，完成后自动继续':action.kind==='execute'?'本次核算已就绪':action.hint}</strong><span>{data?`${entries.length} 站 · ${invalid.length} 站金额待确认 · ${unresolved.length} 站待关联 · ${(data.differences||[]).filter(d=>!accepted.includes(d.id)).length} 项归属待核对`:'站点数量待核实，申请信息已保留'}</span></div>
    <details className="review-advanced"><summary>高级选项：城市映射与目录</summary><div className="review-tools"><label>后台城市<select className="wb-select" aria-label="本次扣款后台城市" value={cityId} disabled={disabled} onChange={e=>setCityId(e.target.value)}><option value="">按申请城市匹配</option>{directory.data?.cities.map(c=><option key={c.id} value={c.id}>{c.name} · {stationCountText(directory.data,c.id)}</option>)}</select></label><button className="wb-button" disabled={disabled} onClick={()=>{setReload(v=>v+1);setNotice('正在更新清单，已填金额保留。');}}>更新清单，保留已填金额</button></div></details>
    {error&&<p role="alert" className="wb-error">{error} {onOpenConnections&&<button className="wb-link" onClick={onOpenConnections}>检查平台登录</button>}</p>}
    {notice&&<p className="wb-notice" role="status">{notice}</p>}
    {loading&&!data&&<p role="status">正在读取申请名单与后台目录…</p>}
    {data&&<>
      {!!data.separation_stations?.length&&<div className="wb-notice"><strong>申请含 {data.separation_stations.length} 个取分离站点{data.separation_enabled?' · 已启用资料关联':''}</strong><p>同步后仍未匹配的名称，可在下方确认后台归属。</p><button className="wb-button" disabled={disabled} onClick={()=>void sync()}>{data.separation_enabled?'重新同步取分离站点':'启用取分离资料关联并同步站点'}</button></div>}
      {!!linkRows.length&&<section ref={linksRef} className="review-associations"><header className="wb-row wb-space"><h3>站点关联 <span className="association-heading-count">{unresolved.length?`${unresolved.length} 个待确认`:'已全部匹配'}</span></h3><button className="wb-link" onClick={()=>setLinksOpen(v=>!v)}>{linksOpen?'收起':'展开核对'}</button></header>
        <div hidden={!linksOpen}><StationAssociations data={data} disabled={disabled} onPendingChange={setLinkEdits} onSubmissionChange={updateLinkSubmission} onSync={()=>{if(platform==='fengshen'&&data.separation_stations?.length)void sync();else{forceDirectory.current=true;setReload(v=>v+1);}}} onConfirm={(links,save)=>perform(async()=>{install(await post('station-links',{links,save_associations:save,review_version:data.review_version,city_id:cityId,confirmed:true}));setNotice('所选站点关联已确认，已填金额保留。');})}/></div>
      </section>}
      <section ref={amountsRef}>
        {!!cities.length&&<section className="city-deduction-default"><h3>城市统一金额</h3><p className="wb-muted">填写完整后自动用于沿用城市规则的站点，保留站点例外及已编辑金额。</p><CityDeductionAmounts entries={cities} columns={data.columns} disabled={disabled} onChange={values=>{setCities(values);setEntries(previous=>applyCityAmounts(previous,values,data.columns));}}/><p className="wb-muted">{entries.filter(e=>e.inherited_city).length} 站沿用城市金额 · {entries.filter(e=>e.station_override||(e.configured&&!e.inherited_city)||e.edited).length} 站保留独立金额</p></section>}
        {!!invalid.length&&<div className="review-missing"><strong>还有 {invalid.length} 站需要完善金额</strong><ul>{invalid.map(entry=>{const issue=deductionIssues(entry,data.columns);return <li key={entry.key}>{entry.station.name}：{issue.zero?'请明确确认本站零扣款':`待填写 ${issue.fields.join('、')}`}</li>;})}</ul></div>}
        <details className="station-exceptions" open={sitesOpen||(!cities.length&&invalid.length>0)} onToggle={e=>setSitesOpen(e.currentTarget.open)}><summary>站点金额与例外（{entries.length} 站）</summary><DeductionAmounts entries={entries} columns={data.columns} disabled={disabled} onChange={setEntries}/></details>
      </section>
      {!!data.differences?.length&&<section ref={differencesRef} className="wb-deduction-differences"><h3>申请名单与账单归属核对</h3><p className="wb-muted">请逐项核实；需要纠正来源时先修改申请表或来源资料，系统不会自动改写团队。</p>{data.differences.map(item=><label key={item.id}><input type="checkbox" disabled={disabled} checked={accepted.includes(item.id)} onChange={e=>setAccepted(previous=>e.target.checked?[...previous,item.id]:previous.filter(id=>id!==item.id))}/>申请第{item.row}行：{item.application} → 账单 {item.bill.join('、')||'未匹配'}。{item.reason}，已人工核实。</label>)}</section>}
      {data.warnings?.map((w,index)=><p className="wb-notice" key={index}>{w}</p>)}
      <label className="wb-zero-confirm"><input type="checkbox" disabled={disabled} checked={saveDefaults} onChange={e=>setSaveDefaults(e.target.checked)}/>保存城市及站点金额，供后续核算沿用</label>
    </>}
    <footer className="review-next-bar"><div><strong>{action.kind==='execute'?'金额及归属已就绪':action.hint}</strong><small>{action.kind==='execute'?'点击确认即表示已核对本次扣款，系统将自动执行。':'点击右侧按钮处理下一步；已填金额会保留。'}</small></div><div className="wb-row"><button className="wb-button" disabled={busy} onClick={onClose}>返回</button><button className="wb-primary" disabled={disabled} onClick={()=>void next()}>{busy?'处理中…':loading?'读取中…':action.label}</button></div></footer>
  </ReviewContainer>;
}
