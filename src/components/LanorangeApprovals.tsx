import { TaskOutcome } from './TaskOutcome';
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {toneClass, normalizeTone} from '../lib/statusSemantics';
import {RefreshCw, ArrowRightLeft, KeyRound, Search, CheckCircle2, ClipboardList, Download, RotateCcw} from 'lucide-react';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';
import {filterApprovalTasks,type ApprovalEligibilityFilter} from '../lib/workbenchFilters';
import {
  buildDemoApprovalHistory,
  buildDemoApprovalPriceDetail,
  buildDemoLanorangeApprovals,
  type DemoApprovalTask,
} from '../lib/showcaseDemoData';

const RECEIPT_LABELS: Record<string, string> = {
  success: '已同意',
  failed: '被拒绝',
  uncertain: '待核实',
  changed: '状态已变',
  not_sent: '未提交',
  pending: '等待中',
};

function toApprovalTask(row: DemoApprovalTask): Task {
  return {
    id: row.id,
    business_id: row.id,
    businessCode: row.businessCode,
    businessTitle: `${row.cityName} ${row.siteName} 薪资单价审批`,
    cityName: row.cityName,
    siteName: row.siteName,
    nodeName: row.nodeName,
    createByName: row.createByName,
    createTime: row.createTime,
    period_start: row.period_start,
    period_end: row.period_end,
    rider_count: row.rider_count,
    settle_month: row.settle_month,
    revision: 'demo-rev-1',
    reason: row.reason,
  };
}

function toApprovalPrice(task: Task): Price {
  const detail = buildDemoApprovalPriceDetail({
    id: task.id,
    businessCode: task.businessCode || task.id,
    cityName: task.cityName || '',
    siteName: task.siteName || '',
    period_start: task.period_start || '2026-10-01',
    period_end: task.period_end || '2026-10-31',
    settle_month: task.settle_month || '2026-10',
    rider_count: task.rider_count || 0,
    nodeName: task.nodeName || '',
    createByName: task.createByName || '',
    createTime: task.createTime || '',
    reason: task.reason || '',
  });
  return {
    columns: [
      { key: 'rider_name', label: '骑手姓名' },
      { key: 'rider_id', label: '骑手ID' },
      { key: 'date', label: '日期' },
      { key: 'base_price', label: '基础单价(元)' },
      { key: 'subsidy', label: '补贴(元)' },
      { key: 'total_price', label: '合计单价(元)' },
      { key: 'status', label: '状态' },
    ],
    rows: detail.rows,
    remark: task.reason ? `阻断原因：${task.reason}` : '系统自动校验通过，单价明细完整无缺失日期',
    version: 3,
  };
}

function toDemoBatches(): Batch[] {
  return buildDemoApprovalHistory().map(b => ({
    id: b.id,
    actor_label: '演示审批账号（区域经理）',
    status: b.status,
    created: Math.floor(Date.parse(b.created_at) / 1000),
    counts: b.summary,
    items: b.items.map(it => ({
      task: {
        id: it.id,
        business_id: it.id,
        businessCode: it.businessCode,
        cityName: it.cityName,
        siteName: it.siteName,
        settle_month: it.settle_month,
        period_start: `${it.settle_month}-01`,
        period_end: `${it.settle_month}-31`,
        revision: 'demo-rev-1',
        reason: '',
      },
      status: it.status,
      status_label: RECEIPT_LABELS[it.status] || it.status,
      message: it.message,
    })),
  }));
}

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
  const moneyKeys=new Set(['base_price','subsidy','total_price']);
  const monoKeys=new Set(['rider_id','date']);
  return <div className="wbx-ap-price-wrap">
    {price.remark && (
      <div className="wbx-ap-detail__remark" role="note">
        <span className="wbx-ap-detail__remark-label">系统校验说明</span>
        <span className="wbx-ap-detail__remark-text">{price.remark}</span>
      </div>
    )}
    <div className="wbx-table-scroll wbx-ap-detail__scroll">
      <table className="wbx-table wbx-ap-detail__table">
        <thead>
          <tr>
            {price.columns.map(c=>(
              <th key={c.key} className={moneyKeys.has(c.key)?'is-num':c.key==='status'?'is-status':''}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {price.rows.slice((page-1)*limit,page*limit).map((row,index)=>(
            <tr key={index}>
              {price.columns.map(c=>{
                const raw=row[c.key];
                if(raw===null || raw===undefined)return <td key={c.key} className={moneyKeys.has(c.key)?'is-num tabular-nums':''}>—</td>;
                const str=String(raw);
                if(moneyKeys.has(c.key)){
                  const num=Number(raw);
                  return <td key={c.key} className="is-num tabular-nums">{Number.isFinite(num)?`¥ ${num.toFixed(2)}`:str}</td>;
                }
                if(c.key==='status'){
                  const ok=/正常|通过|完整|已核/.test(str);
                  return <td key={c.key} className="is-status"><span className={`wbx-ap-row-status ${ok?'is-ok':'is-warn'}`}><i aria-hidden="true" />{str}</span></td>;
                }
                if(c.key==='rider_name'){
                  return <td key={c.key} className="is-name">{str}</td>;
                }
                return <td key={c.key} className={monoKeys.has(c.key)?'tabular-nums is-muted':''}>{str}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <div className="wbx-ap-detail__pagination tabular-nums">
      <span>第 {page} / {pages} 页 · 共 {price.rows.length} 名骑手</span>
      <div className="wbx-approvals__page-btns">
        <button type="button" className="wbx-btn wbx-btn--sm" disabled={page===1} onClick={()=>setPage(p=>p-1)}>上一页明细</button>
        <button type="button" className="wbx-btn wbx-btn--sm" disabled={page>=pages} onClick={()=>setPage(p=>p+1)}>下一页明细</button>
      </div>
    </div>
  </div>;
}

export function LanorangeApprovals({apiFetch,workspaceId,onActiveCount,onSwitchView,focusId}:{apiFetch:Fetcher;workspaceId:string;onActiveCount:(count:number)=>void;onSwitchView?:(view:'approval'|'price-export')=>void;focusId?:string}){
  const fetchRef=useRef(apiFetch);fetchRef.current=apiFetch;
  const query=EMPTY;
  const [page,setPage]=useState(1),[refresh,setRefresh]=useState(0);
  const [allRows,setAllRows]=useState<Task[]>([]);
  const [scopeCities,setScopeCities]=useState<string[]>([]),[scopeMonths,setScopeMonths]=useState<string[]>([]),[scopeSite,setScopeSite]=useState('');
  const [eligibilityFilter,setEligibilityFilter]=useState<ApprovalEligibilityFilter>('all');
  const [keyword,setKeyword]=useState('');
  const [actor,setActor]=useState(''),[sessionVersion,setSessionVersion]=useState('');
  const [selection,setSelection]=useState<Record<string,Task>>({}),[listBusy,setListBusy]=useState(false),[command,setCommand]=useState(''),[error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [preview,setPreview]=useState<Preview|null>(null),[detail,setDetail]=useState<{task:Task;price:Price}|null>(null);
  const [history,setHistory]=useState<Batch[]>([]),[batch,setBatch]=useState<Batch|null>(null),[attempt,setAttempt]=useState<Attempt|null>(null);
  const [attemptMissing,setAttemptMissing]=useState(false);
  const [activeViewTab,setActiveViewTab]=useState<'pending'|'results'>('pending');
  const [receiptStatusFilter,setReceiptStatusFilter]=useState<'all'|'success'|'issue'|'failed'|'uncertain'|'changed'|'not_sent'|'pending'>('all');
  const [demoEnabled,setDemoEnabled]=useState(true);
  const [demoRows,setDemoRows]=useState<Task[]>(()=>buildDemoLanorangeApprovals().map(toApprovalTask));
  const [demoHistory,setDemoHistory]=useState<Batch[]>(()=>toDemoBatches());
  const [demoSelectedBatchId,setDemoSelectedBatchId]=useState<string>('');

  
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
    setActiveViewTab('results');
    void request<Batch>(`/batches/${encodeURIComponent(focusId)}`).then(value=>{if(!disposed){setBatch(value);setActiveViewTab('results');}}).catch(err=>{if(!disposed)setError(err instanceof Error?err.message:'指定记录读取失败');});
    return()=>{disposed=true;};
  },[focusId,workspaceId]);
  async function readHistory(){
    try{
      const value=await request<{batches:Batch[]}>('/batches');if(!alive.current)return;
      setHistory(value.batches);onActiveCount(value.batches.filter(b=>ACTIVE.has(b.status)).length);
      setBatch(current=>value.batches.find(b=>b.id===current?.id) || current || value.batches[0] || null);
    }catch(err){
      if(alive.current){
        setError(message(err));
      }
    }
  }
  useEffect(()=>{void readHistory();const timer=setInterval(()=>void readHistory(),4000);return()=>{clearInterval(timer);};},[workspaceId]);
  useEffect(()=>{
    const sequence=++listSequence.current;setListBusy(true);setError('');
    void (async()=>{
      const auth=await platformAuthRequest<{saved?:boolean;state?:string}>(fetchRef.current,'/api/fengshen-downloads/platform-auth/lanorange').catch(()=>null);
      if(!alive.current || sequence!==listSequence.current)return;
      const loggedIn=Boolean(auth?.saved && !['signed_out','login_required'].includes(auth.state||''));
      if(!loggedIn){
        setAllRows([]);
        setSelection({});
        setPreview(null);
        setError('请先登录蓝橙，再读取本人待办');
        window.dispatchEvent(new CustomEvent('workbench:lanorange-approvals-updated', { detail: { loggedOut: true } }));
        return;
      }
      const value=await request<{rows:Task[];total:number;actor_label:string;session_version:string}>('/pending-scope');
      if(!alive.current || sequence!==listSequence.current)return;
      if(versionRef.current && versionRef.current!==value.session_version){setSelection({});setPreview(null);setError('蓝橙会话已变化，已清除旧勾选，请重新选择。');}
      versionRef.current=value.session_version;setSessionVersion(value.session_version);setAllRows(value.rows);setSelection({});setPreview(null);setActor(value.actor_label);
      window.dispatchEvent(new CustomEvent('workbench:lanorange-approvals-updated', { detail: { rows: value.rows, actor_label: value.actor_label } }));
    })().catch(err=>{
      if(alive.current && sequence===listSequence.current){
        setAllRows([]);
        setError(message(err));
      }
    }).finally(()=>{if(alive.current && sequence===listSequence.current)setListBusy(false);});
  },[refresh,workspaceId]);

  const hasLiveData=allRows.length>0||history.length>0;
  const usingDemo=!hasLiveData&&demoEnabled;
  const effectiveRows=usingDemo?demoRows:allRows;
  const effectiveHistory=usingDemo?demoHistory:history;
  const effectiveBatch=usingDemo
    ?(demoHistory.find(b=>b.id===demoSelectedBatchId)||demoHistory[0]||null)
    :batch;
  const effectiveActor=usingDemo?'演示审批账号（区域经理）':actor;
  const effectiveError=usingDemo&&error.includes('登录')?'':error;

  const scopeFiltered=useMemo(()=>filterApprovalTasks(effectiveRows,{scopeCities,scopeMonths,scopeSite,eligibility:'all',keyword:''}),[effectiveRows,scopeCities,scopeMonths,scopeSite]);
  const filtered=useMemo(()=>filterApprovalTasks(effectiveRows,{scopeCities,scopeMonths,scopeSite,eligibility:eligibilityFilter,keyword}),[effectiveRows,scopeCities,scopeMonths,scopeSite,eligibilityFilter,keyword]);
  const eligibleScopeCount=useMemo(()=>scopeFiltered.filter(r=>!r.reason).length,[scopeFiltered]);
  const blockedScopeCount=scopeFiltered.length-eligibleScopeCount;
  const rows=filtered.slice((page-1)*20,page*20);

  const rowMonth=(r:Task)=>(r.settle_month||r.period_start||'').slice(0,7);
  const cityChoices=useMemo(()=>[...new Set(effectiveRows.map(r=>r.cityName||'').filter(Boolean))].sort(),[effectiveRows]);
  const monthChoices=useMemo(
    ()=>[...new Set(effectiveRows.filter(r=>!scopeCities.length||scopeCities.includes(r.cityName||'')).map(rowMonth).filter(Boolean))].sort().reverse(),
    [effectiveRows,scopeCities],
  );
  const siteChoices=useMemo(
    ()=>[...new Map(
      effectiveRows
        .filter(r=>(!scopeCities.length||scopeCities.includes(r.cityName||''))&&(!scopeMonths.length||scopeMonths.includes(rowMonth(r))))
        .map(r=>[JSON.stringify([r.cityName,r.siteName]),r] as const),
    )],
    [effectiveRows,scopeCities,scopeMonths],
  );
  const hasAnyScopeFilter=scopeCities.length>0||scopeMonths.length>0||Boolean(scopeSite)||Boolean(keyword.trim())||eligibilityFilter!=='all';

  async function perform(kind:string,action:()=>Promise<void>){
    if(inflight.current)return;inflight.current=true;setCommand(kind);setError('');setNotice('');
    try{await action();}catch(err){if(alive.current)setError(message(err));}finally{inflight.current=false;if(alive.current)setCommand('');}
  }
  const selected=Object.values(selection),pages=Math.max(1,Math.ceil(filtered.length/20)),active=effectiveHistory.some(b=>ACTIVE.has(b.status));
  function choose(tasks:Task[],checked:boolean){
    const next={...selection};for(const task of tasks){if(task.reason)continue;if(checked)next[task.id]=task;else delete next[task.id];}
    if(Object.keys(next).length>200){setError('每批最多选择200条，请分批处理。');return;}setSelection(next);
  }
  async function showDetail(task:Task){
    if(usingDemo){
      setDetail({task,price:toApprovalPrice(task)});
      return;
    }
    await perform('detail',async()=>setDetail(await request<{task:Task;price:Price}>(`/pending/${encodeURIComponent(task.id)}?session_version=${encodeURIComponent(sessionVersion)}`)));
  }
  async function makePreview(){
    if(usingDemo){
      setPreview({
        id:`DEMO-PREVIEW-${Date.now()}`,
        actor_label:effectiveActor,
        expires_at:Math.floor(Date.now()/1000)+600,
        eligible_count:selected.filter(t=>!t.reason).length,
        opinion:'同意',
        filters:query,
        items:selected.map(t=>({
          eligible:!t.reason,
          reason:t.reason||'',
          task:t,
          price:toApprovalPrice(t),
        })),
      });
      return;
    }
    await perform('preview',async()=>{
      const value=await request<Preview>('/previews',{selected:selected.map(t=>({id:t.id,revision:t.revision})),filters:query,session_version:sessionVersion},180000);
      if(alive.current)setPreview(value);
    });
  }
  async function sendAttempt(current:Attempt){await perform('submit',async()=>{
    setAttempt(current);setAttemptMissing(false);remember(attemptKey,current);
    try{
      const result=await request<Batch>('/batches',{...current,confirm:true},20000);
      if(alive.current){setBatch(result);setPreview(null);setSelection({});setAttempt(null);remember(attemptKey,null);setReceiptStatusFilter('all');setActiveViewTab('results');setRefresh(x=>x+1);void readHistory();}
    }catch(err){if(!(err instanceof PlatformAuthError && err.uncertain)){setAttempt(null);remember(attemptKey,null);}else throw new Error('本次审批批次尚未确认，请先查找本次提交；系统不会自动重复审批。');throw err;}
  });}
  async function submit(){
    if(!preview)return;
    if(usingDemo){
      const eligibleItems=preview.items.filter(it=>it.eligible);
      const batchId=`AP-DEMO-${Date.now().toString().slice(-6)}`;
      const nextBatch:Batch={
        id:batchId,
        actor_label:effectiveActor,
        status:'completed',
        created:Math.floor(Date.now()/1000),
        counts:{total:eligibleItems.length,success:eligibleItems.length,failed:0,uncertain:0,changed:0,not_sent:0,pending:0},
        items:eligibleItems.map(it=>({
          task:it.task,
          status:'success',
          status_label:'已同意',
          message:'示例审批已模拟同意（未实际提交至蓝橙）',
        })),
      };
      const doneIds=new Set(eligibleItems.map(it=>it.task.id));
      setDemoRows(prev=>prev.filter(r=>!doneIds.has(r.id)));
      setDemoHistory(prev=>[nextBatch,...prev]);
      setDemoSelectedBatchId(batchId);
      setPreview(null);
      setSelection({});
      setReceiptStatusFilter('all');
      setActiveViewTab('results');
      setNotice(`示例模式已模拟同意 ${eligibleItems.length} 条审批单，可在结果回执中查看。`);
      return;
    }
    await sendAttempt(attempt?.preview_id===preview.id?attempt:{preview_id:preview.id,request_id:crypto.randomUUID()});
  }
  async function findAttempt(){if(!attempt)return;await perform('find',async()=>{
    try{const result=await request<Batch>('/batches/by-request/'+encodeURIComponent(attempt.request_id));setBatch(result);setPreview(null);setSelection({});setAttempt(null);setAttemptMissing(false);remember(attemptKey,null);void readHistory();}
    catch(err){if(err instanceof PlatformAuthError && err.status===404){setAttemptMissing(true);throw new Error('尚未找到本次批次。可用原提交标识重试，已存在的批次会直接返回。');}throw err;}
  });}
  async function downloadResult(){
    if(!effectiveBatch)return;
    if(usingDemo){
      setNotice(`示例回执批次「${effectiveBatch.id}」仅用于预览，登录蓝橙并提交真实审批后可导出 CSV。`);
      return;
    }
    await perform('export',async()=>{
      const response=await fetchRef.current(`${BASE}/batches/${effectiveBatch.id}/result.csv`);if(!response.ok)throw new Error('结果下载失败，请稍后重试');
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`蓝橙价格审批结果_${effectiveBatch.id.slice(0,8)}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
  }

  const openLanorangeLogin = () => {
    window.dispatchEvent(new CustomEvent('workbench:connections', { detail: 'lanorange' }));
  };

  const isAuthBlocked = Boolean(effectiveError && effectiveError.includes('登录') && effectiveRows.length === 0);

  return <div className="wb-approvals wbx-approval">
    {/* 顶层清爽下划线视图切换条（与数据采集页保持统一） */}
    <section className="wbx-ap-topbar" aria-label="审批视图切换与操作">
      <div className="wbx-ap-tabs" role="tablist" aria-label="批量审批工作台视图">
        <button
          type="button"
          role="tab"
          aria-selected={activeViewTab === 'pending'}
          className={`wbx-ap-tab ${activeViewTab === 'pending' ? 'is-active' : ''}`}
          onClick={() => setActiveViewTab('pending')}
        >
          <ClipboardList size={15} className="wbx-ap-tab__icon" aria-hidden="true" />
          <span>待办审批列表</span>
          <span className="wbx-ap-tab__count tabular-nums">{effectiveRows.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeViewTab === 'results'}
          className={`wbx-ap-tab ${activeViewTab === 'results' ? 'is-active' : ''}`}
          onClick={() => setActiveViewTab('results')}
        >
          <CheckCircle2 size={15} className="wbx-ap-tab__icon" aria-hidden="true" />
          <span>审批结果回执</span>
          <span className="wbx-ap-tab__count tabular-nums">{effectiveHistory.length}</span>
        </button>
      </div>

      <div className="wbx-ap-topbar__right">
        {activeViewTab === 'pending' && effectiveRows.length > 0 && (
          <span className="wbx-ap-inline-meta tabular-nums">
            可同意 <strong>{eligibleScopeCount}</strong> · 阻断 <strong>{blockedScopeCount}</strong>
          </span>
        )}
        {activeViewTab === 'pending' && effectiveBatch && (
          <button
            type="button"
            className="wbx-ap-link-btn tabular-nums"
            onClick={() => setActiveViewTab('results')}
          >
            最近批次：{batchLabels[effectiveBatch.status] || effectiveBatch.status}（{effectiveBatch.counts.success || 0}/{effectiveBatch.items.length}）→
          </button>
        )}
        {!hasLiveData && (
          <span className="wbx-demo-group">
            {usingDemo && <span className="wbx-demo-badge">示例数据</span>}
            <button
              type="button"
              className="wbx-btn wbx-btn--ghost wbx-btn--sm"
              onClick={() => {
                setDemoEnabled(prev => {
                  const next = !prev;
                  window.dispatchEvent(new CustomEvent('workbench:lanorange-demo-toggled', { detail: { enabled: next } }));
                  return next;
                });
                setSelection({});
                setPage(1);
              }}
            >
              {demoEnabled ? '隐藏示例' : '加载 30 条示例'}
            </button>
          </span>
        )}
        {(() => {
          const needsLogin = !hasLiveData && Boolean(error && error.includes('登录'));
          return (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={listBusy || !!command}
              title={needsLogin ? '需先登录蓝橙账号后同步实时待办' : '刷新并同步本人蓝橙待办'}
              onClick={() => {
                if (needsLogin) {
                  openLanorangeLogin();
                  return;
                }
                setPage(1);
                setRefresh(v => v + 1);
              }}
            >
              {needsLogin ? <KeyRound size={13} /> : <RefreshCw size={13} className={listBusy ? 'wbx-spin' : ''} />}
              <span>{listBusy ? '正在同步…' : needsLogin ? '登录并同步' : '同步本人待办'}</span>
            </button>
          );
        })()}
      </div>
    </section>

    {effectiveError && !isAuthBlocked && (
      <div className={`wbx-ap-notice ${effectiveError.includes('登录') ? 'is-auth' : 'is-danger'}`} role="alert">
        <div className="wbx-ap-notice__body">
          <KeyRound size={15} className="wbx-ap-notice__icon" aria-hidden="true" />
          <div className="wbx-ap-notice__copy">
            <strong>{effectiveError.includes('登录') ? '需先完成蓝橙平台登录授权' : '操作提示'}</strong>
            <span>{effectiveError}</span>
          </div>
        </div>
        <div className="wbx-ap-notice__actions">
          {effectiveError.includes('登录') && (
            <button type="button" className="wbx-btn wbx-btn--primary wbx-btn--sm" onClick={openLanorangeLogin}>
              登录蓝橙
            </button>
          )}
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={listBusy || !!command}
            onClick={() => { setPage(1); setRefresh(v => v + 1); }}
          >
            <RefreshCw size={12.5} className={listBusy ? 'wbx-spin' : ''} />
            <span>重新同步</span>
          </button>
        </div>
      </div>
    )}

    {notice && (
      <div className="wbx-approval__notice-bar" role="status">
        <span>{notice}</span>
        <button type="button" className="wbx-btn wbx-btn--ghost wbx-btn--sm" onClick={() => setNotice('')}>关闭</button>
      </div>
    )}

    {attempt && (
      <div className="wb-approval-notice" role="status">
        <p>本次提交尚待确认。请先查找批次，避免重复审批。</p>
        <button className="wb-button" disabled={!!command} onClick={() => void findAttempt()}>
          查找本次提交
        </button>
        {attemptMissing && (
          <button className="wb-button" disabled={!!command} onClick={() => void sendAttempt(attempt)}>
            用原标识重试提交
          </button>
        )}
      </div>
    )}

    {/* 主体视图 A：本人待办审批队列 */}
    {activeViewTab === 'pending' && (
    <section className="wbx-ap-card wbx-approvals__pending">
      <div className="wbx-approval__head">
        <div className="wbx-approval__queue-title">
          <h3>
            本人待办审批列表
            <span className="tabular-nums">{filtered.length}</span>
          </h3>
          <span className="wbx-approval__queue-meta tabular-nums">
            已勾选 <strong>{selected.length}</strong> 条 · 跨页保留 · 单批上限 200 条
          </span>
        </div>
        <div className="wbx-approval__actions">
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={listBusy || !!command || !filtered.some(r => !r.reason) || filtered.length > 200}
            onClick={() => choose(filtered, true)}
          >
            勾选当前范围 ({filtered.filter(r => !r.reason).length})
          </button>
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={!selected.length || !!command}
            onClick={() => setSelection({})}
          >
            清空勾选
          </button>
          <button
            type="button"
            className="wbx-btn wbx-btn--primary wbx-btn--sm"
            disabled={!selected.length || !!command || active || !!attempt || listBusy}
            onClick={() => void makePreview()}
          >
            {command === 'preview' ? '正在核对明细…' : `预览已选 (${selected.length})`}
          </button>
        </div>
      </div>

      {/* 统一工作台单行页签 + 紧凑筛选控件栏 */}
      {effectiveRows.length > 0 && (
        <div className="wbx-approvals__toolbar">
          <div className="wbx-approvals__tabs" role="tablist" aria-label="按审批状态筛选">
            {([
              ['all', '全部', scopeFiltered.length],
              ['eligible', '可同意提交', eligibleScopeCount],
              ['blocked', '异常阻断', blockedScopeCount],
            ] as const).map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={eligibilityFilter === key}
                className={`wbx-approvals__tab${eligibilityFilter === key ? ' is-active' : ''}`}
                onClick={() => { setEligibilityFilter(key); setPage(1); }}
              >
                <span>{label}</span>
                <span className="wbx-approvals__tab-count tabular-nums">{count}</span>
              </button>
            ))}
          </div>

          <div className="wbx-approvals__filters" aria-label="多维范围筛选">
            <label className="wbx-approvals__search">
              <Search size={13.5} aria-hidden="true" />
              <input
                type="search"
                value={keyword}
                onChange={e => { setKeyword(e.target.value); setPage(1); }}
                placeholder="搜索编号、站点或申请人…"
                aria-label="搜索待办审批"
              />
            </label>

            <select
              className="wbx-approvals__select"
              aria-label="按城市筛选"
              disabled={listBusy || !!command}
              value={scopeCities[0] || ''}
              onChange={e => {
                const next = e.target.value ? [e.target.value] : [];
                setScopeCities(next);
                setScopeMonths([]);
                setScopeSite('');
                setPage(1);
                setSelection({});
                setPreview(null);
              }}
            >
              <option value="">全部城市 ({cityChoices.length})</option>
              {cityChoices.map(c => (
                <option key={c} value={c}>
                  {c} ({effectiveRows.filter(r => r.cityName === c).length})
                </option>
              ))}
            </select>

            <select
              className="wbx-approvals__select"
              aria-label="按结算月份筛选"
              disabled={listBusy || !!command}
              value={scopeMonths[0] || ''}
              onChange={e => {
                const next = e.target.value ? [e.target.value] : [];
                setScopeMonths(next);
                setScopeSite('');
                setPage(1);
                setSelection({});
                setPreview(null);
              }}
            >
              <option value="">全部月份</option>
              {monthChoices.map(m => (
                <option key={m} value={m}>
                  {m} ({effectiveRows.filter(r => (!scopeCities.length || scopeCities.includes(r.cityName || '')) && rowMonth(r) === m).length})
                </option>
              ))}
            </select>

            <select
              className="wbx-approvals__select wbx-approvals__select--site"
              aria-label="待审批站点"
              disabled={listBusy || !!command}
              value={scopeSite}
              onChange={e => {
                setScopeSite(e.target.value);
                setPage(1);
                setSelection({});
                setPreview(null);
              }}
            >
              <option value="">全部站点 ({siteChoices.length})</option>
              {siteChoices.map(([key, r]) => (
                <option value={key} key={key}>
                  {r.cityName} · {r.siteName || '未命名站点'}
                </option>
              ))}
            </select>

            {hasAnyScopeFilter && (
              <button
                type="button"
                className="wbx-approvals__reset"
                onClick={() => {
                  setScopeCities([]);
                  setScopeMonths([]);
                  setScopeSite('');
                  setEligibilityFilter('all');
                  setKeyword('');
                  setPage(1);
                  setSelection({});
                  setPreview(null);
                }}
              >
                <RotateCcw size={12} aria-hidden="true" />
                <span>重置</span>
              </button>
            )}
          </div>
        </div>
      )}

      {filtered.length > 200 && (
        <p className="wbx-approvals__subnote">每批最多审批 200 条，请缩小城市、月份或站点范围，或按页勾选。</p>
      )}
      {active && (
        <p className="wbx-approvals__subnote">已有批次执行中，可在上方「审批结果回执」查看进度；离开此页仍会继续。</p>
      )}

      {filtered.length > 0 ? (
        <>
          <div className="wb-approval-table wbx-table-scroll wbx-approvals__scroll" aria-busy={listBusy}>
            <table className="wbx-table wbx-approvals__table">
              <thead>
                <tr>
                  <th className="ap-col-check">
                    <input
                      type="checkbox"
                      aria-label="选择本页可审批流程"
                      disabled={listBusy || !rows.some(r => !r.reason)}
                      checked={rows.some(r => !r.reason) && rows.filter(r => !r.reason).every(r => !!selection[r.id])}
                      onChange={e => choose(rows, e.target.checked)}
                    />
                  </th>
                  <th className="ap-col-code">业务编号</th>
                  <th className="ap-col-city">城市 / 站点</th>
                  <th className="ap-col-period">结算周期</th>
                  <th className="ap-col-count">人数</th>
                  <th className="ap-col-creator">申请人 / 时间</th>
                  <th className="ap-col-node">当前节点</th>
                  <th className="wbx-table__actions">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(task => (
                  <tr key={task.id} className={task.reason ? 'is-blocked' : ''}>
                    <td className="ap-col-check">
                      <input
                        type="checkbox"
                        aria-label={`选择流程${code(task)}`}
                        checked={!!selection[task.id]}
                        disabled={!!task.reason || listBusy}
                        onChange={e => choose([task], e.target.checked)}
                      />
                    </td>
                    <td className="ap-col-code tabular-nums">
                      <span className="wbx-approvals__code">{code(task)}</span>
                      {task.reason && <small className="wb-error wbx-approvals__reason">{task.reason}</small>}
                    </td>
                    <td className="ap-col-city">
                      <span className="wbx-approvals__city">{task.cityName || '—'}</span>
                      <small className="wbx-approvals__site" title={task.siteName || '—'}>{task.siteName || '—'}</small>
                    </td>
                    <td className="ap-col-period tabular-nums">{period(task)}</td>
                    <td className="ap-col-count tabular-nums">{task.rider_count ?? '—'}</td>
                    <td className="ap-col-creator">
                      <span>{task.createByName || '—'}</span>
                      <small className="tabular-nums">{task.createTime || '—'}</small>
                    </td>
                    <td className="ap-col-node">
                      <span className={`wbx-approvals__node-tag${task.reason ? ' is-blocked' : ''}`}>
                        {task.nodeName || '—'}
                      </span>
                    </td>
                    <td className="wbx-table__actions">
                      <button
                        type="button"
                        className="wbx-approvals__detail-btn"
                        disabled={!!command || !!task.reason}
                        onClick={() => void showDetail(task)}
                      >
                        查看明细
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="wbx-approvals__pagination tabular-nums">
            <span className="wbx-approvals__page-meta">
              共 {filtered.length} 条 · 第 {page} / {pages} 页（每页 20 条）
            </span>
            <div className="wbx-approvals__page-btns">
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                disabled={page <= 1 || listBusy}
                onClick={() => setPage(p => p - 1)}
              >
                上一页
              </button>
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                disabled={page >= pages || listBusy}
                onClick={() => setPage(p => p + 1)}
              >
                下一页
              </button>
            </div>
          </div>
        </>
      ) : listBusy ? (
        <p className="wbx-hint py-6 text-center" role="status">正在读取蓝橙本人待办…</p>
      ) : scopeFiltered.length > 0 ? (
        <div className="pq-empty">
          <Search size={24} />
          <strong>当前筛选条件没有匹配的待办流程</strong>
          <p>可切换“可同意提交 / 异常阻断”标签或清空搜索关键词。</p>
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            onClick={() => { setEligibilityFilter('all'); setKeyword(''); setPage(1); }}
          >
            重置列表筛选
          </button>
        </div>
      ) : isAuthBlocked ? (
        <div className="wbx-ap-empty">
          <span className="wbx-ap-empty__icon" aria-hidden="true">
            <KeyRound size={20} />
          </span>
          <strong>需先完成蓝橙平台登录授权</strong>
          <p>登录蓝橙账号后将自动读取本人名下待审价格提审单，支持按城市、月份与站点多维筛选并批量同意。</p>
          <div className="wbx-ap-empty__actions">
            <button type="button" className="wbx-btn wbx-btn--primary" onClick={openLanorangeLogin}>
              立即登录蓝橙
            </button>
            <button
              type="button"
              className="wbx-btn"
              disabled={listBusy || !!command}
              onClick={() => { setPage(1); setRefresh(v => v + 1); }}
            >
              <RefreshCw size={13} className={listBusy ? 'wbx-spin' : ''} />
              <span>重新同步</span>
            </button>
          </div>
        </div>
      ) : (
        <div className="wbx-ap-empty">
          <span className="wbx-ap-empty__icon" aria-hidden="true">
            <ClipboardList size={20} />
          </span>
          <strong>当前暂无待办审批流程</strong>
          <p>您名下暂无待审批的价格提审单，可点击右上角「同步本人待办」随时刷新最新状态。</p>
        </div>
      )}
    </section>
    )}

    {/* 主体视图 B：独立置顶的审批结果回执面板 */}
    {activeViewTab === 'results' && (
      <section className="wbx-ap-card wbx-approval__results-panel" id="price-record-result" aria-label="审批结果回执">
        <div className="wbx-approval__head">
          <div className="wbx-approval__queue-title">
            <h3>
              审批结果回执
              <span>{effectiveBatch ? effectiveBatch.items.length : 0}</span>
              {effectiveBatch && (
                <em className={`wbx-pill ${toneClass(normalizeTone(effectiveBatch.status))}`}>
                  <span className="wbx-pill__dot" aria-hidden="true" />
                  {batchLabels[effectiveBatch.status] || effectiveBatch.status}
                </em>
              )}
            </h3>
            <p className="tabular-nums">
              {effectiveBatch
                ? `执行账号：${effectiveBatch.actor_label || effectiveActor || '当前授权账号'} · 共 ${effectiveHistory.length} 批记录`
                : '暂无已提交的批量审批批次记录'}
            </p>
          </div>
          <div className="wbx-approval__actions">
            {effectiveHistory.length > 0 && (
              <label className="wbx-approval__batch-picker">
                <span>切换批次</span>
                <select
                  className="wbx-ap-select"
                  aria-label="选择审批回执批次"
                  value={effectiveBatch?.id || ''}
                  onChange={e => {
                    const found = effectiveHistory.find(b => b.id === e.target.value) || null;
                    setReceiptStatusFilter('all');
                    if (usingDemo) setDemoSelectedBatchId(e.target.value);
                    else setBatch(found);
                  }}
                >
                  {effectiveBatch && !effectiveHistory.some(b => b.id === effectiveBatch.id) && (
                    <option value={effectiveBatch.id}>
                      当前任务 · {batchLabels[effectiveBatch.status] || effectiveBatch.status}
                    </option>
                  )}
                  {effectiveHistory.map(b => (
                    <option value={b.id} key={b.id}>
                      {new Date(b.created * 1000).toLocaleString('zh-CN')} · {batchLabels[b.status] || b.status} · {b.items.length}条
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={!!command}
              onClick={() => void readHistory()}
            >
              <RefreshCw size={13} />
              刷新结果
            </button>
            {effectiveBatch && ACTIVE.has(effectiveBatch.status) && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm wbx-btn--danger"
                disabled={!!command || effectiveBatch.status === 'stopping'}
                onClick={() => {
                  if (usingDemo) {
                    setDemoHistory(prev =>
                      prev.map(b => (b.id === effectiveBatch.id ? { ...b, status: 'partial' } : b)),
                    );
                    setNotice('已停止示例批次后续审批。');
                    return;
                  }
                  void perform('stop', async () => {
                    setBatch(await request<Batch>(`/batches/${effectiveBatch.id}/stop`, { confirm: true }));
                    void readHistory();
                  });
                }}
              >
                停止后续审批
              </button>
            )}
            {effectiveBatch && !!effectiveBatch.counts.uncertain && !ACTIVE.has(effectiveBatch.status) && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                disabled={!!command}
                onClick={() => {
                  if (usingDemo) {
                    setNotice('示例模式已完成待核实结果状态校验。');
                    return;
                  }
                  void perform('recheck', async () => {
                    setBatch(await request<Batch>(`/batches/${effectiveBatch.id}/recheck`, {}, 120000));
                    void readHistory();
                    setRefresh(x => x + 1);
                  });
                }}
              >
                核实待确认结果
              </button>
            )}
            {effectiveBatch && (
              <button
                type="button"
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                disabled={!!command}
                onClick={() => void downloadResult()}
              >
                <Download size={13} />
                下载结果 CSV
              </button>
            )}
          </div>
        </div>

        {!effectiveBatch ? (
          <div className="wbx-ap-empty">
            <span className="wbx-ap-empty__icon" aria-hidden="true">
              <CheckCircle2 size={20} />
            </span>
            <strong>暂无审批结果回执</strong>
            <p>可先切换回“待办审批列表”勾选并提交价格提审单，提交完成后将在此直接展示逐项回执。</p>
            <div className="wbx-ap-empty__actions">
              <button
                type="button"
                className="wbx-btn wbx-btn--primary"
                onClick={() => setActiveViewTab('pending')}
              >
                前往待办审批列表
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="wbx-approval__result-banner">
              <div className="wbx-approval__result-status">
                <TaskOutcome task={{ status: effectiveBatch.status, kind: 'approval', availableFiles: 1 }} />
              </div>

              <div className="wbx-approval__result-kpis tabular-nums" role="group" aria-label="按审批结果快捷筛选">
                {([
                  { key: 'success', label: '已同意', count: effectiveBatch.counts.success || 0, tone: 'is-success' },
                  { key: 'failed', label: '被拒绝', count: effectiveBatch.counts.failed || 0, tone: 'is-danger' },
                  { key: 'uncertain', label: '待核实', count: effectiveBatch.counts.uncertain || 0, tone: 'is-warn' },
                  { key: 'changed', label: '状态变化', count: effectiveBatch.counts.changed || 0, tone: 'is-warn' },
                  { key: 'not_sent', label: '未提交', count: effectiveBatch.counts.not_sent || 0, tone: '' },
                  { key: 'pending', label: '等待中', count: effectiveBatch.counts.pending || 0, tone: 'is-primary' },
                ] as const).map(kpi => {
                  const isActive = receiptStatusFilter === kpi.key;
                  const toneCls = kpi.count > 0 ? kpi.tone : 'is-zero';
                  return (
                    <button
                      key={kpi.key}
                      type="button"
                      aria-pressed={isActive}
                      title={kpi.count > 0 ? `点击仅查看「${kpi.label}」明细` : `当前无「${kpi.label}」记录`}
                      className={`wbx-approval__result-kpi ${toneCls}${isActive ? ' is-active' : ''}`}
                      onClick={() => setReceiptStatusFilter(prev => (prev === kpi.key ? 'all' : kpi.key))}
                    >
                      <span>{kpi.label}</span>
                      <strong>{kpi.count}</strong>
                    </button>
                  );
                })}
              </div>
            </div>

            {effectiveBatch.status === 'stopping' && (
              <p className="wb-muted">当前已发出的官方请求会先核实结果，后续条目不再提交。</p>
            )}

            {(() => {
              const allItems = effectiveBatch.items || [];
              const issueCount = allItems.filter(it => it.status !== 'success').length;
              const successCount = allItems.length - issueCount;
              const shownItems =
                receiptStatusFilter === 'all'
                  ? allItems
                  : receiptStatusFilter === 'success'
                    ? allItems.filter(it => it.status === 'success')
                    : receiptStatusFilter === 'issue'
                      ? allItems.filter(it => it.status !== 'success')
                      : allItems.filter(it => it.status === receiptStatusFilter);
              return (
                <div className="wbx-approval__receipts">
                  <div className="wbx-approval__receipts-head">
                    <div className="wbx-approval__receipts-title">
                      <strong>逐项审批结果</strong>
                      <span className="wbx-approval__receipts-meta tabular-nums">
                        显示 {shownItems.length} / {allItems.length} 条
                      </span>
                      {!['all', 'success', 'issue'].includes(receiptStatusFilter) && (
                        <button
                          type="button"
                          className="wbx-ap-link-btn"
                          onClick={() => setReceiptStatusFilter('all')}
                        >
                          清除状态筛选
                        </button>
                      )}
                    </div>
                    <div className="wbx-ap-receipt-tabs" role="tablist" aria-label="按回执状态筛选">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={receiptStatusFilter === 'all'}
                        className={`wbx-ap-receipt-tab ${receiptStatusFilter === 'all' ? 'is-active' : ''}`}
                        onClick={() => setReceiptStatusFilter('all')}
                      >
                        <span>全部</span>
                        <span className="wbx-ap-receipt-tab__count tabular-nums">{allItems.length}</span>
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={receiptStatusFilter === 'success'}
                        className={`wbx-ap-receipt-tab ${receiptStatusFilter === 'success' ? 'is-active' : ''}`}
                        onClick={() => setReceiptStatusFilter('success')}
                      >
                        <span>已同意</span>
                        <span className="wbx-ap-receipt-tab__count tabular-nums">{successCount}</span>
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={receiptStatusFilter === 'issue'}
                        className={`wbx-ap-receipt-tab ${receiptStatusFilter === 'issue' ? 'is-active' : ''}`}
                        onClick={() => setReceiptStatusFilter('issue')}
                      >
                        <span>异常/待核实</span>
                        <span className="wbx-ap-receipt-tab__count tabular-nums">{issueCount}</span>
                      </button>
                    </div>
                  </div>

                  <div className="wbx-table-scroll wbx-approval__receipts-scroll">
                    <table className="wbx-table wbx-approval__receipts-table">
                      <thead>
                        <tr>
                          <th>业务编号</th>
                          <th>城市 / 站点</th>
                          <th>结算周期</th>
                          <th>审批结果</th>
                          <th>回执说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shownItems.map((item, index) => {
                          const pillCls =
                            item.status === 'success'
                              ? 'wbx-pill--success'
                              : item.status === 'uncertain' || item.status === 'failed'
                                ? 'wbx-pill--danger'
                                : 'wbx-pill--warn';
                          return (
                            <tr key={`${item.task.id}-${index}`}>
                              <td className="tabular-nums">
                                <span className="wbx-approvals__code">{code(item.task)}</span>
                              </td>
                              <td>
                                <span className="wbx-approvals__city">{item.task.cityName || '—'}</span>
                                <small className="wbx-approvals__site" title={item.task.siteName || '—'}>
                                  {item.task.siteName || '—'}
                                </small>
                              </td>
                              <td className="tabular-nums">{period(item.task)}</td>
                              <td>
                                <span className={`wbx-pill ${pillCls}`}>
                                  <span className="wbx-pill__dot" aria-hidden="true" />
                                  {item.status_label}
                                </span>
                              </td>
                              <td>{item.message || '—'}</td>
                            </tr>
                          );
                        })}
                        {shownItems.length === 0 && (
                          <tr>
                            <td colSpan={5} className="wbx-approval__receipts-empty">
                              当前筛选状态暂无审批明细记录。
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })()}
          </>
        )}
      </section>
    )}
    {preview && <WorkbenchDrawer title="审批预览" wide onClose={()=>{if(!command)setPreview(null);}}>
      <div className="wb-approval-preview"><p><strong>蓝橙账号：{preview.actor_label}</strong></p><p>本批可提交{preview.eligible_count}条，需另行处理{preview.items.length-preview.eligible_count}条；审批意见统一为“同意”。</p><p className="wb-muted">仅同意本人当前节点，不更改单价。沿用官方默认抄送及站内通知；预览有效至{new Date(preview.expires_at*1000).toLocaleTimeString('zh-CN')}。</p>
      {error && <p className="wb-error" role="alert">{error}</p>}
      <div className="wb-approval-table"><table><thead><tr><th>业务编号</th><th>城市 / 站点</th><th>结算周期</th><th>人数</th><th>本批处理</th><th>明细</th></tr></thead><tbody>{preview.items.map(item=><tr key={item.task.id}><td>{code(item.task)}</td><td>{item.task.cityName} / {item.task.siteName}</td><td>{period(item.task)}</td><td>{item.task.rider_count ?? '—'}</td><td>{item.eligible?'同意当前节点':item.reason}</td><td>{item.price && <button className="wb-button" onClick={()=>setDetail({task:item.task,price:item.price!})}>价格明细</button>}</td></tr>)}</tbody></table></div>
      <div className="wb-approval-preview-actions"><button className="wb-button" disabled={!!command} onClick={()=>setPreview(null)}>返回调整</button><button className="wb-primary" disabled={!preview.eligible_count || !!command || active || !!attempt} onClick={()=>void submit()}>{command==='submit'?'正在创建批次…':`同意并提交${preview.eligible_count}条`}</button></div>
      {attempt && <button className="wb-button" disabled={!!command} onClick={()=>void findAttempt()}>查找本次提交</button>}</div>
    </WorkbenchDrawer>}
    {detail && (() => {
      const navigableTasks = filtered.filter(r => !r.reason);
      const detailIdx = navigableTasks.findIndex(r => r.id === detail.task.id);
      const prevDetail = detailIdx > 0 ? navigableTasks[detailIdx - 1] : null;
      const nextDetail = detailIdx >= 0 && detailIdx < navigableTasks.length - 1 ? navigableTasks[detailIdx + 1] : null;
      return (
        <WorkbenchDrawer title={`价格明细 · ${code(detail.task)}`} wide onClose={()=>setDetail(null)}>
          <div className="wbx-ap-detail">
            <div className="wbx-ap-detail__toolbar">
              <div className="wbx-ap-detail__status">
                <span className={`wbx-pill ${detail.task.reason ? 'wbx-pill--warn' : 'wbx-pill--info'}`}>
                  <span className="wbx-pill__dot" aria-hidden="true" />
                  {detail.task.nodeName || '审批节点'}
                </span>
                <span className="wbx-ap-detail__meta tabular-nums">
                  {detail.price.rows.length} 名骑手 · 版本 {detail.price.version ?? '—'}{detail.price.version_change ? ` · ${detail.price.version_change}` : ''}
                </span>
              </div>
              {navigableTasks.length > 1 && detailIdx >= 0 && (
                <div className="wbx-ap-detail__pager" aria-label="切换相邻审批单">
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                    disabled={!prevDetail || !!command}
                    onClick={() => prevDetail && void showDetail(prevDetail)}
                  >
                    上一条
                  </button>
                  <span className="wbx-ap-detail__pager-pos tabular-nums">
                    {detailIdx + 1} / {navigableTasks.length}
                  </span>
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                    disabled={!nextDetail || !!command}
                    onClick={() => nextDetail && void showDetail(nextDetail)}
                  >
                    下一条
                  </button>
                </div>
              )}
            </div>

            <dl className="wbx-ap-detail__facts">
              <div>
                <dt>业务编号</dt>
                <dd className="tabular-nums">{code(detail.task)}</dd>
              </div>
              <div>
                <dt>城市 / 站点</dt>
                <dd title={`${detail.task.cityName || '—'} · ${detail.task.siteName || '—'}`}>
                  {detail.task.cityName || '—'} · {detail.task.siteName || '—'}
                </dd>
              </div>
              <div>
                <dt>结算周期</dt>
                <dd className="tabular-nums">{period(detail.task)}</dd>
              </div>
              <div>
                <dt>申请人 / 时间</dt>
                <dd className="tabular-nums">
                  {detail.task.createByName || '—'}{detail.task.createTime ? ` · ${detail.task.createTime}` : ''}
                </dd>
              </div>
            </dl>

            <PriceTable key={detail.task.id} price={detail.price}/>
          </div>
        </WorkbenchDrawer>
      );
    })()}
  </div>;
}
