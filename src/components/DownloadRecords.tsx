import { taskGuidance } from '../lib/taskGuidance';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Archive,
  ArchiveRestore,
  Calendar,
  ChevronRight,
  Download,
  ExternalLink,
  FolderOpen,
  Inbox,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  X,
} from 'lucide-react';
import { readDownloadResponse, saveDownloadBlob, downloadErrorMessage } from '../lib/outputDownload';
import {
  computeTaskElapsedSeconds,
  computeTaskProgressMeta,
  datasetGroup,
  formatTaskDuration,
  type DownloadFetch,
} from '../lib/downloadCenterLogic';
import type { RecordModule } from '../lib/downloadModules';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { StatusHoverPopover } from './StatusHoverPopover';
import { WorkbenchDatePicker } from './WorkbenchDatePicker';
import { WorkbenchConfirmModal, WorkbenchToast, type ToastNotice } from './WorkbenchFeedback';
import { SkeletonRows } from './SkeletonRows';
import { EmptyState } from './EmptyState';
import { TaskDetailDrawer, type TaskDetailItem, type TaskDetailTab } from './TaskDetailDrawer';
import { taskTone, toneClass } from '../lib/statusSemantics';
import {
  buildTaskProgressPopoverData,
  cleanTaskTitle,
  computeDatePresetRange,
  computeTaskDiagnosticNote,
  formatCitiesCompact,
  formatCompactTimestamp,
  formatPeriodCompact,
  platformTone,
  resolveTaskPrimaryAction,
  sortTaskDisplayRecords,
  summarizeTaskBatchSelection,
  type TaskAuthSystem,
  type TaskCenterSortKey,
  type TaskDatePreset,
} from '../lib/taskCenterDisplay';
import {
  shouldUseDemoData,
  useDemoDataVisibility,
  usePlatformAuthSnapshot,
} from '../lib/demoMode';
import {
  buildDemoTaskCenterRecords,
  queryDemoTaskCenter,
} from '../lib/showcaseDemoData';
import { DemoDataChip } from './DemoDataChip';
interface File {
  id: string;
  run_id?: string;
  name: string;
  city?: string;
  bytes: number;
  available?: boolean;
  unavailable_reason?: string;
}

type Task = TaskDetailItem;

const API = '/api/workbench/task-center';
const ACTIVE = new Set(['queued', 'running', 'waiting_login', 'waiting_manual', 'cancelling', 'preparing', 'stopping']);
const pollErrorMessage = (error: unknown) => {
  const name = (error as { name?: string })?.name || '';
  const text = String((error as { message?: string })?.message || '');
  if (name === 'TimeoutError' || name === 'AbortError' || /timed out|aborted/i.test(text))
    return '后台仍在启动或响应较慢，正在自动重试…';
  if (error instanceof TypeError) return '后台连接暂时中断，正在自动重试…';
  return downloadErrorMessage(error);
};
const KINDS: Record<string, string> = {
  download: '资料下载',
  generate: '业务报表',
  approval: '价格审批',
  'price-export': '每日价格',
};
const SYSTEMS: Record<string, string> = {
  fengshen: '风神',
  lanorange: '蓝橙',
  baize: '商翼',
  benlai: '本来人力',
  xiaoxiang: '灯塔',
};

export function DownloadRecords({
  apiFetch,
  workspaceId,
  selectedRunId,
  onOpenAttempt,
  execution,
  datasetLabel,
  refreshVersion = 0,
  recordModule,
  onNavigateGenerate,
  onNavigatePayroll,
  onOpenPrice,
  onOpenFengshenLogin,
  onRetryTask,
  initialRunId,
  onInitialFocusHandled,
}: {
  initialRunId?: string;
  onInitialFocusHandled?: () => void;
  apiFetch: DownloadFetch;
  workspaceId: string;
  selectedRunId: string;
  onOpenAttempt: (id: string) => void;
  execution: React.ReactNode;
  datasetLabel: (id: string) => string;
  refreshVersion?: number;
  unified?: boolean;
  recordModule?: RecordModule;
  onNavigateGenerate?: (cities: string[], start: string, end: string) => void;
  onNavigatePayroll?: () => void;
  onOpenPrice?: (view: 'approval' | 'price-export', id?: string) => void;
  onOpenFengshenLogin?: () => void;
  onRetryTask?: (task: TaskDetailItem) => void;
}) {
  const api = useRef(apiFetch);
  api.current = apiFetch;
  const [records, setRecords] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [pages, setPages] = useState(1);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [system, setSystem] = useState('');
  const [kind, setKind] = useState('');
  const [sortKey, setSortKey] = useState<TaskCenterSortKey>('created_desc');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [dateMenuOpen, setDateMenuOpen] = useState(false);
  const [archived, setArchived] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [focused, setFocused] = useState<Task | null>(null);
  const [detailTab, setDetailTab] = useState<TaskDetailTab>('files');
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState<ToastNotice | null>(null);
  const [pollError, setPollError] = useState('');
  const [confirm, setConfirm] = useState<Task[] | null>(null);
  const [directory, setDirectory] = useState<{
    path: string;
    exists: boolean;
    can_open: boolean;
    record_id?: string;
  } | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [syncMs, setSyncMs] = useState(() => Date.now());
  const [hasLiveServerData, setHasLiveServerData] = useState(false);
  const [demoRecords, setDemoRecords] = useState<Task[]>(() =>
    buildDemoTaskCenterRecords().map(item => ({
      ...item,
      member_ids: [item.id],
      attempts: [{ id: item.id, status: item.status }],
      action_run_id: item.id,
      output: item.files.length ? `D:\\薪酬结算输出\\任务归档\\${item.id}` : '',
      files: (item.files || []).map(f => ({ ...f, available: true })),
      source_files: (item.source_files || []).map(f => ({ ...f, available: true })),
    })) as unknown as Task[],
  );
  const [demoArchivedIds, setDemoArchivedIds] = useState<Set<string>>(() => new Set());

  const auth = usePlatformAuthSnapshot();
  const { demoHidden, toggleDemoHidden } = useDemoDataVisibility();
  const demoActive = shouldUseDemoData({
    isLoggedIn: auth.anyLoggedIn,
    hasLiveData: hasLiveServerData,
    demoHidden,
  });

  const dateMenuRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const focusRef = useRef<Task | null>(null);
  const selectedRef = useRef<string[]>([]);
  focusRef.current = focused;
  selectedRef.current = selected;

  const pushToast = (text: string, tone: ToastNotice['tone'] = 'success') => {
    setToast({ id: Date.now() + Math.random(), tone, text });
  };

  useEffect(() => {
    if (!dateMenuOpen) return;
    const onOutside = (event: MouseEvent) => {
      if (dateMenuRef.current && !dateMenuRef.current.contains(event.target as Node)) {
        setDateMenuOpen(false);
      }
    };
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDateMenuOpen(false);
    };
    document.addEventListener('mousedown', onOutside);
    window.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onOutside);
      window.removeEventListener('keydown', onEsc);
    };
  }, [dateMenuOpen]);

  const reset = () => {
    setPage(1);
    setSelected([]);
    setFocused(null);
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setPage(1);
      setSelected([]);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const params = new URLSearchParams({
          page: String(page),
          q: query,
          status,
          system,
          kind,
          from,
          to,
          archived: archived ? '1' : '0',
          module: recordModule || '',
          focus: focusRef.current?.id || '',
        });
        const response = await api.current(`${API}?${params}`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(45000)]),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || '任务列表暂不可读');
        if (controller.signal.aborted) return;
        const serverHasLive =
          (data.records?.length || 0) > 0 || (data.counts?.all || 0) > 0 || (data.counts?.archived || 0) > 0;
        setHasLiveServerData(serverHasLive);
        setRecords(previous =>
          selectedRef.current.length
            ? previous.map(r => data.records.find((next: Task) => next.id === r.id) || r)
            : data.records,
        );
        setSyncMs(Date.now());
        setTotal(data.total);
        setPages(data.pages);
        if (serverHasLive) {
          setPage(data.page);
        }
        setCounts(data.counts);
        setLoading(false);
        setPollError((data.warnings || []).join('；'));
        setFocused(previous =>
          previous
            ? data.focused?.id === previous.id
              ? data.focused
              : data.records.find((r: Task) => r.id === previous.id) || previous
            : null,
        );
      } catch (e) {
        if (!controller.signal.aborted) {
          setPollError(pollErrorMessage(e));
          setLoading(false);
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 5000);
    };
    setLoading(true);
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [page, query, status, system, kind, from, to, archived, recordModule, version, refreshVersion]);

  // 真实登录后立即切回后台实时数据并刷新一次，清除本地演示焦点
  const prevLoggedInRef = useRef(auth.anyLoggedIn);
  useEffect(() => {
    if (auth.anyLoggedIn && !prevLoggedInRef.current) {
      setSelected([]);
      setFocused(null);
      setConfirm(null);
      setPage(1);
      setVersion(v => v + 1);
    }
    prevLoggedInRef.current = auth.anyLoggedIn;
  }, [auth.anyLoggedIn]);

  const demoQueryResult = useMemo(() => {
    if (!demoActive) return null;
    const pool = demoRecords.filter(r =>
      archived ? demoArchivedIds.has(r.id) : !demoArchivedIds.has(r.id),
    );
    const result = queryDemoTaskCenter(pool as any, {
      status: status || 'all',
      q: query,
      system,
      kind,
      from,
      to,
      page,
      pageSize,
    });
    const totalPages = Math.max(1, Math.ceil(result.total / pageSize));
    const safePage = Math.min(Math.max(1, page), totalPages);
    return {
      ...result,
      page: safePage,
      pages: totalPages,
      items: result.items as unknown as Task[],
      counts: {
        ...result.counts,
        archived: demoArchivedIds.size,
      },
    };
  }, [demoActive, demoRecords, demoArchivedIds, archived, status, query, system, kind, from, to, page, pageSize]);

  const effectiveRecords = useMemo(
    () => sortTaskDisplayRecords(demoQueryResult ? demoQueryResult.items : records, sortKey),
    [demoQueryResult, records, sortKey],
  );
  const effectiveTotal = demoQueryResult ? demoQueryResult.total : total;
  const effectivePages = demoQueryResult ? demoQueryResult.pages : pages;
  const effectivePage = demoQueryResult ? demoQueryResult.page : page;
  const effectiveCounts = demoQueryResult ? demoQueryResult.counts : counts;

  useEffect(() => {
    if (!demoActive) return;
    const activeCount = demoRecords.filter(
      r =>
        !demoArchivedIds.has(r.id) &&
        ['queued', 'running', 'cancelling', 'preparing', 'stopping'].includes(r.status),
    ).length;
    window.dispatchEvent(new CustomEvent('workbench:demo-active-count', { detail: activeCount }));
  }, [demoActive, demoRecords, demoArchivedIds]);

  // 同步抽屉内展示的任务对象（确保示例停止/刷新状态实时更新）
  const activeFocused = useMemo(() => {
    if (!focused) return null;
    const inPage = effectiveRecords.find(r => r.id === focused.id);
    if (inPage) return inPage;
    if (demoActive) {
      return demoRecords.find(r => r.id === focused.id) || focused;
    }
    return focused;
  }, [focused, effectiveRecords, demoActive, demoRecords]);

  const hasActiveTasks = useMemo(
    () => effectiveRecords.some(r => ACTIVE.has(r.status)) || (activeFocused ? ACTIVE.has(activeFocused.status) : false),
    [effectiveRecords, activeFocused],
  );
  useEffect(() => {
    if (!hasActiveTasks) return;
    setNowMs(Date.now());
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [hasActiveTasks]);

  useEffect(() => {
    if (!initialRunId) return;
    const record = effectiveRecords.find(
      r => (r.member_ids || []).includes(initialRunId) || r.action_run_id === initialRunId || r.id === initialRunId,
    );
    if (record) {
      setDetailTab(record.files.length ? 'files' : 'history');
      setFocused(record);
      onInitialFocusHandled?.();
    }
  }, [initialRunId, effectiveRecords, onInitialFocusHandled]);

  const rawTitle = (r: Task) => r.title || r.datasets.map(datasetLabel).join('、').replaceAll('（生成表）', '');
  const platform = (r: Task) =>
    r.price_id ? '蓝橙' : [...new Set(r.datasets.map(id => SYSTEMS[datasetGroup(id)]))].filter(Boolean).join(' / ') || '风神';
  const kindLabel = (k: string) => KINDS[k] || '资料下载';

  const openDetail = (r: Task, preferredTab?: TaskDetailTab) => {
    const nextTab: TaskDetailTab =
      preferredTab || (r.files.length > 0 && ['success', 'partial'].includes(r.status) ? 'files' : 'history');
    setDetailTab(nextTab);
    setFocused(r);
    if (r.action_run_id) {
      onOpenAttempt(r.action_run_id);
    }
  };

  const request = async (url: string, payload?: unknown) => {
    const response = await api.current(
      url,
      payload === undefined
        ? { signal: AbortSignal.timeout(120000) }
        : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: AbortSignal.timeout(120000),
          },
    );
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || '操作未完成，请重试');
    }
    return response;
  };

  const act = async (work: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (e) {
      const msg = downloadErrorMessage(e);
      setError(msg);
      pushToast(msg, 'error');
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const download = (r: Task, file?: File, sources = false) =>
    act(async () => {
      if (demoActive) {
        const sampleName = file?.name || `${cleanTaskTitle(rawTitle(r), platform(r), kindLabel(r.kind))}_示例预览.txt`;
        const content = [
          `任务示例文件预览（未登录演示模式）`,
          `任务名称：${rawTitle(r)}`,
          `来源平台：${platform(r)} · ${kindLabel(r.kind)}`,
          `覆盖城市：${(r.cities || []).join('、') || '全量范围'}`,
          `业务周期：${r.start || '—'} ~ ${r.end || '—'}`,
          `状态：${r.status}`,
          `说明：完成真实平台登录后，点击下载将直接拉取后台真实成品文件。`,
        ].join('\n');
        saveDownloadBlob(new Blob([`\uFEFF${content}`], { type: 'text/plain;charset=utf-8' }), sampleName);
        pushToast(`示例模式：已生成预览文件「${sampleName}」`, 'info');
        return;
      }
      let url: string;
      let filename: string;
      if (r.kind === 'approval') {
        url = `/api/fengshen-downloads/lanorange-approvals/batches/${r.price_id}/result.csv`;
        filename = '蓝橙价格审批回执.csv';
      } else if (r.kind === 'price-export') {
        url = `/api/fengshen-downloads/lanorange-prices/exports/${r.price_id}/result.xlsx`;
        filename = '蓝橙待审每日价格.xlsx';
      } else {
        url = file
          ? `/api/fengshen-downloads/runs/${file.run_id || r.id}/files/${file.id}`
          : `/api/fengshen-downloads/records/${r.id}/bundle${sources ? '?purpose=sources' : ''}`;
        filename = file?.name || `${sources ? '来源' : '结果'}_${r.id.slice(0, 8)}.zip`;
      }
      const response = await request(url);
      const disposition = response.headers.get('content-disposition') || '';
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
      if (encoded) {
        try {
          const actual = decodeURIComponent(encoded);
          if (actual && !/[\\/\x00-\x1f]/.test(actual)) filename = actual;
        } catch {
          // fallback
        }
      }
      saveDownloadBlob(await readDownloadResponse(response, filename), filename);
      pushToast('已发起文件保存，请在浏览器下载记录中确认。');
    });

  const downloadResult = (r: Task) => {
    const avail = r.files.filter(f => f.available !== false);
    void download(r, avail.length === 1 ? avail[0] : undefined);
  };

  const stopTask = (r: Task) =>
    void act(async () => {
      if (demoActive) {
        setDemoRecords(prev =>
          prev.map(item =>
            item.id === r.id
              ? {
                  ...item,
                  status: 'cancelled',
                  current_action: '已在本地示例预览中停止',
                  finished_at: Date.now() / 1000,
                }
              : item,
          ),
        );
        pushToast('示例模式：已停止该示例任务（仅本地预览）。', 'info');
        return;
      }
      await request(`${API}/stop`, { id: r.id });
      setVersion(v => v + 1);
      pushToast('已请求停止，确认停止前任务保留在列表。', 'info');
    });

  const batchStopTasks = (ids: string[]) =>
    void act(async () => {
      if (!ids.length) return;
      const targetSet = new Set(ids);
      const targets = effectiveRecords.filter(r => targetSet.has(r.id));
      if (demoActive) {
        setDemoRecords(prev =>
          prev.map(item =>
            targetSet.has(item.id)
              ? {
                  ...item,
                  status: 'cancelled',
                  current_action: '已在本地示例预览中批量停止',
                  finished_at: Date.now() / 1000,
                }
              : item,
          ),
        );
        setSelected([]);
        pushToast(`示例模式：已停止 ${targets.length} 项示例任务（仅本地预览）。`, 'info');
        return;
      }
      for (const item of targets) {
        await request(`${API}/stop`, { id: item.id });
      }
      setSelected([]);
      setVersion(v => v + 1);
      pushToast(`已提交 ${targets.length} 项任务的停止请求。`, 'info');
    });

  const handleOpenAuth = (authSys: TaskAuthSystem) => {
    if (authSys === 'fengshen' && onOpenFengshenLogin) {
      onOpenFengshenLogin();
      return;
    }
    window.dispatchEvent(new CustomEvent('workbench:connections', { detail: authSys }));
  };

  const handleRetryTask = (r: Task) => {
    if (onRetryTask) {
      setFocused(null);
      onRetryTask(r);
      return;
    }
    pushToast('请返回对应采集平台重新发起该任务。', 'info');
  };

  const showDirectory = (r?: Task) =>
    act(async () => {
      if (demoActive) {
        setDirectory({
          path: r
            ? `~/SalaryWorkbench/outputs/${r.id}`
            : '~/SalaryWorkbench/outputs',
          exists: true,
          can_open: false,
          record_id: r?.id,
        });
        pushToast('示例模式：已展示模拟生成目录路径（真实登录后可直接打开本地目录）。', 'info');
        return;
      }
      const response = await request(`${API}/directory${r ? `?record_id=${encodeURIComponent(r.id)}` : ''}`);
      const info = await response.json();
      setDirectory({ ...info, record_id: r?.id });
      if (info.exists && info.can_open) await request(`${API}/directory/open`, { record_id: r?.id });
    });

  const changeVisibility = (rows: Task[]) =>
    act(async () => {
      if (demoActive) {
        setDemoArchivedIds(prev => {
          const next = new Set(prev);
          for (const row of rows) {
            if (archived) next.delete(row.id);
            else next.add(row.id);
          }
          return next;
        });
        setConfirm(null);
        setSelected([]);
        setFocused(null);
        pushToast(
          archived
            ? `示例模式：已恢复 ${rows.length} 条示例任务。`
            : `示例模式：已移出 ${rows.length} 条示例任务，可在「已移出」恢复。`,
        );
        return;
      }
      await request(`${API}/visibility`, { ids: rows.map(r => r.id), restore: archived, stop_first: true });
      setConfirm(null);
      setSelected([]);
      setFocused(null);
      setVersion(v => v + 1);
      pushToast(
        archived
          ? `已恢复 ${rows.length} 个任务，所有同事同步可见。`
          : '已提交移出请求，进行中任务确认停止后移出。文件保留，可在「已移出」恢复。',
      );
    });

  const chosen = effectiveRecords.filter(r => selected.includes(r.id));
  const batchSummary = useMemo(() => summarizeTaskBatchSelection(chosen), [chosen]);
  const context = (r: Task) => ({
    status: r.status,
    kind: r.kind,
    availableFiles: r.available_files,
    failedItems: r.failed_items,
    summaryIssue: r.summary_issue,
  });
  const openPrice = (r: Task) => {
    setFocused(null);
    onOpenPrice?.(r.kind as 'approval' | 'price-export', r.price_id);
  };

  return (
    <div className="wbx-tc-shell" data-workspace-id={workspaceId}>
      <section className="tc-center wbx-taskcenter" aria-label="任务中心列表">
        {/* 1. 与兼职核算统一的卡片顶栏 */}
        <header className="wbx-tc-topbar">
          <div className="wbx-tc-topbar__left">
            <h3 className="wbx-tc-title">
              <span>{archived ? '已移出任务' : '任务中心'}</span>
              <span className="wbx-tc-title__count tabular-nums">{effectiveCounts.all || 0}</span>
            </h3>
          </div>

        <div className="wbx-tc-topbar__right">
          <DemoDataChip
            demoActive={demoActive}
            canShowDemo={!auth.anyLoggedIn && !hasLiveServerData && demoHidden}
            onToggle={() => {
              reset();
              toggleDemoHidden();
            }}
          />
          {!archived && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  if (demoActive) {
                    const completedDemo = demoRecords.filter(
                      r => !demoArchivedIds.has(r.id) && r.status === 'success',
                    );
                    if (completedDemo.length) setConfirm(completedDemo);
                    else pushToast('当前示例范围内没有可整理的已完成任务。', 'info');
                    return;
                  }
                  const params = new URLSearchParams({
                    q: query,
                    system,
                    kind,
                    from,
                    to,
                    module: recordModule || '',
                  });
                  const response = await request(`${API}/organize-preview?${params}`);
                  const data = await response.json();
                  if (data.records.length) setConfirm(data.records);
                  else pushToast('当前筛选范围内没有可整理的已完成任务。', 'info');
                })
              }
            >
              整理已完成
            </button>
          )}
          <button type="button" className="wbx-btn wbx-btn--sm" disabled={busy} onClick={() => void showDirectory()}>
            <FolderOpen size={14} aria-hidden="true" />
            <span>生成根目录</span>
          </button>
          <button
            type="button"
            className={`wbx-btn wbx-btn--sm${archived ? ' wbx-btn--secondary' : ''}`}
            onClick={() => {
              setArchived(!archived);
              reset();
            }}
          >
            <Archive size={13.5} aria-hidden="true" />
            <span>{archived ? '返回列表' : '已移出'}</span>
          </button>
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            aria-label="刷新任务列表"
            title="刷新任务列表"
            onClick={() => {
              setVersion(v => v + 1);
            }}
          >
            <RefreshCw size={13} aria-hidden="true" />
            <span>刷新</span>
          </button>
          </div>
        </header>

        {/* 2. 页签与筛选合并单行工具栏（左侧 5 个状态页签 + 右侧搜索/平台/类型/日期/排序/刷新） */}
        <div className="wbx-taskcenter__filters">
          <div className="wbx-tc-tabs" role="tablist" aria-label="任务状态">
            {(
              [
                ['', '全部', 'all'],
                ['active', '进行中', 'active'],
                ['attention', '待处理', 'attention'],
                ['success', '已完成', 'success'],
                ['stopped', '已停止', 'stopped'],
              ] as const
            ).map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={status === key}
                className={`wbx-tc-tab${status === key ? ' is-active' : ''}`}
                onClick={() => {
                  setStatus(key);
                  reset();
                }}
              >
                <span>{label}</span>
                <span className="wbx-tc-tab__count tabular-nums">{effectiveCounts[count] || 0}</span>
              </button>
            ))}
          </div>

          <div className="wbx-tc-filter-controls">
            <label className="wbx-tc-search">
              <Search size={13.5} aria-hidden="true" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="搜索名称、城市或单号"
                aria-label="搜索任务"
              />
            </label>

            {!recordModule && (
              <>
                <select
                  className="wb-select wbx-tc-select"
                  aria-label="筛选平台"
                  value={system}
                  onChange={e => {
                    setSystem(e.target.value);
                    reset();
                  }}
                >
                  <option value="">全部平台</option>
                  {Object.entries(SYSTEMS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
                <select
                  className="wb-select wbx-tc-select"
                  aria-label="筛选任务类型"
                  value={kind}
                  onChange={e => {
                    setKind(e.target.value);
                    reset();
                  }}
                >
                  <option value="">全部类型</option>
                  {Object.entries(KINDS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </>
            )}

            {/* 快捷日期筛选浮层 */}
            <div className="tc-date-popover-wrap" ref={dateMenuRef}>
              <button
                type="button"
                className={`wbx-btn wbx-btn--sm${from || to ? ' is-filter-active' : ''}`}
                aria-expanded={dateMenuOpen}
                onClick={() => setDateMenuOpen(prev => !prev)}
              >
                <Calendar size={13} aria-hidden="true" />
                <span>{from || to ? `${from || '起'} ~ ${to || '今'}` : '日期筛选'}</span>
              </button>
              {dateMenuOpen && (
                <div className="tc-date-popover" role="dialog" aria-label="按创建日期筛选">
                  <div className="tc-date-presets">
                    {(
                      [
                        ['today', '今天'],
                        ['7d', '近 7 天'],
                        ['month', '本月'],
                      ] as [TaskDatePreset, string][]
                    ).map(([preset, label]) => (
                      <button
                        key={preset}
                        type="button"
                        className="wbx-btn wbx-btn--sm"
                        onClick={() => {
                          const range = computeDatePresetRange(preset, nowMs);
                          setFrom(range.from);
                          setTo(range.to);
                          reset();
                          setDateMenuOpen(false);
                        }}
                      >
                        {label}
                      </button>
                    ))}
                    {(from || to) && (
                      <button
                        type="button"
                        className="wb-link"
                        onClick={() => {
                          setFrom('');
                          setTo('');
                          reset();
                          setDateMenuOpen(false);
                        }}
                      >
                        清除
                      </button>
                    )}
                  </div>
                  <div className="tc-date-custom-row">
                    <div className="tc-filter-date-item">
                      <span>从</span>
                      <WorkbenchDatePicker
                        ariaLabel="创建日期从"
                        value={from}
                        rangeRole="start"
                        rangeStart={from}
                        rangeEnd={to}
                        allowClear
                        align="right"
                        onChange={v => {
                          setFrom(v);
                          reset();
                        }}
                      />
                    </div>
                    <div className="tc-filter-date-item">
                      <span>至</span>
                      <WorkbenchDatePicker
                        ariaLabel="创建日期至"
                        value={to}
                        rangeRole="end"
                        rangeStart={from}
                        rangeEnd={to}
                        allowClear
                        align="right"
                        onChange={v => {
                          setTo(v);
                          reset();
                        }}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>

            <select
              className="wb-select wbx-tc-select"
              aria-label="排序方式"
              value={sortKey}
              onChange={e => setSortKey(e.target.value as TaskCenterSortKey)}
            >
              <option value="created_desc">按创建时间</option>
              <option value="elapsed_desc">按耗时从长到短</option>
              <option value="files_desc">按产出文件数</option>
            </select>
          </div>
        </div>

        {archived && <p className="tc-info">已移出的任务仍保留文件和处理记录，恢复后所有同事同步可见。</p>}
        {pollError && (
          <p role="status" className="wb-notice">
            {pollError}现有记录保留。
          </p>
        )}
        {error && (
          <p role="alert" className="wb-error">
            {error}
          </p>
        )}
        {!!selected.length && (
          <div className="tc-batchbar">
            <strong className="tabular-nums">已选 {batchSummary.total} 项</strong>
            <button
              type="button"
              className="wbx-btn wbx-btn--sm wbx-btn--primary"
              disabled={busy || batchSummary.downloadableCount === 0}
              title={
                batchSummary.downloadableCount === 0
                  ? '所选任务暂无可打包下载的结果文件'
                  : `打包下载 ${batchSummary.downloadableCount} 项可用任务（自动跳过无文件或审批类任务）`
              }
              onClick={() =>
                void act(async () => {
                  const targets = chosen.filter(r => batchSummary.downloadableIds.includes(r.id));
                  const response = await request(`${API}/bundle`, { ids: batchSummary.downloadableIds });
                  saveDownloadBlob(await readDownloadResponse(response, '批量任务结果.zip'), '批量任务结果.zip');
                  pushToast(`已发起 ${targets.length} 项任务的批量文件保存。`);
                })
              }
            >
              <Download size={13.5} />
              <span>
                批量下载{batchSummary.downloadableCount > 0 ? ` (${batchSummary.downloadableCount})` : ''}
              </span>
            </button>
            {batchSummary.skippedDownloadCount > 0 && batchSummary.downloadableCount > 0 && (
              <span className="tc-batchbar__hint tabular-nums">
                自动跳过 {batchSummary.skippedDownloadCount} 项不可下载
              </span>
            )}
            {!archived && batchSummary.activeCount > 0 && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm wbx-btn--danger"
                disabled={busy}
                onClick={() => batchStopTasks(batchSummary.activeIds)}
              >
                <Square size={11.5} aria-hidden="true" />
                <span>批量停止 ({batchSummary.activeCount})</span>
              </button>
            )}
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={busy || !chosen.length}
              onClick={() => setConfirm(chosen)}
            >
              {archived ? '恢复显示' : '移出列表'}
            </button>
            <button type="button" className="wb-link" onClick={() => setSelected([])}>
              取消选择
            </button>
          </div>
        )}

        {/* 3. 单行紧凑 44px 任务列表（仅状态列保留语义色，两级字重，纯文字操作列） */}
        <div className="wbx-table-scroll wbx-taskcenter__scroll">
          <table className="wbx-table tc-table wbx-taskcenter__table">
            <thead>
              <tr>
                <th className="tc-col-check">
                  <input
                    type="checkbox"
                    aria-label="选择当前页任务"
                    checked={effectiveRecords.length > 0 && effectiveRecords.every(r => selected.includes(r.id))}
                    onChange={e => setSelected(e.target.checked ? effectiveRecords.map(r => r.id) : [])}
                  />
                </th>
                <th className="tc-col-task">任务内容</th>
                <th className="tc-col-source">来源 / 类型</th>
                <th className="tc-col-scope">范围 / 周期</th>
                <th className="tc-col-progress">状态与进度</th>
                <th className="tc-col-time">创建时间</th>
                <th className="tc-col-ops">操作</th>
              </tr>
            </thead>
            <tbody>
              {effectiveRecords.map(r => {
                const pName = platform(r);
                const kLabel = kindLabel(r.kind);
                const cleanTitle = cleanTaskTitle(rawTitle(r), pName, kLabel);
                const diagNote = computeTaskDiagnosticNote(r);
                const citiesMeta = formatCitiesCompact(r.cities);
                const periodMeta = formatPeriodCompact(r.start, r.end, r.datasets);
                const createdMeta = formatCompactTimestamp(r.created_at, nowMs);
                const guidance = taskGuidance(context(r));
                const isActive = ACTIVE.has(r.status);
                const progressMeta = computeTaskProgressMeta(r);
                const showProgressBar =
                  progressMeta.isActive &&
                  progressMeta.hasTotal &&
                  r.status !== 'queued' &&
                  (progressMeta.pct ?? 0) > 0;
                const isPausedProgress = ['waiting_login', 'waiting_manual'].includes(r.status);
                const elapsedSec = computeTaskElapsedSeconds(r, nowMs, syncMs);
                const elapsedText = formatTaskDuration(elapsedSec);
                const primaryAction = resolveTaskPrimaryAction(r, archived);
                const isDetailOpen = activeFocused?.id === r.id;
                const pTone = platformTone(pName);
                const resolvedTone = taskTone(r.status);
                const popoverTone = (['active', 'waiting', 'success', 'error', 'muted'].includes(resolvedTone)
                  ? resolvedTone
                  : 'muted') as 'active' | 'waiting' | 'success' | 'error' | 'muted';
                const popoverModel = buildTaskProgressPopoverData(r, {
                  statusLabel: guidance.label,
                  tone: popoverTone,
                  percent: showProgressBar ? progressMeta.pct : null,
                  elapsedText,
                  platformName: pName,
                  diagNote,
                  nowMs,
                });

                return (
                  <tr
                    key={r.id}
                    data-task-ids={(r.member_ids && r.member_ids.length ? r.member_ids : [r.id]).join(' ')}
                    className={`tc-row${isDetailOpen ? ' is-detail-open' : ''}`}
                    onClick={() => openDetail(r)}
                  >
                    <td className="tc-col-check">
                      <input
                        type="checkbox"
                        aria-label={`选择${cleanTitle}`}
                        checked={selected.includes(r.id)}
                        onClick={e => e.stopPropagation()}
                        onChange={e =>
                          setSelected(v => (e.target.checked ? [...v, r.id] : v.filter(id => id !== r.id)))
                        }
                      />
                    </td>

                    {/* 任务内容：严格单行排版，诊断提示合入 title 与右侧详情抽屉 */}
                    <td className="tc-col-task">
                      <span
                        className="tc-task-title"
                        title={diagNote ? `${cleanTitle} — ${diagNote.text}` : rawTitle(r)}
                      >
                        {cleanTitle}
                      </span>
                    </td>

                    {/* 来源 / 类型：单行统一深灰黑字 */}
                    <td className="tc-col-source">
                      <span className={`tc-platform-text is-${pTone}`}>{pName}</span>
                      <span className="tc-source-sep" aria-hidden="true">·</span>
                      <span className="tc-kind-text">{kLabel}</span>
                    </td>

                    {/* 范围 / 周期：单行合并展示 */}
                    <td className="tc-col-scope">
                      <span
                        className="tc-scope-inline tabular-nums"
                        title={`${citiesMeta.full} · ${periodMeta.full}`}
                      >
                        {citiesMeta.short}
                        {periodMeta.short ? ` · ${periodMeta.short}` : ''}
                      </span>
                    </td>

                    {/* 状态与进度：唯一保留语义色的列，悬停进度胶囊浮窗展示耗时与处理节点 */}
                    <td className="tc-col-progress">
                      <div className="tc-progress-top">
                        <StatusHoverPopover model={popoverModel}>
                          <span
                            className={`wbx-pill ${toneClass(resolvedTone)}${showProgressBar ? ' wbx-pill--has-progress' : ''}${isPausedProgress ? ' is-paused' : ''}`}
                            aria-label={showProgressBar ? `${guidance.label} ${progressMeta.pct}%` : guidance.label}
                          >
                            {showProgressBar && (
                              <span
                                className="wbx-pill__fill"
                                style={{ width: `${Math.max(0, Math.min(100, progressMeta.pct ?? 0))}%` }}
                                aria-hidden="true"
                              />
                            )}
                            <span className="wbx-pill__content">
                              <span className="wbx-pill__lead">
                                {isActive && !['stopping', 'cancelling', 'waiting_login', 'waiting_manual', 'queued'].includes(r.status) ? (
                                  <Loader2 size={11.5} className="animate-spin wbx-pill__icon" aria-hidden="true" />
                                ) : (
                                  <span className="wbx-pill__dot" aria-hidden="true" />
                                )}
                                <span className="wbx-pill__label">{guidance.label}</span>
                              </span>
                              {showProgressBar && (
                                <span className="wbx-pill__pct tabular-nums">{progressMeta.pct}%</span>
                              )}
                            </span>
                          </span>
                        </StatusHoverPopover>
                      </div>
                    </td>

                    {/* 创建时间 */}
                    <td className="tc-col-time tabular-nums" title={createdMeta.full}>
                      {createdMeta.short}
                    </td>

                    {/* 4 轨定宽操作网格：[26px 辅助图标] [74px 主操作] [9px 分割线] [26px 移出] */}
                    <td className="tc-col-ops">
                      <div
                        className={`tc-row-ops${archived ? ' is-archived' : ''}`}
                        onClick={e => e.stopPropagation()}
                      >
                        {primaryAction?.type === 'restore' && (
                          <button
                            type="button"
                            className="tc-op-cta is-primary tc-op-slot-main"
                            disabled={busy}
                            onClick={() => setConfirm([r])}
                          >
                            <span>恢复</span>
                          </button>
                        )}

                        {primaryAction?.type === 'download' && (
                          <button
                            type="button"
                            className="tc-op-cta is-primary tc-op-slot-main"
                            disabled={busy}
                            title={r.available_files > 1 ? `打包下载全部 ${r.available_files} 个文件` : '下载结果文件'}
                            onClick={() => downloadResult(r)}
                          >
                            <span>下载</span>
                          </button>
                        )}

                        {primaryAction?.type === 'price' && (
                          <button
                            type="button"
                            className="tc-op-cta is-primary tc-op-slot-main"
                            onClick={() => openPrice(r)}
                          >
                            <span>{primaryAction.label}</span>
                          </button>
                        )}

                        {primaryAction?.type === 'attention' && (
                          <>
                            {!archived && isActive && (
                              <button
                                type="button"
                                className="tc-icon-btn tc-stop-icon-btn tc-op-slot-aux"
                                title={
                                  ['stopping', 'cancelling'].includes(r.status)
                                    ? '停止中'
                                    : r.status === 'queued'
                                      ? '取消排队'
                                      : '停止任务'
                                }
                                aria-label={`${r.status === 'queued' ? '取消排队' : '停止'} ${cleanTitle}`}
                                disabled={busy || ['stopping', 'cancelling'].includes(r.status)}
                                onClick={() => stopTask(r)}
                              >
                                <Square size={9} fill="currentColor" strokeWidth={1.8} aria-hidden="true" />
                              </button>
                            )}
                            {!isActive && r.available_files > 0 && (
                              <button
                                type="button"
                                className="tc-icon-btn tc-op-slot-aux"
                                title={`先下载已生成的 ${r.available_files} 个文件`}
                                aria-label={`下载 ${cleanTitle} 已有文件`}
                                disabled={busy}
                                onClick={() => downloadResult(r)}
                              >
                                <Download size={13.5} aria-hidden="true" />
                              </button>
                            )}
                            <button
                              type="button"
                              className={`tc-op-cta is-${primaryAction.tone} tc-op-slot-main`}
                              onClick={() => (r.price_id ? openPrice(r) : openDetail(r, 'history'))}
                            >
                              <span>{primaryAction.label}</span>
                            </button>
                          </>
                        )}

                        {!archived && isActive && !primaryAction && (
                          <button
                            type="button"
                            className="tc-stop-btn tc-op-slot-main"
                            title={
                              ['stopping', 'cancelling'].includes(r.status)
                                ? '停止中'
                                : r.status === 'queued'
                                  ? '取消排队'
                                  : '停止任务'
                            }
                            aria-label={`${r.status === 'queued' ? '取消排队' : '停止'} ${cleanTitle}`}
                            disabled={busy || ['stopping', 'cancelling'].includes(r.status)}
                            onClick={() => stopTask(r)}
                          >
                            <span>
                              {['stopping', 'cancelling'].includes(r.status)
                                ? '停止中'
                                : r.status === 'queued'
                                  ? '取消'
                                  : '停止'}
                            </span>
                          </button>
                        )}

                        {!archived && !isActive && !primaryAction && (
                          <button
                            type="button"
                            className="tc-op-cta is-neutral tc-op-slot-main"
                            onClick={() => openDetail(r, 'history')}
                          >
                            <span>查看详情</span>
                          </button>
                        )}

                        {!archived && (
                          <>
                            <span className="tc-op-sep tc-op-slot-sep" aria-hidden="true" />
                            <button
                              type="button"
                              className="tc-icon-btn tc-remove-btn tc-op-slot-remove"
                              title={isActive ? '停止并移出列表' : '移出列表'}
                              aria-label={`${isActive ? '停止并移出' : '移出'} ${cleanTitle}`}
                              disabled={busy}
                              onClick={() => setConfirm([r])}
                            >
                              <X size={13.5} aria-hidden="true" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!effectiveRecords.length &&
          (loading ? (
            <div className="wbx-taskcenter__skeleton">
              <SkeletonRows rows={5} columns={6} label="任务列表加载中" />
            </div>
          ) : (
            <EmptyState
              icon={Inbox}
              title={pollError ? '正在连接后台服务' : archived ? '暂无已移出的归档任务' : '当前条件下暂无匹配任务'}
              description={
                pollError
                  ? '正在同步最新任务记录，请稍候自动刷新或手动点击刷新。'
                  : archived
                    ? '被移出列表的历史任务会保存在此处，文件与处理记录均完整保留。'
                    : search || status || system || kind || from || to
                      ? '可尝试清空搜索词或筛选条件，恢复查看全部采集、报表与核算任务。'
                      : '在「新建采集」或「薪资核算」提交任务后，可在此实时追踪进度并一键领取结果文件。'
              }
              actions={
                search || status || system || kind || from || to
                  ? [
                      {
                        label: '重置筛选条件',
                        tone: 'primary',
                        icon: RotateCcw,
                        onClick: () => {
                          setSearch('');
                          setQuery('');
                          setStatus('');
                          setSystem('');
                          setKind('');
                          setFrom('');
                          setTo('');
                          reset();
                        },
                      },
                    ]
                  : [
                      {
                        label: '刷新任务列表',
                        tone: 'secondary',
                        icon: RefreshCw,
                        onClick: () => setVersion(v => v + 1),
                      },
                    ]
              }
            />
          ))}

        <footer className="tc-pagination" aria-label="任务中心分页">
          <div className="tc-pagination__meta tabular-nums">
            <span>
              共 {effectiveTotal} 条 · 当前第{' '}
              {effectiveTotal === 0 ? 0 : (effectivePage - 1) * pageSize + 1}-
              {Math.min(effectivePage * pageSize, effectiveTotal)} 条
            </span>
            <label className="tc-pagination__size">
              <span>每页</span>
              <select
                className="wb-select"
                aria-label="任务中心每页条数"
                value={pageSize}
                onChange={e => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                  setSelected([]);
                }}
              >
                <option value={10}>10 条</option>
                <option value={20}>20 条</option>
                <option value={50}>50 条</option>
              </select>
            </label>
          </div>
          <div className="tc-pagination__controls">
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={effectivePage <= 1 || loading}
              onClick={() => {
                setPage(p => p - 1);
                setSelected([]);
              }}
            >
              上一页
            </button>
            <span className="tabular-nums tc-pagination__indicator">
              第 {effectivePage} / {effectivePages} 页
            </span>
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={effectivePage >= effectivePages || loading}
              onClick={() => {
                setPage(p => p + 1);
                setSelected([]);
              }}
            >
              下一页
            </button>
          </div>
        </footer>

        <TaskDetailDrawer
          task={activeFocused}
          tasks={effectiveRecords}
          initialTab={detailTab}
          archived={archived}
          busy={busy}
          nowMs={nowMs}
          syncMs={syncMs}
          selectedRunId={selectedRunId}
          execution={execution}
          error={error}
          platformName={platform}
          kindLabel={kindLabel}
          rawTitle={rawTitle}
          onClose={() => setFocused(null)}
          onSelectTask={next => {
            setFocused(next);
            if (next.action_run_id) onOpenAttempt(next.action_run_id);
          }}
          onDownloadResult={downloadResult}
          onDownloadFile={(r, file) => void download(r, file)}
          onDownloadSources={r => void download(r, undefined, true)}
          onShowDirectory={r => void showDirectory(r)}
          onStopTask={stopTask}
          onArchiveOrRestore={r => setConfirm([r])}
          onRetryTask={handleRetryTask}
          onOpenAuth={authSys => handleOpenAuth(authSys)}
          onNavigatePayroll={onNavigatePayroll}
          onOpenPrice={onOpenPrice ? openPrice : undefined}
          onNavigateGenerate={onNavigateGenerate}
          onOpenAttempt={onOpenAttempt}
          onReloadExecution={r => openDetail(r, 'history')}
        />

        {directory && (
          <WorkbenchDrawer title="生成文件目录" onClose={() => setDirectory(null)}>
            <p className="wb-muted">这是运行本系统的电脑上的目录，浏览器下载位置由浏览器设置决定。</p>
            <label className="tc-path">
              {directory.record_id ? '本次任务目录' : '生成根目录'}
              <textarea readOnly value={directory.path} onFocus={e => e.target.select()} />
            </label>
            {!directory.exists && <p className="wb-notice">目录尚未生成或已被移动。</p>}
            <div className="tc-detail-actions">
              <button
                type="button"
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                disabled={busy || !directory.exists || !directory.can_open}
                onClick={() =>
                  void act(async () => {
                    await request(`${API}/directory/open`, { record_id: directory.record_id });
                    pushToast('已打开资源管理器。');
                  })
                }
              >
                <FolderOpen size={14} />
                <span>打开文件夹</span>
              </button>
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                onClick={() =>
                  void act(async () => {
                    await navigator.clipboard.writeText(directory.path);
                    pushToast('目录路径已复制到剪贴板。');
                  })
                }
              >
                复制路径
              </button>
            </div>
            {!directory.can_open && <p className="wb-muted">远程访问请下载文件，或使用管理员提供的共享路径。</p>}
            <details>
              <summary>新任务目录结构</summary>
              <pre className="tc-tree">
                {'任务名称_生成时间_编号 /\n  汇总报表.xlsx\n  城市_报表.xlsx\n  文件清单.csv\n\n成品直接平铺；原始资料单独保留，需要时领取复核资料包。'}
              </pre>
            </details>
          </WorkbenchDrawer>
        )}

        {confirm && (
          <WorkbenchConfirmModal
            title={archived ? '恢复任务显示' : '移出任务列表'}
            description={`将${archived ? '恢复' : '移出'} ${confirm.length} 个任务，对共享工作台所有同事生效。`}
            hint={`进行中的任务确认停止后移出。文件、处理记录和业务资料均保留。${archived ? '' : '之后可在「已移出」中恢复。'}`}
            items={confirm.map(r => `${cleanTaskTitle(rawTitle(r), platform(r), kindLabel(r.kind))} · ${r.id.slice(-6).toUpperCase()}`)}
            confirmLabel={archived ? '确认恢复' : '确认移出，保留文件'}
            confirmTone={archived ? 'primary' : 'danger'}
            busy={busy}
            error={error}
            onCancel={() => setConfirm(null)}
            onConfirm={() => void changeVisibility(confirm)}
          />
        )}

        <WorkbenchToast toast={toast} onDismiss={() => setToast(null)} />
      </section>
    </div>
  );
}

