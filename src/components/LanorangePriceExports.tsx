import { TaskOutcome } from './TaskOutcome';
import React,{useEffect,useRef,useState} from 'react';
import {LanorangePriceFilters} from './LanorangePriceFilters';
import {WorkbenchDatePicker} from './WorkbenchDatePicker';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';
import {RefreshCw, ArrowRightLeft, BadgeDollarSign, FileSpreadsheet, ShieldCheck, KeyRound, CheckCircle2, Layers} from 'lucide-react';

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
  const activeCount=history.filter(j=>ACTIVE.has(j.status)).length;
  const active=activeCount>0;
  const openLanorangeLogin=()=>{
    window.dispatchEvent(new CustomEvent('workbench:connections',{detail:'lanorange'}));
  };

  return <div className="wb-approvals wbx-approval">
    {/* 顶部：价格审批双模式切换卡 + 导出引擎总览 */}
    <section className="wbx-approval__top-grid" aria-label="价格审批模式与导出总览">
      <div className="wbx-approval__mode-cards" role="tablist" aria-label="价格审批业务切换">
        <button
          type="button"
          role="tab"
          aria-selected={false}
          className="wbx-approval__mode-card"
          disabled={!onSwitchView}
          onClick={() => onSwitchView?.('approval')}
        >
          <div className="wbx-approval__mode-head">
            <span className="wbx-approval__mode-icon">
              <BadgeDollarSign size={18} />
            </span>
            <div className="wbx-approval__mode-titles">
              <span className="wbx-approval__mode-title">本人待办批量审批</span>
              <span className="wbx-approval__mode-sub">蓝橙官方工作流 · 单批上限 200 条</span>
            </div>
            <span className="wbx-approval__mode-radio" aria-hidden="true" />
          </div>
          <p className="wbx-approval__mode-desc">
            自动读取本人名下蓝橙价格提审流程，支持按城市、结算月份、站点多维筛选，跨页勾选并预览明细后一键批量同意当前节点。
          </p>
          <div className="wbx-approval__mode-meta">
            <span>本人节点精准识别</span>
            <span aria-hidden="true">·</span>
            <span>骑手价格版本预审</span>
            <span aria-hidden="true">·</span>
            <span>防重幂等提交</span>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={true}
          className="wbx-approval__mode-card is-active"
        >
          <div className="wbx-approval__mode-head">
            <span className="wbx-approval__mode-icon">
              <FileSpreadsheet size={18} />
            </span>
            <div className="wbx-approval__mode-titles">
              <span className="wbx-approval__mode-title">待审每日价格导出</span>
              <span className="wbx-approval__mode-sub">骑手 × 日期纵向透视导出</span>
            </div>
            <span className="wbx-approval__mode-radio" aria-hidden="true" />
          </div>
          <p className="wbx-approval__mode-desc">
            读取蓝橙有权限站点的审批中与待审核价格档案，自动取最新版本并按“骑手 × 日期”纵向汇总导出标准 Excel 核对表。
          </p>
          <div className="wbx-approval__mode-meta">
            <span>全权限站点覆盖</span>
            <span aria-hidden="true">·</span>
            <span>审批中/待审双态</span>
            <span aria-hidden="true">·</span>
            <span>自动提取最新版</span>
          </div>
        </button>
      </div>

      <aside className="wbx-approval__console-card" aria-label="蓝橙导出统计与操作">
        <div className="wbx-approval__console-head">
          <div>
            <span className="wbx-approval__console-eyebrow">PRICE EXPORT ENGINE</span>
            <h4>每日价格导出工作台</h4>
          </div>
          <span className={`wbx-approval__session-status ${query.month ? 'is-ready' : 'is-warn'}`}>
            <span className="wbx-dot" />
            {query.month ? `目标月份 · ${query.month}` : '待选择结算月份'}
          </span>
        </div>

        <div className="wbx-approval__kpi-grid">
          <div className="wbx-approval__kpi-box">
            <span>结算月份</span>
            <strong>{query.month || '未选'}</strong>
          </div>
          <div className="wbx-approval__kpi-box is-primary">
            <span>执行中任务</span>
            <strong>{activeCount}</strong>
          </div>
          <div className="wbx-approval__kpi-box is-amber">
            <span>最近导出行数</span>
            <strong>{job?.rows ?? 0}</strong>
          </div>
          <div className="wbx-approval__kpi-box is-emerald">
            <span>累计导出记录</span>
            <strong>{history.length}</strong>
          </div>
        </div>

        <div className="wbx-approval__console-actions">
          <button
            type="button"
            className="wbx-btn wbx-btn--ghost wbx-approval__quick-btn"
            disabled={!!busy}
            onClick={() => void refresh()}
          >
            <RefreshCw size={14} className={busy ? 'wbx-spin' : ''} />
            <span>刷新导出记录</span>
          </button>
          <button
            type="button"
            className="wbx-btn wbx-btn--ghost wbx-approval__quick-btn"
            onClick={openLanorangeLogin}
          >
            <KeyRound size={14} />
            <span>蓝橙账号授权</span>
          </button>
          {onSwitchView && (
            <button
              type="button"
              className="wbx-btn wbx-btn--ghost wbx-approval__quick-btn"
              onClick={() => onSwitchView('approval')}
            >
              <ArrowRightLeft size={14} />
              <span>切到批量审批</span>
            </button>
          )}
        </div>
      </aside>
    </section>

    {/* 中部：导出范围配置卡片 */}
    <section className="wb-approval-card">
      <div className="wbx-approval__head mb-3">
        <div className="wbx-approval__queue-title">
          <h3>待审每日价格导出范围配置</h3>
          <p>读取蓝橙有权限站点，按“骑手 × 日期”纵向汇总导出 Excel（含审批中与待审核最新版本，0 保留，空价格留空）</p>
        </div>
      </div>
      <form onSubmit={start}>
        <div className="wb-approval-filters"><LanorangePriceFilters apiFetch={apiFetch} workspaceId={workspaceId} city={query.city} station={query.station} month={query.month} requiredMonth disabled={!!attempt || !!busy} onChange={value=>setQuery({...query,...value})}/></div>
        <details className="wb-price-date-filter"><summary>限定导出日期（可选）</summary><div className="wb-approval-filters"><div className="wb-approval-filter-item"><span>开始日期</span><WorkbenchDatePicker ariaLabel="限定导出开始日期" value={query.date_from} rangeRole="start" rangeStart={query.date_from} rangeEnd={query.date_to} allowClear disabled={!!attempt} onChange={v=>setQuery({...query,date_from:v})}/></div><div className="wb-approval-filter-item"><span>结束日期</span><WorkbenchDatePicker ariaLabel="限定导出结束日期" value={query.date_to} rangeRole="end" rangeStart={query.date_from} rangeEnd={query.date_to} allowClear disabled={!!attempt} onChange={v=>setQuery({...query,date_to:v})}/></div></div></details>
        <div className="wb-approval-toolbar mt-3"><span>状态范围：审批中、待审核（仅取最新版本，0 保留，空价格留空）</span><button className="wbx-btn wbx-btn--primary" disabled={!!busy || active || (!attempt && !query.month)}>{busy==='start'?'正在创建导出…':attempt?'使用原标识再次发起':'开始导出 Excel'}</button></div>
      </form>
      {error && (
        <div className="wb-error wb-error-with-action mt-3" role="alert">
          <div className="wbx-approval__alert-copy">
            <strong>{error.includes('登录') ? '需先完成蓝橙平台登录授权' : '操作提示'}</strong>
            <span>{error}</span>
          </div>
          {error.includes('登录') && (
            <button type="button" className="wb-inline-login-action" onClick={openLanorangeLogin}>
              立即登录蓝橙
            </button>
          )}
        </div>
      )}
      {attempt && <div className="wb-approval-notice mt-3">本次导出提交尚未确认，请先查找已有任务。<button className="wb-button" disabled={!!busy} onClick={()=>void find()}>查找本次导出</button></div>}
    </section>

    {/* 底部：常驻导出结果与站点回执队列 */}
    <section className="wb-approval-card" id="price-record-result">
      <div className="wbx-approval__head">
        <div className="wbx-approval__queue-title">
          <h3>
            导出结果与站点采集回执
            <span>{history.length}</span>
          </h3>
          <p>
            {job
              ? `当前查看月份：${job.query.month} · 已处理 ${job.completed}/${job.total} 个站点周期 · 共生成 ${job.rows} 行`
              : '在上方选择结算月份并点击「开始导出 Excel」后，此处实时展示各站点采集进度与版本回执'}
          </p>
        </div>
        <div className="wbx-approval__actions">
          <button className="wb-button" disabled={!!busy} onClick={()=>void refresh()}>刷新导出记录</button>
        </div>
      </div>

      {!job ? (
        <div className="wbx-approval__empty-stage">
          <div className="wbx-approval__guide-grid">
            <div className="wbx-approval__guide-card">
              <div className="wbx-approval__guide-head">
                <span className="wbx-approval__guide-step">01. 选择结算月份与站点范围</span>
                <Layers size={16} />
              </div>
              <h4>支持全城全站点或定向站点导出</h4>
              <p>
                选定目标结算月份后，可导出账号权限下全部城市站点，也可按特定城市、站点或起止日期范围精确截取。
              </p>
            </div>

            <div className="wbx-approval__guide-card">
              <div className="wbx-approval__guide-head">
                <span className="wbx-approval__guide-step">02. 自动去重提取最新待审版本</span>
                <ShieldCheck size={16} />
              </div>
              <h4>涵盖审批中与待审核双状态</h4>
              <p>
                系统自动遍历站点周期内所有提审版本，仅保留最新版本号的价格记录，零值原样保留、空价格留空。
              </p>
            </div>

            <div className="wbx-approval__guide-card">
              <div className="wbx-approval__guide-head">
                <span className="wbx-approval__guide-step">03. 骑手×日期纵向透视交付</span>
                <CheckCircle2 size={16} />
              </div>
              <h4>一键下载标准 Excel 与采集明细</h4>
              <p>
                导出完成后生成纵向核对 Excel 表，并附带逐站点采集状态、最新版本号与行数回执供财务复核。
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          <TaskOutcome task={{status:job.status,kind:'price-export',availableFiles:['completed','partial'].includes(job.status)?1:0}}/>
          <label className="wb-approval-history mt-3">查看导出<select className="wb-select" value={job.id} onChange={e=>setJob(history.find(j=>j.id===e.target.value)||null)}>{job&&!history.some(j=>j.id===job.id)&&<option value={job.id}>{job.query.month} · 当前任务</option>}{history.map(j=><option key={j.id} value={j.id}>{j.query.month} · {new Date(j.created*1000).toLocaleString('zh-CN')} · {labels[j.status]||j.status}</option>)}</select></label>
          <div className="wb-approval-toolbar mt-3"><div><p>{job.message}</p><p className="wb-muted">已处理{job.completed}/{job.total}个站点周期 · 已生成{job.rows}行</p></div><div className="wb-row">{ACTIVE.has(job.status)&&<button className="wb-button" disabled={!!busy || job.status==='stopping'} onClick={()=>void perform('stop',async()=>{setJob(await request<Export>(`/exports/${job.id}/stop`,{}));})}>停止后续采集</button>}{['completed','partial'].includes(job.status)&&<button className="wb-primary" disabled={!!busy} onClick={()=>void download()}>下载 Excel</button>}</div></div>
          {job.status==='partial' && <p className="wb-error mt-2">部分站点未导出，请按下方失败原因单独筛选处理；当前文件含已成功读取的数据和完整采集记录。</p>}
          <details className="wb-receipts mt-3" key={job.id} open={['partial','failed','interrupted'].includes(job.status)}><summary>采集明细与版本（{job.receipts.length} 条）</summary><div className="wb-approval-table"><table><thead><tr><th>城市 / 站点</th><th>结算周期</th><th>最新版本</th><th>状态</th><th>行数</th><th>结果 / 原因</th></tr></thead><tbody>{job.receipts.map((r,index)=><tr key={index}><td>{r.city}<small>{r.station}</small></td><td>{r.period}</td><td>{r.version || '—'}</td><td>{r.status || '—'}</td><td>{r.row_count}</td><td className={r.result==='失败'?'wb-error':''}>{r.result}<small>{r.message}</small></td></tr>)}</tbody></table></div></details>
        </div>
      )}
    </section>
  </div>;
}

