import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Download,
  FolderOpen,
  ListChecks,
  Loader2,
  RefreshCw,
  AlertCircle,
  XCircle,
} from 'lucide-react';
import { readDownloadResponse, saveDownloadBlob, downloadErrorMessage } from '../lib/outputDownload';
import { taskGuidance } from '../lib/taskGuidance';
import { datasetGroup, type DownloadFetch } from '../lib/downloadCenterLogic';

interface HeaderTaskFile {
  id: string;
  run_id: string;
  name: string;
  city: string;
  bytes: number;
  available: boolean;
}

interface HeaderTaskRecord {
  id: string;
  kind: string;
  title?: string;
  price_id?: string;
  batch_id?: string;
  cities: string[];
  datasets: string[];
  start: string;
  end: string;
  status: string;
  created_at: string;
  files: HeaderTaskFile[];
  available_files: number;
  failed_items: number;
  completed_items: number;
  total_items: number;
  action_run_id: string;
  summary_issue?: boolean;
}

const API = '/api/workbench/task-center';
const ACTIVE_STATUSES = new Set([
  'queued',
  'running',
  'waiting_login',
  'waiting_manual',
  'cancelling',
  'preparing',
  'stopping',
]);

const SYSTEMS: Record<string, string> = {
  fengshen: '风神',
  lanorange: '蓝橙',
  baize: '商翼',
  benlai: '本来人力',
  xiaoxiang: '灯塔',
};

const KINDS: Record<string, string> = {
  download: '资料采集',
  generate: '专项报表',
  approval: '价格审批',
  'price-export': '每日价格',
};

const DATASET_NAMES: Record<string, string> = {
  rider_info: '骑手信息',
  attendance_detail: '骑手出勤明细',
  fraud: '欺诈单',
  problem: '问题单',
  delivery_waybill: '配送运单',
  rider_bill: '骑手账单',
  daily_analysis: '日分析数据',
  lanorange_staff: '在职人员',
  lanorange_batch_quit: '批次离职人员',
  lanorange_accommodation: '住宿人员',
  lanorange_insurance: '投保人员',
  lanorange_prices: '价格档案',
  payment_binding: '支付绑定',
  abnormal_followup: '异常跟进',
  abnormal_riders: '异常名单',
  baize_employees: '商翼员工总表',
  benlai_employees: '本来人力灵工总表',
  rider_archive: '骑手档案',
  rider_daily: '骑手日数据',
  rider_order_detail: '配送单明细',
  xiaoxiang_attendance_detail: '考勤明细',
};

const formatSize = (bytes: number) =>
  bytes >= 1048576
    ? `${(bytes / 1048576).toFixed(1)} MB`
    : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;

const formatTime = (value: string) => {
  if (!value) return '';
  try {
    return new Date(value).toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return '';
  }
};

export function HeaderDownloadCenter({
  apiFetch,
  datasetLabel = (id: string) => DATASET_NAMES[id] || id,
  activeCount = 0,
  runningTask,
  progress,
  progressText,
  onOpenTaskCenter,
  onNavigateHistory,
  onOpenTaskRecord,
  onOpenPlatformAuth,
  onShowToast,
}: {
  apiFetch: DownloadFetch;
  datasetLabel?: (id: string) => string;
  activeCount?: number;
  runningTask?: string | null;
  progress?: number;
  progressText?: string;
  onOpenTaskCenter?: () => void;
  onNavigateHistory?: () => void;
  onOpenTaskRecord?: (record: HeaderTaskRecord) => void;
  onOpenPlatformAuth?: (platformKey: string) => void;
  onShowToast?: (message: string, type?: 'info' | 'success' | 'error') => void;
}) {
  const apiRef = useRef(apiFetch);
  apiRef.current = apiFetch;

  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState<HeaderTaskRecord[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [downloadingId, setDownloadingId] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'all' | 'active' | 'done'>('all');
  const containerRef = useRef<HTMLDivElement>(null);

  const navigateToTaskCenter = () => {
    if (onOpenTaskCenter) onOpenTaskCenter();
    else if (onNavigateHistory) onNavigateHistory();
  };

  const loadRecentTasks = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const response = await apiRef.current(`${API}?page=1&status=&q=&archived=0`, {
        signal: AbortSignal.timeout(20000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '任务列表暂不可读');
      setRecords(Array.isArray(data.records) ? data.records.slice(0, 12) : []);
      setCounts(data.counts || {});
      setError('');
    } catch (err) {
      if (!silent) setError(downloadErrorMessage(err));
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    void loadRecentTasks(true);
  }, [activeCount, runningTask]);

  useEffect(() => {
    if (!open) return;
    void loadRecentTasks(false);
    const timer = setInterval(() => {
      void loadRecentTasks(true);
    }, 4000);
    return () => clearInterval(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleEsc);
    };
  }, [open]);

  const recordTitle = (r: HeaderTaskRecord) =>
    r.title ||
    r.datasets
      .map(datasetLabel)
      .join('、')
      .replaceAll('（生成表）', '');

  const recordPlatform = (r: HeaderTaskRecord) =>
    r.price_id
      ? '蓝橙'
      : [...new Set(r.datasets.map(id => SYSTEMS[datasetGroup(id)] || '风神'))].join(' / ');

  const triggerDownload = async (r: HeaderTaskRecord, file?: HeaderTaskFile) => {
    if (downloadingId) return;
    setDownloadingId(file ? `${r.id}:${file.id}` : r.id);
    setError('');
    setNotice('');
    try {
      let url = '';
      let filename = '';
      if (r.kind === 'approval') {
        url = `/api/fengshen-downloads/lanorange-approvals/batches/${r.price_id}/result.csv`;
        filename = '蓝橙价格审批回执.csv';
      } else if (r.kind === 'price-export') {
        url = `/api/fengshen-downloads/lanorange-prices/exports/${r.price_id}/result.xlsx`;
        filename = '蓝橙待审每日价格.xlsx';
      } else if (file) {
        url = `/api/fengshen-downloads/runs/${file.run_id}/files/${file.id}`;
        filename = file.name || `结果_${r.id.slice(0, 8)}.xlsx`;
      } else {
        const availableFiles = (r.files || []).filter(f => f.available);
        if (availableFiles.length === 1) {
          const single = availableFiles[0];
          url = `/api/fengshen-downloads/runs/${single.run_id}/files/${single.id}`;
          filename = single.name;
        } else {
          url = `/api/fengshen-downloads/records/${r.id}/bundle`;
          filename = `结果_${r.id.slice(0, 8)}.zip`;
        }
      }
      const response = await apiRef.current(url, { signal: AbortSignal.timeout(120000) });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || '文件下载未完成，请重试');
      }
      const disposition = response.headers.get('content-disposition') || '';
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
      if (encoded) {
        try {
          const decoded = decodeURIComponent(encoded);
          if (decoded && !/[\\/\x00-\x1f]/.test(decoded)) filename = decoded;
        } catch {
          // ignore
        }
      }
      const blob = await readDownloadResponse(response, filename);
      saveDownloadBlob(blob, filename);
      setNotice(`已保存：${filename}`);
      onShowToast?.(`已保存：${filename}`, 'success');
    } catch (err) {
      const msg = downloadErrorMessage(err);
      setError(msg);
      onShowToast?.(msg, 'error');
    } finally {
      setDownloadingId('');
    }
  };

  const liveActiveCount = Math.max(activeCount + (runningTask ? 1 : 0), counts.active || 0);
  const readyCount = counts.success || 0;
  const filteredRecords = records.filter(r => {
    const isAct = ACTIVE_STATUSES.has(r.status);
    if (tab === 'active') return isAct;
    if (tab === 'done') return !isAct;
    return true;
  });

  return (
    <div className="wbx-popover-wrap" ref={containerRef}>
      <button
        type="button"
        className={`wbx-header-tool-btn wbx-cluster-item wbx-popover-trigger${open ? ' is-open' : ''}${liveActiveCount > 0 ? ' is-busy' : ''}`}
        aria-label="打开最近任务与下载中心"
        aria-expanded={open}
        onClick={() => setOpen(value => !value)}
      >
        {liveActiveCount > 0 ? (
          <Loader2 size={14} className="wbx-spin wbx-header-tool-icon is-active" aria-hidden="true" />
        ) : (
          <ListChecks size={14} className="wbx-header-tool-icon" aria-hidden="true" />
        )}
        <span>任务动态</span>
        {liveActiveCount > 0 ? (
          <span className="wbx-header-tool-live tabular-nums" title={`${liveActiveCount} 个任务进行中`}>
            {liveActiveCount} 运行中
          </span>
        ) : readyCount > 0 ? (
          <span className="wbx-header-tool-count tabular-nums" title={`累计 ${readyCount} 个已完成任务`}>
            {readyCount}
          </span>
        ) : null}
      </button>

      {open && (
        <div className="wbx-popover wbx-popover--tasks" role="dialog" aria-label="最近任务与快捷下载">
          <div className="wbx-popover__head">
            <div className="wb-download-drawer-title">
              <strong>最近任务与文件领取</strong>
              <span className="wb-download-drawer-sub tabular-nums">
                进行中 {liveActiveCount} · 已完成 {readyCount}
              </span>
            </div>
            <div className="wbx-popover__actions">
              <button
                type="button"
                className="wb-icon"
                title="刷新任务状态"
                onClick={() => void loadRecentTasks(false)}
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              </button>
              <button
                type="button"
                className="wb-link text-xs inline-flex items-center gap-1"
                onClick={() => {
                  setOpen(false);
                  navigateToTaskCenter();
                }}
              >
                <span>进入任务中心</span>
                <ArrowUpRight size={13} />
              </button>
            </div>
          </div>

          {runningTask && (
            <div className="mb-2.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
              <div className="flex items-center justify-between font-semibold">
                <span>正在执行本地任务</span>
                <span className="tabular-nums">{Math.round(progress || 0)}%</span>
              </div>
              {progressText && <p className="mt-1 text-slate-600 truncate">{progressText}</p>}
            </div>
          )}

          <div className="wb-download-drawer-tabs" role="tablist">
            {(
              [
                ['all', `全部 (${records.length})`],
                ['active', `进行中 (${records.filter(r => ACTIVE_STATUSES.has(r.status)).length})`],
                ['done', `已就绪 (${records.filter(r => !ACTIVE_STATUSES.has(r.status)).length})`],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                className={`wb-download-tab ${tab === key ? 'is-active' : ''}`}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {error && (
            <p role="alert" className="wb-download-drawer-alert is-error">
              <AlertCircle size={14} />
              <span>{error}</span>
            </p>
          )}
          {notice && (
            <p role="status" className="wb-download-drawer-alert is-ok">
              <CheckCircle2 size={14} />
              <span>{notice}</span>
            </p>
          )}

          <div className="wb-download-drawer-list">
            {loading && records.length === 0 ? (
              <div className="wb-download-drawer-empty">
                <Loader2 size={16} className="animate-spin" />
                <span>正在读取任务列表…</span>
              </div>
            ) : filteredRecords.length === 0 ? (
              <div className="wb-download-drawer-empty">
                <span>
                  {tab === 'active'
                    ? '当前没有正在执行的后台任务'
                    : '暂无任务记录，可在数据采集页发起新任务'}
                </span>
              </div>
            ) : (
              filteredRecords.map(r => {
                const isAct = ACTIVE_STATUSES.has(r.status);
                const guidance = taskGuidance({
                  status: r.status,
                  kind: r.kind,
                  availableFiles: r.available_files,
                  failedItems: r.failed_items,
                  summaryIssue: r.summary_issue,
                });
                const pct =
                  r.total_items > 0
                    ? Math.round((r.completed_items / Math.max(1, r.total_items)) * 100)
                    : isAct
                      ? 15
                      : 100;
                const availableFiles = (r.files || []).filter(f => f.available);

                return (
                  <article
                    key={r.id}
                    className={`wb-download-item ${isAct ? 'is-active' : ''} ${r.status === 'error' ? 'is-error' : ''}`}
                  >
                    <div className="wb-download-item-top">
                      <div className="wb-download-item-title-wrap">
                        <span className="wb-download-item-sys">{recordPlatform(r)}</span>
                        <button
                          type="button"
                          className="wb-download-item-title"
                          onClick={() => {
                            setOpen(false);
                            if (onOpenTaskRecord) onOpenTaskRecord(r);
                            else navigateToTaskCenter();
                          }}
                          title={recordTitle(r)}
                        >
                          {recordTitle(r)}
                        </button>
                      </div>
                      <span className={`wb-download-status-pill is-${r.status}`}>
                        {isAct ? (
                          <Clock3 size={11} />
                        ) : r.status === 'success' ? (
                          <CheckCircle2 size={11} />
                        ) : r.status === 'error' ? (
                          <XCircle size={11} />
                        ) : null}
                        <span>{guidance.label}</span>
                      </span>
                    </div>

                    <div className="wb-download-item-meta tabular-nums">
                      <span>{KINDS[r.kind] || '资料采集'}</span>
                      <span>·</span>
                      <span>
                        {r.cities.length > 2
                          ? `${r.cities.slice(0, 2).join('、')}等${r.cities.length}城`
                          : r.cities.join('、') || '全量范围'}
                      </span>
                      <span>·</span>
                      <span>{formatTime(r.created_at)}</span>
                    </div>

                    {isAct && (
                      <div className="wb-download-progress-row">
                        <div className="wb-download-progress-track">
                          <div
                            className="wb-download-progress-fill"
                            style={{ width: `${Math.max(8, Math.min(100, pct))}%` }}
                          />
                        </div>
                        <span className="wb-download-progress-num tabular-nums">
                          {r.total_items > 0 ? `${r.completed_items}/${r.total_items}` : '处理中'}
                        </span>
                      </div>
                    )}

                    <div className="wb-download-item-Bottom">
                      <span className="wb-download-file-hint tabular-nums">
                        {availableFiles.length > 0
                          ? `${availableFiles.length} 个文件就绪（${formatSize(
                              availableFiles.reduce((sum, f) => sum + (f.bytes || 0), 0),
                            )}）`
                          : isAct
                            ? '后台正在生成结果文件…'
                            : guidance.summary}
                      </span>

                      <div className="wb-download-item-actions">
                        {r.status === 'waiting_login' && onOpenPlatformAuth && (
                          <button
                            type="button"
                            className="wb-download-get-btn"
                            onClick={() => {
                              setOpen(false);
                              const firstSys = datasetGroup(r.datasets[0] || '');
                              onOpenPlatformAuth(firstSys || 'fengshen');
                            }}
                          >
                            <span>去验证</span>
                          </button>
                        )}
                        {availableFiles.length > 0 && (
                          <button
                            type="button"
                            className="wb-download-get-btn"
                            disabled={!!downloadingId}
                            onClick={() => void triggerDownload(r)}
                          >
                            {downloadingId === r.id ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : (
                              <Download size={12} />
                            )}
                            <span>{availableFiles.length === 1 ? '直接下载' : '打包下载'}</span>
                          </button>
                        )}
                        <button
                          type="button"
                          className="wb-download-detail-btn"
                          onClick={() => {
                            setOpen(false);
                            if (onOpenTaskRecord) onOpenTaskRecord(r);
                            else navigateToTaskCenter();
                          }}
                        >
                          <FolderOpen size={12} />
                          <span>详情</span>
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
