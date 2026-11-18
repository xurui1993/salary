import { TaskOutcome } from './TaskOutcome';
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {ApprovalScopeFilters} from './ApprovalScopeFilters';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {toneClass, normalizeTone} from '../lib/statusSemantics';
import {RefreshCw, ArrowRightLeft, KeyRound, Search, CheckCircle2, ClipboardList, Download} from 'lucide-react';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';
import {filterApprovalTasks,type ApprovalEligibilityFilter} from '../lib/workbenchFilters';

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
  const [eligibilityFilter,setEligibilityFilter]=useState<ApprovalEligibilityFilter>('all');
  const [keyword,setKeyword]=useState('');
  const [actor,setActor]=useState(''),[sessionVersion,setSessionVersion]=useState('');
  const [selection,setSelection]=useState<Record<string,Task>>({}),[listBusy,setListBusy]=useState(false),[command,setCommand]=useState(''),[error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [preview,setPreview]=useState<Preview|null>(null),[detail,setDetail]=useState<{task:Task;price:Price}|null>(null);
  const [history,setHistory]=useState<Batch[]>([]),[batch,setBatch]=useState<Batch|null>(null),[attempt,setAttempt]=useState<Attempt|null>(null);
  const [attemptMissing,setAttemptMissing]=useState(false);
  const [activeViewTab,setActiveViewTab]=useState<'pending'|'results'>('pending');
  const [receiptStatusFilter,setReceiptStatusFilter]=useState<'all'|'success'|'issue'>('all');

  
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
        return;
      }
      const value=await request<{rows:Task[];total:number;actor_label:string;session_version:string}>('/pending-scope');
      if(!alive.current || sequence!==listSequence.current)return;
      if(versionRef.current && versionRef.current!==value.session_version){setSelection({});setPreview(null);setError('蓝橙会话已变化，已清除旧勾选，请重新选择。');}
      versionRef.current=value.session_version;setSessionVersion(value.session_version);setAllRows(value.rows);setSelection({});setPreview(null);setActor(value.actor_label);
    })().catch(err=>{
      if(alive.current && sequence===listSequence.current){
        setAllRows([]);
        setError(message(err));
      }
    }).finally(()=>{if(alive.current && sequence===listSequence.current)setListBusy(false);});
  },[refresh,workspaceId]);

  const effectiveRows=allRows;
  const effectiveHistory=history;
  const effectiveBatch=batch;
  const effectiveActor=actor;

  const scopeFiltered=useMemo(()=>filterApprovalTasks(effectiveRows,{scopeCities,scopeMonths,scopeSite,eligibility:'all',keyword:''}),[effectiveRows,scopeCities,scopeMonths,scopeSite]);
  const filtered=useMemo(()=>filterApprovalTasks(effectiveRows,{scopeCities,scopeMonths,scopeSite,eligibility:eligibilityFilter,keyword}),[effectiveRows,scopeCities,scopeMonths,scopeSite,eligibilityFilter,keyword]);
  const eligibleScopeCount=useMemo(()=>scopeFiltered.filter(r=>!r.reason).length,[scopeFiltered]);
  const blockedScopeCount=scopeFiltered.length-eligibleScopeCount;
  const rows=filtered.slice((page-1)*20,page*20);

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
    await perform('detail',async()=>setDetail(await request<{task:Task;price:Price}>(`/pending/${encodeURIComponent(task.id)}?session_version=${encodeURIComponent(sessionVersion)}`)));
  }
  async function makePreview(){
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
    await sendAttempt(attempt?.preview_id===preview.id?attempt:{preview_id:preview.id,request_id:crypto.randomUUID()});
  }
  async function findAttempt(){if(!attempt)return;await perform('find',async()=>{
    try{const result=await request<Batch>('/batches/by-request/'+encodeURIComponent(attempt.request_id));setBatch(result);setPreview(null);setSelection({});setAttempt(null);setAttemptMissing(false);remember(attemptKey,null);void readHistory();}
    catch(err){if(err instanceof PlatformAuthError && err.status===404){setAttemptMissing(true);throw new Error('尚未找到本次批次。可用原提交标识重试，已存在的批次会直接返回。');}throw err;}
  });}
  async function downloadResult(){
    if(!effectiveBatch)return;
    await perform('export',async()=>{
      const response=await fetchRef.current(`${BASE}/batches/${effectiveBatch.id}/result.csv`);if(!response.ok)throw new Error('结果下载失败，请稍后重试');
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`蓝橙价格审批结果_${effectiveBatch.id.slice(0,8)}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
  }

  const openLanorangeLogin = () => {
    window.dispatchEvent(new CustomEvent('workbench:connections', { detail: 'lanorange' }));
  };

  return <div className="wb-approvals wbx-approval">
    {/* 顶部：精简连接状态与操作带 */}
    <section className="wbx-approval__compact-bar" aria-label="蓝橙连接与操作">
      <div className="wbx-approval__compact-lead">
        <span className={`wbx-approval__session-status ${effectiveActor ? 'is-ready' : 'is-warn'}`}>
          <span className="wbx-dot" />
          {effectiveActor ? `已连接 · ${effectiveActor}` : '待登录蓝橙平台'}
        </span>
        <span className="wbx-approval__compact-meta tabular-nums">
          待办 {effectiveRows.length} · 可同意 {eligibleScopeCount} · 阻断 {blockedScopeCount}
        </span>
      </div>

      <div className="wbx-approval__compact-actions">
        <button
          type="button"
          className="wbx-btn wbx-btn--ghost wbx-btn--sm"
          disabled={listBusy || !!command}
          onClick={() => { setPage(1); setRefresh(v => v + 1); }}
        >
          <RefreshCw size={13} className={listBusy ? 'wbx-spin' : ''} />
          <span>{listBusy ? '正在同步…' : '同步本人待办'}</span>
        </button>
        <button
          type="button"
          className="wbx-btn wbx-btn--ghost wbx-btn--sm"
          onClick={openLanorangeLogin}
        >
          <KeyRound size={13} />
          <span>蓝橙授权</span>
        </button>
        {onSwitchView && (
          <button
            type="button"
            className="wbx-btn wbx-btn--ghost wbx-btn--sm"
            onClick={() => onSwitchView('price-export')}
          >
            <ArrowRightLeft size={13} />
            <span>每日价格导出</span>
          </button>
        )}
      </div>
    </section>

    {/* 顶层视图切换条：待办审批队列 vs 审批结果回执（无需再滑到页尾并点开折叠详情） */}
    <section className="wbx-approval__view-bar" aria-label="审批视图切换">
      <div className="wbx-segmented" role="tablist" aria-label="批量审批工作台视图">
        <button
          type="button"
          role="tab"
          aria-selected={activeViewTab === 'pending'}
          className={`wbx-segmented__item ${activeViewTab === 'pending' ? 'is-active' : ''}`}
          onClick={() => setActiveViewTab('pending')}
        >
          <ClipboardList size={14} />
          <span>待办审批列表</span>
          <span className="tabular-nums">({effectiveRows.length})</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeViewTab === 'results'}
          className={`wbx-segmented__item ${activeViewTab === 'results' ? 'is-active' : ''}`}
          onClick={() => setActiveViewTab('results')}
        >
          <CheckCircle2 size={14} />
          <span>审批结果回执</span>
          <span className="tabular-nums">({effectiveHistory.length})</span>
        </button>
      </div>

      <div className="wbx-approval__view-summary">
        {activeViewTab === 'pending' && effectiveBatch ? (
          <>
            <span className={`wbx-pill ${toneClass(normalizeTone(effectiveBatch.status))}`}>
              <span className="wbx-pill__dot" aria-hidden="true" />
              最近批次：{batchLabels[effectiveBatch.status] || effectiveBatch.status}
            </span>
            <span className="wbx-hint tabular-nums">
              已同意 {effectiveBatch.counts.success || 0} / {effectiveBatch.items.length} 条
            </span>
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              onClick={() => setActiveViewTab('results')}
            >
              查看审批结果 →
            </button>
          </>
        ) : activeViewTab === 'results' ? (
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            onClick={() => setActiveViewTab('pending')}
          >
            ← 返回待办审批列表 ({effectiveRows.length})
          </button>
        ) : (
          <span className="wbx-hint">提交审批后将自动定位到最新审批结果回执</span>
        )}
      </div>
    </section>

    {/* 中部：多维范围筛选面板（待办视图展示） */}
    {activeViewTab === 'pending' && (
      <ApprovalScopeFilters
        rows={effectiveRows}
        cities={scopeCities}
        months={scopeMonths}
        site={scopeSite}
        busy={listBusy || !!command}
        onChange={(cities, months, site) => {
          setScopeCities(cities);
          setScopeMonths(months);
          setScopeSite(site);
          setPage(1);
          setSelection({});
          setPreview(null);
        }}
        onRefresh={() => {
          setPage(1);
          setRefresh(v => v + 1);
        }}
      />
    )}

    {error && (
      <div className="wb-error wb-error-with-action" role="alert">
        <div className="wbx-approval__alert-copy">
          <strong>{error.includes('登录') ? '需先完成蓝橙平台登录授权' : '操作提示'}</strong>
          <span>{error}</span>
        </div>
        <div className="wbx-approval__alert-actions">
          {error.includes('登录') && (
            <button type="button" className="wb-inline-login-action" onClick={openLanorangeLogin}>
              立即登录蓝橙
            </button>
          )}
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={listBusy || !!command}
            onClick={() => { setPage(1); setRefresh(v => v + 1); }}
          >
            <RefreshCw size={13} className={listBusy ? 'wbx-spin' : ''} />
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
    <section className="wb-approval-card wbx-section wbx-approvals__pending">
      <div className="wbx-approval__head">
        <div className="wbx-approval__queue-title">
          <h3>
            本人待办审批列表
            <span>{filtered.length}</span>
          </h3>
          <p className="tabular-nums">
            已勾选 {selected.length} 条（跨页保留 · 单批上限 200 条）
          </p>
        </div>
        <div className="wbx-approval__actions">
          <button
            type="button"
            className="wb-button"
            disabled={listBusy || !!command || !filtered.some(r => !r.reason) || filtered.length > 200}
            onClick={() => choose(filtered, true)}
          >
            勾选当前范围全部 ({filtered.filter(r => !r.reason).length})
          </button>
          <button
            type="button"
            className="wb-button"
            disabled={!selected.length || !!command}
            onClick={() => setSelection({})}
          >
            清空勾选
          </button>
          <button
            type="button"
            className="wb-primary"
            disabled={!selected.length || !!command || active || !!attempt || listBusy}
            onClick={() => void makePreview()}
          >
            {command === 'preview' ? '正在核对明细…' : `预览已选 (${selected.length})`}
          </button>
        </div>
      </div>

      {scopeFiltered.length > 0 && (
        <div className="wbx-approvals__filter-bar">
          <div className="wbx-segmented" role="tablist" aria-label="按审批状态筛选">
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
                className={`wbx-segmented__item ${eligibilityFilter === key ? 'is-active' : ''}`}
                onClick={() => { setEligibilityFilter(key); setPage(1); }}
              >
                <span>{label}</span>
                <span className="tabular-nums">({count})</span>
              </button>
            ))}
          </div>
          <label className="wbx-approvals__search">
            <Search size={14} />
            <input
              type="search"
              value={keyword}
              onChange={e => { setKeyword(e.target.value); setPage(1); }}
              placeholder="搜索业务编号、城市、站点、节点或申请人..."
              aria-label="搜索待办审批"
            />
          </label>
        </div>
      )}

      {filtered.length > 200 && (
        <p className="wb-muted mt-2">每批最多审批200条，请缩小城市、月份或站点范围，或按页勾选。</p>
      )}
      {active && (
        <p className="wb-muted mt-2">已有批次执行中，可在下方查看进度；离开此页仍会继续。</p>
      )}

      {filtered.length > 0 ? (
        <>
          <div className="wb-approval-table wbx-table-scroll wbx-approvals__scroll mt-3" aria-busy={listBusy}>
            <table className="wbx-table wbx-approvals__table">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="选择本页可审批流程"
                      disabled={listBusy || !rows.some(r => !r.reason)}
                      checked={rows.some(r => !r.reason) && rows.filter(r => !r.reason).every(r => !!selection[r.id])}
                      onChange={e => choose(rows, e.target.checked)}
                    />
                  </th>
                  <th>业务编号</th>
                  <th>城市 / 站点</th>
                  <th>结算周期</th>
                  <th>人数</th>
                  <th>申请人 / 时间</th>
                  <th>当前节点</th>
                  <th className="wbx-table__actions">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(task => (
                  <tr key={task.id} className={task.reason ? 'is-blocked' : ''}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`选择流程${code(task)}`}
                        checked={!!selection[task.id]}
                        disabled={!!task.reason || listBusy}
                        onChange={e => choose([task], e.target.checked)}
                      />
                    </td>
                    <td className="tabular-nums">
                      <span className="wbx-approvals__code">{code(task)}</span>
                      {task.reason && <small className="wb-error wbx-approvals__reason">{task.reason}</small>}
                    </td>
                    <td>
                      <span className="wbx-approvals__city">{task.cityName || '—'}</span>
                      <small className="wbx-approvals__site" title={task.siteName || '—'}>{task.siteName || '—'}</small>
                    </td>
                    <td className="tabular-nums">{period(task)}</td>
                    <td className="tabular-nums">{task.rider_count ?? '—'}</td>
                    <td>
                      <span>{task.createByName || '—'}</span>
                      <small className="tabular-nums">{task.createTime || '—'}</small>
                    </td>
                    <td>
                      <span className={`wbx-pill ${task.reason ? 'wbx-pill--warn' : 'wbx-pill--neutral'}`}>
                        {task.nodeName || '—'}
                      </span>
                    </td>
                    <td className="wbx-table__actions">
                      <button
                        className="wb-button"
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
          <div className="wb-approval-pagination">
            <span className="tabular-nums">第{page}/{pages}页 · 每页20条</span>
            <button className="wb-button" disabled={page <= 1 || listBusy} onClick={() => setPage(p => p - 1)}>
              上一页
            </button>
            <button className="wb-button" disabled={page >= pages || listBusy} onClick={() => setPage(p => p + 1)}>
              下一页
            </button>
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
      ) : (
        <div className="pq-empty">
          <Search size={24} />
          <strong>暂无待办审批流程</strong>
          <p>请完成蓝橙平台账号授权并点击“同步本人待办”，系统会自动按城市、结算月份与站点读取待审价格提审单。</p>
        </div>
      )}
    </section>
    )}

    {/* 主体视图 B：独立置顶的审批结果回执面板（默认展开逐项明细，无需滑至页尾与展开折叠） */}
    {activeViewTab === 'results' && (
      <section className="wb-approval-card wbx-section wbx-approval__results-panel" id="price-record-result" aria-label="审批结果回执">
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
                  className="wb-select"
                  aria-label="选择审批回执批次"
                  value={effectiveBatch?.id || ''}
                  onChange={e => {
                    const found = effectiveHistory.find(b => b.id === e.target.value) || null;
                    setReceiptStatusFilter('all');
                    setBatch(found);
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
                onClick={() =>
                  void perform('stop', async () => {
                    setBatch(await request<Batch>(`/batches/${effectiveBatch.id}/stop`, { confirm: true }));
                    void readHistory();
                  })
                }
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
          <div className="pq-empty">
            <CheckCircle2 size={26} />
            <strong>暂无审批结果回执</strong>
            <p>可先切换回“待办审批列表”勾选并提交价格提审单，提交完成后将在此直接展示逐项回执。</p>
            <button
              type="button"
              className="wbx-btn wbx-btn--primary wbx-btn--sm"
              onClick={() => setActiveViewTab('pending')}
            >
              前往待办审批列表
            </button>
          </div>
        ) : (
          <>
            <div className="wbx-approval__result-banner">
              <div className="wbx-approval__result-status">
                <TaskOutcome task={{ status: effectiveBatch.status, kind: 'approval', availableFiles: 1 }} />
              </div>

              <div className="wbx-approval__result-kpis tabular-nums">
                <div className="wbx-approval__result-kpi is-success">
                  <span>已同意</span>
                  <strong>{effectiveBatch.counts.success || 0}</strong>
                </div>
                <div className="wbx-approval__result-kpi is-danger">
                  <span>被拒绝</span>
                  <strong>{effectiveBatch.counts.failed || 0}</strong>
                </div>
                <div className="wbx-approval__result-kpi is-warn">
                  <span>待核实</span>
                  <strong>{effectiveBatch.counts.uncertain || 0}</strong>
                </div>
                <div className="wbx-approval__result-kpi">
                  <span>状态变化</span>
                  <strong>{effectiveBatch.counts.changed || 0}</strong>
                </div>
                <div className="wbx-approval__result-kpi">
                  <span>未提交</span>
                  <strong>{effectiveBatch.counts.not_sent || 0}</strong>
                </div>
                <div className="wbx-approval__result-kpi">
                  <span>等待中</span>
                  <strong>{effectiveBatch.counts.pending || 0}</strong>
                </div>
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
                receiptStatusFilter === 'success'
                  ? allItems.filter(it => it.status === 'success')
                  : receiptStatusFilter === 'issue'
                    ? allItems.filter(it => it.status !== 'success')
                    : allItems;
              return (
                <div className="wbx-approval__receipts">
                  <div className="wbx-approval__receipts-head">
                    <div className="wbx-approval__receipts-title">
                      <strong>逐项审批结果</strong>
                      <span className="wbx-pill wbx-pill--neutral tabular-nums">
                        显示 {shownItems.length} / {allItems.length} 条
                      </span>
                    </div>
                    <div className="wbx-segmented wbx-segmented--compact" role="tablist" aria-label="按回执状态筛选">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={receiptStatusFilter === 'all'}
                        className={`wbx-segmented__item ${receiptStatusFilter === 'all' ? 'is-active' : ''}`}
                        onClick={() => setReceiptStatusFilter('all')}
                      >
                        全部 ({allItems.length})
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={receiptStatusFilter === 'success'}
                        className={`wbx-segmented__item ${receiptStatusFilter === 'success' ? 'is-active' : ''}`}
                        onClick={() => setReceiptStatusFilter('success')}
                      >
                        已同意 ({successCount})
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={receiptStatusFilter === 'issue'}
                        className={`wbx-segmented__item ${receiptStatusFilter === 'issue' ? 'is-active' : ''}`}
                        onClick={() => setReceiptStatusFilter('issue')}
                      >
                        异常/待核实 ({issueCount})
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
    {detail && <WorkbenchDrawer title="价格明细" wide onClose={()=>setDetail(null)}><h3>{code(detail.task)} · {detail.task.cityName} / {detail.task.siteName}</h3><p>{period(detail.task)}</p><PriceTable key={detail.task.id} price={detail.price}/></WorkbenchDrawer>}
  </div>;
}
