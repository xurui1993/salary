import { TaskOutcome } from './TaskOutcome';
import React,{useEffect,useRef,useState} from 'react';
import {ApprovalScopeFilters} from './ApprovalScopeFilters';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';

type Fetcher=(url:string,init?:RequestInit)=>Promise<Response>;
type Query={city:string;station:string;period:string};
type Task={id:string;business_id:string;businessCode?:string;businessTitle?:string;cityName?:string;siteName?:string;nodeName?:string;createByName?:string;createTime?:string;period_start?:string;period_end?:string;rider_count?:number;settle_month?:string;revision:string;reason:string};
type Price={columns:{key:string;label:string}[];rows:Record<string,unknown>[];remark:string;version?:number;version_change?:string};
type Preview={id:string;actor_label:string;expires_at:number;eligible_count:number;opinion:string;filters:Query;items:{eligible:boolean;reason:string;task:Task;price?:Price}[]};
type Batch={id:string;actor_label:string;status:string;created:number;counts:Record<string,number>;items:{task:Task;status:string;status_label:string;message:string}[]};
type Attempt={preview_id:string;request_id:string};
const BASE='/api/fengshen-downloads/lanorange-approvals',EMPTY:Query={city:'',station:'',period:''};
const ACTIVE=new Set(['queued','running','stopping']);
const batchLabels:Record<string,string>={queued:'等待执行',running:'正在审批',stopping:'正在停止后续',completed:'本批已完成',partial:'部分完成',needs_review:'有结果待核实',interrupted:'执行曾中断'};
const code=(task:Task)=>task.businessCode || task.id;
const period=(task:Task)=>task.period_start?`${task.period_start.slice(0,10)} 至 ${task.period_end?.slice(0,10) || '—'}`:'—';
const message=(error:unknown)=>error instanceof Error?error.message:'操作未完成，请稍后重试';
function remember(key:string,value:Attempt|null){try{if(value)sessionStorage.setItem(key,JSON.stringify(value));else sessionStorage.removeItem(key);}catch{/* A small recovery hint must never break the workbench. */}}

function PriceTable({price}:{price:Price}){
  const [page,setPage]=useState(1),limit=50;const pages=Math.max(1,Math.ceil(price.rows.length/limit));
  return <><p className="wb-muted">{price.rows.length}名骑手 · 版本{price.version ?? '—'}{price.version_change?` · ${price.version_change}`:''}</p>{price.remark && <p>备注：{price.remark}</p>}
    <div className="wb-approval-table"><table><thead><tr>{price.columns.map(c=><th key={c.key}>{c.label}</th>)}</tr></thead><tbody>{price.rows.slice((page-1)*limit,page*limit).map((row,index)=><tr key={index}>{price.columns.map(c=><td key={c.key}>{row[c.key]===null || row[c.key]===undefined?'—':String(row[c.key])}</td>)}</tr>)}</tbody></table></div>
    <div className="wb-approval-pagination"><span>明细第{page}/{pages}页</span><button className="wb-button" disabled={page===1} onClick={()=>setPage(p=>p-1)}>上一页明细</button><button className="wb-button" disabled={page>=pages} onClick={()=>setPage(p=>p+1)}>下一页明细</button></div></>;
}

export function LanorangeApprovals({apiFetch,workspaceId,onActiveCount,onSwitchView,focusId}:{apiFetch:Fetcher;workspaceId:string;onActiveCount:(count:number)=>void;onSwitchView?:(view:'approval'|'price-export')=>void;focusId?:string}){
  const fetchRef=useRef(apiFetch);fetchRef.current=apiFetch;
  const query=EMPTY;
  const [page,setPage]=useState(1),[refresh,setRefresh]=useState(0);
  const [allRows,setAllRows]=useState<Task[]>([]);
  const [scopeCities,setScopeCities]=useState<string[]>([]),[scopeMonths,setScopeMonths]=useState<string[]>([]),[scopeSite,setScopeSite]=useState('');
  const filtered=allRows.filter(r=>(!scopeCities.length||scopeCities.includes(r.cityName||''))&&(!scopeMonths.length||scopeMonths.includes((r.settle_month||r.period_start||'').slice(0,7)))&&(!scopeSite||JSON.stringify([r.cityName,r.siteName])===scopeSite));
  const rows=filtered.slice((page-1)*20,page*20);
  const [actor,setActor]=useState(''),[sessionVersion,setSessionVersion]=useState('');
  const [selection,setSelection]=useState<Record<string,Task>>({}),[listBusy,setListBusy]=useState(false),[command,setCommand]=useState(''),[error,setError]=useState('');
  const [preview,setPreview]=useState<Preview|null>(null),[detail,setDetail]=useState<{task:Task;price:Price}|null>(null);
  const [history,setHistory]=useState<Batch[]>([]),[batch,setBatch]=useState<Batch|null>(null),[attempt,setAttempt]=useState<Attempt|null>(null);
  const [attemptMissing,setAttemptMissing]=useState(false);
  const listSequence=useRef(0),inflight=useRef(false),versionRef=useRef(''),batchRef=useRef<Batch|null>(null),alive=useRef(true);
  batchRef.current=batch;
  const attemptKey=`lanorange-approval-attempt:${workspaceId}`;
  const request=<T,>(path:string,body?:object,timeout=60000)=>platformAuthRequest<T>(fetchRef.current,BASE+path,body,timeout);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;listSequence.current++;};},[]);
  useEffect(()=>{
    try{const value=JSON.parse(sessionStorage.getItem(attemptKey)||'null');if(value && typeof value.preview_id==='string' && typeof value.request_id==='string')setAttempt(value);}catch{}
  },[attemptKey]);
  useEffect(()=>{
    if(!focusId)return;
    let disposed=false;
    void request<Batch>(`/batches/${encodeURIComponent(focusId)}`).then(value=>{if(!disposed){setBatch(value);document.getElementById('price-record-result')?.scrollIntoView({block:'start'});}}).catch(err=>{if(!disposed)setError(err instanceof Error?err.message:'指定记录读取失败');});
    return()=>{disposed=true;};
  },[focusId,workspaceId]);
  async function readHistory(){
    try{
      const value=await request<{batches:Batch[]}>('/batches');if(!alive.current)return;
      setHistory(value.batches);onActiveCount(value.batches.filter(b=>ACTIVE.has(b.status)).length);
      setBatch(current=>value.batches.find(b=>b.id===current?.id) || current || value.batches[0] || null);
    }catch(err){if(alive.current)setError(message(err));}
  }
  useEffect(()=>{void readHistory();const timer=setInterval(()=>void readHistory(),4000);return()=>{clearInterval(timer);};},[workspaceId]);
  useEffect(()=>{
    const sequence=++listSequence.current;setListBusy(true);setError('');
    void request<{rows:Task[];total:number;actor_label:string;session_version:string}>('/pending-scope').then(value=>{
      if(!alive.current || sequence!==listSequence.current)return;
      if(versionRef.current && versionRef.current!==value.session_version){setSelection({});setPreview(null);setError('蓝橙会话已变化，已清除旧勾选，请重新选择。');}
      versionRef.current=value.session_version;setSessionVersion(value.session_version);setAllRows(value.rows);setSelection({});setPreview(null);setActor(value.actor_label);
    }).catch(err=>{if(alive.current && sequence===listSequence.current){setError(message(err));setAllRows([]);}}).finally(()=>{if(alive.current && sequence===listSequence.current)setListBusy(false);});
  },[refresh,workspaceId]);
  async function perform(kind:string,action:()=>Promise<void>){
    if(inflight.current)return;inflight.current=true;setCommand(kind);setError('');
    try{await action();}catch(err){if(alive.current)setError(message(err));}finally{inflight.current=false;if(alive.current)setCommand('');}
  }
  const selected=Object.values(selection),pages=Math.max(1,Math.ceil(filtered.length/20)),active=history.some(b=>ACTIVE.has(b.status));
  function choose(tasks:Task[],checked:boolean){
    const next={...selection};for(const task of tasks){if(task.reason)continue;if(checked)next[task.id]=task;else delete next[task.id];}
    if(Object.keys(next).length>200){setError('每批最多选择200条，请分批处理。');return;}setSelection(next);
  }
  async function showDetail(task:Task){await perform('detail',async()=>setDetail(await request<{task:Task;price:Price}>(`/pending/${encodeURIComponent(task.id)}?session_version=${encodeURIComponent(sessionVersion)}`)));}
  async function makePreview(){await perform('preview',async()=>{
    const value=await request<Preview>('/previews',{selected:selected.map(t=>({id:t.id,revision:t.revision})),filters:query,session_version:sessionVersion},180000);
    if(alive.current)setPreview(value);
  });}
  async function sendAttempt(current:Attempt){await perform('submit',async()=>{
    setAttempt(current);setAttemptMissing(false);remember(attemptKey,current);
    try{
      const result=await request<Batch>('/batches',{...current,confirm:true},20000);
      if(alive.current){setBatch(result);setPreview(null);setSelection({});setAttempt(null);remember(attemptKey,null);setRefresh(x=>x+1);void readHistory();}
    }catch(err){if(!(err instanceof PlatformAuthError && err.uncertain)){setAttempt(null);remember(attemptKey,null);}else throw new Error('本次审批批次尚未确认，请先查找本次提交；系统不会自动重复审批。');throw err;}
  });}
  async function submit(){if(preview)await sendAttempt(attempt?.preview_id===preview.id?attempt:{preview_id:preview.id,request_id:crypto.randomUUID()});}
  async function findAttempt(){if(!attempt)return;await perform('find',async()=>{
    try{const result=await request<Batch>('/batches/by-request/'+encodeURIComponent(attempt.request_id));setBatch(result);setPreview(null);setSelection({});setAttempt(null);setAttemptMissing(false);remember(attemptKey,null);void readHistory();}
    catch(err){if(err instanceof PlatformAuthError && err.status===404){setAttemptMissing(true);throw new Error('尚未找到本次批次。可用原提交标识重试，已存在的批次会直接返回。');}throw err;}
  });}
  async function downloadResult(){if(!batch)return;await perform('export',async()=>{
    const response=await fetchRef.current(`${BASE}/batches/${batch.id}/result.csv`);if(!response.ok)throw new Error('结果下载失败，请稍后重试');
    const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`蓝橙价格审批结果_${batch.id.slice(0,8)}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });}
  return <div className="wb-approvals">
    <section className="wb-approval-card">
      <div className="wb-approval-heading">
        <div className="wb-stage-heading-left">
          <div className="wb-stage-title-row">
            <h2>蓝橙价格审批</h2>
            {onSwitchView && (
              <nav className="wb-module-tabs wb-stage-tabs" aria-label="蓝橙价格管理功能">
                <button type="button" aria-pressed={true} className="wb-button" onClick={() => onSwitchView('approval')}>批量审批</button>
                <button type="button" aria-pressed={false} className="wb-button" onClick={() => onSwitchView('price-export')}>待审每日价格导出</button>
              </nav>
            )}
          </div>
          <p className="wb-muted">筛选并勾选本人待办，预览后统一同意当前节点。单价由你判断。</p>
        </div>
      </div>
      <ApprovalScopeFilters rows={allRows} cities={scopeCities} months={scopeMonths} site={scopeSite} busy={listBusy||!!command} onChange={(cities,months,site)=>{setScopeCities(cities);setScopeMonths(months);setScopeSite(site);setPage(1);setSelection({});setPreview(null);}} onRefresh={()=>{setPage(1);setRefresh(v=>v+1);}}/>
      {error && <p className="wb-error" role="alert">{error}</p>}
      {attempt && <div className="wb-approval-notice" role="status"><p>本次提交尚待确认。请先查找批次，避免重复审批。</p><button className="wb-button" disabled={!!command} onClick={()=>void findAttempt()}>查找本次提交</button>{attemptMissing && <button className="wb-button" disabled={!!command} onClick={()=>void sendAttempt(attempt)}>用原标识重试提交</button>}</div>}
      <div className="wb-approval-toolbar"><span>{actor?`蓝橙账号：${actor} · `:''}当前范围 {filtered.length} 条 / 本人待办 {allRows.length} 条 · 已选{selected.length}条（跨页保留）</span><div className="wb-row"><button className="wb-button" disabled={listBusy||!!command||!filtered.length||filtered.length>200} onClick={()=>choose(filtered,true)}>勾选当前范围全部 {filtered.length} 条</button><button className="wb-button" disabled={!selected.length || !!command} onClick={()=>setSelection({})}>清空勾选</button><button className="wb-primary" disabled={!selected.length || !!command || active || !!attempt || listBusy} onClick={()=>void makePreview()}>{command==='preview'?'正在核对明细…':`预览已选${selected.length}条`}</button></div></div>
      {filtered.length>200&&<p className="wb-muted">每批最多审批200条，请缩小城市、月份或站点范围，或按页勾选。</p>}
      {active && <p className="wb-muted">已有批次执行中，可在下方查看进度；离开此页仍会继续。</p>}
      <div className="wb-approval-table" aria-busy={listBusy}><table><thead><tr><th><input type="checkbox" aria-label="选择本页可审批流程" disabled={listBusy || !rows.some(r=>!r.reason)} checked={rows.some(r=>!r.reason) && rows.filter(r=>!r.reason).every(r=>!!selection[r.id])} onChange={e=>choose(rows,e.target.checked)}/></th><th>业务编号</th><th>城市 / 站点</th><th>结算周期</th><th>人数</th><th>申请人 / 时间</th><th>当前节点</th><th>操作</th></tr></thead><tbody>{rows.map(task=><tr key={task.id}><td><input type="checkbox" aria-label={`选择流程${code(task)}`} checked={!!selection[task.id]} disabled={!!task.reason || listBusy} onChange={e=>choose([task],e.target.checked)}/></td><td>{code(task)}{task.reason && <small className="wb-error">{task.reason}</small>}</td><td>{task.cityName || '—'}<small>{task.siteName || '—'}</small></td><td>{period(task)}</td><td>{task.rider_count ?? '—'}</td><td>{task.createByName || '—'}<small>{task.createTime || '—'}</small></td><td>{task.nodeName || '—'}</td><td><button className="wb-button" disabled={!!command || !!task.reason} onClick={()=>void showDetail(task)}>查看明细</button></td></tr>)}</tbody></table></div>
      {!rows.length && <p className="wb-muted" role="status">{listBusy?'正在读取蓝橙本人待办…':'当前筛选范围没有可显示的骑手价格提审。'}</p>}
      <div className="wb-approval-pagination"><span>第{page}/{pages}页 · 每页20条</span><button className="wb-button" disabled={page<=1 || listBusy} onClick={()=>setPage(p=>p-1)}>上一页</button><button className="wb-button" disabled={page>=pages || listBusy} onClick={()=>setPage(p=>p+1)}>下一页</button></div>
    </section>
    <section className="wb-approval-card" id="price-record-result"><div className="wb-approval-heading"><h2>审批结果</h2><button className="wb-button" disabled={!!command} onClick={()=>void readHistory()}>刷新结果</button></div>
      {history.length>0 && <label className="wb-approval-history">查看批次<select className="wb-select" value={batch?.id || ''} onChange={e=>setBatch(history.find(b=>b.id===e.target.value) || null)}>{batch&&!history.some(b=>b.id===batch.id)&&<option value={batch.id}>当前任务 · {batchLabels[batch.status]||batch.status}</option>}{history.map(b=><option value={b.id} key={b.id}>{new Date(b.created*1000).toLocaleString('zh-CN')} · {batchLabels[b.status] || b.status} · {b.items.length}条</option>)}</select></label>}
      {!batch?<p className="wb-muted">暂无审批批次。</p>:<><TaskOutcome task={{status:batch.status,kind:'approval',availableFiles:1}}/><div className="wb-approval-toolbar"><div><p className="wb-muted">已同意{batch.counts.success || 0} · 被拒绝{batch.counts.failed || 0} · 变化{batch.counts.changed || 0} · 待核实{batch.counts.uncertain || 0} · 未提交{batch.counts.not_sent || 0} · 等待{batch.counts.pending || 0}</p></div><div className="wb-row">
        {ACTIVE.has(batch.status) && <button className="wb-button" disabled={!!command || batch.status==='stopping'} onClick={()=>void perform('stop',async()=>{setBatch(await request<Batch>(`/batches/${batch.id}/stop`,{confirm:true}));void readHistory();})}>停止后续审批</button>}
        {!!batch.counts.uncertain && !ACTIVE.has(batch.status) && <button className="wb-button" disabled={!!command} onClick={()=>void perform('recheck',async()=>{setBatch(await request<Batch>(`/batches/${batch.id}/recheck`,{},120000));void readHistory();setRefresh(x=>x+1);})}>核实待确认结果</button>}
        <button className="wb-button" disabled={!!command} onClick={()=>void downloadResult()}>下载结果</button></div></div>
        {batch.status==='stopping' && <p className="wb-muted">当前已发出的官方请求会先核实结果，后续条目不再提交。</p>}
        <details className="wb-receipts" key={batch.id} open={batch.status!=='completed'}><summary>逐项审批结果（{batch.items.length} 条）</summary><div className="wb-approval-table"><table><thead><tr><th>业务编号</th><th>城市 / 站点</th><th>结果</th><th>说明</th></tr></thead><tbody>{batch.items.map((item,index)=><tr key={index}><td>{code(item.task)}</td><td>{item.task.cityName || '—'} / {item.task.siteName || '—'}</td><td className={item.status==='success'?'wb-success':item.status==='uncertain'?'wb-error':''}>{item.status_label}</td><td>{item.message}</td></tr>)}</tbody></table></div></details></>}
    </section>
    {preview && <WorkbenchDrawer title="审批预览" wide onClose={()=>{if(!command)setPreview(null);}}>
      <div className="wb-approval-preview"><p><strong>蓝橙账号：{preview.actor_label}</strong></p><p>本批可提交{preview.eligible_count}条，需另行处理{preview.items.length-preview.eligible_count}条；审批意见统一为“同意”。</p><p className="wb-muted">仅同意本人当前节点，不更改单价。沿用官方默认抄送及站内通知；预览有效至{new Date(preview.expires_at*1000).toLocaleTimeString('zh-CN')}。</p>
      {error && <p className="wb-error" role="alert">{error}</p>}
      <div className="wb-approval-table"><table><thead><tr><th>业务编号</th><th>城市 / 站点</th><th>结算周期</th><th>人数</th><th>本批处理</th><th>明细</th></tr></thead><tbody>{preview.items.map(item=><tr key={item.task.id}><td>{code(item.task)}</td><td>{item.task.cityName} / {item.task.siteName}</td><td>{period(item.task)}</td><td>{item.task.rider_count ?? '—'}</td><td>{item.eligible?'同意当前节点':item.reason}</td><td>{item.price && <button className="wb-button" onClick={()=>setDetail({task:item.task,price:item.price!})}>价格明细</button>}</td></tr>)}</tbody></table></div>
      <div className="wb-approval-preview-actions"><button className="wb-button" disabled={!!command} onClick={()=>setPreview(null)}>返回调整</button><button className="wb-primary" disabled={!preview.eligible_count || !!command || active || !!attempt} onClick={()=>void submit()}>{command==='submit'?'正在创建批次…':`同意并提交${preview.eligible_count}条`}</button></div>
      {attempt && <button className="wb-button" disabled={!!command} onClick={()=>void findAttempt()}>查找本次提交</button>}</div>
    </WorkbenchDrawer>}
    {detail && <WorkbenchDrawer title="价格明细" wide onClose={()=>setDetail(null)}><h3>{code(detail.task)} · {detail.task.cityName} / {detail.task.siteName}</h3><p>{period(detail.task)}</p><PriceTable key={detail.task.id} price={detail.price}/></WorkbenchDrawer>}
  </div>;
}
