import {useStationDirectory} from '../lib/useStationDirectory';
import {CityStationCount} from './CityStationCount';
import { recoverySummary } from '../lib/downloadCenterLogic';
import { readDownloadResponse, saveDownloadBlob, downloadOutput, downloadErrorMessage } from '../lib/outputDownload';
import { isBaize, isBenlai, isPayoutPlatform, isXiaoxiang, isRiderArchive, isGlobalDataset, datasetGroup,isMerchant,isMerchantSnapshot,toggleDownloadDataset } from '../lib/downloadCenterLogic';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Calendar, CheckCircle2, CloudDownload, Download, FileSpreadsheet, KeyRound, Loader2, Plus, RefreshCw, Square, X, XCircle, Pencil, Trash2, AlertTriangle, UsersRound, Building2, History, ArrowUpRight, Compass, Layers, Radar } from 'lucide-react';
import { DownloadAccountPanel } from './DownloadAccountPanel';
import type { FengshenAuthStatus } from './FengshenLoginModal';
import { itemKey, newRequestId, phaseLabel, recoverable, retainAttempt, selectionKey, isLanorange } from '../lib/downloadCenterLogic';
import type { CreateSelection, DownloadUser, ItemSelection, Recovery, RequestAttempt } from '../lib/downloadCenterLogic';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { DownloadRecords } from './DownloadRecords';
import { ReportBuilder } from './ReportBuilder';
import {
  buildGenerateBatchPayloads,
  buildUnifiedSubmissionPayloads,
  deriveSelectedMonthsFromRange,
  mergeAvailableReports,
  type ReportDefinition,
  type BindingPlatform,
} from '../lib/reportBuilder';
import { isGenerator, inferTaskKind, registerGeneratorIds } from '../lib/taskCatalog';
import { systemShortLabel } from '../lib/platformCatalog';
import {
  computeDynamicScopeRequirements,
  DOWNLOAD_PLATFORMS,
  groupDatasetsByPlatform,
  inferDatasetPlatform,
  moduleAcceptsDataset,
  toggleCrossPlatformDataset,
  type DownloadPlatform,
  type RecordModule,
} from '../lib/downloadModules';
import { WorkbenchDatePicker } from './WorkbenchDatePicker';
import {
  BUILTIN_DOWNLOAD_SCENARIOS,
  buildExecutionRailSummary,
  buildMultiMonthRunRanges,
  buildRecentMonths,
  computeBillingPeriodRange,
  computeDateRangeSpanDays,
  computeLighthousePeriodRange,
  computeMonthSelectionRange,
  countFengshenDatasetsByCategory,
  FENGSHEN_DATASET_CATEGORIES,
  filterFengshenDatasetsByCategory,
  getDatasetCardMeta,
  getPlatformCardBadge,
  getStageHeaderMeta,
  sortCitiesWithLanorangeFirst,
  SYSTEM_META,
  toggleMultiMonthSelection,
  type BillingPeriodPreset,
  type BuiltinScenarioPreset,
  type FengshenDatasetCategoryId,
} from '../lib/workbench';
import {
  shouldUseDemoData,
  useDemoDataVisibility,
  usePlatformAuthSnapshot,
} from '../lib/demoMode';
import { buildDemoBindingPlatforms, buildDemoTaskCenterRecords } from '../lib/showcaseDemoData';

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
  xiaoxiang_all_dates?: boolean;
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
  activeReportId?: string;
  hideNavigation?: boolean;
  onSelectPlatform?: (platform: DownloadPlatform) => void;
  onSelectReport?: (reportId: string) => void;
  onTaskKindChange?: (kind: 'download' | 'generate') => void;
  onViewChange?: (view: 'create' | 'history') => void;
  onFormLock?: (locked: boolean) => void;
  onNavigateGenerate?: (cities: string[], start: string, end: string) => void;
  onOpenPrice?: (view: 'approval' | 'price-export', id?: string) => void;
  prefill?: {
    cities?: string[];
    start?: string;
    end?: string;
    datasets?: string[];
    taskKind?: 'download' | 'generate';
    token?: number;
  } | null;
  embedded?: boolean;
  navigation?: { view: 'create' | 'history'; version: number };
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>;
  workspaceId: string;
  onOpenFengshenLogin?: (accountId?: string) => void;
  onNavigatePayroll?: () => void;
  onAccountChange?: (accountId?: string) => void;
  onActiveCountChange?: (count: number) => void;
  fengshenAuthStatus?: FengshenAuthStatus | null;
}

const API_ROOT = '/api/fengshen-downloads';
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const LANORANGE_CITIES = ['保定','北京','潮州','大连','东莞','广州','惠州','宁波','泉州','三亚','汕头','上海','韶关','深圳','台州','天津'];

function cleanBindingPlatforms(value: unknown): Record<string, BindingPlatform> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result: Record<string, BindingPlatform> = {};
  for (const [city, platform] of Object.entries(value)) {
    if (platform === '本来人力' || platform === '商翼') result[city] = platform;
  }
  return result;
}

// 预设配置现已全面切换为用户自定义，支持增删改与持久化存储

const DATASET_LABELS: Record<string, string> = {
  invitation_records:'邀请记录（全量）',attendance_detail:'骑手出勤明细',baize_employees: '商翼员工资料（全量）', benlai_employees: '本来人力灵工资料（全量）', rider_daily: '日维度骑手分析（灯塔）', rider_archive: '骑手档案（灯塔）', detail_orders: '配送订单明细（灯塔）', detail_kesu: '配送客诉明细（灯塔）', detail_reviews: '配送评价明细（灯塔）', rider_order_detail: '骑手订单明细（灯塔）', xiaoxiang_attendance_detail: '骑手出勤明细合并（灯塔）', delivery_fee: '配送费', penalty: '违规扣款', rider_monthly: '风神骑手月度 UB 账单',
  receive_account: '骑手风神绑定', rider_detail: '骑手数据明细', rider_info: '骑手信息导出', fraud: '欺诈单', problem: '问题单',
  payment_binding: '支付绑定（生成表）', goods_rent: '物资租用登记',
  abnormal_followup: '异常跟进（生成表）',
  abnormal_riders: '异常名单（生成表）',
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

function AuthorizedDownloadCenter({ apiFetch, workspaceId, onOpenFengshenLogin, onNavigatePayroll, onActiveCountChange, fengshenAuthStatus, user, embedded, navigation, taskKind = 'download', platform, recordModule, activeReportId, hideNavigation, onSelectPlatform, onSelectReport, onTaskKindChange, onViewChange, onFormLock, onNavigateGenerate, onOpenPrice, prefill }: Props & { user: DownloadUser }) {
  const apiRef = useRef(apiFetch);
  apiRef.current = apiFetch;
  const [options, setOptions] = useState<DownloadOptions | null>(null);
  const [optionsError, setOptionsError] = useState('');
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionVersion, setOptionVersion] = useState(0);
  const [cities, setCities] = useState<string[]>([]);
  const [bindingPlatforms, setBindingPlatforms] = useState<Record<string, BindingPlatform>>({});
  const [demoBindingPlatforms, setDemoBindingPlatforms] = useState<Record<string, BindingPlatform>>(
    () => buildDemoBindingPlatforms(),
  );
  const [bindingPlatformsBusy, setBindingPlatformsBusy] = useState(false);
  const authSnapshot = usePlatformAuthSnapshot();
  const { demoHidden } = useDemoDataVisibility();
  const bindingPlatformsDemoActive = shouldUseDemoData({
    isLoggedIn: authSnapshot.anyLoggedIn,
    hasLiveData: Object.keys(bindingPlatforms).length > 0,
    demoHidden,
  });
  const effectiveBindingPlatforms = bindingPlatformsDemoActive
    ? demoBindingPlatforms
    : bindingPlatforms;
  const [datasets, setDatasets] = useState<string[]>(() =>
    platform === 'payout'
      ? ['baize_employees', 'benlai_employees']
      : platform === 'xiaoxiang'
        ? ['rider_daily']
        : [],
  );
  const categorySelections = useRef<Record<string, string[]>>({
    download: [],
    payout: ['baize_employees', 'benlai_employees'],
    xiaoxiang: ['rider_daily'],
  });
  const [fengshenCategory, setFengshenCategory] = useState<FengshenDatasetCategoryId>('all');
  /** 「只看已选」独立开关（P0-3）：与分类互不叠加语义，点击仅过滤已勾选资料；无已选资料时自动恢复全览。 */
  const [onlySelectedShown, setOnlySelectedShown] = useState(false);
  useEffect(() => {
    if (datasets.length === 0 && onlySelectedShown) {
      setOnlySelectedShown(false);
    }
  }, [datasets.length, onlySelectedShown]);
  const [payoutAuthStatuses, setPayoutAuthStatuses] = useState<Record<string, any>>({});
  const isGenerateMode = taskKind === 'generate';
  const availableReports = mergeAvailableReports(options?.generators || []);
  const currentReportId =
    activeReportId && availableReports.some(report => report.id === activeReportId)
      ? activeReportId
      : availableReports[0]?.id || 'payment_binding';
  const activeReport =
    availableReports.find(report => report.id === currentReportId) || availableReports[0];
  const selectionScope = isGenerateMode ? `report:${currentReportId}` : (platform || 'download');
  const previousKind = useRef(selectionScope);
  const moduleDataset = (id: string) =>
    platform
      ? moduleAcceptsDataset(id, platform)
      : !isGenerator(id);
  const visibleDatasets = options?.datasets.filter(value => moduleDataset(value.id)) || [];
  const defaultMonthRange = (forXiaoxiang: boolean) => {
    const today = shanghaiToday();
    const recent = buildRecentMonths(today, 2);
    const primary = computeMonthSelectionRange(recent[0], today, { capAtYesterday: forXiaoxiang });
    if (primary.start <= primary.end) return primary;
    return computeMonthSelectionRange(recent[1], today, { capAtYesterday: forXiaoxiang });
  };
  const [start, setStart] = useState(() => taskKind === 'generate' ? computeBillingPeriodRange('last_full_month', shanghaiToday()).start : defaultMonthRange(platform === 'xiaoxiang').start);
  const [end, setEnd] = useState(() => taskKind === 'generate' ? computeBillingPeriodRange('last_full_month', shanghaiToday()).end : defaultMonthRange(platform === 'xiaoxiang').end);
  const [refreshHistory, setRefreshHistory] = useState(false);
  const [waybillAllCitySend, setWaybillAllCitySend] = useState(false);
  const [selectedMonths, setSelectedMonths] = useState<string[]>(() => [
    taskKind === 'generate'
      ? computeBillingPeriodRange('last_full_month', shanghaiToday()).start.slice(0, 7)
      : defaultMonthRange(platform === 'xiaoxiang').start.slice(0, 7),
  ]);
  const [lanorangeMonths, setLanorangeMonths] = useState<string[]>(() => [defaultMonthRange(platform === 'xiaoxiang').start.slice(0, 7)]);
  const [xiaoxiangAllDates, setXiaoxiangAllDates] = useState(false);
  const [blueCities, setBlueCities] = useState<string[]>([]);
  const [includeSeparation, setIncludeSeparation] = useState(false);
  const [excludeSeparation, setExcludeSeparation] = useState(true);
  const scopeSelections = useRef<Record<string, {cities:string[];start:string;end:string;selectedMonths:string[];includeSeparation:boolean;excludeSeparation:boolean;allDates:boolean}>>({});
  const [runs, setRuns] = useState<DownloadRun[]>([]);
  const [cityPickerOpen, setCityPickerOpen] = useState(false);
  const [citySearch, setCitySearch] = useState('');
  const [view, setView] = useState<'create' | 'history'>('create');
  useEffect(() => { if (navigation) setView(navigation.view); }, [navigation?.version]);

  useEffect(() => {
    if (!prefill || !prefill.token) return;
    const target = selectionScope;
    const prefillMonths =
      prefill.start && prefill.end
        ? deriveSelectedMonthsFromRange(
            prefill.start,
            prefill.end,
            buildRecentMonths(shanghaiToday(), 3),
          )
        : [];
    scopeSelections.current[target] = {
      cities: prefill.cities || cities,
      start: prefill.start || start,
      end: prefill.end || end,
      selectedMonths: prefillMonths,
      includeSeparation,
      excludeSeparation,
      allDates: false,
    };
    setXiaoxiangAllDates(false);
    if (prefill.cities && prefill.cities.length) {
      setCities(prefill.cities);
    }
    if (prefill.datasets && prefill.datasets.length) {
      const prefillGen = prefill.datasets.find(isGenerator);
      if (prefill.taskKind === 'generate' && prefillGen) {
        onSelectReport?.(prefillGen);
      } else {
        setDatasets(prefill.datasets.filter(id => !isGenerator(id) && (!options || options.datasets.some(item => item.id === id))));
      }
    }
    if (prefill.start) setStart(prefill.start);
    if (prefill.end) setEnd(prefill.end);
    if (prefill.start || prefill.end) setSelectedMonths(prefillMonths);
    if (prefill.taskKind && onTaskKindChange) onTaskKindChange(prefill.taskKind);
  }, [prefill?.token]);
  const presetsKey = `download-presets:${user.id}`;
  const [presets, setPresets] = useState<{ name: string; cities: string[]; datasets: string[] }[]>(() => {
    try { const parsed = JSON.parse(localStorage.getItem(presetsKey) || '[]'); return Array.isArray(parsed) ? parsed.filter(item => Array.isArray(item?.cities) && Array.isArray(item?.datasets)) : []; } catch { return []; }
  });
  const [presetInputOpen, setPresetInputOpen] = useState(false);
  const [presetDraft, setPresetDraft] = useState('');

  // 自定义城市片区预设 (持久化至 localStorage，删除写死默认片区，纯用户自定义)
  const regionStorageKey = `workbench_region_presets:${user.id}`;
  const [regionPresets, setRegionPresets] = useState<{ id: string; label: string; cities: string[] }[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(regionStorageKey) || 'null');
      if (Array.isArray(saved)) {
        return saved.filter(r => r && !['south', 'east', 'north'].includes(r.id));
      }
    } catch {}
    return [];
  });
  const saveRegionPresetsToStorage = (next: { id: string; label: string; cities: string[] }[]) => {
    setRegionPresets(next);
    try { localStorage.setItem(regionStorageKey, JSON.stringify(next)); } catch {}
  };

  // 自定义资料场景包预设 (持久化至 localStorage，删除写死默认预设，纯用户自定义)
  const scenarioStorageKey = `workbench_scenario_presets:${user.id}`;
  const [scenarioPresets, setScenarioPresets] = useState<{ id: string; label: string; title: string; datasets: string[] }[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(scenarioStorageKey) || 'null');
      if (Array.isArray(saved)) {
        return saved.filter(s => s && !['payroll_bundle', 'risk_bundle', 'snapshot_bundle'].includes(s.id));
      }
    } catch {}
    return [];
  });
  const saveScenarioPresetsToStorage = (next: { id: string; label: string; title: string; datasets: string[] }[]) => {
    setScenarioPresets(next);
    try { localStorage.setItem(scenarioStorageKey, JSON.stringify(next)); } catch {}
  };

  // 预设弹窗状态：支持创建、修改名称/内容及删除
  interface PresetModalState {
    mode: 'create' | 'edit';
    type: 'region' | 'scenario';
    id?: string;
    label: string;
    cities?: string[];
    datasets?: string[];
    syncWithCurrentSelection?: boolean;
  }
  const [presetModal, setPresetModal] = useState<PresetModalState | null>(null);

  // 右侧执行核对栏引导平滑定位
  const [pulsingStep, setPulsingStep] = useState<'cities' | 'datasets' | 'period' | null>(null);
  /** 右栏「清空」的二次确认层（复用 WorkbenchDrawer，不用 window.confirm）。 */
  const [clearConfirm, setClearConfirm] = useState(false);
  const scrollToStep = (step: 'cities' | 'datasets' | 'period') => {
    // 步骤 ID 归一（架构 §4.3 改造点 6）：01=选择资料 / 02=城市+账期。
    // 旧 id `step-03-datasets` 保留为兜底，避免历史锚点失效。
    const targetId = step === 'cities' ? 'step-01-cities' : step === 'period' ? 'step-02-period' : 'step-01-datasets';
    const legacyId = step === 'cities' ? 'step-02-cities' : step === 'period' ? 'step-02-dates' : 'step-03-datasets';
    const el = document.getElementById(targetId) || document.getElementById(legacyId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setPulsingStep(step);
      setTimeout(() => setPulsingStep(curr => (curr === step ? null : curr)), 1600);
    }
  };

  const [systemFilter, setSystemFilter] = useState<'all' | 'fengshen' | 'lanorange' | 'baize' | 'benlai' | 'xiaoxiang'>('all');
  const [historyFocusId,setHistoryFocusId]=useState('');
  const [submittedTaskInfo, setSubmittedTaskInfo] = useState<{ id: string; name: string } | null>(null);

  const lastTaskKey = `download-last-task:${user.id}:${workspaceId}`;
  const [selectedId, setSelectedId] = useState(() => { try { return localStorage.getItem(lastTaskKey) || ''; } catch { return ''; } });
  useEffect(() => { try { if (selectedId) localStorage.setItem(lastTaskKey, selectedId); } catch {} }, [lastTaskKey, selectedId]);
  const selectedIdRef = useRef(selectedId);
  const [selectedRun, setSelectedRun] = useState<DownloadRun | null>(null);
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
    scopeSelections.current[previous] = {cities:[...cities],start,end,selectedMonths:[...selectedMonths],includeSeparation,excludeSeparation,allDates:xiaoxiangAllDates};
    const savedScope = scopeSelections.current[selectionScope];
    if (savedScope) {
      setCities(savedScope.cities); setStart(savedScope.start); setEnd(savedScope.end); setSelectedMonths(savedScope.selectedMonths); setLanorangeMonths(savedScope.selectedMonths); setIncludeSeparation(savedScope.includeSeparation); setExcludeSeparation(savedScope.excludeSeparation); setXiaoxiangAllDates(savedScope.allDates);
    } else if (taskKind === 'generate') {
      const period = computeBillingPeriodRange('last_full_month', shanghaiToday());
      setCities([]); setStart(period.start); setEnd(period.end); setSelectedMonths([period.start.slice(0, 7)]); setIncludeSeparation(false); setExcludeSeparation(true); setXiaoxiangAllDates(false);
    } else {
      const range = defaultMonthRange(platform === 'xiaoxiang');
      const initialMonth = range.start.slice(0, 7);
      setCities([]); setStart(range.start); setEnd(range.end); setSelectedMonths([initialMonth]); setLanorangeMonths([initialMonth]); setIncludeSeparation(false); setExcludeSeparation(true); setXiaoxiangAllDates(false);
    }
    if (!platform) {
      setDatasets(values => {
        categorySelections.current[previous] = values;
        const saved = categorySelections.current[selectionScope] || [];
        return saved.filter(moduleDataset);
      });
    }
    setDuplicateApproval('');
  }, [selectionScope]);

  useEffect(() => {
    if (createAttempt.current) return;
    scopeSelections.current[selectionScope] = {
      cities: [...cities],
      start,
      end,
      selectedMonths: [...selectedMonths],
      includeSeparation,
      excludeSeparation,
      allDates: xiaoxiangAllDates,
    };
  }, [selectionScope, cities, start, end, selectedMonths, includeSeparation, excludeSeparation, xiaoxiangAllDates]);
  useEffect(() => {
    const previous = createAttempt.current?.payload;
    if (previous) { setCities(previous.cities); setDatasets(previous.datasets); setStart(previous.start); setEnd(previous.end); setRefreshHistory(!!previous.refresh_history); setWaybillAllCitySend(!!previous.waybill_all_city_send); setXiaoxiangAllDates(!!previous.xiaoxiang_all_dates); const restoredMonths = Array.isArray(previous.lanorange_months) ? previous.lanorange_months : []; setLanorangeMonths(restoredMonths); if (restoredMonths.length) setSelectedMonths(restoredMonths); setBlueCities(previous.datasets?.every(isLanorange) && !previous.datasets.includes('abnormal_riders') ? (previous.cities || []).filter(city => city !== '全部城市') : []); setIncludeSeparation(!!previous.include_separation); setExcludeSeparation(previous.exclude_separation??true); }
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

  useEffect(() => {
    let active = true;
    void getJson('/api/workbench/binding-platforms')
      .then(data => {
        if (active) setBindingPlatforms(cleanBindingPlatforms(data?.platforms));
      })
      .catch(() => {});
    return () => { active = false; };
  }, [getJson, authSnapshot.anyLoggedIn]);

  const updateBindingPlatforms = useCallback(async (next: Record<string, string>) => {
    const clean = cleanBindingPlatforms(next);
    if (bindingPlatformsDemoActive) {
      setDemoBindingPlatforms(clean);
      return;
    }
    setBindingPlatforms(clean);
    setBindingPlatformsBusy(true);
    try {
      const data = await getJson('/api/workbench/binding-platforms', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platforms: clean }),
      });
      setBindingPlatforms(cleanBindingPlatforms(data?.platforms));
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : '绑定平台配置保存失败');
    } finally {
      setBindingPlatformsBusy(false);
    }
  }, [bindingPlatformsDemoActive, getJson]);

  const stationDirectory=useStationDirectory(platform==='xiaoxiang'?'xiaoxiang':'fengshen',apiRef.current,platform!=='payout');

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent)?.detail;
      if (detail && typeof detail === 'object') {
        setPayoutAuthStatuses(detail);
      }
    };
    window.addEventListener('workbench:platform-statuses', handler);
    return () => window.removeEventListener('workbench:platform-statuses', handler);
  }, []);

  useEffect(() => {
    if (platform !== 'payout') return;
    let cancelled = false;
    Promise.all(
      (['baize', 'benlai'] as const).map(source =>
        apiRef
          .current(`/api/fengshen-downloads/platform-auth/${source}`, { signal: AbortSignal.timeout(10000) })
          .then(res => (res.ok ? res.json() : null))
          .then(data => (data ? ([source, { ...data, offline: false }] as const) : null))
          .catch(() => null),
      ),
    ).then(entries => {
      if (cancelled) return;
      const updates: Record<string, any> = {};
      for (const entry of entries) {
        if (entry) updates[entry[0]] = entry[1];
      }
      if (Object.keys(updates).length) {
        setPayoutAuthStatuses(prev => ({ ...updates, ...prev }));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [platform, workspaceId]);

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
        if (platform !== 'xiaoxiang') {
          setCities(previous => previous.filter(city => data.cities.some((item: { name: string; disabled?: boolean }) => item.name === city && !item.disabled)));
        }
        setDatasets(previous => previous.filter(dataset => data.datasets.some((item: { id: string }) => item.id === dataset)));
      })
      .catch(error => { if (!controller.signal.aborted) setOptionsError(error instanceof Error ? error.message : '无法加载下载选项'); })
      .finally(() => { if (!controller.signal.aborted) setOptionsLoading(false); });
    return () => controller.abort();
  }, [getJson, workspaceId, optionVersion, platform]);

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
  const activePlatform: DownloadPlatform = platform || 'fengshen';
  const groupedByPlatform = groupDatasetsByPlatform(datasets);
  const activePlatformList = (['fengshen', 'lanorange', 'payout', 'xiaoxiang'] as const).filter(
    plat => groupedByPlatform[plat].length > 0,
  );
  const activePlatformCount = activePlatformList.length;
  const activeDatasets = platform ? groupedByPlatform[activePlatform] : datasets;
  const dynamicScopeReq = computeDynamicScopeRequirements(activePlatform, activeDatasets);

  const getPlatformScope = (plat: DownloadPlatform) => {
    if (plat === selectionScope) {
      return { cities, start, end, selectedMonths, includeSeparation, excludeSeparation, allDates: xiaoxiangAllDates };
    }
    const saved = scopeSelections.current[plat];
    if (saved) return saved;
    const defRange = defaultMonthRange(plat === 'xiaoxiang');
    return {
      cities: [],
      start: defRange.start,
      end: defRange.end,
      selectedMonths: [defRange.start.slice(0, 7)],
      includeSeparation: false,
      excludeSeparation: true,
      allDates: false,
    };
  };

  const toggle = (value: string, values: string[], setter: (next: string[]) => void) => setter(values.includes(value) ? values.filter(item => item !== value) : [...values, value]);
  const validDates = DATE_PATTERN.test(start) && DATE_PATTERN.test(end) && start <= end;
  const recentReportMonthCodes = buildRecentMonths(shanghaiToday(), 3);
  const rawSelectedDatasets = activeDatasets.filter(id => !isGenerator(id));
  const selectedGeneratorIds = activeDatasets.filter(isGenerator);
  const abnormalRidersOnly =
    platform !== 'lanorange' &&
    activeDatasets.length > 0 &&
    activeDatasets.every(id => id === 'abnormal_riders');
  const hasAbnormalRiders = activeDatasets.includes('abnormal_riders');
  const payoutHasBaize = datasets.includes('baize_employees');
  const payoutHasBenlai = datasets.includes('benlai_employees');
  const payoutBoth = payoutHasBaize && payoutHasBenlai;
  const baizeOnly: boolean = payoutHasBaize && !payoutHasBenlai && groupedByPlatform.payout.length === 1;
  const benlaiOnly: boolean = payoutHasBenlai && !payoutHasBaize && groupedByPlatform.payout.length === 1;
  const payoutOnly: boolean = platform === 'payout' || (!platform && (payoutBoth || baizeOnly || benlaiOnly));
  const xiaoxiangOnly: boolean = platform ? platform === 'xiaoxiang' : activeDatasets.length > 0 && activeDatasets.every(isXiaoxiang);
  const archiveOnly: boolean = xiaoxiangOnly && activeDatasets.length > 0 && activeDatasets.every(isRiderArchive);
  const xiaoxiangDated: boolean = xiaoxiangOnly && !archiveOnly;
  const xiaoxiangAllDatesActive = xiaoxiangDated && xiaoxiangAllDates;
  useEffect(() => {
    if (!xiaoxiangDated && xiaoxiangAllDates) setXiaoxiangAllDates(false);
  }, [xiaoxiangDated, xiaoxiangAllDates]);
  const yesterday = new Date(shanghaiToday() + 'T00:00:00Z'); yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const dailyDate = yesterday.toISOString().slice(0, 10);
  const blueOnly: boolean =
    platform === 'lanorange' ||
    (!platform && !payoutOnly && !xiaoxiangOnly && !abnormalRidersOnly && activeDatasets.length > 0 && activeDatasets.every(isGlobalDataset));
  const merchantOnly: boolean =
    rawSelectedDatasets.length > 0 &&
    selectedGeneratorIds.length === 0 &&
    rawSelectedDatasets.every(isMerchant);
  const merchantSnapshotOnly: boolean = merchantOnly && !rawSelectedDatasets.includes('attendance_detail');
  const hasAttendance = activeDatasets.includes('attendance_detail');
  const noCity = blueOnly || payoutOnly || abnormalRidersOnly;
  const noDate = payoutOnly || abnormalRidersOnly;
  const attendanceDateMax = new Date(shanghaiToday() + 'T00:00:00Z'); attendanceDateMax.setUTCDate(attendanceDateMax.getUTCDate() - 1); const attendanceLast = attendanceDateMax.toISOString().slice(0, 10);
  const attendanceDateMin = new Date(shanghaiToday() + 'T00:00:00Z'); attendanceDateMin.setUTCDate(attendanceDateMin.getUTCDate() - 90); const attendanceFirst = attendanceDateMin.toISOString().slice(0, 10);
  const xiaoxiangDateMin = new Date(`${shanghaiToday()}T00:00:00Z`); xiaoxiangDateMin.setUTCDate(xiaoxiangDateMin.getUTCDate() - 365); const xiaoxiangFirst = xiaoxiangDateMin.toISOString().slice(0, 10);
  const priceMonthOptions = recentReportMonthCodes;
  const enabledMonthOptions = priceMonthOptions.filter(month => {
    const monthRange = computeMonthSelectionRange(month, shanghaiToday(), { capAtYesterday: xiaoxiangOnly });
    const expectedStart = hasAttendance && monthRange.start < attendanceFirst ? attendanceFirst : monthRange.start;
    const expectedEnd = hasAttendance && monthRange.end > attendanceLast ? attendanceLast : monthRange.end;
    return monthRange.start <= monthRange.end && !(hasAttendance && (monthRange.end < attendanceFirst || monthRange.start > attendanceLast)) && expectedStart <= expectedEnd;
  });
  const activeSelectedMonths = selectedMonths.filter(month => enabledMonthOptions.includes(month));
  const monthRunChunks = !xiaoxiangAllDatesActive && activeSelectedMonths.length > 0
    ? buildMultiMonthRunRanges(activeSelectedMonths, shanghaiToday(), {
        capAtYesterday: xiaoxiangOnly,
        minDate: hasAttendance ? attendanceFirst : undefined,
        maxDate: hasAttendance ? attendanceLast : undefined,
        maxDaysPerRun: xiaoxiangDated ? 31 : undefined,
      })
    : [];
  const isPayoutMultiBatchSubmit =
    !createAttempt.current &&
    activePlatformCount === 1 &&
    activePlatformList[0] === 'payout' &&
    payoutBoth;
  const isMultiBatchMonthSubmit =
    !createAttempt.current &&
    !blueOnly &&
    !payoutOnly &&
    !archiveOnly &&
    !xiaoxiangAllDatesActive &&
    !abnormalRidersOnly &&
    rawSelectedDatasets.length > 0 &&
    activeSelectedMonths.length > 0 &&
    monthRunChunks.length > 1;
  const xiaoxiangSpanDays = validDates ? Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1 : 0;
  const xiaoxiangDateValid = xiaoxiangAllDatesActive
    ? xiaoxiangFirst <= dailyDate
    : activeSelectedMonths.length > 0
      ? monthRunChunks.length > 0 && monthRunChunks.every(chunk => {
          const chunkSpan = computeDateRangeSpanDays(chunk.start, chunk.end) ?? 0;
          return chunk.end <= dailyDate && chunkSpan <= 31;
        })
      : validDates && end <= dailyDate && xiaoxiangSpanDays <= 31;
  const billingPeriodRange=(preset:BillingPeriodPreset)=>{
    const range=xiaoxiangDated
      ? computeLighthousePeriodRange(preset,shanghaiToday())
      : {...computeBillingPeriodRange(preset,shanghaiToday()),blocked:false};
    const nextStart=hasAttendance&&range.start<attendanceFirst?attendanceFirst:range.start;
    const nextEnd=hasAttendance&&range.end>attendanceLast?attendanceLast:range.end;
    return {start:nextStart,end:nextEnd,blocked:range.blocked||nextStart>nextEnd};
  };
  const activeSelectedMonthsKey = activeSelectedMonths.join(',');
  useEffect(()=>{
    if(!xiaoxiangOnly || xiaoxiangAllDatesActive)return;
    if(activeSelectedMonths.length > 0){
      const chunks = buildMultiMonthRunRanges(activeSelectedMonths, shanghaiToday(), { capAtYesterday: true, maxDaysPerRun: 31 });
      if (chunks.length > 0) {
        const nextStart = chunks[0].start;
        const nextEnd = chunks[chunks.length - 1].end;
        if (start !== nextStart) setStart(nextStart);
        if (end !== nextEnd) setEnd(nextEnd);
      } else {
        const fallback = defaultMonthRange(true);
        const fallbackMonth = fallback.start.slice(0, 7);
        setSelectedMonths([fallbackMonth]);
        setStart(fallback.start);
        setEnd(fallback.end);
      }
      return;
    }
    if(end>dailyDate||start>dailyDate){
      const curMonth = start.slice(0, 7);
      const mRange = computeMonthSelectionRange(curMonth, shanghaiToday(), { capAtYesterday: true });
      if (mRange.start <= mRange.end) {
        setStart(mRange.start);
        setEnd(mRange.end);
      } else {
        const fallback = defaultMonthRange(true);
        setStart(fallback.start);
        setEnd(fallback.end);
      }
    }
  },[xiaoxiangOnly,xiaoxiangAllDatesActive,dailyDate,activeSelectedMonthsKey]);
  const merchantDateValid=merchantSnapshotOnly||(validDates&&start>=attendanceFirst&&end<=attendanceLast);
  const invalidBaizeMix = !platform && datasets.some(isPayoutPlatform) && !datasets.every(isPayoutPlatform);
  const invalidBenlaiMix = false;
  const invalidXiaoxiangMix = !platform && datasets.some(isXiaoxiang) && !xiaoxiangOnly;
  const displayedCities = React.useMemo<Array<{ id: string; name: string; disabled?: boolean; note?: string }>>(() => {
    const baseCities = options?.cities ?? [];
    if (platform !== 'xiaoxiang' && !xiaoxiangOnly) {
      return baseCities;
    }
    const realCities = (stationDirectory.data?.cities ?? [])
      .filter(city => city?.name)
      .map(city => ({ id: city.id || city.name, name: city.name }));
    return sortCitiesWithLanorangeFirst(realCities);
  }, [options?.cities, platform, xiaoxiangOnly, stationDirectory.data?.cities]);
  const selectableCities = displayedCities.filter(city => !city.disabled);
  const selectableCityNames = selectableCities.map(city => city.name).join('\u0001');
  useEffect(() => {
    if (!xiaoxiangOnly || stationDirectory.data?.status !== 'ready') return;
    const known = new Set(selectableCities.map(city => city.name));
    setCities(previous => {
      const kept = previous.filter(name => known.has(name));
      return kept.length === previous.length ? previous : kept;
    });
  }, [xiaoxiangOnly, stationDirectory.data?.status, selectableCityNames]);
  const invalidMerchantMix=hasAttendance&&!merchantDateValid;

  const fengshenNeedsCities =
    groupedByPlatform.fengshen.length > 0 &&
    !groupedByPlatform.fengshen.every(id => id === 'abnormal_riders');
  const fengshenScopeCities = getPlatformScope('fengshen').cities;
  const fengshenMissingCities = fengshenNeedsCities && fengshenScopeCities.length === 0;

  const canSubmit = platform
    ? datasets.length > 0 &&
      !fengshenMissingCities &&
      (activePlatform !== 'fengshen' || groupedByPlatform.fengshen.length === 0 || (
        !invalidMerchantMix &&
        (abnormalRidersOnly || (activeSelectedMonths.length > 0 ? monthRunChunks.length > 0 : validDates))
      )) &&
      (activePlatform !== 'xiaoxiang' || groupedByPlatform.xiaoxiang.length === 0 || (
        archiveOnly || xiaoxiangDateValid
      ))
    : datasets.every(moduleDataset) &&
      !invalidBaizeMix &&
      !invalidBenlaiMix &&
      !invalidXiaoxiangMix &&
      !invalidMerchantMix &&
      datasets.length > 0 &&
      (merchantOnly
        ? cities.length > 0 && merchantDateValid
        : archiveOnly || blueOnly || payoutOnly || abnormalRidersOnly ||
          (xiaoxiangDated && xiaoxiangDateValid) ||
          (cities.length > 0 && (activeSelectedMonths.length > 0 ? monthRunChunks.length > 0 : validDates)));

  const monthlyDatasets = rawSelectedDatasets.filter(dataset => MONTHLY_DATASETS.has(dataset));
  const periodDatasets = rawSelectedDatasets.filter(dataset => !isLanorange(dataset) && !MONTHLY_DATASETS.has(dataset) && !SNAPSHOT_DATASETS.has(dataset));
  const followupDatasets = selectedGeneratorIds.filter(id => id !== 'abnormal_riders');
  const monthPreview = monthlyDatasets.length || followupDatasets.length
    ? (activeSelectedMonths.length > 0
        ? activeSelectedMonths.map(m => `${m.slice(0, 4)}年${m.slice(5)}月`)
        : coveredMonths(start, end))
    : [];
  const orderWindowDays = options?.order_window_days || 60;
  const earliestOrderDate = new Date(`${shanghaiToday()}T00:00:00Z`);
  earliestOrderDate.setUTCDate(earliestOrderDate.getUTCDate() - orderWindowDays + 1);
  const earliestOrder = earliestOrderDate.toISOString().slice(0, 10);
  const orderWindowWarning = activeDatasets.some(dataset => ['fraud', 'problem'].includes(dataset)) && (
    activeSelectedMonths.length > 0
      ? monthRunChunks.some(chunk => chunk.start < earliestOrder || chunk.end > shanghaiToday())
      : (validDates && (start < earliestOrder || end > shanghaiToday()))
  );
  const resolvedLanorangeMonths = (activeSelectedMonths.length > 0
    ? [...activeSelectedMonths]
    : lanorangeMonths.length > 0
      ? [...lanorangeMonths]
      : [start.slice(0, 7)]
  ).filter(m => /^\d{4}-\d{2}$/.test(m)).sort();
  const rawSelection: CreateSelection = {
    task_kind: 'download',
    cities: blueOnly
      ? (blueCities.length && !hasAbnormalRiders ? blueCities : ['全部城市'])
      : payoutOnly
        ? ['全部城市']
        : xiaoxiangOnly
          ? (cities.length > 0 ? cities : ['全部城市'])
          : cities,
    datasets: rawSelectedDatasets,
    ...(rawSelectedDatasets.some(isLanorange) || blueOnly ? { lanorange_full_delivery: true } : {}),
    start: archiveOnly
      ? shanghaiToday()
      : xiaoxiangAllDatesActive
        ? xiaoxiangFirst
        : xiaoxiangDated
          ? (monthRunChunks[0]?.start || start)
          : blueOnly || payoutOnly || merchantSnapshotOnly
            ? shanghaiToday()
            : (monthRunChunks[0]?.start || start),
    end: archiveOnly
      ? shanghaiToday()
      : xiaoxiangAllDatesActive
        ? dailyDate
        : xiaoxiangDated
          ? (monthRunChunks[monthRunChunks.length - 1]?.end || end)
          : blueOnly || payoutOnly || merchantSnapshotOnly
            ? shanghaiToday()
            : (monthRunChunks[monthRunChunks.length - 1]?.end || end),
    ...(xiaoxiangAllDatesActive ? { xiaoxiang_all_dates: true } : {}),
    ...(refreshHistory && rawSelectedDatasets.some(dataset => ['fraud', 'problem'].includes(dataset)) ? { refresh_history: true } : {}),
    ...(waybillAllCitySend && rawSelectedDatasets.includes('delivery_waybill') ? { waybill_all_city_send: true } : {}),
    ...(blueOnly && rawSelectedDatasets.includes('lanorange_part_price') ? { lanorange_months: resolvedLanorangeMonths } : {}),
    ...(rawSelectedDatasets.some(isMerchant) ? { merchant_by_city: true } : {}),
    ...(!noCity && !rawSelectedDatasets.every(isMerchant) && !xiaoxiangOnly ? { exclude_separation: excludeSeparation } : {}),
  };
  const unifiedPayloads = buildUnifiedSubmissionPayloads({
    selectedDatasets: activeDatasets,
    availableGenerators: options?.generators || [],
    rawSelection,
    rawMonthChunks: monthRunChunks,
    isMultiBatchRawMonth: isMultiBatchMonthSubmit,
    cities,
    start,
    end,
    today: shanghaiToday(),
    excludeSeparation,
    selectedMonths: activeSelectedMonths.length > 0 ? activeSelectedMonths : undefined,
    isGeneratorFn: isGenerator,
  });

  const buildCrossPlatformPayloads = (): CreateSelection[] => {
    const allPayloads: CreateSelection[] = [];
    const today = shanghaiToday();
    for (const plat of ['fengshen', 'lanorange', 'payout', 'xiaoxiang'] as const) {
      const platDatasets = groupedByPlatform[plat];
      if (!platDatasets.length) continue;
      const pScope = getPlatformScope(plat);

      if (plat === 'payout') {
        for (const datasetId of platDatasets) {
          allPayloads.push({
            task_kind: 'download',
            cities: ['全部城市'],
            datasets: [datasetId],
            start: today,
            end: today,
          });
        }
        continue;
      }

      if (plat === 'lanorange') {
        allPayloads.push({
          task_kind: 'download',
          cities: blueCities.length > 0 ? blueCities : ['全部城市'],
          datasets: platDatasets,
          lanorange_full_delivery: true,
          start: today,
          end: today,
          ...(platDatasets.includes('lanorange_part_price') ? { lanorange_months: resolvedLanorangeMonths } : {}),
        });
        continue;
      }

      if (plat === 'xiaoxiang') {
        const xArchiveOnly = platDatasets.every(isRiderArchive);
        const xAllDates = !!pScope.allDates && !xArchiveOnly;
        const xMonths = pScope.selectedMonths.filter(m => priceMonthOptions.includes(m));
        const xChunks = !xArchiveOnly && !xAllDates && xMonths.length > 0
          ? buildMultiMonthRunRanges(xMonths, today, { capAtYesterday: true, maxDaysPerRun: 31 })
          : [];
        const xAllStartDate = new Date(`${today}T00:00:00Z`); xAllStartDate.setUTCDate(xAllStartDate.getUTCDate() - 365);
        const xAllEndDate = new Date(`${today}T00:00:00Z`); xAllEndDate.setUTCDate(xAllEndDate.getUTCDate() - 1);
        const xAllStart = xAllStartDate.toISOString().slice(0, 10);
        const xAllEnd = xAllEndDate.toISOString().slice(0, 10);
        const xRaw: CreateSelection = {
          task_kind: 'download',
          cities: pScope.cities.length > 0 ? pScope.cities : ['全部城市'],
          datasets: platDatasets,
          start: xArchiveOnly ? today : xAllDates ? xAllStart : (xChunks[0]?.start || pScope.start),
          end: xArchiveOnly ? today : xAllDates ? xAllEnd : (xChunks[xChunks.length - 1]?.end || pScope.end),
          ...(xAllDates ? { xiaoxiang_all_dates: true } : {}),
        };
        const xPayloads = buildUnifiedSubmissionPayloads({
          selectedDatasets: platDatasets,
          availableGenerators: options?.generators || [],
          rawSelection: xRaw,
          rawMonthChunks: xChunks,
          isMultiBatchRawMonth: !xArchiveOnly && !xAllDates && xChunks.length > 1,
          cities: xRaw.cities,
          start: xRaw.start,
          end: xRaw.end,
          today,
          excludeSeparation: false,
          selectedMonths: xMonths.length > 0 ? xMonths : undefined,
          isGeneratorFn: isGenerator,
        });
        allPayloads.push(...(xPayloads as CreateSelection[]));
        continue;
      }

      // fengshen
      const fRawDatasets = platDatasets.filter(id => !isGenerator(id));
      const fAbnormalOnly = platDatasets.every(id => id === 'abnormal_riders');
      const fMerchantSnap =
        fRawDatasets.length > 0 &&
        platDatasets.filter(isGenerator).length === 0 &&
        fRawDatasets.every(isMerchant) &&
        !fRawDatasets.includes('attendance_detail');
      const fHasAtt = platDatasets.includes('attendance_detail');
      const fMonths = pScope.selectedMonths.filter(m => priceMonthOptions.includes(m));
      const fChunks = !fAbnormalOnly && fMonths.length > 0
        ? buildMultiMonthRunRanges(fMonths, today, {
            capAtYesterday: false,
            minDate: fHasAtt ? attendanceFirst : undefined,
            maxDate: fHasAtt ? attendanceLast : undefined,
          })
        : [];
      const fRaw: CreateSelection = {
        task_kind: 'download',
        cities: pScope.cities,
        datasets: fRawDatasets,
        start: fMerchantSnap ? today : (fChunks[0]?.start || pScope.start),
        end: fMerchantSnap ? today : (fChunks[fChunks.length - 1]?.end || pScope.end),
        ...(refreshHistory && fRawDatasets.some(d => ['fraud', 'problem'].includes(d)) ? { refresh_history: true } : {}),
        ...(waybillAllCitySend && fRawDatasets.includes('delivery_waybill') ? { waybill_all_city_send: true } : {}),
        ...(fRawDatasets.some(isMerchant) ? { merchant_by_city: true } : {}),
        ...(!fAbnormalOnly && !fRawDatasets.every(isMerchant) ? { exclude_separation: pScope.excludeSeparation } : {}),
      };
      const fPayloads = buildUnifiedSubmissionPayloads({
        selectedDatasets: platDatasets,
        availableGenerators: options?.generators || [],
        rawSelection: fRaw,
        rawMonthChunks: fChunks,
        isMultiBatchRawMonth: !fAbnormalOnly && fRawDatasets.length > 0 && fChunks.length > 1,
        cities: pScope.cities,
        start: fRaw.start,
        end: fRaw.end,
        today,
        excludeSeparation: pScope.excludeSeparation,
        selectedMonths: fMonths.length > 0 ? fMonths : undefined,
        isGeneratorFn: isGenerator,
      });
      allPayloads.push(...(fPayloads as CreateSelection[]));
    }
    return allPayloads;
  };

  const crossPlatformPayloads = platform ? buildCrossPlatformPayloads() : unifiedPayloads;
  const isUnifiedMultiBatchSubmit =
    !createAttempt.current &&
    !isPayoutMultiBatchSubmit &&
    crossPlatformPayloads.length > 1;
  const currentSelection: CreateSelection = (crossPlatformPayloads[0] as CreateSelection | undefined) || (unifiedPayloads[0] as CreateSelection | undefined) || rawSelection;
  const currentSelectionKey = selectionKey(currentSelection);
  const matchingRun = (isUnifiedMultiBatchSubmit || isPayoutMultiBatchSubmit || activePlatformCount > 1)
    ? undefined
    : (runs.find(run => !TERMINAL_STATUSES.has(run.status) && selectionKey(run) === currentSelectionKey)
      || (!followupDatasets.length && !datasets.some(isLanorange) && !merchantOnly ? runs.find(run => selectionKey(run) === currentSelectionKey && !!run.files?.length) : undefined));
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
    categorySelections.current[selectionScope] = datasets;
    if (preset.datasets.some(isGenerator) && platform && platform !== 'fengshen') {
      onSelectPlatform?.('fengshen');
    }
    onTaskKindChange?.('download');
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
    categorySelections.current[selectionScope] = datasets;
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
    setXiaoxiangAllDates(false);
    setStart(range.start);
    setEnd(range.end);
    setDuplicateApproval('');
  };
  const toggleXiaoxiangAllDates = (next: boolean) => {
    if (formLocked) return;
    setXiaoxiangAllDates(next);
    if (next) {
      setSelectedMonths([]);
      setStart(xiaoxiangFirst);
      setEnd(dailyDate);
    } else {
      const range = defaultMonthRange(true);
      const month = range.start.slice(0, 7);
      setSelectedMonths([month]);
      setLanorangeMonths([month]);
      setStart(range.start);
      setEnd(range.end);
    }
    setDuplicateApproval('');
    setRequestError('');
  };
  const syncMonthSelection = (nextMonths: string[]) => {
    const valid = [...new Set(nextMonths.filter(m => enabledMonthOptions.includes(m)))].sort();
    const fallback = valid.length > 0 ? valid : enabledMonthOptions.length > 0 ? [enabledMonthOptions[0]] : [];
    const chunks = buildMultiMonthRunRanges(fallback, shanghaiToday(), {
      capAtYesterday: xiaoxiangOnly,
      minDate: hasAttendance ? attendanceFirst : undefined,
      maxDate: hasAttendance ? attendanceLast : undefined,
      maxDaysPerRun: xiaoxiangDated ? 31 : undefined,
    });
    setXiaoxiangAllDates(false);
    setSelectedMonths(fallback);
    setLanorangeMonths(fallback);
    if (chunks.length > 0) {
      setStart(chunks[0].start);
      setEnd(chunks[chunks.length - 1].end);
    }
    setDuplicateApproval('');
  };
  const applyMonthSelection = (month: string) => {
    if (formLocked) return;
    if (!enabledMonthOptions.includes(month)) return;
    const nextMonths = activeSelectedMonths.length === 0
      ? [month]
      : toggleMultiMonthSelection(activeSelectedMonths, month, enabledMonthOptions);
    if (!nextMonths.length) return;
    syncMonthSelection(nextMonths);
  };

  // 用历史任务的城市/资料/日期预填新建表单
  const prefillFromRun = (run: DownloadRun) => {
    categorySelections.current[selectionScope] = datasets;
    const runMonths = Array.isArray(run.lanorange_months) && run.lanorange_months.length > 0
      ? run.lanorange_months
      : (!run.datasets.every(isLanorange) && DATE_PATTERN.test(run.start) && DATE_PATTERN.test(run.end)
          ? deriveSelectedMonthsFromRange(run.start, run.end, recentReportMonthCodes)
          : []);
    if (inferTaskKind(run.datasets) === 'generate') {
      const genId = run.datasets.find(isGenerator) || 'payment_binding';
      onSelectReport?.(genId);
      onTaskKindChange?.('generate');
    } else {
      onTaskKindChange?.('download');
      setDatasets(run.datasets.filter(id => !isGenerator(id) && (!options || options.datasets.some(item => item.id === id))));
    }
    setCities(run.cities.filter(city => city !== '全部城市' && (!options || options.cities.some(item => item.name === city && !item.disabled))));
    setBlueCities(run.lanorange_by_city && Array.isArray(run.cities) ? run.cities.filter(city => city !== '全部城市') : []);
    if (!run.datasets.every(isLanorange) && DATE_PATTERN.test(run.start) && DATE_PATTERN.test(run.end)) { setStart(run.start); setEnd(run.end); }
    setRefreshHistory(false);
    setWaybillAllCitySend(run.waybill_all_city_send === true);
    setLanorangeMonths(Array.isArray(run.lanorange_months) ? run.lanorange_months : []);
    setXiaoxiangAllDates(run.xiaoxiang_all_dates === true);
    setSelectedMonths(run.xiaoxiang_all_dates === true ? [] : runMonths);
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

    if (isPayoutMultiBatchSubmit) {
      creatingRef.current = true;
      setCreating(true);
      setRequestError('');
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission();
      try {
        const today = shanghaiToday();
        const createdRuns: DownloadRun[] = [];
        for (const datasetId of datasets.filter(isPayoutPlatform)) {
          const singlePayload: CreateSelection = {
            task_kind: 'download',
            cities: ['全部城市'],
            datasets: [datasetId],
            start: today,
            end: today,
          };
          const data = await getJson(`${API_ROOT}/runs`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...singlePayload, request_id: newRequestId() }),
          });
          if (!data.run?.id) throw new Error('部分发薪平台未取得下载任务，请刷新记录确认');
          createdRuns.push(data.run);
        }
        const lastRun = createdRuns[createdRuns.length - 1];
        setDuplicateApproval('');
        setRuns(previous => [...createdRuns.slice().reverse(), ...previous.filter(item => !createdRuns.some(c => c.id === item.id))]);
        selectedIdRef.current = lastRun.id;
        setSelectedId(lastRun.id);
        setSelectedRun(lastRun);
        setSubmittedTaskInfo({
          id: lastRun.id,
          name: `${createdRuns.flatMap(r => r.datasets).map(datasetLabel).join('、')}（共 ${createdRuns.length} 批）`,
        });
        void refreshRef.current();
      } catch (error) {
        setRequestError(error instanceof Error ? error.message : '部分发薪平台提交失败，请刷新记录查看后再重试');
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
      return;
    }

    if (isUnifiedMultiBatchSubmit) {
      creatingRef.current = true;
      setCreating(true);
      setRequestError('');
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission();
      try {
        const createdRuns: DownloadRun[] = [];
        for (const payload of crossPlatformPayloads) {
          const data = await getJson(`${API_ROOT}/runs`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...payload, request_id: newRequestId() }),
          });
          if (!data.run?.id) throw new Error('部分任务未取得执行回执，请刷新记录确认');
          createdRuns.push(data.run);
        }
        const lastRun = createdRuns[createdRuns.length - 1];
        setDuplicateApproval('');
        setRuns(previous => [...createdRuns.slice().reverse(), ...previous.filter(item => !createdRuns.some(c => c.id === item.id))]);
        selectedIdRef.current = lastRun.id;
        setSelectedId(lastRun.id);
        setSelectedRun(lastRun);
        setSubmittedTaskInfo({
          id: lastRun.id,
          name: `${[...new Set(createdRuns.flatMap(r => r.datasets))].map(datasetLabel).join('、')}（共 ${createdRuns.length} 批）`,
        });
        void refreshRef.current();
      } catch (error) {
        setRequestError(error instanceof Error ? error.message : '部分任务提交失败，请刷新记录查看后再重试');
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
      return;
    }

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

  const reportActiveMonths = selectedMonths.filter(month => recentReportMonthCodes.includes(month));
  const reportPayloads = activeReport
    ? buildGenerateBatchPayloads(
        [activeReport],
        cities,
        start,
        end,
        shanghaiToday(),
        {
          excludeSeparation,
          selectedMonths: reportActiveMonths.length > 0 ? reportActiveMonths : undefined,
          bindingPlatforms: effectiveBindingPlatforms,
        },
      )
    : [];
  const reportCanSubmit = Boolean(
    activeReport &&
    (activeReport.scope === 'all' || (cities.length > 0 && reportPayloads.length > 0 && validDates)),
  );
  const singleReportSelection = reportPayloads.length === 1 ? (reportPayloads[0] as CreateSelection) : undefined;
  const singleReportKey = singleReportSelection ? selectionKey(singleReportSelection) : '';
  const reportMatchingRun = singleReportSelection
    ? runs.find(run => !TERMINAL_STATUSES.has(run.status) && selectionKey(run) === singleReportKey)
      || runs.find(run => selectionKey(run) === singleReportKey && !!run.files?.length)
    : undefined;
  const reportCompletedMatch = Boolean(
    reportMatchingRun && TERMINAL_STATUSES.has(reportMatchingRun.status) && reportMatchingRun.files?.length,
  );

  const startReportGeneration = async () => {
    if (creatingRef.current || !options || !activeReport || (!createAttempt.current && !reportCanSubmit)) return;
    if (!createAttempt.current && reportMatchingRun && !TERMINAL_STATUSES.has(reportMatchingRun.status)) {
      selectRun(reportMatchingRun);
      return;
    }
    if (!createAttempt.current && reportCompletedMatch && duplicateApproval !== singleReportKey) {
      selectRun(reportMatchingRun!);
      return;
    }

    if (!createAttempt.current && reportPayloads.length > 1) {
      creatingRef.current = true;
      setCreating(true);
      setRequestError('');
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission();
      try {
        const createdRuns: DownloadRun[] = [];
        for (const payload of reportPayloads) {
          const data = await getJson(`${API_ROOT}/runs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...payload, request_id: newRequestId() }),
          });
          if (!data.run?.id) throw new Error('部分报表任务未取得执行回执，请刷新记录确认');
          createdRuns.push(data.run);
        }
        const lastRun = createdRuns[createdRuns.length - 1];
        setDuplicateApproval('');
        setRuns(previous => [...createdRuns.slice().reverse(), ...previous.filter(item => !createdRuns.some(c => c.id === item.id))]);
        setSubmittedTaskInfo({
          id: lastRun.id,
          name: `${activeReport.label}（共 ${createdRuns.length} 批）`,
        });
        selectRun(lastRun);
        void refreshRef.current();
      } catch (error) {
        setRequestError(error instanceof Error ? error.message : '专项报表提交失败，请刷新记录查看后再重试');
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
      return;
    }

    if (!singleReportSelection && !createAttempt.current) return;
    createAttempt.current = retainAttempt(createAttempt.current, singleReportSelection!);
    storeAttempt(createStorageKey, createAttempt.current);
    creatingRef.current = true;
    setCreating(true);
    setRequestError('');
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') void Notification.requestPermission();
    try {
      const data = await getJson(`${API_ROOT}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...createAttempt.current.payload, request_id: createAttempt.current.request_id }),
      });
      if (!data.run?.id) throw new Error('未取得报表任务，请刷新记录确认后再试');
      const run: DownloadRun = data.run;
      createAttempt.current = null;
      storeAttempt(createStorageKey, null);
      setUncertainCreate(false);
      setDuplicateApproval('');
      setRuns(previous => [run, ...previous.filter(item => item.id !== run.id)]);
      setSubmittedTaskInfo({ id: run.id, name: activeReport.label });
      selectRun(run);
      void refreshRef.current();
    } catch (error) {
      const rejected = error instanceof DownloadRequestError && [400, 401, 403, 404, 409, 415, 422].includes(error.status);
      if (rejected) {
        createAttempt.current = null;
        storeAttempt(createStorageKey, null);
      }
      setUncertainCreate(!rejected);
      setRequestError(rejected ? error.message : '报表请求结果尚未确认。请点击“确认原请求”，系统会沿用同一请求编号，不会盲目新建任务。');
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  };

  const retrySelected = async (only?: ItemSelection | ItemSelection[]) => {
    if (retryPendingRef.current || (!retryAttempt.current && !selectedRun)) return;
    const isOnlyArray = Array.isArray(only);
    const selected = selectedRun?.items?.filter(item => {
      if (isOnlyArray) {
        return only.some(target => itemKey(target) === itemKey(item)) && recoverable(item);
      }
      return (only ? itemKey(only) === itemKey(item) : retryKeys.includes(itemKey(item))) && recoverable(item);
    }) || [];
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
  const effectiveChunkCount = isMultiBatchMonthSubmit ? monthRunChunks.length : 1;
  const subitemCount = merchantOnly
    ? cities.length * datasets.length
    : payoutBoth
      ? 2
      : baizeOnly || benlaiOnly
        ? 1
        : xiaoxiangOnly
          ? datasets.length * effectiveChunkCount
          : blueOnly
            ? (datasets.filter(value => isLanorange(value) && value !== 'abnormal_riders').length * Math.max(1, blueCityScoped ? blueCities.length : 1)) + (hasAbnormalRiders ? 1 : 0)
            : abnormalRidersOnly
              ? 1
              : rawSelectedDatasets.filter(isLanorange).length +
                cities.length * (
                  periodDatasets.length * effectiveChunkCount +
                  followupDatasets.length * Math.max(1, monthPreview.length) +
                  rawSelectedDatasets.filter(value => SNAPSHOT_DATASETS.has(value)).length +
                  monthlyDatasets.length * Math.max(1, monthPreview.length)
                ) +
                (hasAbnormalRiders ? 1 : 0);
  const submitReady = !!uncertainCreate || canSubmit;
  const railSummary = buildExecutionRailSummary({
    datasetsCount: datasets.length,
    cities: payoutOnly || abnormalRidersOnly ? [] : blueOnly ? (hasAbnormalRiders ? [] : blueCities) : cities,
    start,
    end,
    selectedMonths: activeSelectedMonths,
    noCity,
    noDate,
    archiveOnly,
    xiaoxiangDated,
    xiaoxiangOnly,
    blueOnly,
    baizeOnly,
    benlaiOnly,
    payoutOnly,
    payoutBoth,
    abnormalRidersOnly,
    generatedCount: selectedGeneratorIds.length,
    rawCount: rawSelectedDatasets.length,
    merchantOnly,
    merchantSnapshotOnly,
    merchantDateValid,
    validDates,
    includeSeparation,
    excludeSeparation,
    subitemCount,
    submitReady,
  });

  /**
   * 预计任务量展示文案（US-1.2）：跨平台提交以批数计；其余走 `railSummary` 派生值；
   * 无有效选择时显示「—」（不显示 0）。
   */
  const estimateText = (() => {
    if (activePlatformCount > 1 && crossPlatformPayloads.length > 0) return `${crossPlatformPayloads.length} 批`;
    if (!railSummary.estimateValue) return '—';
    return `${railSummary.estimateValue} ${railSummary.estimateUnit}`.trim();
  })();

  /** 引导到 Step 02 城市区（跨平台时先切回风神平台再定位）。 */
  const goToCitiesStep = () => {
    if (platform && platform !== 'fengshen') {
      onSelectPlatform?.('fengshen');
      setTimeout(() => scrollToStep('cities'), 80);
      return;
    }
    scrollToStep('cities');
  };

  /**
   * 右栏缺项提示（架构 §4.3 改造点 10）：四个分支合并为**单一** `wbx-hint` 渲染，
   * 文案/样式只此一套，`run` 存在时整行可点击定位。
   */
  const railHint: {text: string; tone: 'warn'; title?: string; run?: () => void} | null = (() => {
    if (!submitReady && datasets.length === 0) {
      return {
        text: '请先在左侧勾选至少 1 项待采集资料',
        tone: 'warn',
        title: '点击定位至 Step 01 选择资料',
        run: () => scrollToStep('datasets'),
      };
    }
    if (!canSubmit && !uncertainCreate && !creating && fengshenMissingCities) {
      return {
        text: '请为风神数据选择至少 1 个城市 · 定位',
        tone: 'warn',
        title: '点击定位至风神数据 Step 02 城市选择',
        run: goToCitiesStep,
      };
    }
    if (!submitReady && railSummary.blockerHint) {
      const needsPeriod = !validDates;
      return {
        text: railSummary.blockerHint,
        tone: 'warn',
        title: needsPeriod ? '点击定位至 Step 02 账期配置' : '点击定位至 Step 02 城市选择',
        run: needsPeriod ? () => scrollToStep('period') : goToCitiesStep,
      };
    }
    return null;
  })();

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

  const [demoTaskActiveCount, setDemoTaskActiveCount] = useState<number>(() =>
    buildDemoTaskCenterRecords().filter(r =>
      ['queued', 'running', 'cancelling', 'preparing', 'stopping'].includes(r.status),
    ).length,
  );
  useEffect(() => {
    const onDemoActiveCount = (event: Event) => {
      const next = Number((event as CustomEvent)?.detail);
      if (Number.isFinite(next) && next >= 0) {
        setDemoTaskActiveCount(next);
      }
    };
    window.addEventListener('workbench:demo-active-count', onDemoActiveCount);
    return () => window.removeEventListener('workbench:demo-active-count', onDemoActiveCount);
  }, []);

  const liveRunningCount = runs.filter(run => !TERMINAL_STATUSES.has(run.status.toLowerCase())).length;
  const demoActiveForHeader = shouldUseDemoData({
    isLoggedIn: authSnapshot.anyLoggedIn,
    hasLiveData: runs.length > 0,
    demoHidden,
  });
  const runningCount = demoActiveForHeader ? demoTaskActiveCount : liveRunningCount;
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

      {invalidBaizeMix && <p role="alert" className="wb-notice">发薪平台资料仅支持独立下载，请清除其他资料选择。</p>}
      {invalidXiaoxiangMix && <p role="alert" className="wb-notice">灯塔资料仅支持独立下载，请清除其他资料选择。</p>}
      {requestError && <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"><AlertCircle size={17} className="shrink-0 mt-0.5" />{requestError}<button type="button" aria-label="关闭错误提示" className="ml-auto shrink-0" onClick={() => setRequestError('')}><XCircle size={16} /></button></div>}
      {pollError && <p role="status" className="text-xs text-amber-700">{pollError}。连接恢复后自动更新。</p>}
      {uncertainRetry && <div role="status" className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800"><p>上次失败项处理结果尚未确认，请先确认原请求。</p><button type="button" className={`${smallButton} mt-2`} disabled={retryPending} onClick={() => void retrySelected()}>{retryPending ? '正在确认…' : '重新确认原分项请求'}</button></div>}

      {runs.some(run => ['waiting_login', 'waiting_manual'].includes(run.phase || '')) && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800"><span>有任务正在等待短信验证，请打开验证窗口输入验证码。</span><button type="button" className={smallButton} onClick={() => { selectRun(runs.find(run => ['waiting_login', 'waiting_manual'].includes(run.phase || ''))!); window.dispatchEvent(new CustomEvent('workbench:fengshen-verification')); }}>输入验证码</button></div>}
      {uncertainCreate && view === 'history' && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800"><span>原下载请求仍待确认，请先完成确认。</span><button type="button" className={smallButton} onClick={() => setView('create')}>返回确认原请求</button></div>}

      {(() => {
        const stageMeta = getStageHeaderMeta(taskKind === 'generate' ? 'generate' : 'download', platform, view);
        const reportSubmitLabel = creating
          ? '提交中…'
          : uncertainCreate
            ? '确认原请求'
            : reportMatchingRun && !TERMINAL_STATUSES.has(reportMatchingRun.status)
              ? '查看进行中任务'
              : reportCompletedMatch && duplicateApproval !== singleReportKey
                ? '查看已有文件'
                : '生成报表';
        return (
          <>
            {view === 'create' && isGenerateMode && (
              optionsError && !options ? (
                <div role="alert" className={`${panel} flex flex-wrap items-center gap-3 p-5 text-sm text-rose-700`}>
                  <AlertCircle size={17} />
                  {optionsError}
                  <button
                    type="button"
                    className={smallButton}
                    onClick={() => optionsError.includes('请刷新工作台') || optionsError.includes('账号页面已更新') ? location.reload() : setOptionVersion(version => version + 1)}
                  >
                    重新加载
                  </button>
                </div>
              ) : !options ? (
                <p role="status" className={`${panel} flex items-center gap-2 p-6 text-sm text-slate-500`}>
                  <Loader2 size={16} className="animate-spin" />
                  正在加载专项报表配置…
                </p>
              ) : (
                <ReportBuilder
                  singleReportMode
                  reports={availableReports}
                  selectedIds={activeReport ? [activeReport.id] : []}
                  cities={options.cities}
                  selectedCities={cities}
                  onCities={nextCities => {
                    setCities(nextCities);
                    setDuplicateApproval('');
                  }}
                  start={start}
                  end={end}
                  today={shanghaiToday()}
                  onStart={value => {
                    setStart(value);
                    setDuplicateApproval('');
                  }}
                  onEnd={value => {
                    setEnd(value);
                    setDuplicateApproval('');
                  }}
                  selectedMonths={reportActiveMonths}
                  onSelectedMonths={months => {
                    setSelectedMonths(months);
                    setDuplicateApproval('');
                  }}
                  excludeSeparation={excludeSeparation}
                  onExcludeSeparation={value => {
                    setExcludeSeparation(value);
                    setDuplicateApproval('');
                  }}
                  locked={formLocked}
                  creating={creating}
                  disabled={!uncertainCreate && !reportCanSubmit}
                  submitLabel={reportSubmitLabel}
                  onSubmit={() => void startReportGeneration()}
                  uncertain={uncertainCreate}
                  duplicate={reportCompletedMatch}
                  recollect={duplicateApproval === singleReportKey}
                  onRecollect={checked => setDuplicateApproval(checked ? singleReportKey : '')}
                  refreshing={optionsLoading}
                  onRefreshCities={() => setOptionVersion(version => version + 1)}
                  bindingPlatforms={effectiveBindingPlatforms}
                  onBindingPlatformsChange={next => void updateBindingPlatforms(next)}
                  bindingPlatformsSaving={bindingPlatformsBusy}
                />
              )
            )}
            {view === 'create' && !isGenerateMode && <>
            <section className={`${panel} wb-task-form wb-download-workbench`} aria-label="新建下载配置">
          {optionsError && !options ? <div role="alert" className="flex flex-wrap items-center gap-3 p-5 text-sm text-rose-700"><AlertCircle size={17} />{optionsError}<button className={smallButton} onClick={() => optionsError.includes('请刷新工作台') || optionsError.includes('账号页面已更新') ? location.reload() : setOptionVersion(version => version + 1)}>重新加载</button></div>
            : !options ? <p role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" />正在加载下载选项…</p>
            : <>
              {optionsError && <p role="alert" className="wb-full-span flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 sm:px-6"><AlertCircle size={14} />城市清单刷新失败，仍显示上次结果：{optionsError}</p>}
              {/* @wbx:collection-main-start */}
              <div className="wb-download-main wbx-collection">
                {platform ? (
                  !hideNavigation && (
                    <div className="wbx-dc-tabs" role="tablist" aria-label="四大采集平台切换">
                      {DOWNLOAD_PLATFORMS.map(p => {
                        const isPlatActive = activePlatform === p.id;
                        const platSelectedCount = groupedByPlatform[p.id].length;
                        const PlatIcon =
                          p.id === 'fengshen'
                            ? Compass
                            : p.id === 'lanorange'
                              ? Layers
                              : p.id === 'payout'
                                ? UsersRound
                                : Radar;
                        return (
                          <button
                            key={p.id}
                            type="button"
                            role="tab"
                            aria-selected={isPlatActive}
                            disabled={formLocked}
                            onClick={() => onSelectPlatform?.(p.id)}
                            className={`wbx-dc-tab is-${p.id}${isPlatActive ? ' is-active' : ''}${platSelectedCount > 0 ? ' has-selection' : ''}`}
                          >
                            <PlatIcon size={14.5} className="wbx-dc-tab__icon" aria-hidden="true" />
                            <span className="wbx-dc-tab__name">{p.navLabel}</span>
                            {platSelectedCount > 0 && (
                              <span className="wbx-dc-tab__count tabular-nums" title={`该平台已选 ${platSelectedCount} 项`}>
                                {platSelectedCount}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )
                ) : (
                  <div className="wb-system-overview-bar mb-4" role="group" aria-label="四大系统数据源切换">
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
                        const isSelectableGroup = sys.key === 'fengshen' || sys.key === 'lanorange' || sys.key === 'baize' || sys.key === 'benlai' || sys.key === 'xiaoxiang';
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
                              onClick={() => setSystemFilter(prev => prev === sys.key ? 'all' : sys.key as 'fengshen' | 'lanorange' | 'baize' | 'benlai' | 'xiaoxiang')}
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
                  </div>
                )}

                {/* STEP 01: 选择资料 */}
                {platform === 'payout' ? (
                  <fieldset id="step-01-datasets" aria-labelledby="download-datasets-label" className={`wbx-card wbx-step transition-all duration-300 ${pulsingStep === 'datasets' ? 'wb-field-pulse-highlight' : ''}`}>
                    <div className="wb-step-card-header">
                      <div className="wb-step-badge">
                        <span className="wb-step-number">01</span>
                        {!platform && <span className="wb-sys-badge is-baize">发薪</span>}
                        <span id="download-datasets-label" className="wb-step-title">选择资料</span>
                        <span className="wb-step-count-pill tabular-nums">已选 {groupedByPlatform.payout.length} / 2 平台</span>
                      </div>
                      <div className="wb-city-preset-group" role="group" aria-label="发薪平台快捷选择">
                        <button
                          type="button"
                          disabled={formLocked}
                          onClick={() => setDatasets(prev => [...prev.filter(id => !isPayoutPlatform(id)), 'baize_employees', 'benlai_employees'])}
                          className={`wb-city-preset-btn ${payoutBoth ? 'is-active' : ''}`}
                        >
                          双平台全选
                        </button>
                        <button
                          type="button"
                          disabled={formLocked}
                          onClick={() => setDatasets(prev => [...prev.filter(id => !isPayoutPlatform(id)), 'baize_employees'])}
                          className={`wb-city-preset-btn ${baizeOnly ? 'is-active' : ''}`}
                        >
                          仅白泽商翼
                        </button>
                        <button
                          type="button"
                          disabled={formLocked}
                          onClick={() => setDatasets(prev => [...prev.filter(id => !isPayoutPlatform(id)), 'benlai_employees'])}
                          className={`wb-city-preset-btn ${benlaiOnly ? 'is-active' : ''}`}
                        >
                          仅本来人力
                        </button>
                      </div>
                    </div>

                    <div className="wb-payout-cards-grid" role="group" aria-label="发薪数据源卡片">
                      {([
                        {
                          datasetId: 'baize_employees',
                          authKey: 'baize',
                          title: '白泽商翼 · 员工原表',
                          systemName: '商翼系统',
                          scopeText: '全部授权站点（在职 + 离职全量）',
                          fieldsText: '工号、姓名、身份证号、所属站点、入离职日期与状态',
                          usageText: '独立归档员工原始总表，不参与兼职核算自动补齐',
                          Icon: UsersRound,
                        },
                        {
                          datasetId: 'benlai_employees',
                          authKey: 'benlai',
                          title: '本来人力 · 灵工档案',
                          systemName: '本来人力商户端',
                          scopeText: '全部授权城市与签约商户（实时读取）',
                          fieldsText: '姓名、证件号、手机号、签约城市与当前在签状态',
                          usageText: '用于核验发薪平台绑定关系及实时签约城市归属',
                          Icon: Building2,
                        },
                      ] as const).map(source => {
                        const selected = datasets.includes(source.datasetId);
                        const authRaw = payoutAuthStatuses[source.authKey] || {};
                        const authBadge = getPlatformCardBadge(authRaw);
                        return (
                          <div
                            key={source.datasetId}
                            role="checkbox"
                            aria-checked={selected}
                            tabIndex={formLocked ? -1 : 0}
                            onClick={() => {
                              if (!formLocked) {
                                setDatasets(values => toggleCrossPlatformDataset(values, source.datasetId));
                              }
                            }}
                            onKeyDown={event => {
                              if (!formLocked && (event.key === ' ' || event.key === 'Enter')) {
                                event.preventDefault();
                                setDatasets(values => toggleCrossPlatformDataset(values, source.datasetId));
                              }
                            }}
                            className={`wb-payout-source-card ${selected ? 'is-selected' : ''} ${formLocked ? 'is-disabled' : ''}`}
                          >
                            <div className="wb-payout-card-head">
                              <div className="wb-payout-card-title-wrap">
                                <span className={`wb-payout-check ${selected ? 'is-checked' : ''}`} aria-hidden="true">
                                  {selected ? '✓' : ''}
                                </span>
                                <div className="min-w-0">
                                  <h3 className="wb-payout-card-title">{source.title}</h3>
                                  <span className="wb-payout-card-sub">{source.systemName}</span>
                                </div>
                              </div>
                              <div className="wb-payout-card-auth">
                                <span className={`wb-status-badge is-${authBadge.tone}`}>
                                  <span className={`wb-dot ${authBadge.tone === 'ready' ? 'ready' : authBadge.tone === 'warn' ? 'offline' : authBadge.tone === 'busy' ? 'busy' : ''}`} />
                                  <span>{authBadge.label}</span>
                                </span>
                                <button
                                  type="button"
                                  className="wb-payout-auth-btn"
                                  onClick={event => {
                                    event.stopPropagation();
                                    window.dispatchEvent(new CustomEvent('workbench:connections'));
                                  }}
                                >
                                  管理登录
                                </button>
                              </div>
                            </div>

                            <dl className="wb-payout-spec-list">
                              <div className="wb-payout-spec-row">
                                <dt>采集范围</dt>
                                <dd>{source.scopeText}</dd>
                              </div>
                              <div className="wb-payout-spec-row">
                                <dt>导出字段</dt>
                                <dd>{source.fieldsText}</dd>
                              </div>
                              <div className="wb-payout-spec-row">
                                <dt>核算用途</dt>
                                <dd>{source.usageText}</dd>
                              </div>
                            </dl>
                          </div>
                        );
                      })}
                    </div>
                    <div className="wb-payout-scope-note" role="note">
                      <span className="wb-payout-scope-note__badge">全量实时快照</span>
                      <span>发薪数据源自动按全站全城实时直采并独立归档，无需额外配置处理城市或业务账期。</span>
                    </div>
                  </fieldset>
                ) : (
                  <fieldset id="step-01-datasets" aria-labelledby="download-datasets-label" className={`wbx-card wbx-step transition-all duration-300 ${pulsingStep === 'datasets' ? 'wb-field-pulse-highlight' : ''}`}>
                    {!platform && (
                      <div className="wb-step-card-header">
                        <div className="wb-step-badge">
                          <span className="wb-step-number">01</span>
                          <span id="download-datasets-label" className="wb-step-title">选择资料</span>
                          <span className="wb-step-count-pill">已选 {datasets.length}</span>
                        </div>
                      </div>
                    )}

                    {(['fengshen', 'lanorange', 'baize', 'benlai', 'xiaoxiang'] as const).filter(group => platform ? group === platform : systemFilter === 'all' || systemFilter === group).map(group => {
                      const filteredDatasets = visibleDatasets.filter(value =>
                        group === 'fengshen'
                          ? moduleAcceptsDataset(value.id, 'fengshen')
                          : !isGenerator(value.id) && datasetGroup(value.id) === group,
                      );
                      const displayedDatasets = group === 'fengshen'
                        ? (onlySelectedShown
                          ? filterFengshenDatasetsByCategory(filteredDatasets, fengshenCategory).filter(item => datasets.includes(item.id))
                          : filterFengshenDatasetsByCategory(filteredDatasets, fengshenCategory))
                        : filteredDatasets;
                      const ids = displayedDatasets.map(value => value.id);
                      const allSelected = ids.length > 0 && ids.every(id => datasets.includes(id));
                      const selectedCount = datasets.filter(id =>
                        group === 'fengshen' ? moduleAcceptsDataset(id, 'fengshen') : datasetGroup(id) === group,
                      ).length;
                      return (
                        <div key={group} className="wb-source-group">
                          <div className={platform ? 'wb-step-card-header' : 'wb-source-header'}>
                            <div className={platform ? 'wb-step-badge' : 'wb-source-title'}>
                              {platform && <span className="wb-step-number">01</span>}
                              {!platform && (
                                <span className={`wb-sys-badge is-${group}`}>{group === 'baize' ? '商翼' : group === 'benlai' ? '本来人力' : group === 'xiaoxiang' ? '灯塔' : group === 'lanorange' ? '蓝橙' : '风神'}</span>
                              )}
                              <span id={platform ? 'download-datasets-label' : undefined} className={platform ? 'wb-step-title' : ''}>
                                {platform
                                  ? '选择资料'
                                  : group === 'baize'
                                    ? '选择资料 · 商翼员工资料'
                                    : group === 'benlai'
                                      ? '选择资料 · 本来人力灵工资料'
                                      : group === 'xiaoxiang'
                                        ? '选择资料 · 灯塔资料'
                                        : group === 'lanorange'
                                          ? '选择资料 · 蓝橙资料'
                                          : '选择资料 · 风神资料'}
                              </span>
                              <span className="wb-step-count-pill tabular-nums">已选 {selectedCount} / {filteredDatasets.length}</span>
                            </div>
                            {group !== 'baize' && group !== 'benlai' && (
                              <div className="wbx-step-header-actions">
                                {group === 'fengshen' && (!platform || platform === 'fengshen') && (
                                  <div className="wb-category-scenario-actions" role="toolbar" aria-label="常用业务场景推荐包">
                                    {scenarioPresets.map(bundle => {
                                      const allBundleSelected = bundle.datasets.length > 0 && bundle.datasets.every(id => datasets.includes(id));
                                      return (
                                        <div key={bundle.id} className="wb-preset-pill-item">
                                          <button
                                            type="button"
                                            className={`wb-scenario-btn ${allBundleSelected ? 'is-active' : ''}`}
                                            disabled={formLocked}
                                            title={bundle.title || bundle.label}
                                            onClick={() => {
                                              if (allBundleSelected) {
                                                setDatasets(datasets.filter(id => !bundle.datasets.includes(id)));
                                              } else {
                                                setDatasets(
                                                  platform
                                                    ? [...new Set([...datasets, ...bundle.datasets])]
                                                    : [...new Set([...datasets.filter(id => !isPayoutPlatform(id) && !isXiaoxiang(id)), ...bundle.datasets])],
                                                );
                                              }
                                            }}
                                          >
                                            <span>{bundle.label}</span>
                                          </button>
                                          <div className="wb-preset-actions">
                                            <button
                                              type="button"
                                              className="wb-preset-edit-btn"
                                              title={`修改场景包「${bundle.label}」`}
                                              onClick={e => {
                                                e.stopPropagation();
                                                setPresetModal({
                                                  mode: 'edit',
                                                  type: 'scenario',
                                                  id: bundle.id,
                                                  label: bundle.label,
                                                  datasets: [...bundle.datasets],
                                                  syncWithCurrentSelection: false,
                                                });
                                              }}
                                            >
                                              <Pencil size={11} />
                                            </button>
                                            <button
                                              type="button"
                                              className="wb-preset-remove-btn"
                                              title={`删除场景包「${bundle.label}」`}
                                              onClick={e => {
                                                e.stopPropagation();
                                                saveScenarioPresetsToStorage(scenarioPresets.filter(s => s.id !== bundle.id));
                                              }}
                                            >
                                              <X size={11} />
                                            </button>
                                          </div>
                                        </div>
                                      );
                                    })}
                                    <button
                                      type="button"
                                      className="wb-scenario-btn wbx-preset-trigger"
                                      disabled={formLocked || !activeDatasets.length}
                                      title={activeDatasets.length ? `将当前已勾选的 ${activeDatasets.length} 类资料保存为常用场景包` : '请先勾选资料再保存为新场景包'}
                                      onClick={() => {
                                        setPresetModal({
                                          mode: 'create',
                                          type: 'scenario',
                                          label: '',
                                          datasets: [...activeDatasets],
                                        });
                                      }}
                                    >
                                      <Plus size={12} />
                                      <span>存为场景包</span>
                                    </button>
                                  </div>
                                )}
                                <button
                                  type="button"
                                  disabled={formLocked || !ids.length}
                                  className="wb-city-preset-btn"
                                  onClick={() => {
                                    setDatasets(
                                      allSelected
                                        ? datasets.filter(id => !ids.includes(id))
                                        : platform
                                          ? [...new Set([...datasets, ...ids])]
                                          : group === 'xiaoxiang'
                                            ? ids
                                            : [...new Set([...datasets.filter(id => !isPayoutPlatform(id) && !isXiaoxiang(id)), ...ids])],
                                    );
                                    if (!allSelected && ids.includes('attendance_detail')) {
                                      if (end > attendanceLast) setEnd(attendanceLast);
                                      if (start > attendanceLast) setStart(attendanceLast);
                                      if (start < attendanceFirst) setStart(attendanceFirst);
                                    }
                                  }}
                                >
                                  {group === 'fengshen' ? (allSelected ? '清空所显资料' : '全选所显资料') : (allSelected ? '清空本组' : '全选本组')}
                                </button>
                              </div>
                            )}
                          </div>
                          {group === 'fengshen' && (
                            <div className="wbx-dc-catbar" role="tablist" aria-label="风神资料分类筛选">
                              {FENGSHEN_DATASET_CATEGORIES.map(cat => {
                                const catCount = countFengshenDatasetsByCategory(filteredDatasets, cat.id);
                                const active = fengshenCategory === cat.id;
                                return (
                                  <button
                                    key={cat.id}
                                    type="button"
                                    role="tab"
                                    aria-selected={active}
                                    disabled={formLocked}
                                    onClick={() => setFengshenCategory(cat.id)}
                                    className={`wbx-dc-cat${active ? ' is-active' : ''}`}
                                  >
                                    <span>{cat.label}</span>
                                    <span className="wbx-dc-cat__count tabular-nums">{catCount}</span>
                                  </button>
                                );
                              })}
                              {(datasets.length > 0 || onlySelectedShown) && (
                                <button
                                  type="button"
                                  aria-pressed={onlySelectedShown}
                                  disabled={formLocked}
                                  title={onlySelectedShown ? '点击关闭「只看已选」恢复显示全部资料' : '点击只显示已勾选的资料'}
                                  onClick={() => setOnlySelectedShown(value => !value)}
                                  className={`wbx-dc-cat wbx-dc-cat--selected${onlySelectedShown ? ' is-active' : ''}`}
                                >
                                  <span>{onlySelectedShown ? '只看已选 ×' : '只看已选'}</span>
                                  <span className="wbx-dc-cat__count tabular-nums">{datasets.length}</span>
                                </button>
                              )}
                            </div>
                          )}
                          {(() => {
                            const renderDatasetCard = (dataset: { id: string; label: string }) => {
                              const selected = datasets.includes(dataset.id);
                              const cardMeta = getDatasetCardMeta(dataset.id, dataset.label);
                              const showExceptionTag = Boolean(cardMeta.scopeTag);
                              const descText =
                                group === 'baize'
                                  ? '含员工工号、姓名、身份证号、所属站点、入离职日期及当前在职状态，导出全站原始档案并独立归档'
                                  : group === 'benlai'
                                    ? '含姓名、证件号、手机号、城市与签约状态；导出全站原始档案，签约城市在每次任务开始时实时读取'
                                    : cardMeta.desc;
                              const handleToggle = () => {
                                setDatasets(values =>
                                  platform ? toggleCrossPlatformDataset(values, dataset.id) : toggleDownloadDataset(values, dataset.id),
                                );
                                if (dataset.id === 'attendance_detail') {
                                  if (end > attendanceLast) setEnd(attendanceLast);
                                  if (start > attendanceLast) setStart(attendanceLast);
                                  if (start < attendanceFirst) setStart(attendanceFirst);
                                }
                              };

                              return (
                                <label
                                  key={dataset.id}
                                  title={`${cardMeta.title}：${descText}`}
                                  className={`wbx-dc-card is-tone-${cardMeta.tone}${selected ? ' is-selected' : ''}${formLocked ? ' is-disabled' : ''}`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={selected}
                                    disabled={formLocked}
                                    onChange={handleToggle}
                                    className="wbx-dc-card__checkbox"
                                  />
                                  <div className="wbx-dc-card__body">
                                    <div className="wbx-dc-card__head">
                                      <span className="wbx-dc-card__title">{cardMeta.title}</span>
                                      {showExceptionTag && (
                                        <span className={`wbx-dc-card__scope is-${cardMeta.tone}`}>
                                          {cardMeta.scopeTag}
                                        </span>
                                      )}
                                    </div>
                                    <p className="wbx-dc-card__desc" title={descText}>{descText}</p>
                                  </div>
                                </label>
                              );
                            };

                            if (group === 'xiaoxiang') {
                              const datedItems = displayedDatasets.filter(item => !isRiderArchive(item.id));
                              const snapshotItems = displayedDatasets.filter(item => isRiderArchive(item.id));
                              if (datedItems.length > 0 && snapshotItems.length > 0) {
                                return (
                                  <div className="wbx-dc-subgroups">
                                    <div className="wbx-dc-subgroup">
                                      <div className="wbx-dc-subgroup__head">
                                        <span>按日期区间采集</span>
                                        <small className="tabular-nums">{datedItems.length} 项 · 按下方所选日期区间合并</small>
                                      </div>
                                      <div className="wbx-dc-grid is-two-col">
                                        {datedItems.map(renderDatasetCard)}
                                      </div>
                                    </div>
                                    <div className="wbx-dc-subgroup">
                                      <div className="wbx-dc-subgroup__head">
                                        <span>全城实时快照</span>
                                        <small className="tabular-nums">{snapshotItems.length} 项 · 自动读取当前最新全站档案（不限日期）</small>
                                      </div>
                                      <div className="wbx-dc-grid is-single-wide">
                                        {snapshotItems.map(renderDatasetCard)}
                                      </div>
                                    </div>
                                  </div>
                                );
                              }
                            }

                            return (
                              <div
                                className={
                                  group === 'baize' || group === 'benlai'
                                    ? 'wb-baize-single-grid gap-2.5'
                                    : `wbx-dc-grid${group === 'lanorange' || group === 'xiaoxiang' ? ' is-two-col' : ''}`
                                }
                              >
                                {displayedDatasets.length === 0 && onlySelectedShown && (
                                  <div className="col-span-full flex items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50/70 px-3.5 py-2.5 text-xs text-slate-700">
                                    <span>当前分类下没有已勾选的资料。</span>
                                    <button
                                      type="button"
                                      className="wbx-btn wbx-btn--secondary wbx-btn--sm"
                                      onClick={() => setOnlySelectedShown(false)}
                                    >
                                      <X size={12} />
                                      <span>关闭「只看已选」恢复全览</span>
                                    </button>
                                  </div>
                                )}

                                {displayedDatasets.map(renderDatasetCard)}
                              </div>
                            );
                          })()}
                        </div>
                      );
                    })}
                  </fieldset>
                )}

                {/* STEP 02: 动态范围与账期配置（发薪平台全量实时快照，无需多余 Step 02 空卡） */}
                {platform === 'payout' ? null : !dynamicScopeReq.needsCity && !dynamicScopeReq.needsDate ? (
                  <section className="wbx-card wbx-step" aria-label="动态范围与账期配置">
                    <div className="wb-step-card-header">
                      <div className="wb-step-badge">
                        <span className="wb-step-number">02</span>
                        <span className="wb-step-title">范围与账期配置</span>
                        {dynamicScopeReq.autoScopeBadge && (
                          <span className="wb-step-count-pill">{dynamicScopeReq.autoScopeBadge}</span>
                        )}
                      </div>
                    </div>
                    <div className="wb-baize-inline-banner" role="status">
                      <div className="wb-baize-banner-pill">
                        <span className="wb-city-check-box shrink-0" aria-hidden="true">
                          {dynamicScopeReq.hasSelection ? '✓' : 'i'}
                        </span>
                        <span className="wb-baize-banner-title">
                          {dynamicScopeReq.autoScopeBadge || '智能范围适配'}
                        </span>
                      </div>
                      <span className="wb-baize-banner-desc">
                        {dynamicScopeReq.autoScopeDesc}
                      </span>
                    </div>
                  </section>
                ) : (
                  <>
                    {/* @wbx:steps2-start 02 组：城市 + 账期同排（≥1280 两列） */}
                    <div className={`wbx-steps2${dynamicScopeReq.needsCity && dynamicScopeReq.needsDate ? ' is-pair' : ''}`}>
                    {dynamicScopeReq.needsCity && (
                      <fieldset id="step-01-cities" aria-labelledby="download-cities-label" className={`wbx-card wbx-step transition-all duration-300 ${pulsingStep === 'cities' ? 'wb-field-pulse-highlight' : ''}`}>
                        <div className="wb-step-card-header">
                          <div className="wb-step-badge">
                            <span className="wb-step-number">02</span>
                            <span id="download-cities-label" className="wb-step-title">处理城市与站点</span>
                            {blueOnly ? (
                              <span className="wb-step-count-pill tabular-nums">
                                {blueCities.length > 0
                                  ? `已选 ${blueCities.length} / ${LANORANGE_CITIES.length}`
                                  : `默认全部城市（已选 0 / ${LANORANGE_CITIES.length}）`}
                              </span>
                            ) : (
                              <>
                                <span className="wb-step-count-pill tabular-nums">
                                  {xiaoxiangOnly && cities.length === 0
                                    ? `默认账号全量（已选 0 / ${selectableCities.length}）`
                                    : `已选 ${cities.length} / ${selectableCities.length}`}
                                </span>
                                {optionsLoading && <span className="text-xs text-sky-600 flex items-center gap-1"><Loader2 size={12} className="animate-spin" />同步中</span>}
                              </>
                            )}
                          </div>

                          <div className="wb-inline-city-toolbar flex-wrap">
                            {blueOnly ? (
                              <>
                                <button
                                  type="button"
                                  className="wb-city-preset-btn"
                                  disabled={formLocked}
                                  onClick={() => setBlueCities(blueCities.length === LANORANGE_CITIES.length ? [] : [...LANORANGE_CITIES])}
                                >
                                  {blueCities.length === LANORANGE_CITIES.length ? '清空城市' : '全选城市'}
                                </button>
                                    <span className="wbx-toolbar-sep" aria-hidden="true" />
                                {regionPresets.map(preset => {
                                  const matched = LANORANGE_CITIES.filter(city => preset.cities.includes(city));
                                  if (!matched.length) return null;
                                  const isActive = matched.length > 0 && matched.every(c => blueCities.includes(c));
                                  return (
                                    <div key={preset.id} className="wb-preset-pill-item">
                                      <button
                                        type="button"
                                        className={`wb-city-preset-btn ${isActive ? 'is-active' : ''}`}
                                        disabled={formLocked}
                                        title={`快捷勾选：${matched.join('、')}`}
                                        onClick={() => {
                                          if (isActive) {
                                            setBlueCities(blueCities.filter(c => !matched.includes(c)));
                                          } else {
                                            setBlueCities([...new Set([...blueCities, ...matched])]);
                                          }
                                        }}
                                      >
                                        {preset.label}
                                      </button>
                                      <div className="wb-preset-actions">
                                        <button
                                          type="button"
                                          className="wb-preset-edit-btn"
                                          title={`修改预设「${preset.label}」`}
                                          onClick={e => {
                                            e.stopPropagation();
                                            setPresetModal({
                                              mode: 'edit',
                                              type: 'region',
                                              id: preset.id,
                                              label: preset.label,
                                              cities: [...preset.cities],
                                              syncWithCurrentSelection: false,
                                            });
                                          }}
                                        >
                                          <Pencil size={11} />
                                        </button>
                                        <button
                                          type="button"
                                          className="wb-preset-remove-btn"
                                          title={`删除预设「${preset.label}」`}
                                          onClick={e => {
                                            e.stopPropagation();
                                            saveRegionPresetsToStorage(regionPresets.filter(r => r.id !== preset.id));
                                          }}
                                        >
                                          <X size={11} />
                                        </button>
                                      </div>
                                    </div>
                                  );
                                })}
                                <button
                                  type="button"
                                  className="wb-city-preset-btn wbx-preset-trigger"
                                  disabled={formLocked || !blueCities.length}
                                  title={blueCities.length ? `将当前已勾选的 ${blueCities.length} 个城市保存为新片区预设` : '请先勾选城市再保存为新预设'}
                                  onClick={() => {
                                    setPresetModal({
                                      mode: 'create',
                                      type: 'region',
                                      label: '',
                                      cities: [...blueCities],
                                    });
                                  }}
                                >
                                  <Plus size={13} />
                                  <span>存为预设</span>
                                </button>
                                {blueCities.length > 0 && blueCities.length < LANORANGE_CITIES.length && (
                                  <button
                                    type="button"
                                    className="wb-city-preset-btn"
                                    disabled={formLocked}
                                    onClick={() => setBlueCities([])}
                                  >
                                    清空城市
                                  </button>
                                )}
                              </>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  className="wb-city-preset-btn"
                                  disabled={formLocked || !selectableCities.length}
                                  onClick={() => setCities(cities.length === selectableCities.length ? [] : selectableCities.map(c => c.name))}
                                >
                                  {cities.length === selectableCities.length && cities.length ? '清空城市' : '全选城市'}
                                </button>
                                    <span className="wbx-toolbar-sep" aria-hidden="true" />
                                {regionPresets.map(preset => {
                                    const matched = selectableCities.filter(c =>
                                      preset.cities.some(pc => c.name.includes(pc) || pc.includes(c.name.replace(/市$/, ''))),
                                    );
                                    if (!matched.length) return null;
                                    const matchedNames = matched.map(c => c.name);
                                    const isActive = matchedNames.length > 0 && matchedNames.every(name => cities.includes(name));
                                    return (
                                      <div key={preset.id} className="wb-preset-pill-item">
                                        <button
                                          type="button"
                                          className={`wb-city-preset-btn ${isActive ? 'is-active' : ''}`}
                                          disabled={formLocked}
                                          title={`快捷勾选：${matchedNames.join('、')}`}
                                          onClick={() => {
                                            if (isActive) {
                                              setCities(cities.filter(name => !matchedNames.includes(name)));
                                            } else {
                                              setCities([...new Set([...cities, ...matchedNames])]);
                                            }
                                          }}
                                        >
                                          {preset.label}
                                        </button>
                                        <div className="wb-preset-actions">
                                          <button
                                            type="button"
                                            className="wb-preset-edit-btn"
                                            title={`修改预设「${preset.label}」`}
                                            onClick={e => {
                                              e.stopPropagation();
                                              setPresetModal({
                                                mode: 'edit',
                                                type: 'region',
                                                id: preset.id,
                                                label: preset.label,
                                                cities: [...preset.cities],
                                                syncWithCurrentSelection: false,
                                              });
                                            }}
                                          >
                                            <Pencil size={11} />
                                          </button>
                                          <button
                                            type="button"
                                            className="wb-preset-remove-btn"
                                            title={`删除预设「${preset.label}」`}
                                            onClick={e => {
                                              e.stopPropagation();
                                              saveRegionPresetsToStorage(regionPresets.filter(r => r.id !== preset.id));
                                            }}
                                          >
                                            <X size={11} />
                                          </button>
                                        </div>
                                      </div>
                                    );
                                  })}
                                <button
                                  type="button"
                                  className="wb-city-preset-btn wbx-preset-trigger"
                                  disabled={formLocked || !cities.length}
                                  title={cities.length ? `将当前已勾选的 ${cities.length} 个城市保存为新片区预设` : '请先勾选城市再保存为新片区预设'}
                                  onClick={() => {
                                    setPresetModal({
                                      mode: 'create',
                                      type: 'region',
                                      label: '',
                                      cities: [...cities],
                                    });
                                  }}
                                >
                                  <Plus size={13} />
                                  <span>存为预设</span>
                                </button>
                                {cities.length > 0 && cities.length < selectableCities.length && (
                                  <button
                                    type="button"
                                    className="wb-city-preset-btn"
                                    disabled={formLocked}
                                    onClick={() => setCities([])}
                                  >
                                    清空城市
                                  </button>
                                )}
                                    <span className="wbx-toolbar-sep" aria-hidden="true" />
                                {(!platform || platform === 'fengshen' || platform === 'xiaoxiang') && (
                                  <button
                                    type="button"
                                    className="wb-city-preset-btn"
                                    disabled={formLocked || stationDirectory.data?.status === 'loading'}
                                    onClick={stationDirectory.refresh}
                                    title="从平台重新读取城市下属站点目录"
                                  >
                                    {stationDirectory.data?.status === 'loading' ? '站点同步中…' : '刷新站点数'}
                                  </button>
                                )}
                                {(!platform || platform === 'fengshen') && (
                                  <button
                                    type="button"
                                    className="wb-city-preset-btn wbx-snapshot-btn"
                                    disabled={formLocked || !selectableCities.length}
                                    title="全选城市、仅勾选骑手信息、日期设为今天，一次导出全部城市当前骑手信息快照（不会复用历史数据）。"
                                    onClick={() => {
                                      setCities(selectableCities.map(c => c.name));
                                      setDatasets(prev => [...prev.filter(id => !moduleAcceptsDataset(id, 'fengshen')), 'rider_info']);
                                      setSelectedMonths([]);
                                      setStart(shanghaiToday());
                                      setEnd(shanghaiToday());
                                      if (!platform) setSystemFilter('fengshen');
                                    }}
                                  >
                                    全城快照
                                  </button>
                                )}
                              </>
                            )}
                          </div>
                        </div>

                        {blueOnly ? (
                          <div className="wb-inline-city-grid" role="group" aria-label="处理城市列表">
                            {LANORANGE_CITIES.map(city => {
                              const selected = blueCities.includes(city);
                              return (
                                <button
                                  key={city}
                                  type="button"
                                  disabled={formLocked}
                                  aria-pressed={selected}
                                  onClick={() => toggle(city, blueCities, setBlueCities)}
                                  className={`wb-inline-city-chip ${selected ? 'is-selected' : ''} ${formLocked ? 'is-disabled' : ''}`}
                                >
                                  <span className="wb-city-check-box" aria-hidden="true">
                                    {selected && '✓'}
                                  </span>
                                  <span className="wb-city-chip-name">{city}</span>
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <>
                            <div className="wb-inline-city-grid" role="group" aria-label="处理城市列表">
                              {displayedCities.map(city => {
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
                                    <span className="wb-city-status">
                                      {city.disabled ? (
                                        <span className="wb-city-disabled-badge">{city.note || '下架'}</span>
                                      ) : (
                                        <CityStationCount directory={stationDirectory.data} city={platform === 'xiaoxiang' ? city.name : city.id} />
                                      )}
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                            {xiaoxiangOnly && (
                              <div className="wb-city-count-note">
                                <small>灯塔资料按当前登录账号及已授权站点全量导出；城市选择仅用于核对真实城市与站点范围，不改变导出范围。</small>
                              </div>
                            )}
                            {hasAbnormalRiders && !abnormalRidersOnly && (
                              <div className="wb-city-count-note">
                                <small>同时包含「异常名单」，提交时该报表将自动按全部授权城市全量生成。</small>
                              </div>
                            )}
                            {!selectableCities.length && (
                              <p className="wb-notice mt-3">暂无可下载城市，请检查{platform === 'xiaoxiang' ? '灯塔' : '风神'}权限或网络连接。</p>
                            )}
                            {(stationDirectory.error || stationDirectory.data?.message) && (
                              <div className="wb-city-count-note">
                                <small className="wb-error">{stationDirectory.error || stationDirectory.data?.message}</small>
                              </div>
                            )}
                          </>
                        )}

                        {dynamicScopeReq.needsSeparationRule && (
                          <div className="wb-station-scope-bar" role="group" aria-label="站点范围规则">
                            <span className="wb-station-scope-label">站点范围：</span>
                            <div className="wb-station-radio-group">
                              <button
                                type="button"
                                disabled={formLocked}
                                aria-pressed={excludeSeparation}
                                onClick={() => setExcludeSeparation(true)}
                                className={`wb-station-radio-btn ${excludeSeparation ? 'is-active' : ''}`}
                              >
                                <span className="wb-radio-dot" aria-hidden="true" />
                                <span>排除取分离站点</span>
                              </button>
                              <button
                                type="button"
                                disabled={formLocked}
                                aria-pressed={!excludeSeparation}
                                onClick={() => setExcludeSeparation(false)}
                                className={`wb-station-radio-btn ${!excludeSeparation ? 'is-active' : ''}`}
                              >
                                <span className="wb-radio-dot" aria-hidden="true" />
                                <span>全部站点（含取分离）</span>
                              </button>
                            </div>
                            <label className="sr-only">
                              <input
                                type="checkbox"
                                aria-label="排除取分离站点"
                                checked={excludeSeparation}
                                disabled={formLocked}
                                onChange={event => setExcludeSeparation(event.target.checked)}
                              />
                              <span>排除取分离站点</span>
                            </label>
                          </div>
                        )}

                        {!dynamicScopeReq.needsDate && dynamicScopeReq.autoScopeBadge && (
                          <div className="wb-baize-inline-banner mt-3" role="status">
                            <div className="wb-baize-banner-pill">
                              <span className="wb-city-check-box shrink-0" aria-hidden="true">✓</span>
                              <span className="wb-baize-banner-title">{dynamicScopeReq.autoScopeBadge}</span>
                            </div>
                            <span className="wb-baize-banner-desc">{dynamicScopeReq.autoScopeDesc}</span>
                          </div>
                        )}
                      </fieldset>
                    )}

                    {dynamicScopeReq.needsDate && (
                      <fieldset id="step-02-period" aria-labelledby="download-dates-label" className={`wbx-card wbx-step transition-all duration-300 ${pulsingStep === 'period' ? 'wb-field-pulse-highlight' : ''}`}>
                        <legend className="sr-only">下载日期</legend>
                        {(() => {
                          const isCustomDateRange = activeSelectedMonths.length === 0 && validDates;
                          const allMonthsSelected = enabledMonthOptions.length > 0 && enabledMonthOptions.every(m => activeSelectedMonths.includes(m));
                          return (
                            <>
                              <div className="wb-step-card-header">
                                <div className="wb-step-badge">
                                  <span className="wb-step-number">{dynamicScopeReq.needsCity ? '03' : '02'}</span>
                                  <p id="download-dates-label" className="wb-step-title m-0">
                                    处理月份与账期
                                  </p>
                                  {xiaoxiangAllDatesActive ? (
                                    <span className="wb-step-count-pill tabular-nums">
                                      不限日期（近12个月）
                                    </span>
                                  ) : activeSelectedMonths.length > 1 ? (
                                    <span className="wb-step-count-pill tabular-nums">
                                      已选 {activeSelectedMonths.length} 个月（{activeSelectedMonths.join('、')}）
                                    </span>
                                  ) : activeSelectedMonths.length === 1 ? (
                                    <span className="wb-step-count-pill tabular-nums">
                                      已选 {activeSelectedMonths[0]}
                                    </span>
                                  ) : validDates ? (
                                    <span className="wb-step-count-pill tabular-nums">
                                      自定义区间（{start} ~ {end.slice(5)}）
                                    </span>
                                  ) : null}
                                </div>
                                <div className="wb-city-preset-group">
                                  {xiaoxiangDated && (
                                    <label className="flex items-center gap-1.5 cursor-pointer text-xs text-slate-600">
                                      <input
                                        type="checkbox"
                                        checked={xiaoxiangAllDatesActive}
                                        disabled={formLocked}
                                        onChange={event => toggleXiaoxiangAllDates(event.target.checked)}
                                        className="accent-sky-700 h-3.5 w-3.5 rounded border-slate-300"
                                      />
                                      <span>不限日期（近12个月）</span>
                                    </label>
                                  )}
                                  {!xiaoxiangAllDatesActive && enabledMonthOptions.length > 1 && (
                                    <button
                                      type="button"
                                      className={`wb-city-preset-btn ${allMonthsSelected ? 'is-active' : ''}`}
                                      disabled={formLocked}
                                      onClick={() => syncMonthSelection(allMonthsSelected ? [enabledMonthOptions[0]] : [...enabledMonthOptions])}
                                    >
                                      {allMonthsSelected ? '仅选最新月' : `全选近${enabledMonthOptions.length}月`}
                                    </button>
                                  )}
                                </div>
                              </div>
                              {!blueOnly && !xiaoxiangAllDatesActive && (
                                <div className="wbx-period-rangebar">
                                  <span className="wbx-period-rangebar__label">自定义区间</span>
                                  <WorkbenchDatePicker
                                    mode="range"
                                    compact
                                    align="right"
                                    prefixLabel="按日期范围"
                                    activeHighlight={isCustomDateRange}
                                    ariaLabel="按日期范围筛选"
                                    placeholder="选择起止日期"
                                    value={start}
                                    rangeStart={start}
                                    rangeEnd={end}
                                    min={hasAttendance ? attendanceFirst : xiaoxiangOnly ? xiaoxiangFirst : undefined}
                                    max={hasAttendance ? attendanceLast : xiaoxiangOnly ? dailyDate : shanghaiToday()}
                                    today={shanghaiToday()}
                                    disabled={formLocked}
                                    onChange={nextDate => {
                                      setXiaoxiangAllDates(false);
                                      setSelectedMonths([]);
                                      setStart(nextDate);
                                      setEnd(nextDate);
                                      setLanorangeMonths([nextDate.slice(0, 7)]);
                                      setDuplicateApproval('');
                                    }}
                                    onRangeChange={(nextStart, nextEnd) => {
                                      setXiaoxiangAllDates(false);
                                      setSelectedMonths([]);
                                      setStart(nextStart);
                                      setEnd(nextEnd);
                                      setLanorangeMonths([nextStart.slice(0, 7)]);
                                      setDuplicateApproval('');
                                    }}
                                  />
                                </div>
                              )}
                            </>
                          );
                        })()}

                        {!xiaoxiangAllDatesActive && (
                          <div className="wb-month-grid-3" role="group" aria-label="处理月份列表（支持多选）">
                          {priceMonthOptions.map(month => {
                            const monthRange = computeMonthSelectionRange(month, shanghaiToday(), { capAtYesterday: xiaoxiangOnly });
                            const invalidSpan = monthRange.start > monthRange.end;
                            const monthDisabled = formLocked || invalidSpan || (hasAttendance && (monthRange.end < attendanceFirst || monthRange.start > attendanceLast));
                            const expectedStart = hasAttendance && monthRange.start < attendanceFirst ? attendanceFirst : monthRange.start;
                            const expectedEnd = hasAttendance && monthRange.end > attendanceLast ? attendanceLast : monthRange.end;
                            const selected = !monthDisabled && activeSelectedMonths.includes(month);
                            return (
                              <button
                                key={month}
                                type="button"
                                disabled={monthDisabled}
                                aria-pressed={selected}
                                title={invalidSpan && xiaoxiangOnly ? '灯塔资料只能选择昨天及更早的日期' : monthDisabled && hasAttendance ? '骑手出勤明细仅支持近90天且早于今天的日期' : `${expectedStart} 至 ${expectedEnd}（支持多选）`}
                                onClick={() => applyMonthSelection(month)}
                                className={`wb-month-card-3 tabular-nums ${selected ? 'is-selected' : ''} ${monthDisabled ? 'is-disabled' : ''}`}
                              >
                                <span className="wb-month-chip-left">
                                  <span className="wb-month-check-box" aria-hidden="true">
                                    {selected && '✓'}
                                  </span>
                                  <span className="wb-month-card-title">{month}</span>
                                </span>
                                <span className="wb-month-chip-range">
                                  {expectedStart.slice(5)} ~ {expectedEnd.slice(5)}
                                </span>
                              </button>
                            );
                          })}
                          </div>
                        )}
                        {xiaoxiangAllDatesActive && (
                          <div className="wb-baize-inline-banner mt-3" role="status">
                            <div className="wb-baize-banner-pill">
                              <span className="wb-city-check-box shrink-0" aria-hidden="true">✓</span>
                              <span className="wb-baize-banner-title">近12个月全量</span>
                            </div>
                            <span className="wb-baize-banner-desc">
                              {xiaoxiangFirst} 至 {dailyDate}，系统自动逐日抓取并合并，每类资料输出一个文件。
                            </span>
                          </div>
                        )}
                        {blueOnly && (
                          <p className="mt-2.5 text-xs leading-relaxed text-slate-500">
                            已选月份：{resolvedLanorangeMonths.join('、')}；勾选「价格档案」时按所选月份导出，其余人事表导出全量最新档案。
                          </p>
                        )}
                        {isMultiBatchMonthSubmit && (
                          <p className="mt-2.5 text-xs leading-relaxed text-sky-700">
                            {xiaoxiangDated
                              ? `已多选 ${activeSelectedMonths.length} 个月（灯塔单批上限 31 天），提交后将自动拆分为 ${monthRunChunks.length} 个下载任务依次执行。`
                              : `所选月份非连续区间，提交后将自动拆分为 ${monthRunChunks.length} 个下载任务（${monthRunChunks.map(c => c.months.join(' ~ ')).join('、')}）依次执行。`}
                          </p>
                        )}

                        {!validDates && <p role="alert" className="mt-2.5 text-xs text-rose-700">开始日期不能晚于结束日期，请选择有效日期。</p>}
                        {xiaoxiangOnly && !xiaoxiangAllDatesActive && activeSelectedMonths.length === 0 && validDates && !xiaoxiangDateValid && <p role="alert" className="mt-2.5 text-xs text-rose-700">灯塔资料只能选择昨天及更早的日期，且区间最长31天。</p>}
                        {monthPreview.length > 0 && <p className="mt-2.5 text-xs leading-relaxed text-sky-700">整月资料自动下载：{monthPreview.join('、')}。</p>}
                        {(activeDatasets.some(dataset => ['fraud', 'problem'].includes(dataset)) || activeDatasets.includes('delivery_waybill')) && (
                          <div className="wb-date-rule-bar">
                            {activeDatasets.some(dataset => ['fraud', 'problem'].includes(dataset)) && (
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
                            {activeDatasets.includes('delivery_waybill') && (
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
                            {activeDatasets.includes('delivery_waybill') && <span className="font-normal text-slate-400">运单数据按运单终态时间筛选（当日仅含已完成运单）</span>}
                          </div>
                        )}
                        {orderWindowWarning && <p role="alert" className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">欺诈单和问题单仅支持最近 {orderWindowDays} 天（{earliestOrder} 至 {shanghaiToday()}），请调整日期或取消这两类资料。</p>}
                      </fieldset>
                    )}
                    </div>
                    {/* @wbx:steps2-end */}
                  </>
                )}

                {platform === 'payout' && (() => {
                  const payoutRuns = runs.filter(run => run.datasets.some(isPayoutPlatform)).slice(0, 5);
                  if (payoutRuns.length === 0) return null;
                  return (
                    <section className="wbx-card wbx-step wb-payout-recent-card" aria-label="发薪平台最近采集记录">
                      <div className="wb-step-card-header">
                        <div className="wb-step-badge">
                          <History size={15} className="text-slate-500" />
                          <span className="wb-step-title">最近采集记录</span>
                          <span className="wb-step-count-pill tabular-nums">{payoutRuns.length} 条</span>
                        </div>
                        <button
                          type="button"
                          className="wb-city-preset-btn"
                          onClick={() => setView('history')}
                        >
                          <span>全部任务中心</span>
                          <ArrowUpRight size={13} />
                        </button>
                      </div>
                      <div className="wb-payout-recent-list">
                        {payoutRuns.map(run => {
                          const runStatus = statusInfo(run.status);
                          const readyFiles = run.files || [];
                          const firstFile = readyFiles[0];
                          const isActiveRun = !TERMINAL_STATUSES.has(run.status.toLowerCase());
                          return (
                            <div key={run.id} className="wb-payout-recent-row">
                              <div className="wb-payout-recent-main">
                                <span className="wb-payout-recent-name">
                                  {run.datasets.map(datasetLabel).join('、')}
                                </span>
                                <span className="wb-payout-recent-meta tabular-nums">
                                  {displayTime(run.created_at) || '刚刚'}
                                  {readyFiles.length > 0 ? ` · ${readyFiles.length} 份文件（${formatSize(readyFiles.reduce((s, f) => s + (f.bytes || 0), 0))}）` : ''}
                                </span>
                              </div>
                              <div className="wb-payout-recent-actions">
                                <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${runStatus.color}`}>
                                  {isActiveRun ? `${runStatus.label} ${Math.round(run.progress || 0)}%` : runStatus.label}
                                </span>
                                {readyFiles.length === 1 && firstFile ? (
                                  <button
                                    type="button"
                                    className="wb-city-preset-btn"
                                    onClick={() => {
                                      void downloadOutput(`${API_ROOT}/runs/${run.id}/files/${firstFile.id}`, workspaceId, firstFile.name, apiRef.current)
                                        .catch(err => setRequestError(err instanceof Error ? err.message : '文件领取失败，请重试'));
                                    }}
                                  >
                                    <Download size={12} />
                                    <span>直接下载</span>
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    className="wb-city-preset-btn"
                                    onClick={() => selectRun(run)}
                                  >
                                    <span>查看详情</span>
                                  </button>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  );
                })()}

                {uncertainCreate && <p className="wb-notice mt-3">原请求资料：{createAttempt.current?.payload.datasets.map(datasetLabel).join('、')}。本次继续确认原请求，分类不改变其内容。</p>}
                {uncertainCreate && <p role="status" className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">上次提交结果尚未确认，已锁定原选择。请点击“重新确认原请求”，继续确认同一任务。</p>}
                {!uncertainCreate && matchingRun && <div className="mt-3 rounded-lg bg-sky-50 border border-sky-200 p-3 text-xs text-sky-800 space-y-2"><p>{completedMatch ? '相同选择已有文件，可直接查看和下载。' : '相同选择已有任务正在执行，可直接查看进度。'}</p>{completedMatch && <label className="flex items-center gap-2"><input type="checkbox" checked={duplicateApproval === currentSelectionKey} disabled={creating} onChange={event => setDuplicateApproval(event.target.checked ? currentSelectionKey : '')} />重新采集，创建新版本</label>}</div>}
              </div>
              {/* @wbx:rail-start 执行规则与摘要（V2：右栏不再重复明细清单） */}
              <aside className="wbx-rail" aria-label="执行规则与摘要与开始任务">
                <div className="wbx-rail__card">
                  <header className="wbx-rail__head">
                    <div className="wbx-rail__title-wrap">
                      <h4 className="wbx-rail__title">执行规则与摘要</h4>
                      <span className="wbx-pill wbx-pill--neutral tabular-nums">
                        {datasets.length > 0
                          ? activePlatformCount > 1
                            ? `已选 ${datasets.length} 项 · 跨 ${activePlatformCount} 平台`
                            : activePlatformList[0] && platform && activePlatformList[0] !== platform
                              ? `已选 ${datasets.length} 项（${DOWNLOAD_PLATFORMS.find(item => item.id === activePlatformList[0])?.label || '其它平台'}）`
                              : `已选 ${datasets.length} 项`
                          : '0 项'}
                      </span>
                    </div>
                    {datasets.length > 0 && (
                      <button
                        type="button"
                        className="wbx-btn wbx-btn--ghost wbx-btn--sm"
                        disabled={formLocked}
                        onClick={() => setClearConfirm(true)}
                      >
                        清空
                      </button>
                    )}
                  </header>

                  {datasets.length > 0 && platform && activePlatformList.some(p => p !== platform) && (
                    <div className="wbx-rail__cross-note" role="note">
                      <span>
                        当前队列含{activePlatformList.filter(p => p !== platform).map(p => DOWNLOAD_PLATFORMS.find(item => item.id === p)?.label).filter(Boolean).join(' / ')}待提交项
                      </span>
                      {activePlatformCount === 1 && activePlatformList[0] && onSelectPlatform && (
                        <button
                          type="button"
                          className="wbx-rail__cross-btn"
                          onClick={() => onSelectPlatform(activePlatformList[0])}
                        >
                          切回查看 →
                        </button>
                      )}
                    </div>
                  )}

                  <dl className="wbx-rail__facts">
                    {activePlatformCount > 1 && (
                      <div className="wbx-rail__fact">
                        <dt>合并提交</dt>
                        <dd className="wbx-rail__fact-strong">
                          {activePlatformList.map(p => DOWNLOAD_PLATFORMS.find(item => item.id === p)?.label).join(' + ')}（{crossPlatformPayloads.length} 批）
                        </dd>
                      </div>
                    )}
                    <div className="wbx-rail__fact">
                      <dt>处理城市</dt>
                      <dd title={(blueOnly ? blueCities : cities).join('、')}>
                        {datasets.length === 0 ? (
                          <span className="wbx-rail__pending-hint">待选资料后配置</span>
                        ) : railSummary.cityLabel === '未选择城市' ? (
                          railHint ? (
                            <span className="wbx-rail__missing-text">待勾选城市</span>
                          ) : (
                            <button
                              type="button"
                              className="wbx-rail__missing-chip"
                              onClick={() => {
                                setPulsingStep('cities');
                                document.getElementById('step-01-cities')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                              }}
                            >
                              <span>未选择城市 · 去勾选 →</span>
                            </button>
                          )
                        ) : (
                          railSummary.cityLabel
                        )}
                      </dd>
                    </div>
                    <div className="wbx-rail__fact">
                      <dt>业务账期</dt>
                      <dd>
                        <span className="wbx-rail__mono">{railSummary.periodText}</span>
                        {railSummary.periodSpanBadge && <span className="wbx-pill wbx-pill--progress">{railSummary.periodSpanBadge}</span>}
                      </dd>
                    </div>
                    <div className="wbx-rail__fact">
                      <dt>{railSummary.thirdRowLabel}</dt>
                      <dd>{railSummary.thirdRowValue}</dd>
                    </div>
                    <div className="wbx-rail__fact">
                      <dt>预计任务量</dt>
                      <dd className="wbx-rail__fact-strong tabular-nums">
                        {estimateText}
                      </dd>
                    </div>
                  </dl>

                  <details className="wbx-rail__selected" open={datasets.length > 0 && datasets.length <= 6}>
                    <summary>查看已选资料（{datasets.length}）</summary>
                    {datasets.length > 0 ? (
                      <ul className="wbx-rail__list">
                        {datasets.map((id, index) => {
                          const cardMeta = getDatasetCardMeta(id, datasetLabel(id));
                          const itemPlat = inferDatasetPlatform(id);
                          return (
                            <li key={id} className="wbx-rail__item">
                              <span className="wbx-rail__item-index tabular-nums" aria-hidden="true">
                                {String(index + 1).padStart(2, '0')}
                              </span>
                              <span className={`wb-sys-badge is-${itemPlat === 'payout' ? 'baize' : itemPlat} wbx-rail__item-badge`}>
                                {systemShortLabel(itemPlat === 'payout' ? 'baize' : itemPlat)}
                              </span>
                              <span className="wbx-rail__item-name" title={datasetLabel(id)}>{cardMeta.title}</span>
                              <button
                                type="button"
                                className="wbx-rail__item-remove"
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
                    ) : (
                      <p className="wbx-hint">尚未勾选采集资料，在 Step 01 勾选后这里会列出摘要。</p>
                    )}
                  </details>

                  <div className="wbx-rail__actions">
                    <button
                      type="button"
                      onClick={() => void startDownload()}
                      disabled={creating || (!uncertainCreate && !canSubmit)}
                      className="wbx-btn wbx-btn--primary wbx-btn--lg wbx-rail__submit"
                    >
                      {creating ? <Loader2 size={16} className="animate-spin" /> : <CloudDownload size={16} />}
                      <span>
                        {creating
                          ? '提交中…'
                          : uncertainCreate
                            ? '确认原请求'
                            : matchingRun && !TERMINAL_STATUSES.has(matchingRun.status)
                              ? '查看进行中任务'
                              : completedMatch && duplicateApproval !== currentSelectionKey
                                ? '查看已有文件'
                                : activePlatformCount > 1
                                  ? `一键合并提交 (${datasets.length} 项)`
                                  : rawSelectedDatasets.length === 0 && selectedGeneratorIds.length > 0
                                    ? '生成报表'
                                    : '开始下载'}
                      </span>
                    </button>
                    {railHint && (
                      <p className={`wbx-hint ${railHint.tone === 'warn' ? 'wbx-hint--warn' : ''}`}>
                        {railHint.run ? (
                          <button
                            type="button"
                            className="wbx-hint__link"
                            title={railHint.title}
                            onClick={railHint.run}
                          >
                            <AlertTriangle size={13} className="shrink-0" />
                            <span>{railHint.text}</span>
                          </button>
                        ) : (
                          <span>{railHint.text}</span>
                        )}
                      </p>
                    )}
                    {submittedTaskInfo && (
                      <div role="status" className="wbx-rail__done">
                        <div className="wbx-rail__done-head">
                          <span>
                            <CheckCircle2 size={14} className="shrink-0" />
                            已成功创建任务
                          </span>
                          <button
                            type="button"
                            className="wbx-rail__item-remove"
                            onClick={() => setSubmittedTaskInfo(null)}
                            aria-label="关闭提示"
                          >
                            <X size={13} />
                          </button>
                        </div>
                        <p className="wbx-rail__done-desc">任务已在后台执行，可直接查看进度与结果。</p>
                        <button
                          type="button"
                          className="wbx-btn wbx-btn--sm"
                          onClick={() => {
                            setHistoryFocusId(submittedTaskInfo.id);
                            selectedIdRef.current = submittedTaskInfo.id;
                            setSelectedId(submittedTaskInfo.id);
                            setView('history');
                          }}
                        >
                          查看本次任务
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </aside>
              {/* @wbx:rail-end */}
              {clearConfirm && (
                <WorkbenchDrawer title="清空已选资料" onClose={() => setClearConfirm(false)}>
                  <p>将清空右栏当前已选的 {datasets.length} 类资料勾选，本次配置的其它范围与账期不受影响。</p>
                  <p className="wbx-hint">仅清空当前勾选，不会删除已采集的数据，也不影响历史任务与已生成文件。</p>
                  <div className="wbx-dialog-actions">
                    <button type="button" className="wbx-btn" onClick={() => setClearConfirm(false)}>
                      取消
                    </button>
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--danger"
                      onClick={() => {
                        setDatasets([]);
                        setClearConfirm(false);
                      }}
                    >
                      确认清空
                    </button>
                  </div>
                </WorkbenchDrawer>
              )}
            </>}
        </section>
      </>}
          </>
        );
      })()}

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
                datasetLabel={datasetLabel} refreshVersion={navigation?.version} unified
                onNavigateGenerate={onNavigateGenerate}
                onNavigatePayroll={onNavigatePayroll}
                onOpenFengshenLogin={onOpenFengshenLogin ? () => onOpenFengshenLogin(user.id) : undefined}
                onRetryTask={record => {
                  const nextDatasets = Array.isArray(record.datasets) ? record.datasets : [];
                  if (inferTaskKind(nextDatasets) === 'generate') {
                    const genId = nextDatasets.find(isGenerator) || 'payment_binding';
                    onSelectReport?.(genId);
                    onTaskKindChange?.('generate');
                  } else {
                    if (nextDatasets.some(isBaize) || nextDatasets.some(isBenlai)) {
                      onSelectPlatform?.('payout');
                    } else if (nextDatasets.some(isXiaoxiang)) {
                      onSelectPlatform?.('xiaoxiang');
                    } else if (nextDatasets.some(isLanorange)) {
                      onSelectPlatform?.('lanorange');
                    } else {
                      onSelectPlatform?.('fengshen');
                    }
                    onTaskKindChange?.('download');
                  }
                  const nextCities = (record.cities || []).filter(
                    city => city !== '全部城市' && (!options || options.cities.some(item => item.name === city && !item.disabled)),
                  );
                  if (nextCities.length) setCities(nextCities);
                  const validDatasets = nextDatasets.filter(
                    id => !options || options.datasets.some(item => item.id === id),
                  );
                  if (validDatasets.length) setDatasets(validDatasets);
                  if (record.start && record.end && DATE_PATTERN.test(record.start) && DATE_PATTERN.test(record.end)) {
                    setStart(record.start);
                    setEnd(record.end);
                  }
                  setDuplicateApproval('');
                  setRequestError('');
                  setView('create');
                }}
                onOpenPrice={onOpenPrice}
        onOpenAttempt={id => {
          setRequestError('');
          if (id.startsWith('TC-') || id.startsWith('demo-')) return;
          attemptOpenController.current?.abort();
          const controller = new AbortController(); attemptOpenController.current = controller;
          void getJson(`${API_ROOT}/runs/${encodeURIComponent(id)}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) })
            .then(data => { if (!controller.signal.aborted) selectRun(data.run); }).catch(error => { if (!controller.signal.aborted) setRequestError(error.message); });
        }}
        execution={<>
{selectedRun && <div className={`${panel} wb-task-detail min-w-0 space-y-4 p-4 sm:p-5`}>

              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><h3 className="flex flex-wrap items-center gap-2 text-base font-semibold text-slate-900">{selectedRun.datasets.every(isBaize) ? '商翼全量员工资料' : selectedRun.datasets.every(isBenlai) ? '本来人力全量灵工资料' : selectedRun.datasets.every(id => id === 'abnormal_riders') ? '异常名单（全量）' : selectedRun.datasets.every(isLanorange) ? (selectedRun.lanorange_by_city ? `蓝橙 ${selectedRun.cities.join('、')}` : '蓝橙全量') : selectedRun.cities.length > 2 ? `${selectedRun.cities.length} 个城市` : selectedRun.cities.join('、')}的{selectedRun.datasets.every(isGenerator) ? '报表任务' : '下载任务'} <span className={`rounded-md px-2 py-1 text-xs font-normal ${statusInfo(selectedRun.status).color}`}>{runStatusLabel}</span></h3><p className="mt-2 text-xs text-slate-500">{selectedRun.datasets.every(id => id === 'abnormal_riders') ? '全部授权城市 · 全量最新档案整理' : selectedRun.datasets.every(isLanorange) ? (selectedRun.lanorange_by_city ? '所选城市、全部状态、不按日期筛选' : '全部城市、全部状态、不按日期筛选') : `${selectedRun.start} 至 ${selectedRun.end}`} · {selectedRun.datasets.length} 类资料</p></div>
                {!activeRun && <details><summary className="wb-link">需要重新采集？</summary><p className="text-xs">先处理下方可恢复项。新任务不会继续原导出；结果未知时请先核对原回执。</p><button type="button" className={smallButton} disabled={selectedRun.items?.some(item => item.submission_state === 'unknown')} onClick={() => prefillFromRun(selectedRun)}>重新采集并创建新任务</button></details>}
                {activeRun && <button type="button" className={smallButton} disabled={cancelling || ['cancelling', 'canceling'].includes(selectedRun.status)} onClick={() => void cancelDownload()}>{cancelling ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}停止任务</button>}
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
              {waitingLogin && <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">{selectedRun.datasets.some(id => isLanorange(id) || isBaize(id) || isBenlai(id) || isXiaoxiang(id)) ? <><p>此任务需要来源认证。</p><button className={`${smallButton} mt-2`} onClick={() => window.dispatchEvent(new CustomEvent('workbench:connections', { detail: selectedRun.datasets.some(isBaize) ? 'baize' : selectedRun.datasets.some(isBenlai) ? 'benlai' : selectedRun.datasets.some(isXiaoxiang) ? 'xiaoxiang' : 'lanorange' }))}>完成验证</button></> : <><p>完成风神登录后，任务会继续。</p>{onOpenFengshenLogin ? <button type="button" onClick={() => onOpenFengshenLogin(user.id)} className={`${smallButton} mt-2`}><KeyRound size={14} />打开风神登录</button> : <p>请在运行系统的电脑上完成风神登录。</p>}</>}</div>}
              {selectedRun.phase === 'waiting_manual' && <p role="status" className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">平台要求额外验证，当前任务已暂停。请打开风神验证窗口查看具体原因。</p>}
              {selectedRun.error && <p role="alert" className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 break-words">{selectedRun.error}</p>}

              {canRecoverDetail(selectedRun) && <div className="rounded-lg bg-sky-50 border border-sky-200 p-3 text-xs text-sky-800"><p>可继续查询已提交的明细任务。</p><button type="button" className={`${smallButton} mt-2`} disabled={!!resumingRunId} onClick={() => void resumeDetail()}>{resumingRunId ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}恢复已有明细下载</button>{recoveryError?.runId === selectedRun.id && <p role="alert" className="mt-2 text-amber-700">{recoveryError.message}</p>}</div>}
              {!!selectedRun.items?.length && <details key={`items-${selectedRun.id}`} open={failedItems.length > 0} className="border-t border-slate-200 pt-3">
                <summary className="cursor-pointer text-sm text-slate-700">任务明细{failedItems.length > 0 ? ` · ${failedItems.length} 项需要处理` : ` · ${selectedRun.items.length} 项`}</summary>
                <div className="mt-3 space-y-3">
                  {!activeRun && selectedRecoverable.length > 0 && (
                    <div className="flex flex-wrap items-center justify-between gap-2 p-2 rounded-lg bg-orange-50/70 border border-orange-200/80">
                      <label className="flex items-center gap-2 text-xs text-orange-950 font-medium">
                        <input
                          type="checkbox"
                          disabled={retryPending || uncertainRetry}
                          checked={selectedRecoverable.every(item => retryKeys.includes(itemKey(item)))}
                          onChange={event => setRetryKeys(event.target.checked ? selectedRecoverable.map(itemKey) : [])}
                          className="accent-orange-600 rounded"
                        />
                        全选可重试项 ({selectedRecoverable.length})
                      </label>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          className="wb-retry-all-failed-btn"
                          disabled={retryPending || uncertainRetry}
                          onClick={() => void retrySelected(selectedRecoverable)}
                          title="批量为所有失败或未完成城市发起补采重试"
                        >
                          <RefreshCw size={12} className={retryPending ? 'animate-spin' : ''} />
                          <span>一键重试全部失败城 ({selectedRecoverable.length} 项)</span>
                        </button>
                        <button
                          type="button"
                          className={smallButton}
                          disabled={retryPending || uncertainRetry || !selectedRecoverable.some(item => retryKeys.includes(itemKey(item)))}
                          onClick={() => void retrySelected()}
                        >
                          {retryPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                          <span>处理所选项</span>
                        </button>
                      </div>
                    </div>
                  )}
                  <div className="max-h-96 space-y-2 overflow-y-auto">
                    {selectedRun.items.map((item, index) => (
                      <div key={`${itemKey(item)}-${index}`} className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs">
                        <div className="flex items-start justify-between gap-3">
                          <label className="flex items-start gap-2">
                            {!activeRun && recoverable(item) && (
                              <input
                                aria-label={`选择处理${item.city}${datasetLabel(item.dataset)}${item.start}`}
                                type="checkbox"
                                disabled={retryPending || uncertainRetry}
                                checked={retryKeys.includes(itemKey(item))}
                                onChange={() => toggle(itemKey(item), retryKeys, setRetryKeys)}
                                className="accent-sky-700 rounded mt-0.5"
                              />
                            )}
                            <span className="font-medium text-slate-800">{item.city} · {datasetLabel(item.dataset)}</span>
                          </label>
                          <div className="flex items-center gap-2 shrink-0">
                            {!activeRun && recoverable(item) && (
                              <button
                                type="button"
                                className="wb-retry-single-btn"
                                disabled={retryPending || uncertainRetry}
                                onClick={() => void retrySelected(item)}
                                title={`仅重试 ${item.city} 的 ${datasetLabel(item.dataset)}`}
                              >
                                <RefreshCw size={11} className={retryPending ? 'animate-spin' : ''} />
                                <span>重试此城 ({item.city})</span>
                              </button>
                            )}
                            <span className={`shrink-0 rounded px-1.5 py-0.5 ${statusInfo(item.status).color}`}>
                              {statusInfo(item.status).label}
                            </span>
                          </div>
                        </div>
                    <p className="mt-1.5 text-slate-500">{isBaize(item.dataset) ? '商翼全量员工原表 · 不按城市或日期筛选' : isBenlai(item.dataset) ? '本来人力全量灵工原表 · 不按城市或日期筛选 · 签约城市实时读取' : isRiderArchive(item.dataset) ? '小象灯塔骑手档案 · 全部站点当前快照 · 手机号/身份证为明文 · 照片以链接提供' : item.dataset === 'rider_order_detail' || item.dataset === 'xiaoxiang_attendance_detail' ? `灯塔通知附件合并 · ${item.start} 至 ${item.end} · 按附件数据日期筛选` : isXiaoxiang(item.dataset) ? (item.start===item.end ? `小象灯塔商配送看板 · ${item.start} 单日 · 全部站点一份工作簿` : `小象灯塔商配送看板 · ${item.start} 至 ${item.end} 区间合并 · 全部站点一份工作簿${item.dataset === 'rider_daily' ? ' · 按附件20列格式' : ''}`) : item.dataset === 'abnormal_riders' ? '生成表 · 由本任务的 5 类蓝橙成品整理生成（全部城市一份）' : isLanorange(item.dataset) ? (item.city === '全部城市' ? selectedRun.lanorange_full_delivery ? '全量统一交付 · 全部状态、无日期筛选；缺失批次不计为完成' : '全量原始表 · 全部城市、全部状态、无业务筛选' : item.dataset === 'lanorange_batch_quit' ? '平台城市批次原表 · 汇总按骑手城市归属筛选' : '城市原始表 · 全部状态、不按日期筛选') : item.dataset === 'rider_info' ? '当前快照' : `${item.start} 至 ${item.end}`}{item.phase && !['completed', 'failed', 'cancelled', 'interrupted'].includes(item.phase) ? ` · ${phaseLabel(item.phase)}` : ''}</p>
                    {item.error && <p className="mt-2 break-words text-rose-700">{item.error}</p>}
                    {!activeRun && item.status !== 'success' && item.recovery && <div className="mt-2"><p className={item.recovery.mode === 'blocked' ? 'text-amber-800' : 'text-sky-800'}>{!recoverable(item) ? '需人工核对后处理' : item.recovery.mode === 'resume_existing' ? '复用已有资料，继续处理' : '尚未提交，可重新执行'}</p><details open className="mt-1 text-slate-500"><summary className="cursor-pointer">原因与处理说明</summary><p className="mt-2 leading-relaxed">{item.recovery.reason}</p>{item.failure_phase && <p className="mt-1">失败阶段：{phaseLabel(item.failure_phase)}</p>}</details>{recoverable(item) && <button type="button" className="wb-button wb-item-recovery" disabled={retryPending || uncertainRetry} onClick={() => void retrySelected(item)}>{item.recovery.mode === 'resume_existing' ? '继续此项已有资料' : '仅重试此未提交项'}</button>}</div>}
                  </div>))}</div>
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
              <details className="border-t border-slate-200 pt-3 text-xs text-slate-500"><summary className="cursor-pointer w-fit">任务信息与保存位置</summary><div className="mt-3 space-y-2"><p>编号：{selectedRun.archive_code || selectedRun.id.slice(0, 6).toUpperCase()}</p><p className="break-all">任务目录：{selectedRun.archive_relative_dir || '旧版任务保留原存放位置'}</p><p>城市：{selectedRun.cities.join('、')}</p><p>资料：{selectedRun.datasets.map(datasetLabel).join('、')}</p>{selectedRun.retry_of && <p>此任务处理原任务 {selectedRun.retry_of.slice(0, 6).toUpperCase()} 的未完成项。</p>}{selectedRun.recovery_of && <p>此任务恢复原有平台导出。</p>}{!activeRun && <button type="button" className={smallButton} disabled={rawBusy} onClick={() => void downloadRawBundle()}>下载已保留原始资料</button>}{selectedRun.last_activity_at && <p>最近进展：{displayTime(selectedRun.last_activity_at)}</p>}{!activeRun && <button type="button" className={smallButton} disabled={!!downloadingSummaryId} onClick={() => void downloadSummary()}>{downloadingSummaryId ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}下载说明</button>}</div></details>

              {!!selectedRun.logs?.length && <details className="border-t border-slate-200 pt-3 text-xs text-slate-600"><summary className="cursor-pointer w-fit">执行日志</summary><div className="mt-3 max-h-48 space-y-2 overflow-y-auto font-mono bg-slate-50 border border-slate-200 rounded-lg p-3">{selectedRun.logs.map((log, index) => <p key={index} className="break-words"><span className="mr-2 text-slate-400">{displayTime(log.time)}</span>{log.message}</p>)}</div></details>}
            </div>}
        </>}
              />
            </div>
          </div>
        );
      })()}

    {/* 预设新建 / 修改 / 删除通用弹窗 */}
    {presetModal && (
      <div
        className="wb-modal-backdrop"
        role="dialog"
        aria-modal="true"
        aria-labelledby="custom-preset-title"
        onClick={() => setPresetModal(null)}
      >
        <div className="wb-preset-modal-content" onClick={e => e.stopPropagation()}>
          <div className="wb-preset-modal-header">
            <h3 id="custom-preset-title" className="wb-preset-modal-title">
              {presetModal.mode === 'create'
                ? (presetModal.type === 'region' ? '存为自定义城市片区' : '存为自定义场景包')
                : (presetModal.type === 'region' ? '修改城市片区预设' : '修改业务场景包')}
            </h3>
            <button
              type="button"
              className="wb-popover-close-btn"
              aria-label="关闭"
              onClick={() => setPresetModal(null)}
            >
              <X size={16} />
            </button>
          </div>

          <div className="wb-preset-modal-summary">
            {presetModal.type === 'region' ? (
              <div>
                <div className="font-medium text-slate-700 mb-1">
                  {presetModal.mode === 'create' ? '将包含以下已选城市：' : '当前预设所含城市：'}
                </div>
                <div className="text-xs text-slate-600 break-words leading-relaxed">
                  {(presetModal.mode === 'create' ? (blueOnly ? blueCities : cities) : (presetModal.cities || [])).join('、') || '（未选城市）'}
                </div>
                {presetModal.mode === 'edit' && (
                  <label className="flex items-center gap-2 mt-2 pt-2 border-t border-slate-200 text-xs text-sky-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!presetModal.syncWithCurrentSelection}
                      disabled={!(blueOnly ? blueCities : cities).length}
                      onChange={e => setPresetModal(prev => prev ? { ...prev, syncWithCurrentSelection: e.target.checked } : null)}
                      className="rounded text-sky-600 focus:ring-sky-500"
                    />
                    <span>以当前已勾选的 {(blueOnly ? blueCities : cities).length} 个城市覆盖更新此预设</span>
                  </label>
                )}
              </div>
            ) : (
              <div>
                <div className="font-medium text-slate-700 mb-1">
                  {presetModal.mode === 'create' ? '将包含以下已选资料：' : '当前预设所含资料：'}
                </div>
                <div className="text-xs text-slate-600 break-words leading-relaxed">
                  {(presetModal.mode === 'create' ? datasets : (presetModal.datasets || [])).map(datasetLabel).join('、') || '（未选资料）'}
                </div>
                {presetModal.mode === 'edit' && (
                  <label className="flex items-center gap-2 mt-2 pt-2 border-t border-slate-200 text-xs text-sky-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!presetModal.syncWithCurrentSelection}
                      disabled={!datasets.length}
                      onChange={e => setPresetModal(prev => prev ? { ...prev, syncWithCurrentSelection: e.target.checked } : null)}
                      className="rounded text-sky-600 focus:ring-sky-500"
                    />
                    <span>以当前已勾选的 {datasets.length} 类资料覆盖更新此预设</span>
                  </label>
                )}
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="custom-preset-input" className="block text-xs font-medium text-slate-700">
              预设名称
            </label>
            <input
              id="custom-preset-input"
              type="text"
              autoFocus
              maxLength={15}
              placeholder={presetModal.type === 'region' ? '例如：大湾区核心、包邮区三城' : '例如：阿信日常对账、离职清算包'}
              value={presetModal.label}
              onChange={e => setPresetModal(prev => prev ? { ...prev, label: e.target.value } : null)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  const trimmed = presetModal.label.trim();
                  if (!trimmed) return;
                  if (presetModal.mode === 'create') {
                    if (presetModal.type === 'region') {
                      const cur = blueOnly ? blueCities : cities;
                      const next = [...regionPresets, { id: `custom_reg_${Date.now()}`, label: trimmed, cities: [...cur] }];
                      saveRegionPresetsToStorage(next);
                    } else {
                      const next = [...scenarioPresets, { id: `custom_scen_${Date.now()}`, label: trimmed, title: datasets.map(datasetLabel).join(' + '), datasets: [...datasets] }];
                      saveScenarioPresetsToStorage(next);
                    }
                  } else if (presetModal.id) {
                    if (presetModal.type === 'region') {
                      const cur = blueOnly ? blueCities : cities;
                      const targetCities = presetModal.syncWithCurrentSelection && cur.length > 0
                        ? [...cur]
                        : (presetModal.cities || []);
                      const next = regionPresets.map(p => p.id === presetModal.id ? { ...p, label: trimmed, cities: targetCities } : p);
                      saveRegionPresetsToStorage(next);
                    } else {
                      const targetDatasets = presetModal.syncWithCurrentSelection && datasets.length > 0
                        ? [...datasets]
                        : (presetModal.datasets || []);
                      const next = scenarioPresets.map(s => s.id === presetModal.id ? { ...s, label: trimmed, datasets: targetDatasets, title: targetDatasets.map(datasetLabel).join(' + ') } : s);
                      saveScenarioPresetsToStorage(next);
                    }
                  }
                  setPresetModal(null);
                } else if (e.key === 'Escape') {
                  setPresetModal(null);
                }
              }}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>

          <div className="wb-preset-modal-footer">
            {presetModal.mode === 'edit' && presetModal.id && (
              <button
                type="button"
                className="mr-auto inline-flex items-center gap-1 text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-50 px-2.5 py-1.5 rounded transition-colors"
                onClick={() => {
                  if (presetModal.type === 'region') {
                    saveRegionPresetsToStorage(regionPresets.filter(r => r.id !== presetModal.id));
                  } else {
                    saveScenarioPresetsToStorage(scenarioPresets.filter(s => s.id !== presetModal.id));
                  }
                  setPresetModal(null);
                }}
              >
                <Trash2 size={12} />
                <span>删除此预设</span>
              </button>
            )}
            <button
              type="button"
              className="wb-button"
              onClick={() => setPresetModal(null)}
            >
              取消
            </button>
            <button
              type="button"
              className="wb-primary px-4 py-1.5 text-xs font-medium"
              disabled={!presetModal.label.trim()}
              onClick={() => {
                const trimmed = presetModal.label.trim();
                if (!trimmed) return;
                if (presetModal.mode === 'create') {
                  if (presetModal.type === 'region') {
                    const cur = blueOnly ? blueCities : cities;
                    const next = [...regionPresets, { id: `custom_reg_${Date.now()}`, label: trimmed, cities: [...cur] }];
                    saveRegionPresetsToStorage(next);
                  } else {
                    const next = [...scenarioPresets, { id: `custom_scen_${Date.now()}`, label: trimmed, title: datasets.map(datasetLabel).join(' + '), datasets: [...datasets] }];
                    saveScenarioPresetsToStorage(next);
                  }
                } else if (presetModal.id) {
                  if (presetModal.type === 'region') {
                    const cur = blueOnly ? blueCities : cities;
                    const targetCities = presetModal.syncWithCurrentSelection && cur.length > 0
                      ? [...cur]
                      : (presetModal.cities || []);
                    const next = regionPresets.map(p => p.id === presetModal.id ? { ...p, label: trimmed, cities: targetCities } : p);
                    saveRegionPresetsToStorage(next);
                  } else {
                    const targetDatasets = presetModal.syncWithCurrentSelection && datasets.length > 0
                      ? [...datasets]
                      : (presetModal.datasets || []);
                    const next = scenarioPresets.map(s => s.id === presetModal.id ? { ...s, label: trimmed, datasets: targetDatasets, title: targetDatasets.map(datasetLabel).join(' + ') } : s);
                    saveScenarioPresetsToStorage(next);
                  }
                }
                setPresetModal(null);
              }}
            >
              {presetModal.mode === 'create' ? '保存预设' : '保存修改'}
            </button>
          </div>
        </div>
      </div>
    )}

    </div>
  );
}
