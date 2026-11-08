import type { PayrollReview } from './PayrollReviewSummary';
import React, { useState, useRef } from 'react';
import { PayrollPerformancePanel, type PayrollPerformance } from './PayrollPerformancePanel';
import { inferDatasetSystemTag } from '../lib/workbench';
import { Search, Filter, RefreshCw, Upload, CheckSquare, Sparkles } from 'lucide-react';

export interface PayrollPreparationState {
  id: string;
  mode: 'manual' | 'fengshen' | 'xiaoxiang';
  status: string;
  workflow?: string;
  only_separation?: boolean;
  exclude_separation?: boolean;
  download_scope?: string;
  execution_logs?: {text:string;level:string}[];
  input_policy?: string;
  automatic_deductions?: {zero_stations:string[];sources:{station:{name:string};source:string}[]};
  pause_reason?: string;
  stop_requested?: boolean;
  execution?: {waiting_login:boolean;waiting_verification?:boolean;phase:string};
  execution_started_at?: string;
  downloads?: {key:string;label:string;status:string;detail:string;completed_groups:number;total_groups:number;groups:{scope:string;label:string;status:string;detail:string;error?:string;files:string[]}[]}[];
  performance?: PayrollPerformance;
  created_at?: string;
  result?: { output: string; input_hashes_verified: boolean; review_summary?: PayrollReview };
  deductions?: { version: string; scope: string; frozen: boolean };
  plan: {city: string; start: string; end: string; month: string; applicants: number};
  jobs: string[];
  items: Record<string, {label: string; status: string; error?: string; recovery_allowed?: boolean}>;
}

export const PayrollPreparation = React.memo(function PayrollPreparation({value, busy, apiFetch, onChange, onContinue, upload}: {
  value: PayrollPreparationState; busy: boolean;
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  onChange: (value: PayrollPreparationState) => void;
  onContinue: () => void;
  upload: (file: File) => Promise<{path: string} | null>;
}) {
  const [pending, setPending] = useState(false);
  const [confirmOmitAll, setConfirmOmitAll] = useState(false);
  const bulkPending = useRef(false);
  const [error, setError] = useState('');
  const [filterStatus, setFilterStatus] = useState<'all' | 'pending' | 'ready'>('pending');
  const [searchTerm, setSearchTerm] = useState('');
  const [showOptional, setShowOptional] = useState(false);
  const [reusable, setReusable] = useState<{run_id: string; file_id: string; dataset: string; name: string; created_at: string}[] | null>(null);

  async function findReusable() {
    setPending(true); setError('');
    try {
      const response = await apiFetch(`/api/workbench/batches/${value.id}/reusable`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '已有资料读取失败');
      setReusable(data.files);
    } catch (error) { setError(error instanceof Error ? error.message : '读取失败'); }
    finally { setPending(false); }
  }

  async function reuse(file: {run_id: string; file_id: string}) {
    setPending(true); setError('');
    try {
      const response = await apiFetch(`/api/workbench/batches/${value.id}/reuse`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(file)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '资料引用失败');
      onChange(result); setReusable(null);
      if (result.status === 'ready') onContinue();
    } catch (error) { setError(error instanceof Error ? error.message : '引用失败'); }
    finally { setPending(false); }
  }

  async function resolve(dataset: string, action: string, file?: File) {
    setPending(true); setError('');
    try {
      const source = file ? await upload(file) : null;
      if (file && !source) return;
      const response = await apiFetch(`/api/parttime/preparations/${value.id}/${file ? 'supplement' : 'resolve'}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(file ? {dataset, path: source!.path} : {dataset, action}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '资料处理失败');
      onChange(result);
      if (action === 'retry' || result.status === 'ready') onContinue();
    } catch (e) { setError(e instanceof Error ? e.message : '资料处理失败'); }
    finally { setPending(false); }
  }

  const [confirmOmitKind, setConfirmOmitKind] = useState<string | null>(null);
  const missing = Object.values(value.items).filter(item => !['ready', 'omitted'].includes(item.status)).length;

  const requiredMissing = Object.entries(value.items).filter(([kind,item])=>kind==='delivery_fee' && !['ready','omitted'].includes(item.status)).length;
  const optionalMissing = Object.entries(value.items).filter(([kind,item])=>kind!=='delivery_fee' && !['ready','omitted'].includes(item.status)).length;
  const readyCount = Object.values(value.items).filter(item=>item.status==='ready').length;
  const filteredItems = Object.entries(value.items).filter(([kind, item]) => {
    const matchesSearch = item.label.toLowerCase().includes(searchTerm.toLowerCase()) || kind.toLowerCase().includes(searchTerm.toLowerCase());
    if (!matchesSearch) return false;
    if (filterStatus === 'ready') return item.status === 'ready';
    if (filterStatus === 'pending') return item.status !== 'ready' && item.status !== 'omitted' && (kind === 'delivery_fee' || showOptional || !requiredMissing || !!searchTerm);
    return true;
  }).sort(([a],[b]) => Number(b==='delivery_fee')-Number(a==='delivery_fee'));

  return <section className="wb-preparation" aria-label="核算资料清单">
    <p className="wb-notice" role="status">{value.plan.city} · {value.plan.start} 至 {value.plan.end}：必需缺项 {requiredMissing} 项，可选待处理 {optionalMissing} 项，已就绪 {readyCount} 项。{requiredMissing ? '先补齐必需资料。' : optionalMissing ? '可选项需补传或明确选择不提供。' : '资料已齐全，可以继续处理。'}</p>
    <details className="wb-advanced"><summary>资料准备性能记录</summary><PayrollPerformancePanel value={value.performance} /></details>
    <div className="flex items-center justify-between flex-wrap gap-2">
      <div>
        <h3 className="font-medium text-slate-900">资料准备 · {{pending_download: '待准备', preparing: '准备中', waiting_materials: '等待处理', ready: '已就绪', calculating: '核算中', calculated: '已核算'}[value.status] || value.status}</h3>
        <p className="text-xs text-slate-500">{value.mode === 'xiaoxiang' ? '美团灯塔 · 手动上传本批次资料' : `淘宝闪购 · 月账单 ${value.plan.month} 整月（风神 + 蓝橙联动）`}</p>
      </div>

      {/* 快捷搜素与状态筛选栏 */}
      <div className="flex items-center gap-2 text-xs">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2 text-slate-400" />
          <input
            type="text"
            placeholder="搜资料名称..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-7 pr-2 py-1 text-xs border border-slate-200 rounded-lg bg-white w-32 focus:outline-hidden focus:ring-1 focus:ring-blue-500"
          />
        </div>
        {Object.entries(value.items).some(([kind, item]) => kind !== 'delivery_fee' && !['ready', 'omitted'].includes(item.status)) && (
          <button
            type="button"
            disabled={pending}
            onClick={() => setConfirmOmitAll(true)}
            className="px-2.5 py-1 text-xs font-semibold rounded-lg border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 flex items-center gap-1 shrink-0"
            title="仅作用于本批次可选缺项，确认后标注为未提供"
          >
            本批次可选缺项均不提供
          </button>
        )}
        <div className="wb-segment">
          <button
            type="button"
            className={filterStatus === 'all' ? 'is-active' : ''}
            onClick={() => setFilterStatus('all')}
          >
            全部
          </button>
          <button
            type="button"
            className={filterStatus === 'pending' ? 'is-active' : ''}
            onClick={() => setFilterStatus('pending')}
          >
            待补 ({missing})
          </button>
          <button
            type="button"
            className={filterStatus === 'ready' ? 'is-active' : ''}
            onClick={() => setFilterStatus('ready')}
          >
            就绪 ({readyCount})
          </button>
        </div>
      </div>
    </div>

    {confirmOmitAll && <section role="alert" className="wb-notice" aria-label="确认本批次可选资料范围">
      <p>以下可选资料将标注为本批次未提供；必需配送费不会被忽略：</p>
      <ul>{Object.entries(value.items).filter(([kind,item])=>kind!=='delivery_fee' && !['ready','omitted'].includes(item.status)).map(([kind,item])=><li key={kind}>{item.label}</li>)}</ul>
      <div className="wb-row"><button type="button" className="wb-button" disabled={pending} onClick={()=>setConfirmOmitAll(false)}>返回补传资料</button>
      <button type="button" className="wb-button" disabled={pending || busy} onClick={async()=>{
        if(bulkPending.current)return; bulkPending.current=true; setPending(true);setError('');
        try {
          let latest = value;
          for(const [dataset,item] of Object.entries(value.items)) {
            if(dataset==='delivery_fee' || ['ready','omitted'].includes(item.status))continue;
            const response=await apiFetch(`/api/parttime/preparations/${value.id}/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset,action:'omit'})});
            const result=await response.json(); if(!response.ok)throw new Error(result.detail || '本批次资料标注失败，已处理项保留');
            latest = result; onChange(result);
          }
          setConfirmOmitAll(false);
          if (latest.status === 'ready') onContinue();
        } catch(error) {setError(error instanceof Error ? error.message : '处理失败，请检查本批次资料');}
        finally {bulkPending.current=false;setPending(false);}
      }}>确认本批次可选缺项均不提供</button></div>
    </section>}

    <details className="wb-materials" key={`${value.id}:${value.status}`} open={missing > 0}>
      <summary className="cursor-pointer font-medium mb-3">
        资料清单 · {Object.keys(value.items).length - missing}/{Object.keys(value.items).length} 项已处理{missing ? ` · ${missing} 项待处理` : ''}
      </summary>

      {filterStatus === 'pending' && requiredMissing > 0 && optionalMissing > 0 && <button type="button" className="wb-button" aria-expanded={showOptional} onClick={()=>setShowOptional(v=>!v)}>{showOptional ? '收起可选缺项' : `展开可选待处理资料（${optionalMissing}）`}</button>}
      <div className="space-y-2 mt-2">
        {filteredItems.length === 0 ? (
          <p className="text-xs text-slate-400 py-4 text-center">{filterStatus === 'pending' && !missing ? '缺项已处理；本次操作齐套后继续核算，已就绪资料可切换筛选查看。' : '无匹配资料项'}</p>
        ) : (
          filteredItems.map(([kind, item]) => {
            const sysTag = inferDatasetSystemTag(kind, value.mode);
            const sysKey = sysTag === '蓝橙' ? 'lanorange' : sysTag === '灯塔' ? 'dengta' : 'fengshen';
            const isRequired = kind === 'delivery_fee';
            const statusClass = item.status === 'ready' ? 'is-ready' : item.status === 'failed' ? 'is-failed' : item.status === 'omitted' ? 'is-omitted' : 'is-pending';
            const statusLabel = { pending: '待下载', failed: '需要处理', ready: '已就绪', omitted: '未提供' }[item.status] || item.status;
            return (
              <div key={kind} className={`wb-checklist-card ${statusClass}`}>
                <div className="wb-checklist-header">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`wb-sys-badge is-${sysKey}`}>{sysTag}</span>
                    <span className="font-semibold text-sm text-slate-900">{item.label}</span>
                    <span className={`text-[11px] px-1.5 py-0.5 rounded font-mono ${isRequired ? 'bg-rose-50 text-rose-600 border border-rose-200' : 'bg-slate-100 text-slate-600'}`}>
                      {isRequired ? '必需资料' : '可选'}
                    </span>
                  </div>
                  <span className={`wb-checklist-status-badge ${statusClass}`}>
                    {item.status === 'ready' && '✓ '}
                    {statusLabel}
                  </span>
                </div>

                {item.error && item.status === 'failed' && /登录|认证|会话|权限/.test(item.error) && <button type="button" className="wb-button" onClick={() => window.dispatchEvent(new CustomEvent('workbench:connections',{detail:sysKey === 'dengta' ? 'xiaoxiang' : sysKey}))}>检查平台连接</button>}
                {item.error && item.status === 'failed' && (
                  <p className="text-xs text-rose-700 bg-rose-50/80 p-2 rounded border border-rose-200">{item.error}</p>
                )}

                {!busy && (item.status === 'failed' || (value.status === 'pending_download' && item.status === 'pending')) && (
                  <div className="wb-checklist-actions">
                    {item.recovery_allowed && (
                      <button
                        type="button"
                        className="wb-button text-xs py-1 px-2.5 min-h-[30px]"
                        disabled={pending}
                        onClick={() => void resolve(kind, 'retry')}
                      >
                        重试此项
                      </button>
                    )}
                    <label className="wb-button text-xs py-1 px-2.5 min-h-[30px] cursor-pointer inline-flex items-center gap-1.5">
                      <span>手动补传 Excel</span>
                      <input
                        type="file"
                        className="hidden"
                        accept=".xlsx,.xls,.csv"
                        disabled={pending}
                        onChange={event => {
                          const file = event.target.files?.[0];
                          event.target.value = '';
                          if (file) void resolve(kind, 'supplement', file);
                        }}
                      />
                    </label>
                    {!isRequired && (
                      confirmOmitKind === kind ? (
                        <div className="inline-flex items-center gap-1.5 bg-amber-50 border border-amber-300 p-1 rounded text-xs">
                          <span className="text-amber-800">确认不提供？核算将标注缺失</span>
                          <button
                            type="button"
                            className="text-xs text-rose-600 font-semibold px-1.5 py-0.5 rounded hover:bg-rose-100"
                            disabled={pending}
                            onClick={() => {
                              setConfirmOmitKind(null);
                              void resolve(kind, 'omit');
                            }}
                          >
                            确认本项不提供
                          </button>
                          <button
                            type="button"
                            className="text-xs text-slate-500 px-1 py-0.5 rounded hover:bg-slate-100"
                            onClick={() => setConfirmOmitKind(null)}
                          >
                            取消
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="wb-link text-xs text-slate-500 hover:text-slate-700"
                          disabled={pending}
                          onClick={() => setConfirmOmitKind(kind)}
                        >
                          不提供此项
                        </button>
                      )
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </details>

    {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
    {!busy && value.status === 'pending_download' && <div className="wb-action-bar"><span className="wb-muted">{value.plan.city} · {missing} 项待准备</span><button className="wb-primary" disabled={pending} onClick={onContinue}>下载本批次缺项</button><button className="wb-button" disabled={pending} onClick={() => void findReusable()}>查找本批次可复用资料</button></div>}
    {reusable && <div className="wb-reusable"><p className="wb-muted">仅列出城市、周期完全匹配且已完成的资料。引用后保留来源及文件校验记录。</p>{!reusable.length && <p className="wb-muted">暂无符合条件的已有资料，可下载或手动补传。</p>}{reusable.map(file => <div className="wb-row wb-space" key={`${file.run_id}:${file.file_id}`}><span className="wb-file-name">{file.name}<small className="block wb-muted">{file.created_at}</small></span><button className="wb-button" disabled={pending} onClick={() => void reuse(file)}>引用此文件到本批次</button></div>)}</div>}
    {!busy && value.status === 'ready' && <div className="wb-action-bar"><span className="wb-muted">资料已就绪 · 核对本次扣款金额和站点归属</span><button disabled={pending} onClick={onContinue} className="wb-primary">确认扣款清单</button></div>}
    {!busy && value.status === 'preparing' && <button disabled={pending} onClick={onContinue} className="rounded border border-blue-600 text-blue-700 bg-blue-50 px-4 py-2">继续检查原下载任务</button>}
    {value.jobs.length > 0 && <details className="wb-advanced"><summary>资料处理记录</summary><p className="wb-muted">关联下载：{value.jobs.map(id => id.slice(0, 6).toUpperCase()).join('、')}。认证与恢复沿用原任务。</p></details>}
  </section>;
});
