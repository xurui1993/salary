import { CollectionScope } from './CollectionScope';
import {useStationDirectory} from '../lib/useStationDirectory';
import {CityStationCount} from './CityStationCount';
import { TaskFlowSteps } from './TaskFlowSteps';
import { recoverySummary } from '../lib/downloadCenterLogic';
import { readDownloadResponse, saveDownloadBlob, downloadOutput, downloadErrorMessage } from '../lib/outputDownload';
import { isBaize, isXiaoxiang, isRiderArchive, isGlobalDataset, datasetGroup,isMerchant,isMerchantSnapshot,toggleDownloadDataset } from '../lib/downloadCenterLogic';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, CloudDownload, Download, KeyRound, Loader2, RefreshCw, Square, X, XCircle, FileSpreadsheet, Calculator } from 'lucide-react';
import { DownloadAccountPanel } from './DownloadAccountPanel';
import type { FengshenAuthStatus } from './FengshenLoginModal';
import { itemKey, phaseLabel, recoverable, retainAttempt, selectionKey, isLanorange } from '../lib/downloadCenterLogic';
import type { CreateSelection, DownloadUser, ItemSelection, Recovery, RequestAttempt } from '../lib/downloadCenterLogic';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { DownloadRecords } from './DownloadRecords';
import { ReportBuilder } from './ReportBuilder';
import { reportRange, type ReportDefinition } from '../lib/reportBuilder';
import { isGenerator, inferTaskKind, registerGeneratorIds } from '../lib/taskCatalog';
import { DOWNLOAD_PLATFORMS,moduleAcceptsDataset,type DownloadPlatform,type RecordModule } from '../lib/downloadModules';
import { WorkbenchDatePicker } from './WorkbenchDatePicker';
import {
  BUILTIN_DOWNLOAD_SCENARIOS,
  buildExecutionRailSummary,
  computeBillingPeriodRange,
  computeLighthousePeriodRange,
  getDatasetCardMeta,
  getStageHeaderMeta,
  SYSTEM_META,
  type BillingPeriodPreset,
  type BuiltinScenarioPreset,
} from '../lib/workbench';

interface DownloadOptions {
  generators?: ReportDefinition[];
  cities: { name: string; id: string; disabled?: boolean; note?: string }[];
  cities_source?: 'fengshen' | 'config';
  cities_updated_at?: string;
  datasets: { id: string; label: string; group?: string; scope?: string }[];
  timezone: string;
  order_window_days: number;
  archive_root?: string;
  archive_naming_version?: string | number;
}

interface DownloadFile {
  artifact_role?: 'summary';
  id: string;
  name: string;
  city: string;
  dataset: string;
  start: string;
  end: string;
  bytes: number;
}

interface DownloadItem extends ItemSelection {
  status: string; error?: string; phase?: string; phase_since?: string;
  failure_phase?: string; submission_state?: 'not_submitted' | 'submitted' | 'unknown'; recovery?: Recovery;
}
const ORDER_TIMING_LABELS: Record<string, string> = {
  platform_poll_wait_seconds: '等待平台生成（轮询间隔）', source_download_seconds: '下载原始文件',
  source_read_seconds: '读取原始文件', source_validate_seconds: '校验来源资料',
  cache_read_seconds: '读取历史缓存', cache_write_seconds: '保存历史缓存',
  spool_write_seconds: '写入预处理资料', spool_read_seconds: '读取预处理资料',
  merge_seconds: '合并与重复检查', penalty_clean_seconds: '整理奖惩数据',
  classification_seconds: '问题单分类', summary_seconds: '生成问题单汇总',
  finalize_seconds: '本地汇总处理', csv_write_seconds: '写入结果文件',
};

interface PerformanceReport {
  order_pipelines?: {collection_seconds?: number; parser_seconds?: number; finalize_seconds?: number; timings?: Record<string, number>}[];
  elapsed_seconds?: number; total_seconds?: number; queued_seconds?: number; summary_seconds?: number;
  sampled_process_peak_rss_bytes?: number;
  stages?: Record<string, {seconds: number; calls: number}>;
  source_cache?: {hits: number; misses: number; retained_bytes: number; spill_files?: number; spill_bytes?: number};
  scheduler?: {collection_released_before_local_work: boolean; local_queue_seconds: number};
  generators?: {name: string; scope?: {city: string; month: string}; elapsed_seconds: number; stages: Record<string, {seconds: number; calls: number}>}[];
}
interface DownloadRun {
  performance?: PerformanceReport;
  lanorange_by_city?: boolean;
  lanorange_full_delivery?: boolean;
  lanorange_months?: string[];
  refresh_history?: boolean;
  waybill_all_city_send?: boolean;
  include_separation?: boolean;
  exclude_separation?: boolean;
  order_progress?: { batches?: number; batch?: number; obtained?: number; downloaded?: number; processed?: number;
    cached_days?: number; download_bytes?: number; processed_rows?: number; elapsed_seconds?: number; stage?: string };
  summary_progress?: { stage?: 'merging' | 'completed' | 'failed'; current?: number; total?: number; city?: string; month?: string };
  id: string;
  status: string;
  created_at: string;
  start: string;
  end: string;
  cities: string[];
  datasets: string[];
  progress: number;
  summary?: string | { total?: number; completed?: number; success?: number; error?: number; cancelled?: number; files?: number };
  error?: string;
  logs?: { time: string; message: string }[];
  items?: DownloadItem[];
  files?: DownloadFile[];
  recovery_of?: string;
  archive_relative_dir?: string;
  archive_code?: string;
  archive_version?: string | number;
  retry_of?: string;
  phase?: string;
  phase_since?: string;
  last_activity_at?: string;
  queue_position?: number;
  queue_wait_reason?: 'local_capacity' | 'collection_busy' | 'queued';
}

interface Props {
  platform?: DownloadPlatform;
  recordModule?: RecordModule;
  taskKind?: 'download' | 'generate';
  hideNavigation?: boolean;
  onTaskKindChange?: (kind: 'download' | 'generate') => void;
  onViewChange?: (view: 'create' | 'history') => void;
  onFormLock?: (locked: boolean) => void;
  onOpenPayroll?: (id: string) => void;
  onNavigateGenerate?: (cities: string[], start: string, end: string) => void;
  onNavigatePayroll?: (city?: string) => void;
  onOpenPrice?: (view: 'approval' | 'price-export', id?: string) => void;
  prefill?: {
    cities?: string[];
    start?: string;
    end?: string;
    taskKind?: 'download' | 'generate';
    token?: number;
  } | null;
  embedded?: boolean;
  navigation?: { view: 'create' | 'history'; version: number };
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>;
  workspaceId: string;
  onOpenFengshenLogin?: (accountId?: string) => void;
  onAccountChange?: (accountId?: string) => void;
  onActiveCountChange?: (count: number) => void;
  fengshenAuthStatus?: FengshenAuthStatus | null;
}

const API_ROOT = '/api/fengshen-downloads';
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const LANORANGE_CITIES = ['保定','北京','潮州','大连','东莞','广州','惠州','宁波','泉州','三亚','汕头','上海','韶关','深圳','台州','天津'];
const DATASET_LABELS: Record<string, string> = {
  invitation_records:'邀请记录（全量）',attendance_detail:'骑手出勤明细',baize_employees: '商翼员工资料（全量）', rider_daily: '日维度骑手分析（灯塔）', rider_archive: '骑手档案（灯塔）', detail_orders: '配送订单明细（灯塔）', detail_kesu: '配送客诉明细（灯塔）', detail_reviews: '配送评价明细（灯塔）', rider_order_detail: '骑手订单明细（灯塔）', xiaoxiang_attendance_detail: '骑手出勤明细合并（灯塔）', delivery_fee: '配送费', penalty: '违规扣款', rider_monthly: '风神骑手月度 UB 账单',
  receive_account: '骑手风神绑定', rider_detail: '骑手数据明细', rider_info: '骑手信息导出', fraud: '欺诈单', problem: '问题单',
  payment_binding: '骑手支付绑定（生成表）', goods_rent: '物资租用登记',
  abnormal_followup: '异常骑手跟进（生成表）',
  abnormal_riders: '异常骑手整理（生成表）',
  lanorange_summary: '蓝橙资料汇总',
};
const MONTHLY_DATASETS = new Set(['rider_monthly', 'receive_account']);
const SNAPSHOT_DATASETS = new Set(['rider_info', 'goods_rent']);
const TERMINAL_STATUSES = new Set(['success', 'succeeded', 'completed', 'complete', 'partial', 'partial_failed', 'partial_failure', 'partially_completed', 'error', 'failed', 'cancelled', 'canceled', 'interrupted', 'aborted']);

function canRecoverDetail(run: DownloadRun | null) {
  return !!run && !run.recovery_of && run.cities?.length === 1
    && !run.items?.some(item => !!item.recovery)
    && ['error', 'partial'].includes(run.status.toLowerCase())
    && !!run.items?.some(item => item.dataset === 'rider_detail' && item.status.toLowerCase() !== 'success');
}

function readAttempt<T>(key: string): RequestAttempt<T> | null {
  try { const value = JSON.parse(sessionStorage.getItem(key) || 'null'); return value?.request_id && value?.payload ? value : null; }
  catch { return null; }
}
function storeAttempt(key: string, value: unknown) {
  try { if (value) sessionStorage.setItem(key, JSON.stringify(value)); else sessionStorage.removeItem(key); } catch {}
}
class DownloadRequestError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

function statusInfo(status: string) {
  const normalized = (status || '').toLowerCase();
  if (['success', 'succeeded', 'completed', 'complete'].includes(normalized)) return { label: '已完成', color: 'text-emerald-700 bg-emerald-50 border border-emerald-200' };
  if (['partial', 'partial_failed', 'partial_failure', 'partially_completed'].includes(normalized)) return { label: '部分完成', color: 'text-amber-700 bg-amber-50 border border-amber-200' };
  if (['waiting_login', 'waiting_for_login', 'login_required', 'waiting_auth'].includes(normalized)) return { label: '等待认证', color: 'text-amber-700 bg-amber-50 border border-amber-200' };
  if (['queued', 'pending', 'waiting'].includes(normalized)) return { label: '排队中', color: 'text-slate-600 bg-slate-100 border border-slate-200' };
  if (['error', 'failed'].includes(normalized)) return { label: '失败', color: 'text-rose-700 bg-rose-50 border border-rose-200' };
  if (['cancelled', 'canceled'].includes(normalized)) return { label: '已取消', color: 'text-slate-600 bg-slate-100 border border-slate-200' };
  if (['interrupted', 'aborted'].includes(normalized)) return { label: '已中断', color: 'text-amber-700 bg-amber-50 border border-amber-200' };
  if (['cancelling', 'canceling'].includes(normalized)) return { label: '正在停止', color: 'text-slate-600 bg-slate-100 border border-slate-200' };
  if (normalized === 'empty' || normalized === 'no_data') return { label: '无记录', color: 'text-slate-600 bg-slate-100 border border-slate-200' };
  return { label: normalized === 'running' || normalized === 'downloading' ? '下载中' : '处理中', color: 'text-sky-700 bg-sky-50 border border-sky-200' };
}

function shanghaiToday() {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const value = (type: string) => parts.find(part => part.type === type)?.value || '';
  return `${value('year')}-${value('month')}-${value('day')}`;
}

function coveredMonths(start: string, end: string) {
  if (!DATE_PATTERN.test(start) || !DATE_PATTERN.test(end) || start > end) return [];
  const [startYear, startMonth] = start.split('-').map(Number);
  const [endYear, endMonth] = end.split('-').map(Number);
  const first = startYear * 12 + startMonth - 1;
  const last = endYear * 12 + endMonth - 1;
  if (last - first > 1200) return [];
  return Array.from({ length: last - first + 1 }, (_, index) => {
    const month = first + index;
    return `${Math.floor(month / 12)}年${String(month % 12 + 1).padStart(2, '0')}月`;
  });
}

function displayTime(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
}

function formatSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

function saveBlobToDevice(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename.replace(/[\\/:*?"<>|]/g, '_');
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function FengshenDownloadCenter(props: Props) {
  return <DownloadAccountPanel apiFetch={props.apiFetch} onAccountChange={props.onAccountChange}>{(user, authenticatedFetch) => <AuthorizedDownloadCenter key={user.id} {...props} apiFetch={authenticatedFetch} user={user} />}</DownloadAccountPanel>;
}

function AuthorizedDownloadCenter({ apiFetch, workspaceId, onOpenFengshenLogin, onActiveCountChange, fengshenAuthStatus, user, embedded, navigation, taskKind = 'download', platform,recordModule,hideNavigation, onTaskKindChange, onViewChange, onFormLock, onOpenPayroll, onNavigateGenerate, onNavigatePayroll, onOpenPrice, prefill }: Props & { user: DownloadUser }) {
  const apiRef = useRef(apiFetch);
  apiRef.current = apiFetch;
  const [options, setOptions] = useState<DownloadOptions | null>(null);
  const [optionsError, setOptionsError] = useState('');
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionVersion, setOptionVersion] = useState(0);
  const [cities, setCities] = useState<string[]>([]);
  const [datasets, setDatasets] = useState<string[]>(() => taskKind === 'generate' ? ['payment_binding'] : []);
  const categorySelections = useRef<Record<string, string[]>>({download: [], generate: ['payment_binding'],baize:['baize_employees'],xiaoxiang:['rider_daily']});
  const selectionScope=taskKind==='generate'?'generate':platform||'download';
  const previousKind = useRef(selectionScope);
  const moduleDataset=(id:string)=>taskKind==='generate'?isGenerator(id):!isGenerator(id)&&(!platform||moduleAcceptsDataset(id,platform));
  const visibleDatasets=options?.datasets.filter(value=>moduleDataset(value.id))||[];
  const [start, setStart] = useState(() => taskKind === 'generate' ? computeBillingPeriodRange('last_full_month', shanghaiToday()).start : `${shanghaiToday().slice(0, 7)}-01`);
  const [end, setEnd] = useState(() => taskKind === 'generate' ? computeBillingPeriodRange('last_full_month', shanghaiToday()).end : shanghaiToday());
  const [refreshHistory, setRefreshHistory] = useState(false);
  const [waybillAllCitySend, setWaybillAllCitySend] = useState(false);
  const [lanorangeMonths, setLanorangeMonths] = useState<string[]>([]);
  const [blueCities, setBlueCities] = useState<string[]>([]);
  const [includeSeparation, setIncludeSeparation] = useState(false);
  const [excludeSeparation, setExcludeSeparation] = useState(true);
  const scopeSelections = useRef<Record<string, {cities:string[];start:string;end:string;includeSeparation:boolean;excludeSeparation:boolean}>>({});
  const [runs, setRuns] = useState<DownloadRun[]>([]);
  const [cityPickerOpen, setCityPickerOpen] = useState(false);
  const [citySearch, setCitySearch] = useState('');
  const [view, setView] = useState<'create' | 'history'>('create');
  useEffect(() => { if (navigation) setView(navigation.view); }, [navigation?.version]);

  useEffect(() => {
    if (!prefill || !prefill.token) return;
    const target = prefill.taskKind === 'generate' ? 'generate' : selectionScope;
    scopeSelections.current[target] = {cities:prefill.cities || cities, start:prefill.start || start, end:prefill.end || end, includeSeparation,excludeSeparation};
    if (prefill.cities && prefill.cities.length) {
      setCities(prefill.cities);
    }
    if (prefill.start) setStart(prefill.start);
    if (prefill.end) setEnd(prefill.end);
    if (prefill.taskKind && onTaskKindChange) onTaskKindChange(prefill.taskKind);
  }, [prefill?.token]);
  const presetsKey = `download-presets:${user.id}`;
  const [presets, setPresets] = useState<{ name: string; cities: string[]; datasets: string[] }[]>(() => {
    try { const parsed = JSON.parse(localStorage.getItem(presetsKey) || '[]'); return Array.isArray(parsed) ? parsed.filter(item => Array.isArray(item?.cities) && Array.isArray(item?.datasets)) : []; } catch { return []; }
  });
  const [presetInputOpen, setPresetInputOpen] = useState(false);
  const [presetDraft, setPresetDraft] = useState('');
  const [systemFilter, setSystemFilter] = useState<'all' | 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang'>('all');
  const [historyFocusId,setHistoryFocusId]=useState('');
  const [submittedTaskInfo, setSubmittedTaskInfo] = useState<{ id: string; name: string } | null>(null);

  const lastTaskKey = `download-last-task:${user.id}:${workspaceId}`;
  const [selectedId, setSelectedId] = useState(() => { try { return localStorage.getItem(lastTaskKey) || ''; } catch { return ''; } });
  useEffect(() => { try { if (selectedId) localStorage.setItem(lastTaskKey, selectedId); } catch {} }, [lastTaskKey, selectedId]);
  const selectedIdRef = useRef(selectedId);
  const [selectedRun, setSelectedRun] = useState<DownloadRun | null>(null);
  const [scopeReview, setScopeReview] = useState<CreateSelection | null>(null);
  useEffect(() => {
    const changed = () => setScopeReview(null);
    window.addEventListener('platform-auth:changed', changed);
    return () => window.removeEventListener('platform-auth:changed', changed);
  }, []);
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);
  const createStorageKey = `download-create-attempt:${user.id}`;
  const retryStorageKey = `download-retry-attempt:${user.id}`;
  const createAttempt = useRef(readAttempt<CreateSelection>(createStorageKey));
  const retryAttempt = useRef(readAttempt<{ runId: string; items: ItemSelection[] }>(retryStorageKey));
  const [uncertainCreate, setUncertainCreate] = useState(!!createAttempt.current);
  useEffect(() => { onFormLock?.(uncertainCreate || creating); }, [uncertainCreate, creating]);
  useEffect(() => { onViewChange?.(view); }, [view]);
  useEffect(() => {
    if (previousKind.current === selectionScope || createAttempt.current) return;
    const previous = previousKind.current; previousKind.current = selectionScope;
    scopeSelections.current[previous] = {cities:[...cities],start,end,includeSeparation,excludeSeparation};
    const savedScope = scopeSelections.current[selectionScope];
    if (savedScope) {
      setCities(savedScope.cities); setStart(savedScope.start); setEnd(savedScope.end); setIncludeSeparation(savedScope.includeSeparation); setExcludeSeparation(savedScope.excludeSeparation);
    } else if (taskKind === 'generate') {
      const period = computeBillingPeriodRange('last_full_month', shanghaiToday());
      setCities([]); setStart(period.start); setEnd(period.end); setIncludeSeparation(false); setExcludeSeparation(true);
    } else {
      const yesterday = new Date(shanghaiToday() + 'T00:00:00Z'); yesterday.setUTCDate(yesterday.getUTCDate() - 1);
      const lastDay = yesterday.toISOString().slice(0, 10);
      setCities([]); setStart(platform === 'xiaoxiang' ? lastDay : `${shanghaiToday().slice(0, 7)}-01`);
      setEnd(platform === 'xiaoxiang' ? lastDay : shanghaiToday()); setIncludeSeparation(false); setExcludeSeparation(true);
    }
    setDatasets(values => {
      categorySelections.current[previous] = values;
      const saved = categorySelections.current[selectionScope]||[];
      return taskKind === 'download' ? saved.filter(moduleDataset) : [saved.find(isGenerator) || 'payment_binding'];
    });
    setDuplicateApproval('');
  }, [selectionScope]);
  useEffect(() => {
    const previous = createAttempt.current?.payload;
    if (previous) { setCities(previous.cities); setDatasets(previous.datasets); setStart(previous.start); setEnd(previous.end); setRefreshHistory(!!previous.refresh_history); setWaybillAllCitySend(!!previous.waybill_all_city_send); setLanorangeMonths(Array.isArray(previous.lanorange_months) ? previous.lanorange_months : []); setBlueCities(previous.datasets?.every(isLanorange) && !previous.datasets.includes('abnormal_riders') ? (previous.cities || []).filter(city => city !== '全部城市') : []); setIncludeSeparation(!!previous.include_separation); setExcludeSeparation(previous.exclude_separation??true); }
  }, []);
  const [uncertainRetry, setUncertainRetry] = useState(!!retryAttempt.current);
  const [retryPending, setRetryPending] = useState(false);
  const retryPendingRef = useRef(false);
  const [retryKeys, setRetryKeys] = useState<string[]>([]);
  const [duplicateApproval, setDuplicateApproval] = useState('');
  const [resumingRunId, setResumingRunId] = useState('');
  const resumingRef = useRef(false);
  const [recoveryError, setRecoveryError] = useState<{ runId: string; message: string } | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [downloadingSummaryId, setDownloadingSummaryId] = useState('');
  const downloadingSummaryRef = useRef(false);
  const downloadControllers = useRef(new Set<AbortController>());
  const attemptOpenController = useRef<AbortController | null>(null);
  const [requestError, setRequestError] = useState('');
  const [pollError, setPollError] = useState('');
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const prevRunStatuses = useRef<Map<string, string>>(new Map());

  useEffect(() => () => {
    attemptOpenController.current?.abort();
    for (const controller of downloadControllers.current) controller.abort();
    downloadControllers.current.clear();
  }, [workspaceId]);

  const getJson = useCallback(async (url: string, init: RequestInit = {}) => {
    const response = await apiRef.current(url, { ...init, signal: init.signal || AbortSignal.timeout(15000) });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || data.success === false) {
      const reason = data?.error || data?.detail || data?.message;
      throw new DownloadRequestError(typeof reason === 'string' ? reason : '下载服务暂不可用，请稍后重试', response.status);
    }
    return data;
  }, []);
  const stationDirectory=useStationDirectory(platform==='xiaoxiang'?'xiaoxiang':'fengshen',apiRef.current,platform!=='baize');

  useEffect(() => {
    const controller = new AbortController();
    setOptionsError('');
    setOptionsLoading(true);
    // First paint uses cached options; explicit refresh synchronizes the platform.
    void getJson(`${API_ROOT}/options?${optionVersion ? 'refresh=1' : 'cached=1'}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]) })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.cities) || !Array.isArray(data.datasets)) throw new Error('下载选项暂不可用，请重试');
        registerGeneratorIds((data.generators || []).map((report: ReportDefinition) => report.id));
        setOptions(data);
        window.dispatchEvent(new CustomEvent('workbench:city-directory',{detail:data}));
        setCities(previous => previous.filter(city => data.cities.some((item: { name: string; disabled?: boolean }) => item.name === city && !item.disabled)));
        setDatasets(previous => previous.filter(dataset => data.datasets.some((item: { id: string }) => item.id === dataset)));
      })
      .catch(error => { if (!controller.signal.aborted) setOptionsError(error instanceof Error ? error.message : '无法加载下载选项'); })
      .finally(() => { if (!controller.signal.aborted) setOptionsLoading(false); });
    return () => controller.abort();
  }, [getJson, workspaceId, optionVersion]);

  // 任务从运行中翻转为终态时发一次系统通知（需浏览器通知权限）
  const notifyFinishedRuns = (nextRuns: DownloadRun[]) => {
    const previous = prevRunStatuses.current;
    for (const run of nextRuns) {
      const before = previous.get(run.id);
      if (!before || TERMINAL_STATUSES.has(before.toLowerCase()) || !TERMINAL_STATUSES.has(run.status.toLowerCase())) continue;
      const normalized = run.status.toLowerCase();
      const title = ['success', 'succeeded', 'completed', 'complete'].includes(normalized) ? '下载任务已完成'
        : normalized.includes('partial') ? '下载任务部分完成（含失败项）' : '下载任务已结束';
      const scope = run.cities.length > 2 ? `${run.cities.length} 个城市` : (run.cities.join('、') || '蓝橙全量');
      const body = `${scope} · ${run.datasets.length} 类资料${run.files?.length ? ` · ${run.files.length} 个文件` : ''}`;
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        try { new Notification(title, { body }); } catch { /* 通知失败不影响轮询 */ }
      }
    }
    prevRunStatuses.current = new Map(nextRuns.map(run => [run.id, run.status]));
  };

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    let polling = false;
    const snapshot = async () => {
      if (busy || controller.signal.aborted || document.visibilityState !== 'visible') return;
      busy = true;
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]);
        const data = await getJson(`${API_ROOT}/runs`, { signal });
        if (controller.signal.aborted) return;
        const nextRuns: DownloadRun[] = Array.isArray(data.runs) ? data.runs : [];
        setRuns(nextRuns);
        notifyFinishedRuns(nextRuns);
        let id = selectedIdRef.current;
        if ((!id || !nextRuns.some(run => run.id === id)) && nextRuns.length) {
          id = nextRuns[0].id;
          selectedIdRef.current = id;
          setSelectedId(id);
        }
        if (id) {
          const detail = await getJson(`${API_ROOT}/runs/${encodeURIComponent(id)}`, { signal });
          if (!controller.signal.aborted && selectedIdRef.current === id) setSelectedRun(detail.run || null);
        }
        if (!controller.signal.aborted) setPollError('');
      } catch (error) {
        if (!controller.signal.aborted) setPollError(error instanceof Error ? error.message : '暂时无法更新下载记录');
      } finally {
        busy = false;
        if (!controller.signal.aborted) setLoadingHistory(false);
      }
    };
    refreshRef.current = snapshot;
    const tick = async () => {
      if (polling) return;
      polling = true;
      try { await snapshot(); }
      finally {
        polling = false;
        if (!controller.signal.aborted && document.visibilityState === 'visible') timer = setTimeout(tick, 2000);
      }
    };
    const onVisibility = () => {
      clearTimeout(timer);
      if (document.visibilityState === 'visible') void tick();
    };
    void tick();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      refreshRef.current = async () => {};
    };
  }, [getJson, workspaceId]);

  const datasetLabel = (id: string) => {
    const raw = options?.datasets.find(dataset => dataset.id === id)?.label || DATASET_LABELS[id] || id;
    return raw.replaceAll('白泽', '商翼').replaceAll('小象灯塔', '灯塔').replaceAll('小象', '灯塔');
  };
  const citySyncedAt = options?.cities_updated_at ? new Date(options.cities_updated_at) : null;
  const citySourceLabel = options?.cities_source === 'fengshen'
    ? `风神同步${citySyncedAt && !Number.isNaN(citySyncedAt.getTime()) ? ` · ${citySyncedAt.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}` : ''}`
    : '本地配置';
  const toggle = (value: string, values: string[], setter: (next: string[]) => void) => setter(values.includes(value) ? values.filter(item => item !== value) : [...values, value]);
  const validDates = DATE_PATTERN.test(start) && DATE_PATTERN.test(end) && start <= end;
  const selectedReport = options?.generators?.find(report => report.id === datasets[0]);
  const generationRange = reportRange(selectedReport, start, end, shanghaiToday());
  const generationAll = taskKind === 'generate' && selectedReport?.scope === 'all';
  const baizeOnly = platform === 'baize' || (datasets.length > 0 && datasets.every(isBaize));
  const xiaoxiangOnly = taskKind === 'download' && (platform ? platform === 'xiaoxiang' : datasets.length > 0 && datasets.every(isXiaoxiang));
  const archiveOnly = xiaoxiangOnly && datasets.length > 0 && datasets.every(isRiderArchive);
  const xiaoxiangDated = xiaoxiangOnly && !archiveOnly;
  const yesterday = new Date(shanghaiToday() + 'T00:00:00Z'); yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const dailyDate = yesterday.toISOString().slice(0, 10);
  const blueOnly = platform === 'lanorange' || (datasets.length > 0 && datasets.every(isGlobalDataset));
  const merchantOnly=datasets.length>0&&datasets.every(isMerchant),merchantSnapshotOnly=merchantOnly&&!datasets.includes('attendance_detail');
  const hasAttendance=datasets.includes('attendance_detail');
  const noCity=blueOnly||xiaoxiangOnly||baizeOnly,noDate=blueOnly||baizeOnly||merchantSnapshotOnly||archiveOnly;
  const attendanceDateMax=new Date(shanghaiToday()+'T00:00:00Z');attendanceDateMax.setUTCDate(attendanceDateMax.getUTCDate()-1);const attendanceLast=attendanceDateMax.toISOString().slice(0,10);
  const attendanceDateMin=new Date(shanghaiToday()+'T00:00:00Z');attendanceDateMin.setUTCDate(attendanceDateMin.getUTCDate()-90);const attendanceFirst=attendanceDateMin.toISOString().slice(0,10);
  const xiaoxiangDateMin=new Date(`${shanghaiToday()}T00:00:00Z`);xiaoxiangDateMin.setUTCDate(xiaoxiangDateMin.getUTCDate()-365);const xiaoxiangFirst=xiaoxiangDateMin.toISOString().slice(0,10);
  const xiaoxiangSpanDays=validDates?Math.round((Date.parse(`${end}T00:00:00Z`)-Date.parse(`${start}T00:00:00Z`))/86400000)+1:0;
  const xiaoxiangDateValid=validDates&&end<=dailyDate&&xiaoxiangSpanDays<=31;
  const billingPeriodRange=(preset:BillingPeriodPreset)=>{
    const range=xiaoxiangDated
      ? computeLighthousePeriodRange(preset,shanghaiToday())
      : {...computeBillingPeriodRange(preset,shanghaiToday()),blocked:false};
    const nextStart=hasAttendance&&range.start<attendanceFirst?attendanceFirst:range.start;
    const nextEnd=hasAttendance&&range.end>attendanceLast?attendanceLast:range.end;
    return {start:nextStart,end:nextEnd,blocked:range.blocked||nextStart>nextEnd};
  };
  useEffect(()=>{
    if(!xiaoxiangOnly||archiveOnly)return;
    if(end>dailyDate||start>dailyDate){setStart(dailyDate);setEnd(dailyDate);}
  },[xiaoxiangOnly,archiveOnly,dailyDate]);
  const merchantDateValid=merchantSnapshotOnly||(validDates&&start>=attendanceFirst&&end<=attendanceLast);
  const invalidBaizeMix = datasets.some(isBaize) && !baizeOnly;
  const invalidXiaoxiangMix = datasets.some(isXiaoxiang) && !xiaoxiangOnly;
  const selectableCities = options?.cities.filter(city => !city.disabled) ?? [];
  const invalidMerchantMix=hasAttendance&&!merchantDateValid;
  const canSubmit = taskKind === 'generate' ? datasets.length === 1 && !!selectedReport && !!generationRange && (generationAll || cities.length > 0) : datasets.every(moduleDataset) && !invalidBaizeMix && !invalidXiaoxiangMix && !invalidMerchantMix && datasets.length > 0 && (merchantOnly?(cities.length>0&&merchantDateValid):(archiveOnly || blueOnly || (xiaoxiangDated && xiaoxiangDateValid) || (cities.length > 0 && validDates)));
  const monthlyDatasets = datasets.filter(dataset => MONTHLY_DATASETS.has(dataset));
  const periodDatasets = datasets.filter(dataset => !isLanorange(dataset) && !MONTHLY_DATASETS.has(dataset) && !SNAPSHOT_DATASETS.has(dataset) && !['payment_binding', 'abnormal_followup'].includes(dataset));
  const followupDatasets = ['payment_binding', 'abnormal_followup'].filter(id => datasets.includes(id));
  const monthPreview = monthlyDatasets.length || followupDatasets.length ? coveredMonths(start, end) : [];
  const orderWindowDays = options?.order_window_days || 60;
  const earliestOrderDate = new Date(`${shanghaiToday()}T00:00:00Z`);
  earliestOrderDate.setUTCDate(earliestOrderDate.getUTCDate() - orderWindowDays + 1);
  const earliestOrder = earliestOrderDate.toISOString().slice(0, 10);
  const orderWindowWarning = datasets.some(dataset => ['fraud', 'problem'].includes(dataset)) && validDates && (start < earliestOrder || end > shanghaiToday());
  const priceMonthOptions = (() => {
    const [year, month] = shanghaiToday().split('-').map(Number);
    return Array.from({ length: 12 }, (_, index) => {
      const value = new Date(Date.UTC(year, month - 1 - index, 1));
      return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, '0')}`;
    });
  })();
  const currentSelection: CreateSelection = taskKind === 'generate' ? {
    task_kind: 'generate', generation_target: datasets[0], datasets,
    cities: generationAll ? ['全部城市'] : cities,
    start: generationAll ? shanghaiToday() : generationRange?.start || start,
    end: generationAll ? shanghaiToday() : generationRange?.end || end,
    ...(datasets.some(isLanorange) ? {lanorange_full_delivery:true} : {}),
    ...(selectedReport?.station_rule === 'separation' && !generationAll && includeSeparation ? {include_separation:true} : {}),
  } : { task_kind: taskKind, cities: blueOnly ? (blueCities.length && !datasets.includes('abnormal_riders') ? blueCities : ['全部城市']) : xiaoxiangOnly || baizeOnly ? ['全部城市'] : cities, datasets, ...(datasets.some(isLanorange) || blueOnly ? {lanorange_full_delivery:true} : {}),
    start: archiveOnly ? shanghaiToday() : xiaoxiangDated ? start : blueOnly||baizeOnly||merchantSnapshotOnly ? shanghaiToday() : start, end: archiveOnly ? shanghaiToday() : xiaoxiangDated ? end : blueOnly||baizeOnly||merchantSnapshotOnly ? shanghaiToday() : end,
    ...(refreshHistory && datasets.some(dataset => ['fraud', 'problem'].includes(dataset)) ? { refresh_history: true } : {}),
    ...(waybillAllCitySend && datasets.includes('delivery_waybill') ? { waybill_all_city_send: true } : {}),
    ...(blueOnly && datasets.includes('lanorange_part_price') && lanorangeMonths.length ? { lanorange_months: [...lanorangeMonths].sort() } : {}),
    ...(datasets.some(isMerchant)?{merchant_by_city:true}:{}), ...(!noCity && !merchantOnly ? { exclude_separation: excludeSeparation } : {}) };
  const currentSelectionKey = selectionKey(currentSelection);
  const matchingRun = runs.find(run => !TERMINAL_STATUSES.has(run.status) && selectionKey(run) === currentSelectionKey)
    || (!followupDatasets.length && !datasets.some(isLanorange) && !merchantOnly ? runs.find(run => selectionKey(run) === currentSelectionKey && !!run.files?.length) : undefined);
  const completedMatch = matchingRun && TERMINAL_STATUSES.has(matchingRun.status) && !!matchingRun.files?.length;
  const formLocked = creating || uncertainCreate;

  const selectRun = (run: DownloadRun) => {
    setView('history');
    selectedIdRef.current = run.id;
    setSelectedId(run.id);
    setSelectedRun(run);
    setRetryKeys([]);
    setRequestError('');
    void refreshRef.current();
  };

  const savePreset = (customName?: string) => {
    const rawName = typeof customName === 'string' ? customName : presetDraft;
    const trimmed = rawName.trim();
    if (!trimmed) return;
    const next = [...presets.filter(preset => preset.name !== trimmed), { name: trimmed, cities: [...cities], datasets: [...datasets] }].slice(-12);
    setPresets(next);
    setPresetDraft('');
    setPresetInputOpen(false);
    try { localStorage.setItem(presetsKey, JSON.stringify(next)); } catch { /* 存储不可用时仅保留在内存 */ }
  };
  const applyPreset = (preset: { name: string; cities: string[]; datasets: string[] }) => {
    if (preset.datasets.some(isGenerator) && preset.datasets.length !== 1) { setRequestError('此预设包含旧版混合选择，请按任务类型分别新建。'); return; }
    categorySelections.current[taskKind] = datasets;
    categorySelections.current[inferTaskKind(preset.datasets)] = preset.datasets;
    onTaskKindChange?.(inferTaskKind(preset.datasets));
    setCities(preset.cities.filter(city => !options || options.cities.some(item => item.name === city && !item.disabled)));
    setDatasets(preset.datasets.filter(id => !options || options.datasets.some(item => item.id === id)));
    setDuplicateApproval('');
  };
  const removePreset = (name: string) => {
    const next = presets.filter(preset => preset.name !== name);
    setPresets(next);
    try { localStorage.setItem(presetsKey, JSON.stringify(next)); } catch { /* 同上 */ }
  };
  const applyBuiltinScenario = (scenario: BuiltinScenarioPreset) => {
    if (formLocked) return;
    const validIds = scenario.datasets.filter(id => !options || options.datasets.some(item => item.id === id));
    categorySelections.current[taskKind] = datasets;
    categorySelections.current.download = validIds;
    onTaskKindChange?.('download');
    setDatasets(validIds);
    setDuplicateApproval('');
    setRequestError('');
  };
  const applyBillingPeriod = (preset: BillingPeriodPreset) => {
    if (formLocked) return;
    const range = billingPeriodRange(preset);
    if (range.blocked) return;
    setStart(range.start);
    setEnd(range.end);
    setDuplicateApproval('');
  };

  // 用历史任务的城市/资料/日期预填新建表单
  const prefillFromRun = (run: DownloadRun) => {
    if (run.datasets.some(isGenerator) && (run.datasets.length !== 1 || !isGenerator(run.datasets[0]))) {
      setRequestError('此记录包含旧版混合选择，请按资料下载或业务表生成分别新建。'); return;
    }
    categorySelections.current[taskKind] = datasets;
    categorySelections.current[inferTaskKind(run.datasets)] = run.datasets;
    if (inferTaskKind(run.datasets) === 'generate') {
      scopeSelections.current.generate = {
        cities:run.cities.filter(city => city !== '全部城市' && (!options || options.cities.some(item => item.name === city && !item.disabled))),
        start:!run.datasets.every(isLanorange) && DATE_PATTERN.test(run.start) ? run.start : start,
        end:!run.datasets.every(isLanorange) && DATE_PATTERN.test(run.end) ? run.end : end,
        includeSeparation:false,excludeSeparation:true,
      };
    }
    onTaskKindChange?.(inferTaskKind(run.datasets));
    setCities(run.cities.filter(city => city !== '全部城市' && (!options || options.cities.some(item => item.name === city && !item.disabled))));
    setBlueCities(run.lanorange_by_city && Array.isArray(run.cities) ? run.cities.filter(city => city !== '全部城市') : []);
    setDatasets(run.datasets.filter(id => !options || options.datasets.some(item => item.id === id)));
    if (!run.datasets.every(isLanorange) && DATE_PATTERN.test(run.start) && DATE_PATTERN.test(run.end)) { setStart(run.start); setEnd(run.end); }
    setRefreshHistory(false);
    setWaybillAllCitySend(run.waybill_all_city_send === true);
    setLanorangeMonths(Array.isArray(run.lanorange_months) ? run.lanorange_months : []);
    setIncludeSeparation(false);
    setExcludeSeparation(run.exclude_separation??true);
    setDuplicateApproval('');
    setRequestError('');
    setView('create');
  };

  const startDownload = async (confirmedKey?: string) => {
    if (creatingRef.current || !options || (!createAttempt.current && !canSubmit)) return;
    if (!createAttempt.current && matchingRun && !TERMINAL_STATUSES.has(matchingRun.status)) { selectRun(matchingRun); return; }
    if (!createAttempt.current && completedMatch && duplicateApproval !== currentSelectionKey) { selectRun(matchingRun!); return; }
    if (!createAttempt.current && confirmedKey !== currentSelectionKey) { setScopeReview(JSON.parse(JSON.stringify(currentSelection))); return; }
    createAttempt.current = retainAttempt(createAttempt.current, currentSelection);
    storeAttempt(createStorageKey, createAttempt.current);
    creatingRef.current = true;
    setCreating(true);
    setRequestError('');
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission();
    try {
      const data = await getJson(`${API_ROOT}/runs`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...createAttempt.current.payload, request_id: createAttempt.current.request_id }),
      });
      if (!data.run?.id) throw new Error('未取得下载任务，请刷新记录确认后再试');
      const run: DownloadRun = data.run;
      createAttempt.current = null; storeAttempt(createStorageKey, null); setUncertainCreate(false); setDuplicateApproval('');
      setRuns(previous => [run, ...previous.filter(item => item.id !== run.id)]);
      selectedIdRef.current = run.id;
      setSelectedId(run.id);
      setSelectedRun(run);
      setSubmittedTaskInfo({
        id: run.id,
        name: run.datasets.map(datasetLabel).join('、'),
      });
      if (taskKind === 'generate') selectRun(run);
      void refreshRef.current();
    } catch (error) {
      const rejected = error instanceof DownloadRequestError && [400, 401, 403, 404, 409, 415, 422].includes(error.status);
      if (rejected) { createAttempt.current = null; storeAttempt(createStorageKey, null); }
      setUncertainCreate(!rejected);
      setRequestError(rejected ? error.message : '下载请求结果尚未确认。请使用“重新确认原请求”，系统会沿用同一请求编号，不会盲目新建任务。');
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  };

  const retrySelected = async (only?: ItemSelection) => {
    if (retryPendingRef.current || (!retryAttempt.current && !selectedRun)) return;
    const selected = selectedRun?.items?.filter(item => (only ? itemKey(only) === itemKey(item) : retryKeys.includes(itemKey(item))) && recoverable(item)) || [];
    if (!retryAttempt.current && !selected.length) return;
    if (!retryAttempt.current) retryAttempt.current = retainAttempt(null, { runId: selectedRun!.id, items: selected.map(({ city, dataset, start, end }) => ({ city, dataset, start, end })) });
    storeAttempt(retryStorageKey, retryAttempt.current);
    retryPendingRef.current = true; setRetryPending(true); setRequestError('');
    try {
      const attempt = retryAttempt.current;
      const data = await getJson(`${API_ROOT}/runs/${encodeURIComponent(attempt.payload.runId)}/retry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: attempt.payload.items, request_id: attempt.request_id }),
      });
      if (!data.run?.id) throw new Error('未取得分项处理任务');
      retryAttempt.current = null; storeAttempt(retryStorageKey, null); setUncertainRetry(false); setRetryKeys([]);
      setRuns(previous => [data.run, ...previous.filter(run => run.id !== data.run.id)]);
      selectRun(data.run);
    } catch (error) {
      const rejected = error instanceof DownloadRequestError && [400, 401, 403, 404, 409, 415, 422].includes(error.status);
      if (rejected) { retryAttempt.current = null; storeAttempt(retryStorageKey, null); }
      setUncertainRetry(!rejected);
      setRequestError(rejected ? error.message : '分项操作结果尚未确认，请重新确认原分项请求；不会更换请求编号或重新发起不明导出。');
    } finally { retryPendingRef.current = false; setRetryPending(false); }
  };

  const cancelDownload = async () => {
    if (!selectedRun || cancelling) return;
    const id = selectedRun.id;
    setCancelling(true);
    setRequestError('');
    try {
      const data = await getJson(`${API_ROOT}/runs/${encodeURIComponent(id)}/cancel`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      if (selectedIdRef.current === id && data.run) setSelectedRun(data.run);
      void refreshRef.current();
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : '无法停止任务');
    } finally { setCancelling(false); }
  };

  const resumeDetail = async () => {
    if (resumingRef.current || !canRecoverDetail(selectedRun)) return;
    const id = selectedRun!.id;
    resumingRef.current = true;
    setResumingRunId(id);
    setRecoveryError(null);
    try {
      const data = await getJson(`${API_ROOT}/runs/${encodeURIComponent(id)}/resume-detail`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      if (!data.run?.id || data.run.id === id) throw new Error('恢复任务状态尚未确认，请刷新下载记录查看，不要重新发起导出');
      const run: DownloadRun = { ...data.run, recovery_of: data.run.recovery_of || id };
      setRuns(previous => [run, ...previous.filter(item => item.id !== run.id)]);
      selectedIdRef.current = run.id;
      setSelectedId(run.id);
      setSelectedRun(run);
      setView('history');
      void refreshRef.current();
    } catch (error) {
      const uncertain = error instanceof Error && ['TimeoutError', 'AbortError', 'TypeError'].includes(error.name);
      setRecoveryError({
        runId: id,
        message: uncertain ? '恢复请求结果尚未确认，请刷新下载记录查看，不要重新发起导出'
          : error instanceof Error ? error.message : '恢复未能启动，请查看下载记录，不要重新发起导出',
      });
    } finally {
      resumingRef.current = false;
      setResumingRunId('');
    }
  };

  const downloadSummary = async () => {
    if (!selectedRun || downloadingSummaryRef.current || !TERMINAL_STATUSES.has(selectedRun.status.toLowerCase())) return;
    const run = selectedRun;
    const controller = new AbortController();
    downloadControllers.current.add(controller);
    downloadingSummaryRef.current = true;
    setDownloadingSummaryId(run.id);
    setRequestError('');
    try {
      const response = await apiRef.current(`${API_ROOT}/runs/${encodeURIComponent(run.id)}/summary`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]) });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(typeof data?.detail === 'string' ? data.detail : typeof data?.error === 'string' ? data.error : '下载说明暂不可用，请稍后重试');
      }
      const code = run.archive_code || run.id.slice(0, 6).toUpperCase();
      const blob = await readDownloadResponse(response, `下载说明_${code}.txt`);
      if (!controller.signal.aborted) saveBlobToDevice(blob, `下载说明_${code}.txt`);
    } catch (error) {
      if (!controller.signal.aborted) setRequestError(error instanceof Error ? error.message : '下载说明保存失败，请重试');
    } finally {
      downloadControllers.current.delete(controller);
      downloadingSummaryRef.current = false;
      setDownloadingSummaryId('');
    }
  };

  const [rawBusy, setRawBusy] = useState(false);
  const rawBusyRef = useRef(false);
  const downloadRawBundle = async () => {
    if (!selectedRun || rawBusyRef.current) return;
    rawBusyRef.current = true; setRawBusy(true);
    setRequestError('');
    try {
      const response = await apiRef.current(`${API_ROOT}/runs/${selectedRun.id}/raw-bundle`, { signal: AbortSignal.timeout(120000) });
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '原始资料领取失败'); }
      saveDownloadBlob(await readDownloadResponse(response, `原始资料_${selectedRun.id.slice(0, 8)}.zip`), `原始资料_${selectedRun.id.slice(0, 8)}.zip`);
    } catch (error) { setRequestError(downloadErrorMessage(error)); }
    finally { rawBusyRef.current = false; setRawBusy(false); }
  };

  const [fileBusy, setFileBusy] = useState('');
  const fileBusyRef = useRef(false);
  const downloadFile = async (id: string, name: string) => {
    if (!selectedRun || fileBusyRef.current) return;
    fileBusyRef.current = true; setFileBusy(id); setRequestError('');
    try { await downloadOutput(`${API_ROOT}/runs/${selectedRun.id}/files/${id}`, workspaceId, name, apiRef.current); }
    catch (error) { setRequestError(error instanceof Error ? error.message : '文件领取失败，请重试'); }
    finally { fileBusyRef.current = false; setFileBusy(''); }
  };
  const panel = 'rounded-xl border border-slate-200 bg-white';
  const smallButton = 'inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed';
  const activeRun = selectedRun && !TERMINAL_STATUSES.has(selectedRun.status.toLowerCase());
  const waitingLogin = selectedRun && (selectedRun.phase === 'waiting_login' || ['waiting_login', 'waiting_for_login', 'login_required', 'waiting_auth'].includes(selectedRun.status.toLowerCase()));
  const selectedRecoverable = selectedRun?.items?.filter(recoverable) || [];
  const blueCityScoped = blueOnly && !datasets.includes('abnormal_riders');
  const subitemCount = merchantOnly?cities.length*datasets.length:baizeOnly ? 1 : xiaoxiangOnly ? datasets.length : blueOnly ? (datasets.filter(value => isLanorange(value) && value !== 'abnormal_riders').length * Math.max(1, blueCityScoped ? blueCities.length : 1)) + (datasets.includes('abnormal_riders') ? 1 : 0) : datasets.filter(isLanorange).length + cities.length * (periodDatasets.length + followupDatasets.length * monthPreview.length + datasets.filter(value => SNAPSHOT_DATASETS.has(value)).length + monthlyDatasets.length * monthPreview.length);
  const submitHint = taskKind === 'generate'
    ? datasets[0] === 'abnormal_riders' ? '全部城市 · 全量资料 · 生成一份整理表'
      : !cities.length ? '请选择生成范围的城市' : !validDates ? '请选择有效日期' : `${cities.length} 个城市 · 按 ${monthPreview.length} 个月份生成`
    : merchantOnly?merchantSnapshotOnly?'所选城市全部邀请记录 · 按城市分别保存 · 不筛选日期':merchantDateValid?'所选城市全部站点 · 出勤按城市和日期采集后分别领取':'出勤明细请选择最近90天内、早于今天的起止日期'
    : baizeOnly ? '商翼全量员工原表 · 一份文件 · 不参与兼职自动补齐'
    : xiaoxiangOnly ? (archiveOnly ? `灯塔骑手档案 · ${datasets.length} 类资料 · 快照` : start===end ? `灯塔资料 · ${datasets.length} 类 · ${start} 单日` : `灯塔资料 · ${datasets.length} 类 · ${start} 至 ${end}，共 ${xiaoxiangSpanDays} 天`)
    : blueOnly
    ? `蓝橙全量 · ${datasets.length} 类资料，每类一个文件` + (blueCityScoped && blueCities.length ? ` · ${blueCities.length} 个城市按城市分别导出` : '，无需选择城市和日期') + (datasets.includes('lanorange_part_price') && lanorangeMonths.length ? ` · 价格档案按 ${lanorangeMonths.length} 个月份筛选` : '')
    : !datasets.length ? '请选择资料'
    : !cities.length ? '请选择城市'
    : !validDates ? '开始日期不能晚于结束日期'
    : `${cities.length} 个城市 · ${datasets.length} 类资料 · 共 ${subitemCount} 项`;
  const submitReady = !!uncertainCreate || canSubmit;
  const railSummary = buildExecutionRailSummary({
    datasetsCount: datasets.length,
    cities,
    start,
    end,
    noCity,
    noDate,
    archiveOnly,
    xiaoxiangDated,
    xiaoxiangOnly,
    blueOnly,
    baizeOnly,
    merchantOnly,
    merchantSnapshotOnly,
    merchantDateValid,
    validDates,
    includeSeparation,
    ...(taskKind === 'download' ? {excludeSeparation} : {}),
    subitemCount,
    submitReady,
  });
  const elapsed = (since?: string) => { const seconds = Math.max(0, Math.floor((now - new Date(since || "").getTime()) / 1000)); return Number.isFinite(seconds) ? seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : ""; };
  const progress = Math.max(0, Math.min(100, Number(selectedRun?.progress) || 0));
  const summaryDetail = selectedRun?.summary_progress;
  const summarizing = selectedRun?.phase === 'summarizing';
  const runStatusLabel = summarizing ? '汇总合并中' : selectedRun ? statusInfo(selectedRun.status).label : '';
  const summaryMonth = summaryDetail?.month ? `${Number(summaryDetail.month.slice(5))}月` : '';
  const summaryHint = !summarizing ? '' : summaryDetail?.stage === 'failed'
    ? '汇总合并未完成，城市文件已保留，请查看错误提示。'
    : `资料项已结束，正在生成多城市汇总${summaryMonth ? `（${summaryMonth}）` : ''}${summaryDetail?.total ? `：${summaryDetail.current || 0}/${summaryDetail.total} 个城市` : ''}${summaryDetail?.city ? ` · 正在合并 ${summaryDetail.city}` : ''}。`;
  const summary = selectedRun?.summary && typeof selectedRun.summary === 'object' ? selectedRun.summary : null;

  const runningCount = runs.filter(run => !TERMINAL_STATUSES.has(run.status.toLowerCase())).length;
  useEffect(() => { onActiveCountChange?.(runningCount); }, [runningCount, onActiveCountChange]);
  const failedItems = selectedRun?.items?.filter(item => ['error', 'failed', 'interrupted'].includes(item.status)) || [];
  const choiceStyle = (selected: boolean) => `flex min-w-0 cursor-pointer items-center gap-2.5 rounded-lg border px-3.5 py-2.5 text-sm transition-all select-none ${selected ? 'border-sky-600 bg-sky-50 text-sky-900 font-medium shadow-2xs' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50/80'}`;
  const primaryButton = 'wb-primary';
  const fieldStyle = 'min-w-0 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-600 focus:outline-none [color-scheme:light]';

  return (
    <div className="relative z-10 mx-auto flex w-full max-w-full min-w-0 flex-col gap-4 pb-5 text-slate-900">
      {!embedded && <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2.5 text-xl font-semibold"><CloudDownload size={23} className="text-sky-700" />下载中心</h1>
          <p className="mt-1.5 text-sm text-slate-500">新建下载、跟踪进度、浏览产出文件；风神资料按城市和日期，蓝橙资料统一交付。</p>
        </div>
      </header>}

      {!hideNavigation && <nav aria-label="下载中心导航" className="flex gap-1 border-b border-slate-200">
        {([['create', '新建下载'], ['history', '下载记录']] as const).map(([key, title]) => <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)} className={`border-b-2 px-4 pb-3 pt-2 text-sm font-medium ${view === key ? 'border-sky-700 text-sky-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>
          {title}{key === 'history' && runningCount > 0 && <span className="ml-2 rounded-full bg-sky-50 px-2 py-0.5 text-xs text-sky-700">{runningCount} 进行中</span>}
        </button>)}
      </nav>}

      {invalidBaizeMix && <p role="alert" className="wb-notice">商翼仅支持独立下载，请清除其他资料选择。</p>}
      {invalidXiaoxiangMix && <p role="alert" className="wb-notice">灯塔资料仅支持独立下载，请清除其他资料选择。</p>}
      {requestError && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"><AlertCircle size={17} className="shrink-0 mt-0.5" />{requestError}<button type="button" aria-label="关闭错误提示" className="ml-auto shrink-0" onClick={() => setRequestError('')}><XCircle size={16} /></button></div>}
      {pollError && <p role="status" className="text-xs text-amber-700">{pollError}。连接恢复后自动更新。</p>}
      {uncertainRetry && <div role="status" className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800"><p>上次失败项处理结果尚未确认，请先确认原请求。</p><button type="button" className={`${smallButton} mt-2`} disabled={retryPending} onClick={() => void retrySelected()}>{retryPending ? '正在确认…' : '重新确认原分项请求'}</button></div>}

      {runs.some(run => ['waiting_login', 'waiting_manual'].includes(run.phase || '')) && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800"><span>有任务正在等待登录或人工验证。</span><button type="button" className={smallButton} onClick={() => selectRun(runs.find(run => ['waiting_login', 'waiting_manual'].includes(run.phase || ''))!)}>查看并处理</button></div>}
      {uncertainCreate && view === 'history' && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800"><span>原下载请求仍待确认，请先完成确认。</span><button type="button" className={smallButton} onClick={() => setView('create')}>返回确认原请求</button></div>}

      {(() => {
        const stageMeta = getStageHeaderMeta(taskKind === 'generate' ? 'generate' : 'download', platform, view);
        return (
          <>
            {view === 'create' && <>
              <section className={taskKind === 'generate' ? 'rb-shell' : `${panel} wb-task-form wb-download-workbench ${noCity && noDate ? 'is-simple-collection' : ''}`} aria-label={taskKind === 'generate' ? '业务报表配置' : '新建下载配置'}>
                {taskKind === 'download' && !embedded && <div className="wb-form-heading">
                  <div className="wb-stage-heading-left">
                    <div className="wb-stage-title-row">
                      <h2>{stageMeta.title}</h2>
                    </div>
                    <p className="wb-muted">{stageMeta.subtitle}</p>
                  </div>
                </div>}
          {optionsError && !options ? <div role="alert" className="flex flex-wrap items-center gap-3 p-5 text-sm text-rose-700"><AlertCircle size={17} />{optionsError}<button className={smallButton} onClick={() => optionsError.includes('请刷新工作台') || optionsError.includes('账号页面已更新') ? location.reload() : setOptionVersion(version => version + 1)}>重新加载</button></div>
            : !options ? <p role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500"><Loader2 size={16} />正在加载下载选项…</p>
            : <>
              {optionsError && <p role="alert" className="wb-full-span flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 sm:px-6"><AlertCircle size={14} />城市清单刷新失败，仍显示上次结果：{optionsError}</p>}
              {taskKind === 'generate' && <ReportBuilder
                reports={(options.generators || []).filter(report => options.datasets.some(dataset => dataset.id === report.id))} selectedId={datasets[0] || ''}
                onSelect={id => { setDatasets([id]); setDuplicateApproval(''); }}
                cities={options.cities} selectedCities={cities} onCities={setCities}
                start={start} end={end} today={shanghaiToday()} onStart={setStart} onEnd={setEnd}
                includeSeparation={includeSeparation} onSeparation={setIncludeSeparation}
                locked={formLocked} creating={creating} disabled={creating || (!uncertainCreate && !canSubmit)}
                submitLabel={uncertainCreate ? '确认原请求' : matchingRun && !TERMINAL_STATUSES.has(matchingRun.status) ? '查看进行中任务' : completedMatch && duplicateApproval !== currentSelectionKey ? '查看已有结果' : '生成报表'}
                onSubmit={() => void startDownload(currentSelectionKey)}
                uncertain={uncertainCreate} duplicate={!!completedMatch} recollect={duplicateApproval === currentSelectionKey}
                onRecollect={value => setDuplicateApproval(value ? currentSelectionKey : '')}
                refreshing={optionsLoading} onRefreshCities={() => setOptionVersion(value => value + 1)}
              />}
              {taskKind === 'download' && <>
              <div className="wb-download-main">
                {!platform && <div className="wb-system-overview-bar mb-4" role="group" aria-label="四大系统数据源切换">
                  <div className="wb-row">
                    <button
                      type="button"
                      aria-pressed={systemFilter === 'all'}
                      onClick={() => setSystemFilter('all')}
                      className={`wb-system-filter-btn ${systemFilter === 'all' ? 'is-active' : ''}`}
                    >
                      全部系统
                    </button>
                    {SYSTEM_META.map(sys => {
                      const isSelectableGroup = sys.key === 'fengshen' || sys.key === 'lanorange' || sys.key === 'baize' || sys.key === 'xiaoxiang';
                      const count = isSelectableGroup
                        ? datasets.filter(id => datasetGroup(id) === sys.key).length
                        : 0;
                      if (isSelectableGroup) {
                        return (
                          <button
                            key={sys.key}
                            type="button"
                            aria-pressed={systemFilter === sys.key}
                            title={`${sys.label}（${sys.businessLine}）：${sys.description}`}
                            onClick={() => setSystemFilter(prev => prev === sys.key ? 'all' : sys.key as 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang')}
                            className={`wb-system-filter-btn ${systemFilter === sys.key ? 'is-active' : ''}`}
                          >
                            <span>{sys.label}</span>
                            {count > 0 && <small className="wb-system-count">{count}</small>}
                          </button>
                        );
                      }
                      return (
                        <span
                          key={sys.key}
                          title={`${sys.label}（${sys.businessLine}）：${sys.description}`}
                          className={`wb-system-filter-tag ${sys.planned ? 'is-planned' : ''}`}
                        >
                          <span>{sys.label}</span>
                          <small>手动上传</small>
                        </span>
                      );
                    })}
                  </div>
                </div>}

                {noCity && noDate && <CollectionScope platform={platform} />}

                {!noCity && (
                  <fieldset aria-labelledby="download-cities-label" className="wb-step-card">
                    <div className="wb-step-card-header">
                      <div className="wb-step-badge">
                        <span className="wb-step-number">01</span>
                        <span id="download-cities-label" className="wb-step-title">处理城市</span>
                        <span className="wb-step-count-pill">已选 {cities.length} / {selectableCities.length}</span>
                        {optionsLoading && <span className="text-xs text-sky-600 flex items-center gap-1"><Loader2 size={12} className="animate-spin" />同步中</span>}
                      </div>

                      <div className="wb-inline-city-toolbar">
                        <button
                          type="button"
                          className="wb-city-preset-btn"
                          disabled={formLocked || !selectableCities.length}
                          onClick={() => setCities(cities.length === selectableCities.length ? [] : selectableCities.map(c => c.name))}
                        >
                          {cities.length === selectableCities.length && cities.length ? '清空城市' : '全选城市'}
                        </button>
                        {(!platform || platform === 'fengshen') && (
                          <button
                            type="button"
                            className="wb-city-preset-btn"
                            disabled={formLocked || !selectableCities.length}
                            title="全选城市、仅勾选骑手信息、日期设为今天。一次任务导出全部城市快照（约25分钟验证窗口跨城市生效，全程只需一条验证码）；当天各时段、各城市的兼职核算会自动复用这些快照，不再触发导出和验证码。"
                            onClick={() => {
                              setCities(selectableCities.map(c => c.name));
                              setDatasets(['rider_info']);
                              setStart(shanghaiToday());
                              setEnd(shanghaiToday());
                              if (!platform) setSystemFilter('fengshen');
                            }}
                          >
                            一键全城市快照
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="wb-inline-city-grid" role="group" aria-label="处理城市列表">
                      {options.cities.map(city => {
                        const selected = !city.disabled && cities.includes(city.name);
                        return (
                          <button
                            key={city.id}
                            type="button"
                            disabled={formLocked || city.disabled}
                            title={city.disabled ? city.note : undefined}
                            aria-pressed={selected}
                            onClick={() => toggle(city.name, cities, setCities)}
                            className={`wb-inline-city-chip ${selected ? 'is-selected' : ''} ${city.disabled ? 'is-disabled' : ''}`}
                          >
                            <span className="wb-city-check-box" aria-hidden="true">
                              {selected && '✓'}
                            </span>
                            <span className="wb-city-chip-name">{city.name}</span>
                            <span className="wb-city-status"><CityStationCount directory={stationDirectory.data} city={city.id}/>
                            {city.disabled && (
                              <span className="wb-city-disabled-badge">{city.note || '下架'}</span>
                            )}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                    {!selectableCities.length && (
                      <p className="wb-notice mt-3">暂无可下载城市，请检查风神权限或网络连接。</p>
                    )}
                    <div className="wb-city-count-note"><small>{stationDirectory.data?.status==='loading'?'站点数正在按后台目录逐城同步':stationDirectory.data?.fetched_at?`站点数更新于 ${new Date(stationDirectory.data.fetched_at).toLocaleTimeString('zh-CN',{hour12:false})}`:'站点数尚未同步'}{stationDirectory.error||stationDirectory.data?.message?` · ${stationDirectory.error||stationDirectory.data?.message}`:''}</small><button type="button" className="wb-link" onClick={stationDirectory.refresh}>刷新站点数</button></div>
                  </fieldset>
                )}

                {!noDate && <fieldset aria-labelledby="download-dates-label" className="wb-step-card">
                  <legend className="sr-only">下载日期</legend>
                  <div className="wb-step-card-header">
                    <div className="wb-step-badge">
                      <span className="wb-step-number">{noCity ? '01' : '02'}</span>
                      <p id="download-dates-label" className="wb-step-title m-0">
                        处理日期 <span className="ml-1.5 text-xs font-normal text-slate-500">北京时间</span>
                      </p>
                      {noCity && (
                        <span className="wb-step-count-pill">覆盖范围：可访问全部城市</span>
                      )}
                    </div>
                    <div className="wb-period-quick-bar" role="group" aria-label="核算账期快捷选择">
                      {([
                        ['last_full_month', '上月整月'],
                        ['current_first_half', '本月1-15日'],
                        ['last_second_half', '上月16-月末'],
                        ['current_month_to_date', '本月至今'],
                      ] as const).map(([presetKey, label]) => {
                        const range = billingPeriodRange(presetKey);
                        const isCurrent = !range.blocked && start === range.start && end === range.end;
                        return (
                          <button
                            key={presetKey}
                            type="button"
                            disabled={formLocked||range.blocked}
                            aria-pressed={isCurrent}
                            title={range.blocked&&xiaoxiangDated?'灯塔资料只能选择昨天及更早的日期':undefined}
                            onClick={() => applyBillingPeriod(presetKey)}
                            className={`wb-period-chip ${isCurrent ? 'is-active' : ''}`}
                          >
                            {(hasAttendance||xiaoxiangDated)&&presetKey==='current_month_to_date'?'本月至昨日':label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="grid w-full grid-cols-1 gap-3.5 sm:grid-cols-2">
                    <div className="flex min-w-0 flex-col gap-1.5 text-xs font-medium text-slate-600">
                      <span>开始日期</span>
                      <WorkbenchDatePicker
                        ariaLabel="下载开始日期"
                        min={hasAttendance ? attendanceFirst : xiaoxiangOnly ? xiaoxiangFirst : undefined}
                        max={hasAttendance ? attendanceLast : xiaoxiangOnly ? dailyDate : undefined}
                        value={start}
                        rangeRole="start"
                        rangeStart={start}
                        rangeEnd={end}
                        today={shanghaiToday()}
                        disabled={formLocked}
                        onChange={nextValue => setStart(nextValue)}
                      />
                    </div>
                    <div className="flex min-w-0 flex-col gap-1.5 text-xs font-medium text-slate-600">
                      <span>结束日期</span>
                      <WorkbenchDatePicker
                        ariaLabel="下载结束日期"
                        min={hasAttendance ? attendanceFirst : xiaoxiangOnly ? xiaoxiangFirst : undefined}
                        max={hasAttendance ? attendanceLast : xiaoxiangOnly ? dailyDate : undefined}
                        value={end}
                        rangeRole="end"
                        rangeStart={start}
                        rangeEnd={end}
                        today={shanghaiToday()}
                        disabled={formLocked}
                        onChange={nextValue => setEnd(nextValue)}
                      />
                    </div>
                  </div>

                  {!validDates && <p role="alert" className="mt-2.5 text-xs text-rose-700">开始日期不能晚于结束日期，请选择有效日期。</p>}
                  {xiaoxiangOnly && validDates && !xiaoxiangDateValid && <p role="alert" className="mt-2.5 text-xs text-rose-700">灯塔资料只能选择昨天及更早的日期，且区间最长31天。</p>}
                  {monthPreview.length > 0 && <p className="mt-2.5 text-xs leading-relaxed text-sky-700">整月资料自动下载：{monthPreview.join('、')}。</p>}
                  {!merchantOnly && !xiaoxiangOnly && (
                    <div className="wb-date-rule-bar">
                      <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                        <input
                          type="checkbox"
                          aria-label="排除取分离站点"
                          checked={excludeSeparation}
                          disabled={formLocked}
                          onChange={event => setExcludeSeparation(event.target.checked)}
                          className="accent-sky-700 h-3.5 w-3.5 rounded border-slate-300"
                        />
                        <span>排除取分离站点 <span className="font-normal text-slate-400">（不勾选则下载全部站点）</span></span>
                      </label>
                      {datasets.some(dataset => ['fraud', 'problem'].includes(dataset)) && (
                        <label className="flex items-center gap-1.5 cursor-pointer text-slate-500">
                          <input
                            type="checkbox"
                            checked={refreshHistory}
                            disabled={formLocked}
                            onChange={event => setRefreshHistory(event.target.checked)}
                            className="accent-sky-700 h-3.5 w-3.5 rounded border-slate-300"
                          />
                          <span>强制刷新24小时内历史运单</span>
                        </label>
                      )}
                      {datasets.includes('delivery_waybill') && (
                        <label className="flex items-center gap-1.5 cursor-pointer text-slate-500">
                          <input
                            type="checkbox"
                            aria-label="运单全城送筛选"
                            checked={waybillAllCitySend}
                            disabled={formLocked}
                            onChange={event => setWaybillAllCitySend(event.target.checked)}
                            className="accent-sky-700 h-3.5 w-3.5 rounded border-slate-300"
                          />
                          <span>全城送 <span className="font-normal text-slate-400">（仅导出配送标品为全城送的运单）</span></span>
                        </label>
                      )}
                      {datasets.includes('delivery_waybill') && <span className="font-normal text-slate-400">运单数据按运单终态时间筛选（当日仅含已完成运单）</span>}
                    </div>
                  )}
                  {orderWindowWarning && <p role="alert" className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">欺诈单和问题单仅支持最近 {orderWindowDays} 天（{earliestOrder} 至 {shanghaiToday()}），请调整日期或取消这两类资料。</p>}
                </fieldset>}

                <fieldset aria-labelledby="download-datasets-label" className="wb-step-card">
                  {!platform && (
                    <div className="wb-step-card-header">
                      <div className="wb-step-badge">
                        <span className="wb-step-number">{noCity && noDate ? '01' : noCity || noDate ? '02' : '03'}</span>
                        <span id="download-datasets-label" className="wb-step-title">选择资料</span>
                        <span className="wb-step-count-pill">已选 {datasets.length}</span>
                      </div>
                    </div>
                  )}
                  {(['fengshen', 'lanorange', 'baize', 'xiaoxiang'] as const).filter(group => platform?group===platform:systemFilter === 'all' || systemFilter === group).map(group => {
                    const groupDatasets = visibleDatasets.filter(value => !isGenerator(value.id) && datasetGroup(value.id) === group);
                    const ids = groupDatasets.map(value => value.id);
                    const allSelected = ids.length > 0 && ids.every(id => datasets.includes(id));
                    const selectedCount = datasets.filter(id => datasetGroup(id) === group).length;
                    const stepNum = noCity && noDate ? '01' : noCity || noDate ? '02' : '03';
                    return (
                      <div key={group} className="wb-source-group">
                        <div className={platform ? 'wb-step-card-header' : 'wb-source-header'}>
                          <div className={platform ? 'wb-step-badge' : 'wb-source-title'}>
                            {platform && <span className="wb-step-number">{stepNum}</span>}
                            <span className={`wb-sys-badge is-${group}`}>{group === 'baize' ? '商翼' : group === 'xiaoxiang' ? '灯塔' : group === 'lanorange' ? '蓝橙' : '风神'}</span>
                            <span id={platform ? 'download-datasets-label' : undefined} className={platform ? 'wb-step-title' : ''}>
                              {group === 'baize' ? '选择资料 · 商翼员工资料' : group === 'xiaoxiang' ? '选择资料 · 灯塔资料' : group === 'lanorange' ? '选择资料 · 蓝橙资料' : '选择资料 · 风神资料'}
                            </span>
                            <span className="wb-step-count-pill">已选 {selectedCount} / {groupDatasets.length}</span>
                          </div>
                          <button
                            type="button"
                            disabled={formLocked}
                            className="wb-city-preset-btn"
                            onClick={() => {
                              setDatasets(allSelected ? datasets.filter(id => !ids.includes(id)) : group === 'baize' || group === 'xiaoxiang' ? ids : [...new Set([...datasets.filter(id => !isBaize(id) && !isXiaoxiang(id)), ...ids])]);
                              if(!allSelected&&ids.includes('attendance_detail')){if(end>attendanceLast)setEnd(attendanceLast);if(start>attendanceLast)setStart(attendanceLast);if(start<attendanceFirst)setStart(attendanceFirst);}
                            }}
                          >
                            {group === 'fengshen' ? (allSelected ? '清空城市资料' : '全选城市资料') : (allSelected ? '清空本组' : '全选本组')}
                          </button>
                        </div>
                        <div className={`grid grid-cols-1 gap-2.5 ${group === 'baize' || groupDatasets.length === 1 ? 'is-single-item sm:grid-cols-1' : 'sm:grid-cols-2 lg:grid-cols-3'}`}>
                          {groupDatasets.map(dataset => {
                            const selected = datasets.includes(dataset.id);
                            const cardMeta = getDatasetCardMeta(dataset.id, dataset.label);
                            return (
                              <label key={dataset.id} className={`${choiceStyle(selected)} wb-dataset-card ${selected ? 'is-selected' : ''}`}>
                                <input
                                  type="checkbox"
                                  checked={selected}
                                  disabled={formLocked}
                                  onChange={() => {
                                    setDatasets(values => toggleDownloadDataset(values, dataset.id));
                                    if (dataset.id === 'attendance_detail') {
                                      if (end > attendanceLast) setEnd(attendanceLast);
                                      if (start > attendanceLast) setStart(attendanceLast);
                                      if (start < attendanceFirst) setStart(attendanceFirst);
                                    }
                                  }}
                                  className="accent-sky-700 shrink-0 h-4 w-4 rounded border-slate-300 wb-dataset-checkbox"
                                />
                                <div className="wb-dataset-body">
                                  <div className="wb-dataset-top-row">
                                    <span className="wb-dataset-title truncate">{cardMeta.title}</span>
                                    <span className={`wb-dataset-tag is-${cardMeta.tone}`}>{cardMeta.scopeTag}</span>
                                  </div>
                                  <span className="wb-dataset-desc truncate">{cardMeta.desc}</span>
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </fieldset>

                {blueCityScoped && (
                  <fieldset aria-labelledby="download-blue-cities-label" className="wb-step-card">
                    <div className="wb-step-card-header">
                      <div className="wb-step-badge">
                        <span id="download-blue-cities-label" className="wb-step-title">蓝橙城市 <span className="text-xs font-normal text-slate-500">可选 · 按城市分别导出</span></span>
                        {blueCities.length > 0 && <span className="wb-step-count-pill">已选 {blueCities.length} 个城市</span>}
                      </div>
                      {blueCities.length > 0 && <button type="button" className="wb-city-preset-btn" disabled={formLocked} onClick={() => setBlueCities([])}>恢复全部城市</button>}
                    </div>
                    <div className="wb-inline-city-grid" role="group" aria-label="蓝橙城市列表">
                      <button
                        type="button"
                        disabled={formLocked}
                        aria-pressed={!blueCities.length}
                        onClick={() => setBlueCities([])}
                        className={`wb-inline-city-chip ${!blueCities.length ? 'is-selected' : ''}`}
                      >
                        <span className="wb-city-check-box" aria-hidden="true">{!blueCities.length && '✓'}</span>
                        <span className="wb-city-chip-name">全部城市</span>
                      </button>
                      {LANORANGE_CITIES.map(city => {
                        const selected = blueCities.includes(city);
                        return (
                          <button
                            key={city}
                            type="button"
                            disabled={formLocked}
                            aria-pressed={selected}
                            onClick={() => toggle(city, blueCities, setBlueCities)}
                            className={`wb-inline-city-chip ${selected ? 'is-selected' : ''}`}
                          >
                            <span className="wb-city-check-box" aria-hidden="true">{selected && '✓'}</span>
                            <span className="wb-city-chip-name">{city}</span>
                          </button>
                        );
                      })}
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-500">{blueCities.length ? `仅导出所选 ${blueCities.length} 个城市，每城市一个文件${blueCities.length > 1 ? '，并生成蓝橙跨城市汇总' : ''}；价格档案可同时选择月份。` : '默认导出平台全部可访问城市（全量）。'}</p>
                  </fieldset>
                )}

                {blueOnly && datasets.includes('lanorange_part_price') && (
                  <fieldset aria-labelledby="download-price-months-label" className="wb-step-card">
                    <div className="wb-step-card-header">
                      <div className="wb-step-badge">
                        <span id="download-price-months-label" className="wb-step-title">价格档案月份 <span className="text-xs font-normal text-slate-500">可选 · 对应价格档案「日期」列</span></span>
                        {lanorangeMonths.length > 0 && <span className="wb-step-count-pill">已选 {lanorangeMonths.length} 个月</span>}
                      </div>
                      {lanorangeMonths.length > 0 && <button type="button" className="wb-city-preset-btn" disabled={formLocked} onClick={() => setLanorangeMonths([])}>清空月份</button>}
                    </div>
                    <div className="wb-inline-city-grid" role="group" aria-label="价格档案月份列表">
                      {priceMonthOptions.map(month => {
                        const selected = lanorangeMonths.includes(month);
                        return (
                          <button
                            key={month}
                            type="button"
                            disabled={formLocked}
                            aria-pressed={selected}
                            onClick={() => toggle(month, lanorangeMonths, setLanorangeMonths)}
                            className={`wb-inline-city-chip ${selected ? 'is-selected' : ''}`}
                          >
                            <span className="wb-city-check-box" aria-hidden="true">{selected && '✓'}</span>
                            <span className="wb-city-chip-name">{month}</span>
                          </button>
                        );
                      })}
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-500">{lanorangeMonths.length ? '平台将只导出所选月份（不连续月份会先下载连续区间、再仅保留所选月份）；成品文件名会标注月份。' : '未选择月份时下载账号全部可访问月份（全量）。'}</p>
                  </fieldset>
                )}
                {uncertainCreate && <p className="wb-notice mt-3">原请求资料：{createAttempt.current?.payload.datasets.map(datasetLabel).join('、')}。本次继续确认原请求，分类不改变其内容。</p>}
                {uncertainCreate && <p role="status" className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">上次提交结果尚未确认，已锁定原选择。请点击“重新确认原请求”，继续确认同一任务。</p>}
                {!uncertainCreate && matchingRun && <div className="mt-3 rounded-lg bg-sky-50 border border-sky-200 p-3 text-xs text-sky-800 space-y-2"><p>{completedMatch ? '相同选择已有文件，可直接查看和下载。' : '相同选择已有任务正在执行，可直接查看进度。'}</p>{completedMatch && <label className="flex items-center gap-2"><input type="checkbox" checked={duplicateApproval === currentSelectionKey} disabled={creating} onChange={event => setDuplicateApproval(event.target.checked ? currentSelectionKey : '')} />重新采集，创建新版本</label>}</div>}
              </div>
              <aside className="wb-task-preview wb-preview-compact" aria-label="本次任务已选清单与执行">
                {!(noCity && noDate) && <div className="wb-compact-rail-top">
                  <div className="wb-compact-rail-header">
                    <div className="wb-compact-rail-title">
                      <h4>已选清单</h4>
                      <span className="wb-compact-count-pill">
                        {datasets.length > 0 ? `已选 ${datasets.length} 项` : '0 项'}
                      </span>
                    </div>
                    {datasets.length > 0 && (
                      <button
                        type="button"
                        className="wb-compact-clear-btn"
                        disabled={formLocked}
                        onClick={() => setDatasets([])}
                      >
                        清空
                      </button>
                    )}
                  </div>

                  <div className="wb-compact-list-wrap">
                    {datasets.length > 0 ? (
                      <div className="wb-compact-list-surface">
                        <ul className={`wb-compact-dataset-list ${datasets.length <= 3 ? 'is-detailed' : 'is-dense'}`}>
                          {datasets.map((id, index) => {
                            const cardMeta = getDatasetCardMeta(id, datasetLabel(id));
                            return (
                              <li key={id} className="wb-compact-dataset-item">
                                <span className="wb-compact-item-index" aria-hidden="true">
                                  {String(index + 1).padStart(2, '0')}
                                </span>
                                <div className="wb-compact-item-body">
                                  <div className="wb-compact-item-row">
                                    <span className="wb-compact-item-name" title={datasetLabel(id)}>
                                      {cardMeta.title}
                                    </span>
                                    <span className={`wb-dataset-tag wb-compact-item-tag is-${cardMeta.tone}`}>
                                      {cardMeta.scopeTag}
                                    </span>
                                  </div>
                                  {datasets.length <= 3 && (
                                    <span className="wb-compact-item-desc" title={cardMeta.desc}>
                                      {cardMeta.desc}
                                    </span>
                                  )}
                                </div>
                                <button
                                  type="button"
                                  className="wb-compact-item-remove"
                                  disabled={formLocked}
                                  aria-label={`移除 ${datasetLabel(id)}`}
                                  onClick={() => setDatasets(values => values.filter(v => v !== id))}
                                >
                                  ×
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                        {railSummary.listFooterText && (
                          <div className="wb-compact-list-footer">
                            <span className="wb-compact-footer-text">{railSummary.listFooterText}</span>
                            <span className={`wb-compact-ready-badge ${submitReady ? 'is-ready' : 'is-warn'}`}>
                              {submitReady ? '配置就绪' : '待完善'}
                            </span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="wb-compact-empty">
                        <span className="wb-compact-empty-dot" />
                        <p>尚未勾选采集资料</p>
                        <small>请在左侧模块勾选需要下载的数据表</small>
                      </div>
                    )}
                  </div>
                </div>}

                <div className="wb-compact-rail-bottom">
                  {!(noCity && noDate) && <div className="wb-compact-scope-box">
                    <div className="wb-compact-scope-header">
                      <span>执行范围核对</span>
                      <span className="wb-compact-scope-sub">北京时间</span>
                    </div>
                    <div className="wb-compact-scope-row">
                      <span className="wb-compact-scope-k">处理城市</span>
                      <span className="wb-compact-scope-v" title={cities.join('、')}>
                        {railSummary.cityLabel}
                      </span>
                    </div>
                    <div className="wb-compact-scope-row">
                      <span className="wb-compact-scope-k">业务账期</span>
                      <span className="wb-compact-scope-v wb-compact-scope-period">
                        <span className="font-mono">{railSummary.periodText}</span>
                        {railSummary.periodSpanBadge && (
                          <span className="wb-compact-period-badge">{railSummary.periodSpanBadge}</span>
                        )}
                      </span>
                    </div>
                    <div className="wb-compact-scope-row">
                      <span className="wb-compact-scope-k">{railSummary.thirdRowLabel}</span>
                      <span className="wb-compact-scope-v">
                        {railSummary.thirdRowValue}
                      </span>
                    </div>
                  </div>}

                  <div className="wb-compact-action-area">
                    {noCity && noDate && <p className="wb-muted">已选 {datasets.length} 类资料 · 成品在任务中心领取</p>}
                    <button
                      type="button"
                      onClick={() => void startDownload()}
                      disabled={creating || (!uncertainCreate && !canSubmit)}
                      className="wb-compact-submit-btn"
                    >
                      {creating ? <Loader2 size={16} className="animate-spin" /> : <CloudDownload size={16} />}
                      <span>
                        {creating ? '提交中…' : uncertainCreate ? '确认原请求' : matchingRun && !TERMINAL_STATUSES.has(matchingRun.status) ? '查看进行中任务' : completedMatch && duplicateApproval !== currentSelectionKey ? '查看已有文件' : '开始下载'}
                      </span>
                    </button>
                    {!submitReady && railSummary.blockerHint && (
                      <p className="wb-compact-submit-hint is-warn">
                        {railSummary.blockerHint}
                      </p>
                    )}
                    {submittedTaskInfo && (
                      <div role="status" className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50/95 p-2.5 text-xs text-emerald-800">
                        <div className="flex items-center justify-between gap-2 font-medium">
                          <span className="flex items-center gap-1.5 text-emerald-700">
                            <CheckCircle2 size={14} className="shrink-0 text-emerald-600" />
                            已成功创建任务
                          </span>
                          <button
                            type="button"
                            className="text-slate-400 hover:text-slate-600 p-0.5"
                            onClick={() => setSubmittedTaskInfo(null)}
                            aria-label="关闭提示"
                          >
                            <X size={13} />
                          </button>
                        </div>
                        <p className="mt-1 text-slate-600 text-[11px] leading-relaxed">
                          任务已在后台执行，可直接查看进度与结果。
                        </p>
                        <button type="button" className="wb-button mt-2" onClick={()=>{setHistoryFocusId(submittedTaskInfo.id);selectedIdRef.current=submittedTaskInfo.id;setSelectedId(submittedTaskInfo.id);setView('history');}}>查看本次任务</button>
                      </div>
                    )}
                  </div>
                </div>
              </aside>
              </>}
            </>}
        </section>
      </>}
          </>
        );
      })()}

      {scopeReview && <WorkbenchDrawer title="确认新任务范围" onClose={() => setScopeReview(null)}>
        <TaskFlowSteps status="review" />
        <dl className="wb-scope-review"><dt>本次业务</dt><dd>{scopeReview.task_kind === 'generate' ? '业务报表生成' : '资料下载'}</dd>
        <dt>资料或报表</dt><dd>{scopeReview.datasets.map(datasetLabel).join('、')}</dd>
        <dt>城市范围</dt><dd>{scopeReview.datasets.length===1&&isRiderArchive(scopeReview.datasets[0]) ? '账号全部站点 · 当前快照' : scopeReview.datasets.every(isXiaoxiang) ? '账号可访问全部城市 · 日期区间导出' : scopeReview.datasets.every(isGlobalDataset) ? (scopeReview.cities.length && !scopeReview.cities.includes('全部城市') ? `${scopeReview.cities.join('、')} · 按城市分别导出` : '全部城市 · 按现有全量规则') : scopeReview.cities.join('、')}</dd>
        {scopeReview.exclude_separation !== undefined && <><dt>站点范围</dt><dd>{scopeReview.exclude_separation ? '排除取分离站点' : '全部站点（含取分离）'}</dd></>}
        {scopeReview.waybill_all_city_send === true && <><dt>运单标品</dt><dd>仅全城送</dd></>}
        {!!scopeReview.lanorange_months?.length && <><dt>价格档案月份</dt><dd>{scopeReview.lanorange_months.join('、')}</dd></>}
        <dt>日期范围</dt><dd>{scopeReview.datasets.length===1&&isRiderArchive(scopeReview.datasets[0])?'当前快照，不按日期筛选':scopeReview.datasets.every(isMerchantSnapshot)?'邀请记录全量，不按日期筛选':scopeReview.datasets.every(isGlobalDataset) ? '全量交付，不按所选日期筛选' : `${scopeReview.start} 至 ${scopeReview.end}`}</dd></dl>
        {scopeReview.datasets.includes('invitation_records')&&<p className="wb-muted">邀请记录按所选城市获取全量快照，不按日期筛选；出勤按城市全部可见站点获取。其他资料沿用各自规则。</p>}
        <p className="wb-notice">这是新建任务。继续已有任务请返回任务中心；页面关闭或返回修改不会提交导出。</p>
        {scopeReview.task_kind === 'generate' && <p className="wb-muted">系统按既有规则关联来源资料；关键资料不完整时保留任务并提示处理，不代表所有来源均可自动复用。</p>}
        <div className="wb-row"><button type="button" className="wb-button" onClick={() => setScopeReview(null)}>返回修改范围</button><button type="button" className="wb-primary" disabled={creating} onClick={() => {
          const key=selectionKey(scopeReview); setScopeReview(null);
          if (key !== currentSelectionKey) { setRequestError('范围已发生变化，请重新确认后创建任务'); return; }
          void startDownload(key);
        }}>确认并创建任务</button></div>
      </WorkbenchDrawer>}

      {view === 'history' && (() => {
        const stageMeta = getStageHeaderMeta(taskKind === 'generate' ? 'generate' : 'download', platform, 'history');
        return (
          <div className={recordModule ? `${panel} wb-task-form wb-stage-history-card` : undefined}>
            {recordModule && (
              <div className="wb-form-heading wb-stage-history-heading">
                <div className="wb-stage-heading-left">
                  <div className="wb-stage-title-row">
                    <h2>{stageMeta.title}</h2>
                    <button type="button" className="wb-button text-xs" onClick={() => setView('create')}>
                      返回配置
                    </button>
                  </div>
                  <p className="wb-muted">{stageMeta.subtitle}</p>
                </div>
              </div>
            )}
            <div className={recordModule ? 'wb-stage-history-body' : undefined}>
              <DownloadRecords initialRunId={historyFocusId} onInitialFocusHandled={()=>setHistoryFocusId('')} key={recordModule||'all'} recordModule={recordModule} apiFetch={apiFetch} workspaceId={workspaceId} selectedRunId={selectedId}
                datasetLabel={id => id === 'payroll' ? '兼职薪资核算' : datasetLabel(id)} refreshVersion={navigation?.version} unified onOpenPayroll={onOpenPayroll}
                onNavigateGenerate={onNavigateGenerate}
                onNavigatePayroll={onNavigatePayroll}
                onOpenPrice={onOpenPrice}
        onOpenAttempt={id => {
          setRequestError('');
          attemptOpenController.current?.abort();
          const controller = new AbortController(); attemptOpenController.current = controller;
          void getJson(`${API_ROOT}/runs/${encodeURIComponent(id)}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) })
            .then(data => { if (!controller.signal.aborted) selectRun(data.run); }).catch(error => { if (!controller.signal.aborted) setRequestError(error.message); });
        }}
        execution={<>
{selectedRun && <div className={`${panel} wb-task-detail min-w-0 space-y-4 p-4 sm:p-5`}>

              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><h3 className="flex flex-wrap items-center gap-2 text-base font-semibold text-slate-900">{selectedRun.datasets.every(isBaize) ? '商翼全量员工资料' : selectedRun.datasets.every(isLanorange) ? (selectedRun.lanorange_by_city ? `蓝橙 ${selectedRun.cities.join('、')}` : '蓝橙全量') : selectedRun.cities.length > 2 ? `${selectedRun.cities.length} 个城市` : selectedRun.cities.join('、')}的下载任务 <span className={`rounded-md px-2 py-1 text-xs font-normal ${statusInfo(selectedRun.status).color}`}>{runStatusLabel}</span></h3><p className="mt-2 text-xs text-slate-500">{selectedRun.datasets.every(isLanorange) ? (selectedRun.lanorange_by_city ? '所选城市、全部状态、不按日期筛选' : '全部城市、全部状态、不按日期筛选') : `${selectedRun.start} 至 ${selectedRun.end}`} · {selectedRun.datasets.length} 类资料</p></div>
                {!activeRun && <details><summary className="wb-link">需要重新采集？</summary><p className="text-xs">先处理下方可恢复项。新任务不会继续原导出；结果未知时请先核对原回执。</p><button type="button" className={smallButton} disabled={selectedRun.items?.some(item => item.submission_state === 'unknown')} onClick={() => prefillFromRun(selectedRun)}>重新采集并创建新任务</button></details>}
                {activeRun && <button type="button" className={smallButton} disabled={cancelling || ['cancelling', 'canceling'].includes(selectedRun.status)} onClick={() => void cancelDownload()}>{cancelling ? <Loader2 size={13} /> : <Square size={13} />}停止任务</button>}
              </div>
              <div role="status" className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>{activeRun ? phaseLabel(selectedRun.phase) : statusInfo(selectedRun.status).label}{selectedRun.queue_position ? ` · 排队第 ${selectedRun.queue_position} 位` : ''}{activeRun && selectedRun.phase_since ? ` · ${elapsed(selectedRun.phase_since)}` : ''}</span><span>{Math.round(progress)}%</span></div>
                {selectedRun.status === 'queued' && <p className="wb-muted">{selectedRun.queue_wait_reason === 'local_capacity' ? '正在等待本机处理名额；最多同时保留两个在途任务。' : '正在等待前一项平台采集结束；采集完成后的纯蓝橙整理可释放队列。'}</p>}
                <div role="progressbar" aria-label="下载进度" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} className="h-1.5 overflow-hidden rounded-full bg-slate-200"><div style={{ width: `${progress}%` }} className="h-full bg-sky-700" /></div>
                {summaryHint && <p role="status" className={`text-xs ${summaryDetail?.stage === 'failed' ? 'text-rose-700' : 'text-sky-700'}`}>{summaryHint}</p>}
                {summary && typeof summary.total === 'number' && <p className="text-xs text-slate-500">完成 {summary.success || 0} / {summary.total} 项{summary.error ? ` · 失败 ${summary.error} 项` : ''}{summary.cancelled ? ` · 取消 ${summary.cancelled} 项` : ''}</p>}
                {typeof selectedRun.summary === 'string' && <p className="text-xs text-slate-500">{selectedRun.summary}</p>}
                {selectedRun.order_progress && <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-700 space-y-1" aria-label="运单分批处理进度"><p>{({ collecting: '采集资料与后台处理并行中', processing: '本地校验处理中', merging: '合并并生成成品', completed: '分批处理完成' } as Record<string, string>)[selectedRun.order_progress.stage || ''] || '运单处理中'} · 批次 {selectedRun.order_progress.batch || 0}/{selectedRun.order_progress.batches || 0}</p><p>已获取 {selectedRun.order_progress.obtained || 0} 批 · 已校验 {selectedRun.order_progress.processed || 0} 批 · 已处理 {(selectedRun.order_progress.processed_rows || 0).toLocaleString()} 条运单</p><p>复用历史 {selectedRun.order_progress.cached_days || 0} 天 · 本次下载 {formatSize(selectedRun.order_progress.download_bytes || 0)} · 已用 {Math.round(selectedRun.order_progress.elapsed_seconds || 0)} 秒</p></div>}
              </div>
              {waitingLogin && <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">{selectedRun.datasets.some(id => isLanorange(id) || isBaize(id) || isXiaoxiang(id)) ? <><p>此任务需要来源认证。</p><button className={`${smallButton} mt-2`} onClick={() => window.dispatchEvent(new CustomEvent('workbench:connections', { detail: selectedRun.datasets.some(isBaize) ? 'baize' : selectedRun.datasets.some(isXiaoxiang) ? 'xiaoxiang' : 'lanorange' }))}>完成验证</button></> : <><p>完成风神登录后，任务会继续。</p>{onOpenFengshenLogin ? <button type="button" onClick={() => onOpenFengshenLogin(user.id)} className={`${smallButton} mt-2`}><KeyRound size={14} />打开风神登录</button> : <p>请在运行系统的电脑上完成风神登录。</p>}</>}</div>}
              {selectedRun.phase === 'waiting_manual' && <p role="status" className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">平台要求额外验证，当前任务已暂停。请打开风神验证窗口查看具体原因。</p>}
              {selectedRun.error && <p role="alert" className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 break-words">{selectedRun.error}</p>}

              {canRecoverDetail(selectedRun) && <div className="rounded-lg bg-sky-50 border border-sky-200 p-3 text-xs text-sky-800"><p>可继续查询已提交的明细任务。</p><button type="button" className={`${smallButton} mt-2`} disabled={!!resumingRunId} onClick={() => void resumeDetail()}>{resumingRunId ? <Loader2 size={14} /> : <RefreshCw size={14} />}恢复已有明细下载</button>{recoveryError?.runId === selectedRun.id && <p role="alert" className="mt-2 text-amber-700">{recoveryError.message}</p>}</div>}
              {!!selectedRun.items?.length && <details key={`items-${selectedRun.id}`} open={failedItems.length > 0} className="border-t border-slate-200 pt-3">
                <summary className="cursor-pointer text-sm text-slate-700">任务明细{failedItems.length > 0 ? ` · ${failedItems.length} 项需要处理` : ` · ${selectedRun.items.length} 项`}</summary>
                <div className="mt-3 space-y-3">
                  {!activeRun && selectedRecoverable.length > 0 && <div className="flex flex-wrap items-center justify-between gap-2"><label className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={retryPending || uncertainRetry} checked={selectedRecoverable.every(item => retryKeys.includes(itemKey(item)))} onChange={event => setRetryKeys(event.target.checked ? selectedRecoverable.map(itemKey) : [])} />全选可恢复项</label><button type="button" className={smallButton} disabled={retryPending || uncertainRetry || !selectedRecoverable.some(item => retryKeys.includes(itemKey(item)))} onClick={() => void retrySelected()}>{retryPending ? <Loader2 size={14} /> : <RefreshCw size={14} />}处理选中的失败项</button></div>}
                  <div className="max-h-96 space-y-2 overflow-y-auto">{selectedRun.items.map((item, index) => <div key={`${itemKey(item)}-${index}`} className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs">
                    <div className="flex items-start justify-between gap-3"><label className="flex items-start gap-2">{!activeRun && recoverable(item) && <input aria-label={`选择处理${item.city}${datasetLabel(item.dataset)}${item.start}`} type="checkbox" disabled={retryPending || uncertainRetry} checked={retryKeys.includes(itemKey(item))} onChange={() => toggle(itemKey(item), retryKeys, setRetryKeys)} />}<span className="font-medium text-slate-800">{item.city} · {datasetLabel(item.dataset)}</span></label><span className={`shrink-0 rounded px-1.5 py-0.5 ${statusInfo(item.status).color}`}>{statusInfo(item.status).label}</span></div>
                    <p className="mt-1.5 text-slate-500">{isBaize(item.dataset) ? '商翼全量员工原表 · 不按城市或日期筛选' : isRiderArchive(item.dataset) ? '小象灯塔骑手档案 · 全部站点当前快照 · 手机号/身份证为明文 · 照片以链接提供' : item.dataset === 'rider_order_detail' || item.dataset === 'xiaoxiang_attendance_detail' ? `灯塔通知附件合并 · ${item.start} 至 ${item.end} · 按附件数据日期筛选` : isXiaoxiang(item.dataset) ? (item.start===item.end ? `小象灯塔商配送看板 · ${item.start} 单日 · 全部站点一份工作簿` : `小象灯塔商配送看板 · ${item.start} 至 ${item.end} 区间合并 · 全部站点一份工作簿${item.dataset === 'rider_daily' ? ' · 按附件20列格式' : ''}`) : item.dataset === 'abnormal_riders' ? '生成表 · 由本任务的 5 类蓝橙成品整理生成（全部城市一份）' : isLanorange(item.dataset) ? (item.city === '全部城市' ? selectedRun.lanorange_full_delivery ? '全量统一交付 · 全部状态、无日期筛选；缺失批次不计为完成' : '全量原始表 · 全部城市、全部状态、无业务筛选' : item.dataset === 'lanorange_batch_quit' ? '平台城市批次原表 · 汇总按骑手城市归属筛选' : '城市原始表 · 全部状态、不按日期筛选') : item.dataset === 'rider_info' ? '当前快照' : `${item.start} 至 ${item.end}`}{item.phase && !['completed', 'failed', 'cancelled', 'interrupted'].includes(item.phase) ? ` · ${phaseLabel(item.phase)}` : ''}</p>
                    {item.error && <p className="mt-2 break-words text-rose-700">{item.error}</p>}
                    {!activeRun && item.status !== 'success' && item.recovery && <div className="mt-2"><p className={item.recovery.mode === 'blocked' ? 'text-amber-800' : 'text-sky-800'}>{!recoverable(item) ? '需人工核对后处理' : item.recovery.mode === 'resume_existing' ? '复用已有资料，继续处理' : '尚未提交，可重新执行'}</p><details open className="mt-1 text-slate-500"><summary className="cursor-pointer">原因与处理说明</summary><p className="mt-2 leading-relaxed">{item.recovery.reason}</p>{item.failure_phase && <p className="mt-1">失败阶段：{phaseLabel(item.failure_phase)}</p>}</details>{recoverable(item) && <button type="button" className="wb-button wb-item-recovery" disabled={retryPending || uncertainRetry} onClick={() => void retrySelected(item)}>{item.recovery.mode === 'resume_existing' ? '继续此项已有资料' : '仅重试此未提交项'}</button>}</div>}
                  </div>)}</div>
                </div>
              </details>}
              {selectedRun.performance && <details className="wb-performance"><summary>底层运行诊断（耗时与内存）</summary>
                <div className="wb-row wb-muted"><span>总耗时（含认证、汇总） {Number(selectedRun.performance.total_seconds ?? selectedRun.performance.elapsed_seconds ?? 0).toFixed(1)} 秒</span><span>排队 {Number(selectedRun.performance.queued_seconds || 0).toFixed(1)} 秒</span><span>汇总 {Number(selectedRun.performance.summary_seconds || 0).toFixed(1)} 秒</span><span>进程内存峰值采样 {(Number(selectedRun.performance.sampled_process_peak_rss_bytes || 0) / 1048576).toFixed(0)} MB</span></div>
                <p className="wb-muted">下表为主流程所处阶段的时间；后台城市生成可能同时进行。“生成业务表”阶段不是所有城市的计算总耗时，阶段与子任务不能相加。</p>
                <button type="button" className="wb-button" onClick={() => saveDownloadBlob(new Blob([JSON.stringify({format_version:1,exported_at:new Date().toISOString(),task:{id:selectedRun.id,cities:selectedRun.cities,start:selectedRun.start,end:selectedRun.end,datasets:selectedRun.datasets,status:selectedRun.status},performance:selectedRun.performance},null,2)],{type:'application/json'}),`性能诊断_${selectedRun.id.slice(0,8)}.json`)}>保存本任务性能诊断（不含人员明细）</button>
                {selectedRun.performance.stages?.source_row_filter && <p className="wb-muted">取分离过滤实际调用累计 {Number(selectedRun.performance.stages.source_row_filter.seconds).toFixed(2)} 秒（包含在上方总耗时内）</p>}
                {selectedRun.performance.stages?.archive_projection && <p className="wb-muted">骑手档案格式化与排序 {Number(selectedRun.performance.stages.archive_projection.seconds).toFixed(2)} 秒（包含在归档阶段内）</p>}
                {selectedRun.performance.scheduler && <p className="wb-muted">本地处理等待 {Number(selectedRun.performance.scheduler.local_queue_seconds).toFixed(2)} 秒；{selectedRun.performance.scheduler.collection_released_before_local_work ? '采集结束后已释放采集队列' : '本任务保持串行采集'}。平台采集串行，本地重任务按任务串行。</p>}
                <dl>{Object.entries(selectedRun.performance.stages || {}).filter(([key]) => key.startsWith('phase:')).map(([key, value]) => <div className="wb-row wb-space" key={key}><dt>{phaseLabel(key.slice(6))}</dt><dd>{Number(value.seconds || 0).toFixed(2)} 秒</dd></div>)}</dl>
                {!!selectedRun.performance.order_pipelines?.length && <div className="space-y-2">{selectedRun.performance.order_pipelines.map((orders, index) => <div key={index}><p className="font-medium">问题单处理{selectedRun.performance!.order_pipelines!.length > 1 ? ` · ${index + 1}` : ''}</p><p className="wb-muted">平台采集 {Number(orders.collection_seconds || 0).toFixed(2)} 秒 · 分批解析 {Number(orders.parser_seconds || 0).toFixed(2)} 秒</p><dl>{Object.entries(orders.timings || {}).filter(([key]) => key in ORDER_TIMING_LABELS).map(([key, seconds]) => <div className="wb-row wb-space" key={key}><dt>{ORDER_TIMING_LABELS[key]}</dt><dd>{Number(seconds).toFixed(2)} 秒</dd></div>)}</dl><p className="wb-muted">采集与处理可能并行，部分阶段包含子阶段，耗时不能直接相加。</p></div>)}</div>}
                {!!selectedRun.performance.generators?.length && <div>{selectedRun.performance.generators.map((generator, index) => <div key={index}><p className="wb-muted">{datasetLabel(generator.name)}{generator.scope ? ` · ${generator.scope.city} · ${generator.scope.month}` : ` · 子任务 ${index + 1}`} · {Number(generator.elapsed_seconds || 0).toFixed(2)} 秒</p>{generator.name === 'abnormal_riders' && <p className="wb-muted pl-3">读取来源 {generator.stages?.read_sources ? `${Number(generator.stages.read_sources.seconds).toFixed(2)} 秒` : '未记录'} · 写入子表 {generator.stages?.write_sheets ? `${Number(generator.stages.write_sheets.seconds).toFixed(2)} 秒` : '未记录'} · 保存压缩 {generator.stages?.save_workbook ? `${Number(generator.stages.save_workbook.seconds).toFixed(2)} 秒` : '未记录'}（均包含在该子任务耗时内）</p>}</div>)}</div>}
                {selectedRun.performance.source_cache && <p className="wb-muted">本任务解析缓存命中 {selectedRun.performance.source_cache.hits} 次；临时大表缓存 {selectedRun.performance.source_cache.spill_files || 0} 份、{((selectedRun.performance.source_cache.spill_bytes || 0) / 1048576).toFixed(1)} MB。任务结束自动清理；内存为服务进程采样，非任务独占。</p>}
              </details>}
              <details className="border-t border-slate-200 pt-3 text-xs text-slate-500"><summary className="cursor-pointer w-fit">任务信息与保存位置</summary><div className="mt-3 space-y-2"><p>编号：{selectedRun.archive_code || selectedRun.id.slice(0, 6).toUpperCase()}</p><p className="break-all">任务目录：{selectedRun.archive_relative_dir || '旧版任务保留原存放位置'}</p><p>城市：{selectedRun.cities.join('、')}</p><p>资料：{selectedRun.datasets.map(datasetLabel).join('、')}</p>{selectedRun.retry_of && <p>此任务处理原任务 {selectedRun.retry_of.slice(0, 6).toUpperCase()} 的未完成项。</p>}{selectedRun.recovery_of && <p>此任务恢复原有平台导出。</p>}{!activeRun && <button type="button" className={smallButton} disabled={rawBusy} onClick={() => void downloadRawBundle()}>下载已保留原始资料</button>}{selectedRun.last_activity_at && <p>最近进展：{displayTime(selectedRun.last_activity_at)}</p>}{!activeRun && <button type="button" className={smallButton} disabled={!!downloadingSummaryId} onClick={() => void downloadSummary()}>{downloadingSummaryId ? <Loader2 size={14} /> : <Download size={14} />}下载说明</button>}</div></details>

              {!!selectedRun.logs?.length && <details className="border-t border-slate-200 pt-3 text-xs text-slate-600"><summary className="cursor-pointer w-fit">执行日志</summary><div className="mt-3 max-h-48 space-y-2 overflow-y-auto font-mono bg-slate-50 border border-slate-200 rounded-lg p-3">{selectedRun.logs.map((log, index) => <p key={index} className="break-words"><span className="mr-2 text-slate-400">{displayTime(log.time)}</span>{log.message}</p>)}</div></details>}
            </div>}
        </>}
              />
            </div>
          </div>
        );
      })()}

    </div>
  );
}
