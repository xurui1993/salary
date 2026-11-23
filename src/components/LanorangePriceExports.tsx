import React,{useEffect,useMemo,useRef,useState} from 'react';
import {LanorangePriceFilters} from './LanorangePriceFilters';
import {WorkbenchDatePicker} from './WorkbenchDatePicker';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';
import {RefreshCw, ArrowRightLeft, CalendarRange, Download, FileSpreadsheet, KeyRound, ChevronRight} from 'lucide-react';

type Query={month:string;city:string;station:string;date_from:string;date_to:string};
type Export={id:string;request_id:string;status:string;created:number;message:string;completed:number;total:number;rows:number;query:Query;receipts:{city:string;station:string;period:string;version:string;status:string;row_count:number;result:string;message:string}[]};
type Attempt={request_id:string;query:Query};
const BASE='/api/fengshen-downloads/lanorange-prices';
const ACTIVE=new Set(['queued','running','stopping']);
const labels:Record<string,string>={queued:'等待采集',running:'正在导出',stopping:'正在停止',completed:'已完成',partial:'部分完成',failed:'导出失败',interrupted:'执行曾中断',cancelled:'已停止'};

function formatCompactStamp(unixSeconds: number): string {
  const d = new Date(unixSeconds * 1000);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${mm}/${dd} ${hh}:${mi}`;
}

function exportStatusTone(status: string): string {
  if (status === 'completed') return 'wbx-pill--done';
  if (status === 'partial' || status === 'interrupted') return 'wbx-pill--warn';
  if (status === 'failed') return 'wbx-pill--danger';
  if (ACTIVE.has(status)) return 'wbx-pill--progress';
  return 'wbx-pill--neutral';
}

export function LanorangePriceExports({apiFetch,workspaceId,lanorangeConnected,onActiveCount,onSwitchView,focusId}:{apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;workspaceId:string;lanorangeConnected?:boolean;onActiveCount:(count:number)=>void;onSwitchView?:(view:'approval'|'price-export')=>void;focusId?:string}){
  const [query,setQuery]=useState<Query>(()=>({month:'2026-10',city:'',station:'',date_from:'',date_to:''}));
  const [history,setHistory]=useState<Export[]>([]),[job,setJob]=useState<Export|null>(null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[attempt,setAttempt]=useState<Attempt|null>(null);
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

  
  async function perform(kind:string,fn:()=>Promise<void>){if(inflight.current)return;inflight.current=true;setBusy(kind);setError('');setNotice('');try{await fn();}catch(err){if(alive.current)setError(err instanceof Error?err.message:'操作未完成');}finally{inflight.current=false;if(alive.current)setBusy('');}}
  async function start(event:React.FormEvent){event.preventDefault();await perform('start',async()=>{
    const current=attempt || {request_id:crypto.randomUUID(),query:{...query}};save(current);
    try{const value=await request<Export>('/exports',current);save(null);setJob(value);void refresh();}
    catch(err){if(err instanceof PlatformAuthError && err.uncertain)throw Error('本次导出提交尚未确认，请先查找本次导出；系统不会自动重发。');save(null);throw err;}
  });}
  async function find(){await perform('find',async()=>{const result=await request<{exports:Export[]}>('/exports');const found=result.exports.find(j=>j.request_id===attempt?.request_id);if(!found)throw Error('尚未找到本次提交，可使用原标识再次发起导出；不会创建重复任务。');setHistory(result.exports);setJob(found);save(null);});}
  async function download(){if(!job)return;await perform('download',async()=>{
    const response=await fetchRef.current(BASE+`/exports/${job.id}/result.xlsx`);if(!response.ok){const value=await response.json();throw Error(value.detail||'文件未就绪或校验失败');}const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`${job.query.month}_蓝橙待审每日价格${job.status==='partial'?'_部分':''}.xlsx`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });}
  const activeCount=history.filter(j=>ACTIVE.has(j.status)).length;
  const active=activeCount>0;
  const hasDateRange = Boolean(query.date_from || query.date_to);

  return <div className="wb-approvals wbx-approval">
    {/* 顶部：极简摘要指标与快捷操作行 */}
    <section className="wbx-ap-topbar" aria-label="每日价格导出摘要与快捷操作">
      <div className="wbx-ap-metrics tabular-nums">
        <span className="wbx-ap-metric">
          <span className="wbx-ap-metric__label">结算月份</span>
          <strong className={`wbx-ap-metric__val ${query.month ? 'is-primary' : ''}`}>{query.month || '未选'}</strong>
        </span>
        <span className="wbx-ap-metric">
          <span className="wbx-ap-metric__label">执行中</span>
          <strong className={`wbx-ap-metric__val ${activeCount > 0 ? 'is-primary' : ''}`}>{activeCount}</strong>
        </span>
        <span className="wbx-ap-metric">
          <span className="wbx-ap-metric__label">最近导出</span>
          <strong className="wbx-ap-metric__val">{job?.rows ?? 0} 行</strong>
        </span>
        <span className="wbx-ap-metric">
          <span className="wbx-ap-metric__label">历史记录</span>
          <strong className="wbx-ap-metric__val">{history.length} 条</strong>
        </span>
      </div>

      <div className="wbx-ap-topbar__right">
        <button
          type="button"
          className="wbx-btn wbx-btn--sm"
          disabled={!!busy}
          onClick={() => void refresh()}
        >
          <RefreshCw size={13} className={busy ? 'wbx-spin' : ''} />
          <span>刷新记录</span>
        </button>
        {onSwitchView && (
          <button
            type="button"
            className="wbx-btn wbx-btn--ghost wbx-btn--sm"
            onClick={() => onSwitchView('approval')}
          >
            <ArrowRightLeft size={13} />
            <span>前往批量审批</span>
          </button>
        )}
      </div>
    </section>

    {/* 主体 1：导出范围配置卡片 */}
    <section className="wbx-ap-card">
      <div className="wbx-approval__head">
        <div className="wbx-approval__queue-title">
          <h3>待审每日价格导出范围配置</h3>
          <p>读取蓝橙权限站点最新待审价格档案，按“骑手 × 日期”纵向汇总导出标准 Excel</p>
        </div>
      </div>

      <form onSubmit={start} className="wbx-ap-form">
        <div className="wbx-ap-form-grid">
          <LanorangePriceFilters
            apiFetch={apiFetch}
            workspaceId={workspaceId}
            city={query.city}
            station={query.station}
            month={query.month}
            requiredMonth
            lanorangeConnected={lanorangeConnected}
            disabled={!!attempt || !!busy}
            onChange={value=>setQuery({...query,...value})}
          />
        </div>

        <div className="wbx-ap-form-foot wbx-ap-form-foot--export">
          <div className="wbx-ap-form-foot__left">
            <details className="wbx-ap-date-disclosure" open={hasDateRange}>
              <summary>
                <CalendarRange size={13} aria-hidden="true" />
                <span>限定导出日期（可选）</span>
                {hasDateRange && (
                  <span className="wbx-ap-date-badge tabular-nums">
                    {query.date_from || '起'} ~ {query.date_to || '止'}
                  </span>
                )}
              </summary>
              <div className="wbx-ap-date-grid">
                <div className="wbx-ap-field">
                  <span className="wbx-ap-field__label">开始日期</span>
                  <WorkbenchDatePicker ariaLabel="限定导出开始日期" value={query.date_from} rangeRole="start" rangeStart={query.date_from} rangeEnd={query.date_to} allowClear disabled={!!attempt} onChange={v=>setQuery({...query,date_from:v})}/>
                </div>
                <div className="wbx-ap-field">
                  <span className="wbx-ap-field__label">结束日期</span>
                  <WorkbenchDatePicker ariaLabel="限定导出结束日期" value={query.date_to} rangeRole="end" rangeStart={query.date_from} rangeEnd={query.date_to} allowClear disabled={!!attempt} onChange={v=>setQuery({...query,date_to:v})}/>
                </div>
              </div>
            </details>
            <span className="wbx-ap-form-hint">范围：审批中、待审核（仅取最新版，0 保留）</span>
          </div>
          <button
            type="submit"
            className="wbx-btn wbx-btn--primary"
            disabled={!!busy || active || (!attempt && !query.month)}
          >
            <FileSpreadsheet size={14} aria-hidden="true" />
            <span>{busy==='start'?'正在创建导出…':attempt?'使用原标识再次发起':'开始导出 Excel'}</span>
          </button>
        </div>
      </form>

      {notice && (
        <div className="wbx-approval__notice-bar mt-3" role="status">
          <span>{notice}</span>
          <button type="button" className="wbx-btn wbx-btn--ghost wbx-btn--sm" onClick={() => setNotice('')}>
            知道了
          </button>
        </div>
      )}

      {error && (
        <div className={`wbx-ap-notice mt-3 ${error.includes('登录') ? 'is-auth' : 'is-danger'}`} role="alert">
          <div className="wbx-ap-notice__body">
            <KeyRound size={15} className="wbx-ap-notice__icon" aria-hidden="true" />
            <div className="wbx-ap-notice__copy">
              <strong>{error.includes('登录') ? '请点击页面顶部「去登录」完成蓝橙平台授权' : '操作提示'}</strong>
              {!error.includes('登录') && <span>{error}</span>}
            </div>
          </div>
        </div>
      )}
      {attempt && (
        <div className="wb-approval-notice mt-3">
          <span>本次导出提交尚未确认，请先查找已有任务。</span>
          <button type="button" className="wbx-btn wbx-btn--sm" disabled={!!busy} onClick={()=>void find()}>
            查找本次导出
          </button>
        </div>
      )}
    </section>

    {/* 主体 2：导出结果与站点采集回执 */}
    <section className="wbx-ap-card" id="price-record-result">
      <div className="wbx-approval__head">
        <div className="wbx-approval__queue-title">
          <h3>
            导出结果与站点采集回执
            <span>{history.length}</span>
          </h3>
          <p className="tabular-nums">
            {job
              ? `当前查看 ${job.query.month} · 共 ${job.total} 个站点周期`
              : '选择结算月份并点击「开始导出 Excel」后，此处实时展示各站点采集进度与版本回执'}
          </p>
        </div>
        {history.length > 0 && (
          <div className="wbx-approval__actions">
            <label className="wbx-approval__batch-picker">
              <span>切换记录</span>
              <select
                className="wbx-ap-select wbx-ap-select--history"
                aria-label="选择历史导出记录"
                value={job?.id || ''}
                onChange={e => {
                  setJob(history.find(j => j.id === e.target.value) || null);
                }}
              >
                {job && !history.some(j => j.id === job.id) && (
                  <option value={job.id}>{job.query.month} · 当前任务</option>
                )}
                {history.map(j => (
                  <option key={j.id} value={j.id}>
                    {j.query.month} · {formatCompactStamp(j.created)} · {labels[j.status] || j.status}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {!job ? (
        <div className="wbx-ap-empty wbx-ap-empty--compact">
          <div className="wbx-ap-steps" aria-label="导出流程说明">
            <div className="wbx-ap-step">
              <span className="wbx-ap-step__num">01</span>
              <div>
                <strong>选定月份与范围</strong>
                <p>默认覆盖全部权限站点，可按城市、站点或日期截取</p>
              </div>
            </div>
            <ChevronRight size={15} className="wbx-ap-step__arrow" aria-hidden="true" />
            <div className="wbx-ap-step">
              <span className="wbx-ap-step__num">02</span>
              <div>
                <strong>提取最新待审版本</strong>
                <p>涵盖审批中与待审核双态，自动去重仅取最新版本</p>
              </div>
            </div>
            <ChevronRight size={15} className="wbx-ap-step__arrow" aria-hidden="true" />
            <div className="wbx-ap-step">
              <span className="wbx-ap-step__num">03</span>
              <div>
                <strong>导出纵向核对表</strong>
                <p>生成骑手 × 日期 Excel 并附逐站点版本行数回执</p>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="wbx-export-result-body">
          <div className="wbx-export-receipt-strip">
            <div className="wbx-export-receipt-strip__left">
              <span className={`wbx-pill ${exportStatusTone(job.status)}`}>
                <span className="wbx-pill__dot" aria-hidden="true" />
                {labels[job.status] || job.status}
              </span>
              <span className="wbx-export-receipt-strip__msg">{job.message}</span>
              <span className="wbx-export-receipt-strip__meta tabular-nums">
                {job.completed}/{job.total} 站点周期 · {job.rows} 行
              </span>
            </div>
            <div className="wbx-export-receipt-strip__actions">
              {ACTIVE.has(job.status)&&(
                <button type="button" className="wbx-btn wbx-btn--sm wbx-btn--danger" disabled={!!busy || job.status==='stopping'} onClick={()=>void perform('stop',async()=>{setJob(await request<Export>(`/exports/${job.id}/stop`,{}));})}>
                  停止后续采集
                </button>
              )}
              {['completed','partial'].includes(job.status)&&(
                <button type="button" className="wbx-btn wbx-btn--secondary wbx-btn--sm" disabled={!!busy} onClick={()=>void download()}>
                  <Download size={13.5} aria-hidden="true" />
                  <span>下载 Excel</span>
                </button>
              )}
            </div>
          </div>
          {job.status==='partial' && <p className="wb-error mt-2">部分站点未导出，请按下方失败原因单独筛选处理；当前文件含已成功读取的数据和完整采集记录。</p>}
          <details className="wb-receipts mt-2.5" key={job.id} open={true}>
            <summary>采集明细与版本（{job.receipts.length} 条）</summary>
            <div className="wb-approval-table">
              <table>
                <thead><tr><th>城市 / 站点</th><th>结算周期</th><th>最新版本</th><th>状态</th><th>行数</th><th>结果 / 原因</th></tr></thead>
                <tbody>
                  {job.receipts.map((r,index)=>(
                    <tr key={index}>
                      <td>{r.city}<small>{r.station}</small></td>
                      <td className="tabular-nums">{r.period}</td>
                      <td className="tabular-nums">{r.version || '—'}</td>
                      <td>
                        <span className={`wbx-pill ${r.status === '审批中' ? 'wbx-pill--progress' : r.status === '待审核' ? 'wbx-pill--warn' : 'wbx-pill--neutral'}`}>
                          <span className="wbx-pill__dot" aria-hidden="true" />
                          {r.status || '—'}
                        </span>
                      </td>
                      <td className="tabular-nums">{r.row_count}</td>
                      <td className={r.result==='失败'?'wb-error':''}>
                        <span className={`wbx-export-res-tag ${r.result==='失败' ? 'is-fail' : 'is-ok'}`}>{r.result}</span>
                        <small>{r.message}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </section>
  </div>;
}


