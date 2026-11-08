import { TaskOutcome } from './TaskOutcome';
import React,{useEffect,useRef,useState} from 'react';
import {LanorangePriceFilters} from './LanorangePriceFilters';
import {WorkbenchDatePicker} from './WorkbenchDatePicker';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';
type Query={month:string;city:string;station:string;date_from:string;date_to:string};
type Export={id:string;request_id:string;status:string;created:number;message:string;completed:number;total:number;rows:number;query:Query;receipts:{city:string;station:string;period:string;version:string;status:string;row_count:number;result:string;message:string}[]};
type Attempt={request_id:string;query:Query};
const BASE='/api/fengshen-downloads/lanorange-prices';
const ACTIVE=new Set(['queued','running','stopping']);
const labels:Record<string,string>={queued:'等待采集',running:'正在导出',stopping:'正在停止',completed:'已完成',partial:'部分完成',failed:'导出失败',interrupted:'执行曾中断',cancelled:'已停止'};
const defaultQuery=():Query=>({month:'',city:'',station:'',date_from:'',date_to:''});
export function LanorangePriceExports({apiFetch,workspaceId,onActiveCount,onSwitchView,focusId}:{apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;workspaceId:string;onActiveCount:(count:number)=>void;onSwitchView?:(view:'approval'|'price-export')=>void;focusId?:string}){
  const [query,setQuery]=useState<Query>(defaultQuery),[history,setHistory]=useState<Export[]>([]),[job,setJob]=useState<Export|null>(null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[attempt,setAttempt]=useState<Attempt|null>(null);
  const fetchRef=useRef(apiFetch),alive=useRef(true),inflight=useRef(false);fetchRef.current=apiFetch;
  const key='lanorange-price-export-attempt:'+workspaceId;
  const request=<T,>(route:string,body?:object)=>platformAuthRequest<T>(fetchRef.current,BASE+route,body,30000);
  useEffect(()=>{
    if(!focusId)return;
    let disposed=false;
    void request<Export>(`/exports/${encodeURIComponent(focusId)}`).then(value=>{if(!disposed){setJob(value);document.getElementById('price-record-result')?.scrollIntoView({block:'start'});}}).catch(err=>{if(!disposed)setError(err instanceof Error?err.message:'指定记录读取失败');});
    return()=>{disposed=true;};
  },[focusId,workspaceId]);
  function save(value:Attempt|null){setAttempt(value);try{if(value)sessionStorage.setItem(key,JSON.stringify(value));else sessionStorage.removeItem(key);}catch{}}
  async function refresh(){try{const result=await request<{exports:Export[]}>('/exports');if(!alive.current)return;setHistory(result.exports);setJob(old=>result.exports.find(j=>j.id===old?.id)||old||result.exports[0]||null);onActiveCount(result.exports.filter(j=>ACTIVE.has(j.status)).length);}catch(err){if(alive.current)setError(err instanceof Error?err.message:'读取导出记录失败');}}
  useEffect(()=>{alive.current=true;try{const old=JSON.parse(sessionStorage.getItem(key)||'null');if(old?.request_id&&old?.query){setAttempt(old);setQuery(old.query);}}catch{}void refresh();const timer=setInterval(()=>void refresh(),4000);return()=>{alive.current=false;clearInterval(timer);};},[workspaceId]);
  async function perform(kind:string,fn:()=>Promise<void>){if(inflight.current)return;inflight.current=true;setBusy(kind);setError('');try{await fn();}catch(err){if(alive.current)setError(err instanceof Error?err.message:'操作未完成');}finally{inflight.current=false;if(alive.current)setBusy('');}}
  async function start(event:React.FormEvent){event.preventDefault();await perform('start',async()=>{
    const current=attempt || {request_id:crypto.randomUUID(),query:{...query}};save(current);
    try{const value=await request<Export>('/exports',current);save(null);setJob(value);void refresh();}
    catch(err){if(err instanceof PlatformAuthError && err.uncertain)throw Error('本次导出提交尚未确认，请先查找本次导出；系统不会自动重发。');save(null);throw err;}
  });}
  async function find(){await perform('find',async()=>{const result=await request<{exports:Export[]}>('/exports');const found=result.exports.find(j=>j.request_id===attempt?.request_id);if(!found)throw Error('尚未找到本次提交，可使用原标识再次发起导出；不会创建重复任务。');setHistory(result.exports);setJob(found);save(null);});}
  async function download(){if(!job)return;await perform('download',async()=>{const response=await fetchRef.current(BASE+`/exports/${job.id}/result.xlsx`);if(!response.ok){const value=await response.json();throw Error(value.detail||'文件未就绪或校验失败');}const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`${job.query.month}_蓝橙待审每日价格${job.status==='partial'?'_部分':''}.xlsx`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});}
  const active=history.some(j=>ACTIVE.has(j.status));
  return <div className="wb-approvals">
    {onSwitchView && (
      <div className="pq-mode-bar">
        <div className="pq-mode-left">
          <div className="wb-segment pq-mode-tabs" role="tablist" aria-label="蓝橙价格管理功能">
            <button type="button" role="tab" aria-selected={false} onClick={() => onSwitchView('approval')}>批量审批</button>
            <button type="button" role="tab" aria-selected={true} className="is-active" onClick={() => onSwitchView('price-export')}>待审每日价格导出</button>
          </div>
          <span className="pq-mode-hint">读取蓝橙有权限站点，按“骑手 × 日期”纵向生成 Excel</span>
        </div>
      </div>
    )}
    <section className="wb-approval-card">
    <form onSubmit={start}>
      <div className="wb-approval-filters"><LanorangePriceFilters apiFetch={apiFetch} workspaceId={workspaceId} city={query.city} station={query.station} month={query.month} requiredMonth disabled={!!attempt || !!busy} onChange={value=>setQuery({...query,...value})}/></div>
      <details className="wb-price-date-filter"><summary>限定导出日期（可选）</summary><div className="wb-approval-filters"><div className="wb-approval-filter-item"><span>开始日期</span><WorkbenchDatePicker ariaLabel="限定导出开始日期" value={query.date_from} rangeRole="start" rangeStart={query.date_from} rangeEnd={query.date_to} allowClear disabled={!!attempt} onChange={v=>setQuery({...query,date_from:v})}/></div><div className="wb-approval-filter-item"><span>结束日期</span><WorkbenchDatePicker ariaLabel="限定导出结束日期" value={query.date_to} rangeRole="end" rangeStart={query.date_from} rangeEnd={query.date_to} allowClear disabled={!!attempt} onChange={v=>setQuery({...query,date_to:v})}/></div></div></details>
      <div className="wb-approval-toolbar"><span>状态：审批中、待审核；仅取最新版本。0保留，空价格留空。</span><button className="wb-primary" disabled={!!busy || active || (!attempt && !query.month)}>{busy==='start'?'正在创建导出…':attempt?'使用原标识再次发起':'开始导出'}</button></div>
    </form>
    {error && (
      <div className="wb-error wb-error-with-action" role="alert">
        <span>{error}</span>
        {error.includes('登录') && (
          <button type="button" className="wb-button wb-error-login-btn" onClick={() => window.dispatchEvent(new CustomEvent('workbench:connections'))}>
            立即登录蓝橙
          </button>
        )}
      </div>
    )}
    {attempt && <div className="wb-approval-notice">本次导出提交尚未确认，请先查找已有任务。<button className="wb-button" disabled={!!busy} onClick={()=>void find()}>查找本次导出</button></div>}
  </section>
  {(history.length > 0 || !!job) && <section className="wb-approval-card" id="price-record-result"><div className="wb-approval-heading"><h2>导出结果</h2><button className="wb-button" disabled={!!busy} onClick={()=>void refresh()}>刷新导出记录</button></div>
    {!job?<p className="wb-muted">暂无导出任务。</p>:<><TaskOutcome task={{status:job.status,kind:'price-export',availableFiles:['completed','partial'].includes(job.status)?1:0}}/><label className="wb-approval-history">查看导出<select className="wb-select" value={job.id} onChange={e=>setJob(history.find(j=>j.id===e.target.value)||null)}>{job&&!history.some(j=>j.id===job.id)&&<option value={job.id}>{job.query.month} · 当前任务</option>}{history.map(j=><option key={j.id} value={j.id}>{j.query.month} · {new Date(j.created*1000).toLocaleString('zh-CN')} · {labels[j.status]||j.status}</option>)}</select></label>
      <div className="wb-approval-toolbar"><div><p>{job.message}</p><p className="wb-muted">已处理{job.completed}/{job.total}个站点周期 · 已生成{job.rows}行</p></div><div className="wb-row">{ACTIVE.has(job.status)&&<button className="wb-button" disabled={!!busy || job.status==='stopping'} onClick={()=>void perform('stop',async()=>{setJob(await request<Export>(`/exports/${job.id}/stop`,{}));})}>停止后续采集</button>}{['completed','partial'].includes(job.status)&&<button className="wb-primary" disabled={!!busy} onClick={()=>void download()}>下载 Excel</button>}</div></div>
      {job.status==='partial' && <p className="wb-error">部分站点未导出，请按下方失败原因单独筛选处理；当前文件含已成功读取的数据和完整采集记录。</p>}
      <details className="wb-receipts" key={job.id} open={['partial','failed','interrupted'].includes(job.status)}><summary>采集明细与版本（{job.receipts.length} 条）</summary><div className="wb-approval-table"><table><thead><tr><th>城市 / 站点</th><th>结算周期</th><th>最新版本</th><th>状态</th><th>行数</th><th>结果 / 原因</th></tr></thead><tbody>{job.receipts.map((r,index)=><tr key={index}><td>{r.city}<small>{r.station}</small></td><td>{r.period}</td><td>{r.version || '—'}</td><td>{r.status || '—'}</td><td>{r.row_count}</td><td className={r.result==='失败'?'wb-error':''}>{r.result}<small>{r.message}</small></td></tr>)}</tbody></table></div></details>
    </>}
  </section>}</div>;
}
