import React, { useState, useEffect, useLayoutEffect, useRef } from "react";
import {createUploadArchive} from './lib/uploadArchive';
import { uploadSource } from "./lib/uploadSource";
import {pendingQueueSubmission,prepareQueueSubmission,sendQueueSubmission} from './lib/payrollQueueSubmit';
import {planPayrollUpload} from './lib/payrollUploadPlan';
import { THEMES } from "./constants";
import { LogEntry, AppConfig } from "./types";
import { FengshenLoginModal, FengshenAuthStatus } from "./components/FengshenLoginModal";
import { CorePage, TaskItem } from "./components/CorePage";
import {
  X,
  Menu,
  SlidersHorizontal,
  Calculator,
  FileSpreadsheet,
  FolderCheck,
  Layers,
  UsersRound,
  Radar,
  Search,
} from "lucide-react";
import { UploadProgressOverlay } from "./components/UploadProgressOverlay";
import type { PayrollPreparationState } from './components/PayrollPreparation';
import type { RunResult } from './components/RunResultCard';
import { restorePayrollSourceMode } from './payrollSource';
import { FengshenDownloadCenter } from "./components/FengshenDownloadCenter";
import * as XLSX from "xlsx";
import { getWorkspaceId } from "./utils";
import { WorkbenchDrawer } from "./components/WorkbenchDrawer";
import { SystemConnections } from "./components/SystemConnections";
import { fetchWithPreflight } from "./lib/authPreflight";
import { HeaderApprovalNotifier } from "./components/HeaderApprovalNotifier";
import { TaskStatusNotifier } from "./components/TaskStatusNotifier";
import { LanorangeApprovals } from "./components/LanorangeApprovals";
import { LanorangePriceExports } from "./components/LanorangePriceExports";
import { FilePickup } from "./components/FilePickup";
import { StationDeductionManager } from "./components/StationDeductionManager";
import {useStationDirectory,stationCountText} from './lib/useStationDirectory';
import { SystemTemplatesPanel } from "./components/SystemTemplatesPanel";
import { initialTaskKind, TASK_KIND_LABELS, type TaskKind } from "./lib/taskCatalog";
import {
  COLLECTION_SUB_VIEWS,
  getPayrollSidebarBadge,
  type PayrollSubView,
  type PlatformStatusMap,
} from "./lib/workbench";
import { DOWNLOAD_PLATFORMS,type DownloadPlatform } from './lib/downloadModules';
import { PlatformDock } from './components/PlatformDock';
import { DualRailSidebar } from './components/DualRailSidebar';
import { HeaderBreadcrumb } from './components/HeaderBreadcrumb';
import { CommandPaletteModal } from './components/CommandPaletteModal';
import { TerminalPanel } from './components/TerminalPanel';
import {
  buildShellCommands,
  getBreadcrumbModel,
  SPECIAL_REPORT_SUBMODULES,
  type ShellCommandAction,
} from './lib/shellNav';
import { APP_TITLE } from './lib/appMeta';
import { BP, currentViewportWidth } from './lib/breakpoints';
import {
  syncGlobalPlatformAuth,
} from './lib/demoMode';
import {
  buildTaskReturnTarget,
  detectTaskNotifications,
  readAutoJumpPreference,
  writeAutoJumpPreference,
  type TaskNotificationRecord,
  type TaskReturnTarget,
  type TaskStatusAlert,
} from './lib/taskWorkflow';
import { arePlatformStatusMapsEqual } from './lib/perfUtils';
import { AuthLoadingSplash, AuthPortal } from './components/AuthPortal';
import {
  AccountManagementPage,
  NoModuleAccessNotice,
  type AccountConsoleTab,
} from './components/AccountManagementPage';
import { PlatformAuthCenterPage } from './components/PlatformAuthCenterPage';
import { DisplayAdaptationPage } from './components/DisplayAdaptationPage';
import {
  DEFAULT_DISPLAY_CONFIG,
  applyDisplayAdaptationToDocument,
  detectScreenEnvironment,
  formatDisplayAdaptationBadge,
  loadLocalDisplayConfig,
  saveLocalDisplayConfig,
  type DisplayAdaptationConfig,
} from './lib/displayAdaptation';
import { HeaderAccountBar, WorkspaceInspectBanner } from './components/HeaderAccountBar';
import {
  fetchWorkspaceSession,
  hasModulePermission,
  loginWorkspaceAccount,
  logoutWorkspaceAccount,
  switchInspectWorkspace,
  switchToHostAdmin,
  syncStoredWorkspaceId,
  type WorkspaceSessionState,
} from './lib/workspaceAuth';

const showDesktopNotification = (title: string, body: string) => {
  if (!("Notification" in window)) {
    return;
  }
  
  if (Notification.permission === "granted") {
    new Notification(title, { body });
  } else if (Notification.permission !== "denied") {
    Notification.requestPermission().then((permission) => {
      if (permission === "granted") {
        new Notification(title, { body });
      }
    });
  }
};

export default function App() {
  const [session, setSession] = useState<WorkspaceSessionState | null>(null);
  const [loadingSession, setLoadingSession] = useState(true);

  const refreshSession = async () => {
    try {
      const next = await fetchWorkspaceSession();
      setSession(next);
    } catch {
      // keep previous or null on transient startup delay
    } finally {
      setLoadingSession(false);
    }
  };

  useEffect(() => {
    void refreshSession();
  }, []);

  // Poll pending approvals lightly when logged in as admin
  useEffect(() => {
    if (!session?.authenticated || session.user?.role !== 'admin') return;
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        void refreshSession();
      }
    }, 25000);
    return () => clearInterval(timer);
  }, [session?.authenticated, session?.user?.role]);

  if (loadingSession && !session) {
    return <AuthLoadingSplash />;
  }

  if (!session || !session.authenticated || !session.user) {
    return (
      <AuthPortal
        session={
          session || {
            initialized: true,
            authenticated: false,
            host_machine: false,
            local_loopback: false,
            host_auto_login: false,
            can_switch_to_host: false,
            bootstrap_allowed: false,
            user: null,
            role_templates: {},
            permission_keys: [],
            permission_labels: {} as any,
            workspaces: [],
            pending_count: 0,
          }
        }
        onAuthenticated={next => setSession(next)}
        onRefreshSession={refreshSession}
      />
    );
  }

  return (
    <AuthenticatedWorkbench
      key={`${session.user.id}:${session.user.effective_workspace}`}
      session={session}
      onSessionUpdate={setSession}
      onRefreshSession={refreshSession}
    />
  );
}

function AuthenticatedWorkbench({
  session,
  onSessionUpdate,
  onRefreshSession,
}: {
  session: WorkspaceSessionState;
  onSessionUpdate: React.Dispatch<React.SetStateAction<WorkspaceSessionState | null>>;
  onRefreshSession: () => Promise<void>;
}) {
  const currentUser = session.user!;
  const [accountsTabReq, setAccountsTabReq] = useState<{
    tab: AccountConsoleTab | null;
    version: number;
  }>({ tab: null, version: 0 });
  const theme = THEMES[0];

  const [missingCityTeams, setMissingCityTeams] = useState<string[]>([]);
  const [missingCityMap, setMissingCityMap] = useState<Record<string, string>>({});
  const [missingCityUuid, setMissingCityUuid] = useState<string | null>(null);
  
  const handleSaveMissingCities = async () => {
    try {
      const res1 = await fetch("/api/update_config_cities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mapping: missingCityMap }),
      });
      const data1 = await res1.json();
      if (!data1.success) {
        throw new Error(data1.error || "保存失败");
      }
      
      if (missingCityUuid) {
        const res2 = await fetch("/api/resume_task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ uuid: missingCityUuid, action: true }),
        });
        const data2 = await res2.json();
        if (data2.error) {
          throw new Error(data2.error);
        }
      }
      
      setMissingCityTeams([]);
      setMissingCityMap({});
      setMissingCityUuid(null);
      showToast("映射保存成功，任务继续执行...", "success");
    } catch (e) {
      showToast("保存失败: " + String(e), "error");
    }
  };

  const handleCancelMissingCities = async () => {
    try {
      if (missingCityUuid) {
        await fetch("/api/resume_task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ uuid: missingCityUuid, action: false }),
        });
      }
      setMissingCityTeams([]);
      setMissingCityMap({});
      setMissingCityUuid(null);
      showToast("任务已取消", "info");
    } catch (e) {
      showToast("取消失败: " + String(e), "error");
    }
  };

  const appTheme = 'light' as const;

  useEffect(() => {
    document.title = APP_TITLE;
    document.documentElement.setAttribute('data-theme', 'light');
    document.documentElement.classList.remove('dark');
    try { localStorage.setItem('app_theme', 'light'); } catch {}
  }, []);

  const workspaceId = currentUser.effective_workspace || 'download_shared';
  useEffect(() => {
    syncStoredWorkspaceId(workspaceId);
  }, [workspaceId]);

  const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set("x-workspace-id", encodeURIComponent(workspaceId));
    if (currentUser.inspecting) {
      headers.set("x-inspect-workspace", encodeURIComponent(workspaceId));
    }
    const response = await fetchWithPreflight(
      url,
      { ...options, credentials: "same-origin", headers },
      (requestUrl, requestOptions) => fetch(requestUrl, requestOptions),
    );
    if (response.status === 401) {
      void onRefreshSession();
    }
    return response;
  };

  const [activeMenu, setActiveMenu] = useState(new URLSearchParams(window.location.search).has('batch') ? 'core' : 'fengshen_downloads');
  const activeMenuRef = useRef(activeMenu);
  useEffect(() => {
    activeMenuRef.current = activeMenu;
  }, [activeMenu]);

  const quickPayrollInputRef = useRef<HTMLInputElement>(null);
  // 外壳断点状态（D6：只用 1280/1024/768 三档；纯函数来自 lib/breakpoints）
  const [viewportWidth, setViewportWidth] = useState<number>(() => currentViewportWidth());
  const [screenEnv, setScreenEnv] = useState(() => detectScreenEnvironment());
  const [displayConfig, setDisplayConfig] = useState<DisplayAdaptationConfig>(() =>
    loadLocalDisplayConfig(),
  );
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [logDrawerOpen, setLogDrawerOpen] = useState(false);
  useEffect(() => {
    let frame = 0;
    const onResize = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setViewportWidth(currentViewportWidth());
        setScreenEnv(detectScreenEnvironment());
      });
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  const isDrawerMode = viewportWidth <= BP.sm;
  const [sidebarIsCollapsed, setSidebarIsCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('workbench_sidebar_collapsed') === '1';
    } catch {
      return false;
    }
  });
  const setSidebarCollapsedPersist = (next: boolean) => {
    setSidebarIsCollapsed(next);
    try {
      localStorage.setItem('workbench_sidebar_collapsed', next ? '1' : '0');
    } catch {}
  };
  const toggleSidebarCollapsed = () => {
    setSidebarIsCollapsed(prev => {
      const next = !prev;
      try {
        localStorage.setItem('workbench_sidebar_collapsed', next ? '1' : '0');
      } catch {}
      return next;
    });
  };
  const handleUpdateDisplayConfig = (next: DisplayAdaptationConfig) => {
    setDisplayConfig(next);
    saveLocalDisplayConfig(next);
  };
  const handleResetDisplayConfig = () => {
    const def = { ...DEFAULT_DISPLAY_CONFIG };
    setDisplayConfig(def);
    saveLocalDisplayConfig(def);
  };
  useLayoutEffect(() => {
    const tokens = applyDisplayAdaptationToDocument(displayConfig, screenEnv.detectedClass);
    if (tokens.shouldCollapseSidebarOnLaptop && !sidebarIsCollapsed) {
      setSidebarIsCollapsed(true);
    }
  }, [displayConfig, screenEnv.detectedClass]);
  useEffect(() => {
    if (!isDrawerMode) setMobileNavOpen(false);
  }, [isDrawerMode]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCmdkOpen(prev => !prev);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const isEditable =
        !!target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable);
      if (isEditable) return;
      if (event.key.toLowerCase() === 'l') {
        event.preventDefault();
        setLogDrawerOpen(prev => !prev);
      } else if (event.key === '[') {
        event.preventDefault();
        toggleSidebarCollapsed();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isDrawerMode]);
  const [deductionDefaultOnly, setDeductionDefaultOnly] = useState(false);
  const [deductionVersion, setDeductionVersion] = useState(0);
  const [payrollSubView, setPayrollSubView] = useState<PayrollSubView>('batches');
  const [workspaceView, setWorkspaceView] = useState<
    | 'create'
    | 'history'
    | 'approval'
    | 'price-export'
    | 'pickup'
    | 'accounts'
    | 'platform-auth'
    | 'display-adaptation'
  >('create');
  const [downloadPlatform,setDownloadPlatform]=useState<DownloadPlatform>(()=>{
    try{
      const saved=localStorage.getItem('workbench_download_platform');
      if (saved === 'baize' || saved === 'benlai') return 'payout';
      return DOWNLOAD_PLATFORMS.find(value=>value.id===saved)?.id||'fengshen';
    }catch{return 'fengshen';}
  });
  const [activeReportId, setActiveReportId] = useState<string>(() => {
    try {
      const saved = localStorage.getItem('workbench_active_report_id');
      return SPECIAL_REPORT_SUBMODULES.find(item => item.id === saved)?.id || SPECIAL_REPORT_SUBMODULES[0].id;
    } catch {
      return SPECIAL_REPORT_SUBMODULES[0].id;
    }
  });
  const [historyAll,setHistoryAll]=useState(false);
  const platformMeta=DOWNLOAD_PLATFORMS.find(value=>value.id===downloadPlatform)!;
  const platformLabel=platformMeta.label;
  const platformNavLabel=platformMeta.navLabel;
  const [approvalActiveCount,setApprovalActiveCount]=useState(0);
  const [approvalPendingCount,setApprovalPendingCount]=useState(0);
  const [priceRecordId,setPriceRecordId]=useState<string|undefined>();
  const canApproval = hasModulePermission(currentUser, 'approval');
  const canCollection = hasModulePermission(currentUser, 'collection');
  const canReports = hasModulePermission(currentUser, 'reports');
  const canPayroll = hasModulePermission(currentUser, 'payroll');
  const canManageSharedAuth = hasModulePermission(currentUser, 'shared_auth_manage');

  useEffect(()=>{
    if (!canApproval) {
      setApprovalActiveCount(0);
      return;
    }
    let disposed=false;const controller=new AbortController();
    const read=()=>{
      if (document.visibilityState !== 'visible') return;
      fetchWithAuth('/api/fengshen-downloads/lanorange-approvals/activity',{signal:controller.signal})
        .then(r=>r.ok?r.json():null)
        .then(value=>{
          if(!disposed && value){
            const next = value.active ? 1 : 0;
            setApprovalActiveCount(prev => (prev === next ? prev : next));
          }
        })
        .catch(()=>{});
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void read();
    };
    void read();
    const timer=setInterval(read,12000);
    document.addEventListener('visibilitychange', onVisibility);
    return()=>{disposed=true;controller.abort();clearInterval(timer);document.removeEventListener('visibilitychange', onVisibility);};
  },[workspaceId, canApproval]);
  const [taskKind, setTaskKind] = useState<TaskKind>(() => {
    const initial = initialTaskKind();
    if (initial === 'payroll' && !canPayroll) {
      if (canCollection) return 'download';
      if (canReports) return 'generate';
    }
    if (initial === 'download' && !canCollection) {
      if (canReports) return 'generate';
      if (canPayroll) return 'payroll';
    }
    if (initial === 'generate' && !canReports) {
      if (canCollection) return 'download';
      if (canPayroll) return 'payroll';
    }
    return initial;
  });
  useEffect(() => {
    if (!canCollection && !canReports && !canPayroll && canApproval && workspaceView === 'create') {
      setWorkspaceView('approval');
    } else if (!canCollection && !canReports && !canPayroll && !canApproval && workspaceView === 'create') {
      setWorkspaceView('history');
    }
  }, [canCollection, canReports, canPayroll, canApproval]);
  const [taskFormLocked, setTaskFormLocked] = useState(false);
  const [activeDownloadCount, setActiveDownloadCount] = useState(0);
  const [taskAttentionCount, setTaskAttentionCount] = useState(0);
  const [autoJumpTaskCenter, setAutoJumpTaskCenter] = useState<boolean>(() => readAutoJumpPreference());
  const [taskReturnTarget, setTaskReturnTarget] = useState<TaskReturnTarget | null>(null);
  const [taskHighlightId, setTaskHighlightId] = useState('');
  const [taskFocusRecordId, setTaskFocusRecordId] = useState('');
  const [taskAlerts, setTaskAlerts] = useState<TaskStatusAlert[]>([]);
  const taskSnapshotRef = useRef<Map<string, string> | null>(null);
  const seenTaskAlertKeysRef = useRef<Set<string>>(new Set());
  const [payrollResumeVersion, setPayrollResumeVersion] = useState(0);
  const mainScrollRef = useRef<HTMLElement | null>(null);
  const lastRouteSigRef = useRef('');
  const currentRouteSig = `${workspaceView}|${taskKind}|${downloadPlatform}|${activeReportId}|${payrollSubView}`;
  useLayoutEffect(() => {
    if (!lastRouteSigRef.current) {
      lastRouteSigRef.current = currentRouteSig;
      return;
    }
    if (lastRouteSigRef.current !== currentRouteSig) {
      lastRouteSigRef.current = currentRouteSig;
      if (mainScrollRef.current) {
        mainScrollRef.current.scrollTop = 0;
      }
    }
  }, [currentRouteSig]);

  const handleToggleAutoJumpTaskCenter = (next: boolean) => {
    setAutoJumpTaskCenter(next);
    writeAutoJumpPreference(next);
  };
  useEffect(() => { try { localStorage.setItem('workbench_task_kind', taskKind); } catch {} setActiveMenu(taskKind === 'payroll' ? 'core' : 'fengshen_downloads'); }, [taskKind]);
  const navigateWorkspace = (
    view:
      | 'create'
      | 'history'
      | 'approval'
      | 'price-export'
      | 'pickup'
      | 'accounts'
      | 'platform-auth'
      | 'display-adaptation',
  ) => {
    if (view === 'accounts' && currentUser.role !== 'admin') {
      showToast('仅系统管理员可访问账户与权限管理', 'error');
      return;
    }
    setWorkspaceView(view);
    if (view === 'create' || view === 'history') {
      setDownloadNavigation(previous => ({ view, version: previous.version + 1 }));
    }
  };
  const triggerUrlDownload = (url: string) => {
    const link = document.createElement('a');
    link.href = url;
    link.download = '';
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
  };
  const openDownloadModule=(platform:DownloadPlatform)=>{
    setDownloadPlatform(platform);try{localStorage.setItem('workbench_download_platform',platform);}catch{}
    setHistoryAll(false);setTaskKind('download');navigateWorkspace('create');
  };
  const openReportModule = (reportId: string) => {
    setActiveReportId(reportId);
    try { localStorage.setItem('workbench_active_report_id', reportId); } catch {}
    setHistoryAll(false);
    setTaskKind('generate');
    navigateWorkspace('create');
  };
  const [platformStatuses, setPlatformStatuses] = useState<PlatformStatusMap>({});
  useEffect(() => {
    const onStatuses = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail && typeof detail === 'object') {
        setPlatformStatuses(prev =>
          arePlatformStatusMapsEqual(prev, detail as PlatformStatusMap)
            ? prev
            : (detail as PlatformStatusMap),
        );
      }
    };
    window.addEventListener('workbench:platform-statuses', onStatuses);
    return () => window.removeEventListener('workbench:platform-statuses', onStatuses);
  }, []);

  const [mountedPanels, setMountedPanels] = useState<{
    batches: boolean;
    deductions: boolean;
    templates: boolean;
    approval: boolean;
    priceExport: boolean;
  }>(() => ({
    batches: workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'batches',
    deductions: workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'deductions',
    templates: workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'templates',
    approval: workspaceView === 'approval',
    priceExport: workspaceView === 'price-export',
  }));

  useEffect(() => {
    const wantBatches = workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'batches';
    const wantDeductions = workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'deductions';
    const wantTemplates = workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'templates';
    const wantApproval = workspaceView === 'approval';
    const wantPriceExport = workspaceView === 'price-export';
    setMountedPanels(prev => {
      if (
        ( !wantBatches || prev.batches ) &&
        ( !wantDeductions || prev.deductions ) &&
        ( !wantTemplates || prev.templates ) &&
        ( !wantApproval || prev.approval ) &&
        ( !wantPriceExport || prev.priceExport )
      ) {
        return prev;
      }
      return {
        batches: prev.batches || wantBatches,
        deductions: prev.deductions || wantDeductions,
        templates: prev.templates || wantTemplates,
        approval: prev.approval || wantApproval,
        priceExport: prev.priceExport || wantPriceExport,
      };
    });
  }, [workspaceView, taskKind, payrollSubView]);
  const openTaskCenterFromCurrent = (options?: { focusId?: string; highlightId?: string }) => {
    const returnTarget = buildTaskReturnTarget({
      workspaceView,
      taskKind,
      downloadPlatform,
      payrollSubView,
      reportId: activeReportId,
    });
    if (returnTarget) {
      setTaskReturnTarget(returnTarget);
    }
    if (options?.focusId) {
      setTaskFocusRecordId(options.focusId);
    }
    if (options?.highlightId) {
      setTaskHighlightId(options.highlightId);
    }
    setHistoryAll(true);
    setTaskKind('download');
    navigateWorkspace('history');
  };

  const executeShellAction = (action: ShellCommandAction) => {
    if (action.type === 'platform') {
      setTaskReturnTarget(null);
      openDownloadModule(action.platform);
      setMobileNavOpen(false);
      return;
    }
    if (action.type === 'report') {
      setTaskReturnTarget(null);
      openReportModule(action.reportId);
      setMobileNavOpen(false);
      return;
    }
    if (action.type === 'payroll') {
      setTaskReturnTarget(null);
      setPayrollSubView(action.subView);
      setTaskKind('payroll');
      navigateWorkspace('create');
      setMobileNavOpen(false);
      return;
    }
    if (action.type === 'workspace') {
      if (action.view === 'history') {
        openTaskCenterFromCurrent();
      } else {
        setTaskReturnTarget(null);
        setPriceRecordId(undefined);
        navigateWorkspace(action.view);
      }
      setMobileNavOpen(false);
      return;
    }
    if (action.type === 'open-dock') {
      navigateWorkspace('platform-auth');
      if (action.source) {
        window.dispatchEvent(new CustomEvent('workbench:connections', { detail: action.source }));
      }
      setMobileNavOpen(false);
      return;
    }
    if (action.type === 'open-logs') {
      setLogDrawerOpen(true);
      return;
    }
    if (action.type === 'toggle-sidebar') {
      toggleSidebarCollapsed();
    }
  };
  const [downloadNavigation, setDownloadNavigation] = useState({ view: 'create' as 'create' | 'history', version: 0 });
  const uploadSubmission = useRef(false);
  const [payrollPreparation, setPayrollPreparation] = useState<PayrollPreparationState | null>(null);
  useEffect(() => {
    setPayrollPreparation(null);
    const linkedBatch = new URLSearchParams(window.location.search).get('batch');
    let savedPrepId: string | null = null;
    try { savedPrepId = localStorage.getItem(`payroll_preparation_${workspaceId}`); } catch {}
    const id = linkedBatch && /^[a-f0-9]{32}$/.test(linkedBatch) ? linkedBatch : savedPrepId;
    if (!id) return;
    let active = true;
    fetchWithAuth(`/api/parttime/preparations/${id}`).then(r => r.ok ? r.json() : null)
      .then(value => { if (active && value) { setPayrollPreparation(value); try { localStorage.setItem(`payroll_preparation_${workspaceId}`, value.id); } catch {} } }).catch(() => {});
    return () => { active = false; };
  }, [workspaceId]);

  const [runningTask, setRunningTask] = useState<string | null>(null);
  const executionSequence = useRef(0);
  const [isRiderSourceUploading, setIsRiderSourceUploading] = useState(false);
  const [lastRiderSourcesOutput, setLastRiderSourcesOutput] = useState<string | null>(null);
  const [lastShangyiOutput, setLastShangyiOutput] = useState<string | null>(null);
  const [lastOutputFolder, setLastOutputFolder] = useState<string | null>(() => {
    try { return localStorage.getItem("lastOutputFolder") || null; } catch { return null; }
  });
  const [lastRunResult, setLastRunResult] = useState<RunResult | null>(null);
  useEffect(() => {
    if (!payrollPreparation || runningTask || !['preparing', 'calculating', 'stopping'].includes(payrollPreparation.status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetchWithAuth(`/api/parttime/preparations/${payrollPreparation.id}`, { signal: controller.signal });
        if (response.ok && !stopped) {
          const value = await response.json();
          setPayrollPreparation(value);
          if (value.result?.output) { setLastOutputFolder(value.result.output); try { localStorage.setItem('lastOutputFolder', value.result.output); } catch {} }
          if (!['preparing', 'calculating', 'stopping'].includes(value.status)) return;
        }
      } catch { /* Preserve the last known state while the network reconnects. */ }
      if (!stopped) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [payrollPreparation?.id, payrollPreparation?.status, runningTask, workspaceId]);


  const isRunning = runningTask !== null;
  const [progressMap, setProgressMap] = useState<Record<string, number>>({});
  const [progressTextMap, setProgressTextMap] = useState<Record<string, string>>({});

  const progress = progressMap['core'] || 0;
  const progressText = progressTextMap['core'] || '等待开始';

  const setProgress = (val: number, target: string = "core") => {
    if (target === 'download_rider_sources' || target === 'download_shangyi_employees') target = 'core';
    setProgressMap(prev => ({ ...prev, [target]: val }));
  };

  const _setProgressText = (text: string, target: string = "core") => {
    if (target === 'download_rider_sources' || target === 'download_shangyi_employees') target = 'core';
    setProgressTextMap(prev => ({ ...prev, [target]: text }));
  };
  
  const [activePrompt, setActivePrompt] = useState<{ uuid: string; title: string; message: string } | null>(null);
  const [fengshenLoginRequest, setFengshenLoginRequest] = useState(0);
  const [downloadAccountId, setDownloadAccountId] = useState<string | undefined>();
  useEffect(() => { setFengshenLoginRequest(0); }, [workspaceId]);
  const [fengshenAuthStatus, setFengshenAuthStatus] = useState<FengshenAuthStatus | null>(null);
  const [fengshenAuthEvent, setFengshenAuthEvent] = useState<FengshenAuthStatus | null>(null);

  useEffect(() => {
    syncGlobalPlatformAuth(platformStatuses, fengshenAuthStatus);
  }, [platformStatuses, fengshenAuthStatus]);

  const [logsMap, setLogsMap] = useState<Record<string, LogEntry[]>>({});

  const logs = logsMap['core'] || [{ text: theme.log_init, level: "INFO" }];

  const setLogs = (updater: any, target: string = activeMenu) => {
    if (target === 'download_rider_sources' || target === 'download_shangyi_employees') target = 'core';
    // Determine the target menu. If this is called from within an async task,
    // we should ideally use the action name but for simplicity we can use activeMenu.
    // To make it robust, we'll keep activeMenu.
    setLogsMap(prev => {
        const prevLogs = prev[target] || [{ text: theme.log_init, level: "INFO" }];
        const newLogs = typeof updater === "function" ? updater(prevLogs) : updater;
        return { ...prev, [target]: newLogs };
    });
  };

  const [activeTab, setActiveTab] = useState<"task" | "output">("output");
  const [downloadPrefill, setDownloadPrefill] = useState<{
    cities?: string[];
    start?: string;
    end?: string;
    datasets?: string[];
    taskKind?: 'download' | 'generate';
    token?: number;
  } | null>(null);

  const handleNavigateGenerate = (cities: string[], start?: string, end?: string) => {
    openReportModule('payment_binding');
    setDownloadPrefill({
      cities,
      start,
      end,
      datasets: ['payment_binding'],
      taskKind: 'generate',
      token: Date.now(),
    });
    showToast(
      cities.length
        ? `已带入 ${cities.length} 个城市至「业务报表 / 支付绑定」，请确认月份后生成`
        : '已跳转至「业务报表 / 支付绑定」',
      'info',
    );
  };

  const handleNavigatePayroll = (city?: string) => {
    if (city) {
      setAppConfig(prev => ({ ...prev, city }));
    }
    setPayrollSubView('batches');
    setTaskKind('payroll');
    navigateWorkspace('create');
    showToast(city ? `已切换至兼职薪资核算，目标城市：${city}` : '已切换至兼职薪资核算', 'info');
  };

  const [rawTaskQueue, setRawTaskQueue] = useState<TaskItem[]>([]);
  const isLegacyBindSystemTask = (t: TaskItem) => {
    if (t.isSalaryBind) return true;
    const name = (t.name || '').trim();
    const lowerName = name.toLowerCase();
    return (
      name === '绑定' ||
      name === '发薪工具' ||
      lowerName === 'salary_bind' ||
      lowerName === 'rider_bind'
    );
  };
  const taskQueue = rawTaskQueue.filter(t => !isLegacyBindSystemTask(t));
  const setTaskQueue = (value: TaskItem[] | ((prev: TaskItem[]) => TaskItem[])) => {
    const filterFn = (list: TaskItem[]) => list.filter(t => !isLegacyBindSystemTask(t));
    if (typeof value === 'function') {
      setRawTaskQueue(prev => filterFn(value(prev)));
    } else {
      setRawTaskQueue(filterFn(value));
    }
  };
  const [uploadStatus, setUploadStatus] = useState<any | null>(null);

  const seenProgressTexts = useRef<Set<string>>(new Set());
  const seenLogs = useRef<Set<string>>(new Set());

  const isMuttering = (text: string) => {
    return (
      text.includes("...")
    );
  };

  const setProgressText = (text: string, target: string = "core") => {
    if (isMuttering(text)) {
      if (seenProgressTexts.current.has(text)) return;
      seenProgressTexts.current.add(text);
    }
    // Also add to logs since the frontend can sometimes duplicate
    _setProgressText(text, target);
  };

  const [appConfig, setAppConfig] = useState<AppConfig>(() => {
    const defaultState: AppConfig = {
      city: "",
      payrollSourceMode: "fengshen",
      payrollExcludeSeparation: true,
      sourcePath: "./uploads",
      basePath: "",
      cities: [],
      enableInterceptor: false,
      enableCrossStationMerge: false,
    };
    let saved: string | null = null;
    try { saved = localStorage.getItem("appConfig"); } catch {}
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        delete parsed.cycle;
        delete parsed.cycles;
        parsed.payrollSourceMode = restorePayrollSourceMode(parsed);
        delete parsed.payrollSourceModeSelected;
        return { ...defaultState, ...parsed };
      } catch (e) {
        console.error("Failed to parse appConfig from localStorage", e);
      }
    }
    return defaultState;
  });

  const [directoryCities,setDirectoryCities]=useState<string[]>([]);
  const appStationDirectory=useStationDirectory(appConfig.payrollSourceMode==='xiaoxiang'?'xiaoxiang':'fengshen',fetchWithAuth);
  const [directoryMessage,setDirectoryMessage]=useState('');
  useEffect(() => {
    const controller=new AbortController();
    let sequence=0;
    const accept=(data:any)=>{
      if(controller.signal.aborted || !Array.isArray(data.cities))return;
      setDirectoryCities([...new Set<string>(data.cities.map((c:any)=>c.name).filter((name:any)=>typeof name==='string'))]);
      setDirectoryMessage(data.cities_source==='config'?'当前为本机城市缓存，平台授权范围待刷新确认':'城市来自平台目录；历史归属仍可核对');
    };
    setDirectoryCities([]);
    const lighthouse=appConfig.payrollSourceMode==='xiaoxiang';
    const update=(event:Event)=>{if(!lighthouse){sequence++;accept((event as CustomEvent).detail);}};
    const read=(refresh=false)=>{const request=++sequence;void fetchWithAuth(lighthouse?`/api/workbench/deduction-stations?platform=xiaoxiang${refresh?'&refresh=1':''}`:`/api/fengshen-downloads/options?${refresh?'refresh=1':'cached=1'}`,{signal:controller.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{if(request===sequence)accept(data);}).catch(()=>{if(!controller.signal.aborted && request===sequence){setDirectoryCities([]);setDirectoryMessage('城市目录读取失败，请重试；未使用固定城市列表');}});};
    const changed=()=>{setDirectoryCities([]);read(true);};
    window.addEventListener('workbench:city-directory',update);
    window.addEventListener('workbench:platform-session-changed',changed);
    window.addEventListener('workbench:refresh-city-directory',changed);
    read();
    return()=>{controller.abort();window.removeEventListener('workbench:city-directory',update);window.removeEventListener('workbench:platform-session-changed',changed);window.removeEventListener('workbench:refresh-city-directory',changed);};
  }, [appConfig.payrollSourceMode,workspaceId]);

  const isLoadedRef = React.useRef(false);

  useEffect(() => {
    const fetchWithRetry = async (url: string, retries = 5, delay = 1000) => {
      for (let i = 0; i < retries; i++) {
        try {
          const res = await fetchWithAuth(url);
          const ct = res.headers.get("content-type");
          if (res.ok && ct && ct.includes("application/json")) return res;
        } catch (e) {
          // ignore loop catch
        }
        if (i < retries - 1) await new Promise((r) => setTimeout(r, delay));
      }
      throw new Error("Network response was not ok or not JSON");
    };

    fetchWithRetry("/api/default_paths", 10, 2000)
      .then((res) => res.json())
      .then((defaultData) => {
        fetchWithRetry("/api/config", 2, 1000)
          .then((res) => res.json())
          .then((data) => {
            if (data && Object.keys(data).length > 0 && !data.error) {
              setAppConfig((prev) => {
                let newConfig = { ...prev, ...data };
                if (prev.cities && prev.cities.length > 0) {
                  newConfig.cities = prev.cities;
                }
                if (
                  !newConfig.sourcePath ||
                  newConfig.sourcePath === "./data" ||
                  newConfig.sourcePath === "/mock/data" ||
                  /dist[\\/]data$/i.test(newConfig.sourcePath) ||
                  /[\\/]applet[\\/]data[\\/]/i.test(newConfig.sourcePath) ||
                  /[\\/]三亚$/i.test(newConfig.sourcePath)
                ) {
                  newConfig.sourcePath = defaultData.dataPath;
                }
                return newConfig;
              });
            } else {
              setAppConfig((prev) => {
                let newConfig = { ...prev };
                if (
                  !newConfig.sourcePath ||
                  newConfig.sourcePath === "./data" ||
                  newConfig.sourcePath === "/mock/data" ||
                  /dist[\\/]data$/i.test(newConfig.sourcePath) ||
                  /[\\/]applet[\\/]data[\\/]/i.test(newConfig.sourcePath) ||
                  /[\\/]三亚$/i.test(newConfig.sourcePath)
                ) {
                  newConfig.sourcePath = defaultData.dataPath;
                }
                return newConfig;
              });
            }
          })
          .catch((err) => {
            console.error("Failed to load config from backend", err);
          })
          .finally(() => {
            isLoadedRef.current = true;
          });
      })
      .catch((err) => {
        console.error("Failed to fetch default_paths", err);
        isLoadedRef.current = true;
      });
  }, []);

  useEffect(() => {
    if (!isLoadedRef.current) return;
    try { localStorage.setItem("appConfig", JSON.stringify(appConfig)); } catch {}
    fetchWithAuth("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(appConfig),
    }).catch((err) => console.error("Failed to save config to backend", err));
  }, [appConfig]);

  const appendLog = (text: string, level: LogEntry["level"] = "INFO", target: string = activeMenu) => {
    if (isMuttering(text)) {
      if (seenLogs.current.has(text)) return;
      seenLogs.current.add(text);
    }
    setLogs((prev: any) => [...prev, { text, level }], target);
  };

  const [toastMsg, setToastMsg] = useState<{
    id: number;
    text: string;
    type: string;
    actionLabel?: string;
    onAction?: () => void;
  } | null>(null);
  const showToast = (
    text: string,
    type: string = "info",
    options?: { actionLabel?: string; onAction?: () => void; durationMs?: number },
  ) => {
    const id = Date.now();
    setToastMsg({
      id,
      text,
      type,
      actionLabel: options?.actionLabel,
      onAction: options?.onAction,
    });
    setTimeout(
      () => setToastMsg((prev) => (prev && prev.id === id ? null : prev)),
      options?.durationMs ?? (options?.actionLabel ? 5500 : 3200),
    );
  };

  const handleTaskRecordsPolled = (
    records: TaskNotificationRecord[],
    summary: { activeCount: number; attentionCount: number; readyCount: number },
  ) => {
    setTaskAttentionCount(summary.attentionCount);
    const { alerts, nextSnapshot } = detectTaskNotifications(
      taskSnapshotRef.current,
      records,
      seenTaskAlertKeysRef.current,
    );
    taskSnapshotRef.current = nextSnapshot;
    if (alerts.length > 0) {
      for (const item of alerts) {
        seenTaskAlertKeysRef.current.add(item.key);
      }
      setTaskAlerts(prev => {
        const existingKeys = new Set(prev.map(item => item.key));
        const fresh = alerts.filter(item => !existingKeys.has(item.key));
        return [...fresh, ...prev].slice(0, 4);
      });
      const latest = alerts[0];
      showDesktopNotification(
        latest.kind === 'completed' ? '任务已完成' : '任务需要处理',
        `${latest.title} — ${latest.subtitle}`,
      );
    }
  };

  const handleOpenAlertDirectory = async (alert: TaskStatusAlert) => {
    try {
      const infoRes = await fetchWithAuth(
        `/api/workbench/task-center/directory?record_id=${encodeURIComponent(alert.taskId)}`,
        { signal: AbortSignal.timeout(15000) },
      );
      const info = await infoRes.json().catch(() => ({}));
      if (infoRes.ok && info.exists && info.can_open) {
        const openRes = await fetchWithAuth('/api/workbench/task-center/directory/open', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ record_id: alert.taskId }),
          signal: AbortSignal.timeout(15000),
        });
        if (openRes.ok) {
          showToast('已打开本地结果目录', 'success');
          return;
        }
      }
    } catch {
      // Fallback to opening the task detail drawer in Task Center.
    }
    openTaskCenterFromCurrent({ focusId: alert.taskId });
  };

  const handleTaskSubmitted = (info: { id: string; name: string; autoJump: boolean }) => {
    if (info.autoJump) {
      openTaskCenterFromCurrent({ highlightId: info.id });
      showToast(`已提交「${info.name}」，已定位到任务中心`, 'success');
      return;
    }
    showToast(`「${info.name}」已在后台开始执行`, 'success', {
      actionLabel: '查看任务中心',
      onAction: () => openTaskCenterFromCurrent({ highlightId: info.id }),
    });
  };

  const uploadExtractedFilesAndGetPath = async (
    initialFileList: { file: File; relativePath: string }[],
    downloadOnly = false,
  ): Promise<{ path: string, tasks: any[] } | null> => {
    if (!initialFileList || initialFileList.length === 0) {
      return null;
    }

    // Filter out irrelevant files before zipping to optimize cloud upload
    const allowedExtensions = ['.xls', '.xlsx', '.csv', '.txt'];
    const fileList = initialFileList.filter(f => 
      allowedExtensions.some(ext => f.relativePath.toLowerCase().endsWith(ext)) && 
      !f.relativePath.split('/').pop()?.startsWith('~') && 
      !f.relativePath.includes('.DS_Store')
    );

    if (fileList.length === 0) {
      showToast("目录中未找到表格文件(Excel/CSV)", "warn");
      return null;
    }

    try {
      setUploadStatus({
        active: true,
        stage: 'zipping',
        fileCount: fileList.length,
      });
      setLogs([
        {
          text: `>>> 📦 正在打包过滤后的有效表格文件并上传服务器... (共 ${fileList.length} 个文件)`,
          level: "INFO",
        },
      ]);
      setLogs((prev: any[]) => [
        ...prev,
        { text: `>>> 📦 打包中，请稍候...`, level: "INFO" },
      ]);
      const blob = await createUploadArchive(fileList, percent => setUploadStatus((prev: any) => prev ? {...prev, stage: 'zipping', percent} : null));

      const sizeStr = `${(blob.size / 1024 / 1024).toFixed(2)} MB`;
      setUploadStatus((prev: any) => prev ? { ...prev, stage: 'uploading', size: sizeStr, percent: 0 } : null);
      setLogs((prev: any[]) => [
        ...prev,
        {
          text: `>>> ☁️ 正在上传资料... (压缩包体积: ${sizeStr})`,
          level: "INFO",
        },
      ]);
      const formData = new FormData();
      formData.append("file", blob, "source.zip");


      setLogs((prev: any[]) => [
        ...prev,
        {
          text: `>>> 正在发送资料，传输完成后由服务器解包与检查目录...`,
          level: "INFO",
        },
      ]);
      const r = await uploadSource('/api/upload/source_zip', formData, workspaceId,
        percent => setUploadStatus((prev: any) => prev ? { ...prev, stage: 'uploading', percent } : null),
        () => setUploadStatus((prev: any) => prev ? { ...prev, stage: 'extracting', percent: 100 } : null));
      const ct = r.headers.get("content-type");
      if (!r.ok && (!ct || !ct.includes("application/json"))) {
        if (r.status === 413) throw new Error("文件体积过大，超出上传限制 (413)");
        throw new Error(`服务器异常 (${r.status})`);
      }
      const d = await r.json();

      if (d.success && d.path) {
        setUploadStatus((prev: any) => prev ? { ...prev, stage: 'success' } : null);
        setLogs((prev: any[]) => [
          ...prev,
          {
            text: downloadOnly ? '资料已上传，准备下载骑手原始资料' : `>>> 资料上传与目录整理完成，正在校验模板，自动识别范围并准备资料、核算...`,
            level: "SUCCESS",
          },
        ]);
        setTimeout(() => {
          setUploadStatus((prev: any) => prev?.stage === 'success' ? null : prev);
        }, 1200);
        return { path: d.path, tasks: d.tasks || [] };
      } else {
        throw new Error(d.error || "上传失败");
      }
    } catch (err: any) {
      setUploadStatus({
        active: true,
        stage: 'error',
        error: err.message || String(err),
      });
      setTimeout(() => {
        setUploadStatus(null);
      }, 6000);
      setLogs((prev: any[]) => [
        ...prev,
        { text: `>>> ❌ 处理出错: ${err}`, level: "ERROR" },
      ]);
      showToast("处理出错", "error");
      return null;
    }
  };

  const uploadFilesAndExecute = async (files: { file: File; relativePath: string }[]) => {
    if (!files.length || uploadSubmission.current) return;
    uploadSubmission.current = true;
    try {
      const groups = planPayrollUpload(files);
      let totalTasks = 0;
      for (const group of groups) {
        const uploaded = await uploadExtractedFilesAndGetPath(group.files);
        if (!uploaded) continue;
        let safeSession: Storage | undefined;
        try { safeSession = sessionStorage; } catch {}
        const attempt = prepareQueueSubmission(workspaceId, {
          source_path: uploaded.path,
          mode: group.mode,
          config: { ...appConfig },
        }, safeSession);
        const submitted = await sendQueueSubmission(workspaceId, attempt, fetchWithAuth, safeSession);
        totalTasks += submitted.tasks.length;
        window.dispatchEvent(new CustomEvent('payroll-queue:changed', { detail: { tasks: submitted.tasks } }));
      }
      setUploadStatus(null);
      appendLog(`已加入 ${totalTasks} 个核算任务，按提交顺序执行。`, 'INFO', 'core');
      window.dispatchEvent(new CustomEvent('payroll-queue:changed'));
    } catch (error) {
      setUploadStatus(null);
      const message = error instanceof Error ? error.message : '模板无法读取';
      appendLog(message, 'ERROR', 'core');
      showToast(message, 'error');
    } finally {
      uploadSubmission.current = false;
    }
  };

  const recoveredQueueSubmission=useRef('');
  useEffect(()=>{
    let safeSession: Storage | undefined;
    try { safeSession = sessionStorage; } catch {}
    const attempt=pendingQueueSubmission(workspaceId,safeSession);
    if(!attempt||recoveredQueueSubmission.current===attempt.request_id)return;
    recoveredQueueSubmission.current=attempt.request_id;
    void sendQueueSubmission(workspaceId,attempt,fetchWithAuth,safeSession).then(()=>{
      window.dispatchEvent(new CustomEvent('payroll-queue:changed'));
      showToast('原提交已确认，核算队列已恢复。','info');
    }).catch(error=>showToast(error instanceof Error?error.message:'任务提交结果尚未确认','warn'));
  },[workspaceId]);

  const downloadRiderSources = async (file: File) => {
    if (isRunning || isRiderSourceUploading) return;
    setIsRiderSourceUploading(true);
    try {
      if (!file.name.toLowerCase().includes('template') || !file.name.toLowerCase().endsWith('.xlsx')) {
        throw new Error('请选择一个 .xlsx 薪资申请表（标准模板）文件');
      }
      const uploaded = await uploadExtractedFilesAndGetPath([{ file, relativePath: file.name }], true);
      if (!uploaded) return;
      const response = await fetchWithAuth('/api/parttime/fengshen/rider-sources/plan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: uploaded.path }),
      });
      if (!response.ok) throw new Error('骑手资料模板预检接口不可用');
      const data = await response.json();
      if (!data.success) throw new Error(data.error || '骑手资料模板预检失败');
      await handleRun({ action: 'download_rider_sources', sourcePath: uploaded.path, city: data.plan.city });
    } catch (error) {
      const message = error instanceof Error ? error.message : '骑手资料下载未启动';
      appendLog(message, 'ERROR', 'core');
      showToast(message, 'error');
    } finally {
      setIsRiderSourceUploading(false);
    }
  };

  const handleRun = async (overrides?: Partial<AppConfig>) => {
    if (isRunning || (isRiderSourceUploading && overrides?.action !== 'download_rider_sources')) return;
    const executionId = ++executionSequence.current;
    
    seenProgressTexts.current.clear();
    seenLogs.current.clear();
    const targetAction = overrides?.action || "core";
    const riderDownload = targetAction === 'download_rider_sources';
    const shangyiDownload = targetAction === 'download_shangyi_employees';
    const sourceDownload = riderDownload || shangyiDownload;
    setRunningTask(targetAction);
    setProgress(0, targetAction);
    setProgressText(shangyiDownload ? '正在下载商翼员工原始资料' : riderDownload ? '正在下载骑手原始资料' : targetAction === "core" ? "正在校验模板与核算资料" : "正在启动核算", targetAction);

    const initText = shangyiDownload ? '正在下载商翼全部员工原始资料，未执行核算' : riderDownload ? '>>> 正在下载三份骑手原始资料，未执行核算' : targetAction === "core"
      ? ">>> 正在准备兼职核算资料"
      : ">>> 正在启动核算";
    seenLogs.current.add(initText);
    setLogs([{ text: initText, level: "SYSTEM" }], targetAction);

    if ("Notification" in window && Notification.permission !== "denied" && Notification.permission !== "granted") {
      Notification.requestPermission();
    }

    const wid = getWorkspaceId();
    if (!sourceDownload) {
      try {
        localStorage.removeItem(`deduction_config_v5_${wid}`);
      } catch(e) {}
    }
    let effectiveConfig = { ...appConfig, taskQueue: taskQueue.map(t => t.id), ...overrides, action: targetAction };
    if (targetAction === 'core') effectiveConfig.payrollPreparationId = overrides?.payrollPreparationId || '';

    // Check if sourcePath is invalid or placeholder
    if (!effectiveConfig.payrollPreparationId && !shangyiDownload && (
      !effectiveConfig.sourcePath ||
      ["/mock/data", "./data", "."].includes(effectiveConfig.sourcePath.trim())
    )) {
      try {
        const smartResp = await fetchWithAuth(`/api/dialog/smart_source`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const ct = smartResp.headers.get("content-type");
        if (!smartResp.ok || !ct || !ct.includes("application/json")) throw new Error("Smart source failed");
        const smartData = await smartResp.json();

        if (smartData.smart && smartData.path) {
          effectiveConfig.sourcePath = smartData.path;
          setAppConfig((prev) => ({ ...prev, sourcePath: smartData.path }));
          appendLog(
            `[SYS] 检测到系统高速缓存，自动建立数据源软链接: ${smartData.path}`,
            "INFO",
            targetAction
          );
        } else {
          showToast("必须先选择干活灶台 (有效的数据目录) 才能执行！", "warn");
          appendLog(
            `[ERROR] 核心数据槽位 (干活灶台) 未挂载，拒绝执行！`,
            "ERROR",
            targetAction
          );
          setRunningTask(null);
          return;
        }
      } catch (err) {
        showToast("无法校验干活灶台目录", "error");
        appendLog(`[ERROR] 目录校验失败: ${err}`, "ERROR", targetAction);
        setRunningTask(null);
        return;
      }
    }

    appendLog(`正在连接核算服务`, "INFO", targetAction);

    try {
      const response = await fetchWithAuth("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...effectiveConfig,
          theme: {
            msg_start: [
              "正在启动薪资核算流程...",
              "正在校验数据源...",
            ],
            msg_awake: [
              "数据处理模块就绪。",
            ],
            msg_empty: [
              "当前工作区未检测到待处理文件。",
            ],
            msg_process: [
              "开始处理文件：{wb_name}",
              "正在计算薪资明细：{wb_name}",
            ],
            msg_success: [
              "✅ 处理成功：{wb_name}",
            ],
            msg_final: [
              "提示：检测到数据异常: {result_msg}",
            ],
            msg_end: [
              "薪资核算完成。",
            ],
          },
        }),
      });

      if (!response.ok) {
         let errMsg = "请求失败";
         try {
             const ct = response.headers.get("content-type");
             if (ct && ct.includes("application/json")) {
                 const errData = await response.json();
                 errMsg = errData.error || (typeof errData.detail === 'string' ? errData.detail : `请求参数或接口异常 (${response.status})`);
             } else {
                 errMsg = `服务器异常 (${response.status})`;
             }
         } catch (e) {}
         throw new Error(errMsg);
      }

      if (!response.body) throw new Error("服务器无响应数据流");

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const payload = line.substring(6).trim();
              if (!payload) continue;
              const data = JSON.parse(payload);

              if (data.type === 'payroll_stage') { setProgressText(data.text || '正在处理核算资料', targetAction); continue; }
              if (data.type === 'payroll_preparation') {
                setPayrollPreparation(data.preparation);
                try { localStorage.setItem(`payroll_preparation_${workspaceId}`, data.preparation.id); } catch {}
                continue;
              }
              if (data.type === "fengshen_auth") {
                setFengshenAuthEvent(data.status);
                if (data.status.state === 'login_required') setProgressText('等待风神登录验证', targetAction);
                continue;
              }
              if (data.type === "missing_city") {
                setMissingCityTeams(data.teams);
                setMissingCityUuid(data.uuid);
                const initialMap: Record<string, string> = {};
                data.teams.forEach((t: string) => initialMap[t] = "");
                setMissingCityMap(initialMap);
                appendLog(`发现 ${data.teams.length} 个未匹配城市，等待输入...`, "WARN");
                continue;
              }
              if (data.type === "log") {
                if (data.msg.includes("!!CITY!!")) {
                  const parts = data.msg.split("!!CITY!!");
                  appendLog(parts[0], data.level, targetAction);
                  setAppConfig((prev) => ({ ...prev, city: parts[1] }));
                } else {
                  appendLog(data.msg, data.level, targetAction);
                  if (data.msg.includes("开始执行子任务")) {
                    const match = data.msg.match(/开始执行子任务 \[.*?\]: (.*)/);
                    if (match && match[1] && targetAction === "core") {
                      setTaskQueue(prev => prev.map(t => t.id === match[1] ? { ...t, status: 'running' } : t));
                    }
                  } else if (data.msg.includes("执行成功") && data.msg.includes("子任务")) {
                    const match = data.msg.match(/子任务 (.*?) 执行成功(?: \| OUT:(.*))?/);
                    if (match && match[1] && targetAction === "core") {
                      const outPath = match[2] ? match[2].trim() : undefined;
                      setTaskQueue(prev => prev.map(t => t.id === match[1] ? { ...t, status: 'completed', outPath, mtime: Date.now() / 1000 } : t));
                    }
                  } else if (data.msg.includes("执行失败") && data.msg.includes("子任务")) {
                    const match = data.msg.match(/子任务 (.*) 执行失败/);
                    if (match && match[1] && targetAction === "core") {
                      setTaskQueue(prev => prev.map(t => t.id === match[1] ? { ...t, status: 'error' } : t));
                    }
                  }
                }
              } else if (data.type === "progress") {
                setProgress(Math.floor(data.value * 100), targetAction);
                if (data.text) setProgressText(data.text, targetAction);
              } else if (data.type === "prompt") {
                setActivePrompt({ uuid: data.uuid, title: data.title, message: data.message });
              } else if (data.type === "finish") {
                setRunningTask(null);
                if (data.status === 'paused') {
                  setProgressText(data.result_msg || '等待处理核算资料', targetAction);
                  appendLog(data.result_msg || '等待处理核算资料', 'WARN', targetAction);
                  continue;
                }
                setLastRunResult({
                  action: targetAction,
                  status: data.status === 'success' ? 'success' : 'error',
                  resultMsg: data.result_msg || '',
                  outPath: data.out_file || undefined,
                  finishedAt: Date.now(),
                  stats: data.stats || undefined,
                  review: data.review_summary || undefined,
                });
                if (targetAction === 'core' && data.status === 'success') {
                  setPayrollPreparation(previous => previous ? {...previous, status: 'calculated', result: { ...previous.result, output: data.out_file || '', input_hashes_verified: true, review_summary: data.review_summary || previous.result?.review_summary }} : previous);
                }
                if (data.status === "error") {
                  setProgressText(
                    `执行失败: ${data.result_msg}`,
                    targetAction
                  );
                  appendLog(`[ERROR] 执行失败: ${data.result_msg}`, "ERROR", targetAction);
                } else {
                  setProgress(100, targetAction);
                  setProgressText(
                    data.result_msg || "系统休眠中...",
                    targetAction
                  );
                }

                if (data.status === "success") {
                  setProgress(100, targetAction);
                  appendLog(`>>> 🎉 任务完成！`, "SUCCESS", targetAction);
                  showDesktopNotification("任务执行完毕", sourceDownload ? '原始资料已下载并校验，未执行核算' : "该次核算已圆满完成！");
                  if (data.out_file) {
                    if (targetAction === "core") {
                      setLastOutputFolder(data.out_file);
                      try { localStorage.setItem("lastOutputFolder", data.out_file); } catch {}
                    } else if (riderDownload) {
                      setLastRiderSourcesOutput(data.out_file);
                    } else if (shangyiDownload) {
                      setLastShangyiOutput(data.out_file);
                    }
                    appendLog(sourceDownload ? `原始资料及校验清单已保存至: ${data.out_file}` : `>>> 📦 生成的工作薄已保存至: ${data.out_file}，请点击【导出列表】查看下载`, "SUCCESS", targetAction);
                  }
                  appendLog(
                    `>>> 薪资计算与对账结果已成功生成。`,
                    "INFO",
                    targetAction
                  );
                  showToast("任务圆满完成!", "success");
                } else {
                  appendLog(
                    `[引擎断开] ${data.result_msg || "发生未知错误"}`,
                    "ERROR",
                    targetAction
                  );
                  showToast(
                    `发生异常: ${data.result_msg || "未知错误"}`,
                    "error",
                  );
                }
              }
            } catch (e) {
              // Ignore malformed JSON chunks from raw console prints
            }
          }
        }
      }
    } catch (err) {
      appendLog(
        `[ERROR] 本地后端服务未响应，请确保通过 node server.ts 正常启动！: ${String(err)}`,
        "ERROR",
        targetAction
      );
      showToast("无法连接运算引擎", "error");
      setRunningTask(null);
      setLastRunResult({
        action: targetAction,
        status: 'error',
        resultMsg: String(err),
        finishedAt: Date.now(),
      });
    } finally {
      // A disconnected event stream does not stop the durable server task.
      // Release the browser busy state so manifest polling can reconnect.
      if (executionSequence.current === executionId) setRunningTask(null);
    }
  };

  return (
    <div className="workbench-app">
      <div
        className={`wb-shell wbx-shell ${sidebarIsCollapsed ? 'has-collapsed-sidebar' : ''}`}
        data-sidebar={sidebarIsCollapsed ? 'collapsed' : 'expanded'}
        data-collapsed={sidebarIsCollapsed ? 'true' : 'false'}
        data-mobile-open={mobileNavOpen ? 'true' : 'false'}
      >
        {mobileNavOpen && (
          <button
            type="button"
            className="wbx-scrim"
            aria-label="关闭导航抽屉"
            onClick={() => setMobileNavOpen(false)}
          />
        )}
        <DualRailSidebar
          workspaceView={workspaceView}
          taskKind={taskKind}
          downloadPlatform={downloadPlatform}
          activeReportId={activeReportId}
          payrollSubView={payrollSubView}
          collapsed={sidebarIsCollapsed}
          isDrawerMode={isDrawerMode}
          taskFormLocked={taskFormLocked}
          platformStatuses={platformStatuses}
          activeDownloadCount={activeDownloadCount}
          payrollBadge={getPayrollSidebarBadge(payrollPreparation?.status, isRunning)}
          approvalActiveCount={approvalActiveCount}
          approvalPendingCount={approvalPendingCount}
          totalActiveCount={activeDownloadCount + (isRunning ? 1 : 0) + approvalActiveCount}
          taskAttentionCount={taskAttentionCount}
          onExecuteAction={executeShellAction}
          onToggleCollapse={toggleSidebarCollapsed}
          onCloseMobile={() => setMobileNavOpen(false)}
          onOpenPlatformDock={() => setDockOpen(true)}
          permissions={currentUser.permissions}
          isAdmin={currentUser.role === 'admin'}
          pendingAccountCount={session.pending_count}
          displayAdaptationBadge={formatDisplayAdaptationBadge(displayConfig, screenEnv.detectedClass)}
        />
        <div className="wb-viewport wbx-workspace">
          {(() => {
            const breadcrumbModel = getBreadcrumbModel({
              workspaceView,
              taskKind,
              downloadPlatform,
              payrollSubView,
              reportId: activeReportId,
            });
            const errorLogCount = logs.filter(entry => entry.level === 'ERROR').length;
            const totalActiveCount =
              activeDownloadCount + (isRunning ? 1 : 0) + approvalActiveCount;

            return (
              <header className="wb-header wbx-header">
                <div className="wb-brand wbx-header__lead">
                  <button
                    type="button"
                    className="wbx-burger"
                    aria-label={mobileNavOpen ? '收起导航' : '展开导航'}
                    aria-expanded={mobileNavOpen}
                    onClick={() => setMobileNavOpen(value => !value)}
                  >
                    <Menu size={17} />
                  </button>

                  <HeaderBreadcrumb
                    model={breadcrumbModel}
                    disabled={taskFormLocked}
                    platformStatuses={platformStatuses}
                    isRunning={isRunning}
                    progress={progress}
                    progressText={progressText}
                    activeDownloadCount={activeDownloadCount}
                    errorLogCount={errorLogCount}
                    onOpenLogDrawer={() => setLogDrawerOpen(true)}
                    onSelect={executeShellAction}
                    onOpenPlatformAuth={plat => {
                      if (plat === 'fengshen') {
                        setFengshenLoginRequest(value => value + 1);
                      } else {
                        window.dispatchEvent(
                          new CustomEvent('workbench:connections', { detail: plat }),
                        );
                      }
                    }}
                  />
                </div>

                <div
                  className="wb-header-actions wbx-header__tools"
                  role="group"
                  aria-label="全局审批待办通知与空间账户"
                >
                  {canApproval && (
                    <HeaderApprovalNotifier
                      apiFetch={fetchWithAuth}
                      workspaceId={workspaceId}
                      isApprovalViewActive={workspaceView === 'approval'}
                      onNavigateApproval={() => navigateWorkspace('approval')}
                      onOpenLanorangeAuth={() =>
                        window.dispatchEvent(
                          new CustomEvent('workbench:connections', { detail: 'lanorange' }),
                        )
                      }
                      onPendingCountChange={setApprovalPendingCount}
                      onShowToast={showToast}
                      onDesktopNotify={showDesktopNotification}
                    />
                  )}

                  <HeaderAccountBar
                    user={currentUser}
                    workspaces={session.workspaces}
                    hostMachine={session.host_machine}
                    hostAutoLogin={session.host_auto_login}
                    canSwitchToHost={session.can_switch_to_host}
                    onSwitchWorkspace={async targetWid => {
                      try {
                        const updated = await switchInspectWorkspace(targetWid);
                        onSessionUpdate(updated);
                        showToast(
                          targetWid
                            ? `已切换至巡检空间：${updated.user?.inspect_target?.display_name || targetWid}`
                            : '已返回管理员主空间',
                          'info',
                        );
                      } catch (err) {
                        showToast(err instanceof Error ? err.message : '切换空间失败', 'error');
                      }
                    }}
                    onSwitchAccount={async payload => {
                      const updated = await loginWorkspaceAccount(payload);
                      onSessionUpdate(updated);
                      showToast(
                        `已切换至账号：${updated.user?.display_name || payload.username}`,
                        'success',
                      );
                    }}
                    onSwitchToHost={async () => {
                      const updated = await switchToHostAdmin();
                      onSessionUpdate(updated);
                      showToast('已一键切回主机管理员身份', 'success');
                    }}
                    onLogout={async () => {
                      await logoutWorkspaceAccount();
                      await onRefreshSession();
                    }}
                    onToast={(msg, type) => showToast(msg, type || 'info')}
                  />
                </div>
              </header>
            );
          })()}
          <main ref={mainScrollRef} className="wb-main wbx-main">
            <div className="wbx-page">
            <WorkspaceInspectBanner
              user={currentUser}
              workspaces={session.workspaces}
              onSwitchWorkspace={targetWid => {
                void switchInspectWorkspace(targetWid)
                  .then(updated => {
                    onSessionUpdate(updated);
                    showToast(
                      targetWid
                        ? `已切换至巡检空间：${updated.user?.inspect_target?.display_name || targetWid}`
                        : '已返回管理员主空间',
                      'info',
                    );
                  })
                  .catch(err => {
                    showToast(err instanceof Error ? err.message : '切换空间失败', 'error');
                  });
              }}
              onExitInspect={() => {
                void switchInspectWorkspace('').then(updated => {
                  onSessionUpdate(updated);
                  showToast('已退出巡检，返回管理员主空间', 'info');
                });
              }}
            />
            {missingCityTeams.length > 0 && (
              <section className="mb-4 rounded-xl border border-amber-300 bg-amber-50/95 p-4 shadow-xs" role="alert" aria-label="未匹配城市团队警告">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-amber-600 font-bold text-base">⚠️</span>
                    <h3 className="text-sm font-bold text-slate-900">发现未匹配城市团队</h3>
                  </div>
                  <button 
                    onClick={handleCancelMissingCities}
                    className="p-1 rounded-lg hover:bg-amber-100 text-slate-500 text-xs"
                    title="取消并关闭"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                
                <p className="text-xs mb-3 text-slate-600">
                  检测到以下团队在配置文件中没有对应的城市映射，请手动指定其归属城市以继续核算流程：
                </p>
                <p className="wb-muted">{directoryMessage}</p>
                <button type="button" className="wb-button" onClick={()=>window.dispatchEvent(new CustomEvent('workbench:refresh-city-directory'))}>刷新城市目录</button>

                <div className="flex flex-col gap-2 max-h-48 overflow-y-auto custom-scrollbar pr-1 mb-3">
                  {missingCityTeams.map((team) => (
                    <div key={team} className="p-2.5 rounded-lg border flex flex-col sm:flex-row sm:items-center justify-between gap-2 bg-white border-amber-200">
                      <span className="text-xs font-medium break-all text-slate-800">
                        {team}
                      </span>
                      
                      <select
                        value={missingCityMap[team] || ""}
                        onChange={(e) => {
                          setMissingCityMap(prev => ({
                            ...prev,
                            [team]: e.target.value
                          }));
                        }}
                        className="text-xs rounded-md border px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-sky-700 max-w-full sm:max-w-[200px] border-slate-300 bg-white text-slate-800"
                      >
                        <option value="">-- 请选择城市 --</option>
                        {directoryCities.map((city) => (
                          <option key={city} value={city}>
                            {city} · {stationCountText(appStationDirectory.data,city)}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-amber-200">
                  <button
                    onClick={handleCancelMissingCities}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg text-slate-600 bg-white border border-slate-300 hover:bg-slate-50"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleSaveMissingCities}
                    disabled={missingCityTeams.some(team => !missingCityMap[team])}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-lg ${
                      missingCityTeams.some(team => !missingCityMap[team])
                        ? 'opacity-50 cursor-not-allowed bg-slate-200 text-slate-400'
                        : 'bg-sky-700 hover:bg-sky-800 text-white'
                    }`}
                  >
                    确认并继续执行
                  </button>
                </div>
              </section>
            )}

            {(mountedPanels.approval || workspaceView === 'approval') && (
              <div
                className="wbx-route-stage"
                hidden={workspaceView !== 'approval'}
                aria-hidden={workspaceView !== 'approval' || undefined}
              >
                <LanorangeApprovals
                  active={workspaceView === 'approval'}
                  focusId={priceRecordId}
                  apiFetch={fetchWithAuth}
                  workspaceId={workspaceId}
                  onActiveCount={setApprovalActiveCount}
                  onSwitchView={view => navigateWorkspace(view)}
                />
              </div>
            )}
            {(mountedPanels.priceExport || workspaceView === 'price-export') && (
              <div
                className="wbx-route-stage"
                hidden={workspaceView !== 'price-export'}
                aria-hidden={workspaceView !== 'price-export' || undefined}
              >
                <LanorangePriceExports
                  active={workspaceView === 'price-export'}
                  focusId={priceRecordId}
                  apiFetch={fetchWithAuth}
                  workspaceId={workspaceId}
                  onActiveCount={setApprovalActiveCount}
                  onSwitchView={view => navigateWorkspace(view)}
                />
              </div>
            )}
            <section
              className="wbx-route-stage"
              hidden={
                workspaceView === 'approval' ||
                workspaceView === 'price-export' ||
                workspaceView === 'pickup' ||
                workspaceView === 'accounts' ||
                workspaceView === 'platform-auth' ||
                workspaceView === 'display-adaptation' ||
                (workspaceView === 'create' &&
                  ((taskKind === 'download' && !canCollection) ||
                    (taskKind === 'generate' && !canReports))) ||
                (workspaceView !== 'history' && taskKind === 'payroll')
              }
              aria-hidden={
                workspaceView === 'approval' ||
                workspaceView === 'price-export' ||
                workspaceView === 'pickup' ||
                workspaceView === 'accounts' ||
                workspaceView === 'platform-auth' ||
                workspaceView === 'display-adaptation' ||
                (workspaceView === 'create' &&
                  ((taskKind === 'download' && !canCollection) ||
                    (taskKind === 'generate' && !canReports))) ||
                (workspaceView !== 'history' && taskKind === 'payroll') ||
                undefined
              }
              aria-label="任务下载"
            >
              <FengshenDownloadCenter
                apiFetch={fetchWithAuth}
                workspaceId={workspaceId}
                navigation={downloadNavigation}
                isVisible={
                  !(
                    workspaceView === 'approval' ||
                    workspaceView === 'price-export' ||
                    workspaceView === 'pickup' ||
                    workspaceView === 'accounts' ||
                    workspaceView === 'platform-auth' ||
                    workspaceView === 'display-adaptation' ||
                    (workspaceView === 'create' &&
                      ((taskKind === 'download' && !canCollection) ||
                        (taskKind === 'generate' && !canReports))) ||
                    (workspaceView !== 'history' && taskKind === 'payroll')
                  )
                }
                embedded
                hideNavigation
                taskKind={taskKind === 'generate' ? 'generate' : 'download'}
                platform={downloadPlatform}
                activeReportId={activeReportId}
                recordModule={undefined}
                onSelectPlatform={(nextPlatform) => {
                  setDownloadPlatform(nextPlatform);
                  try { localStorage.setItem('workbench_download_platform', nextPlatform); } catch {}
                }}
                onSelectReport={(nextReportId) => {
                  setActiveReportId(nextReportId);
                  try { localStorage.setItem('workbench_active_report_id', nextReportId); } catch {}
                }}
                onTaskKindChange={(nextKind) => setTaskKind(nextKind)}
                onViewChange={setWorkspaceView}
                onFormLock={setTaskFormLocked}
                onNavigateGenerate={handleNavigateGenerate}
                onOpenPrice={(view,id)=>{setPriceRecordId(id);navigateWorkspace(view);}}
                prefill={downloadPrefill}
                onActiveCountChange={setActiveDownloadCount}
                onOpenFengshenLogin={() => setFengshenLoginRequest(value => value + 1)}
                onNavigatePayroll={() => {
                  setTaskKind('payroll');
                  setPayrollSubView('batches');
                  navigateWorkspace('create');
                }}
                fengshenAuthStatus={fengshenAuthStatus}
                onAccountChange={setDownloadAccountId}
                autoJumpTaskCenter={autoJumpTaskCenter}
                onAutoJumpTaskCenterChange={handleToggleAutoJumpTaskCenter}
                focusTaskId={taskFocusRecordId}
                onFocusTaskHandled={() => setTaskFocusRecordId('')}
                highlightTaskId={taskHighlightId}
                onHighlightHandled={() => setTaskHighlightId('')}
                returnTarget={taskReturnTarget}
                onReturnSource={
                  taskReturnTarget
                    ? () => {
                        const target = taskReturnTarget;
                        setTaskReturnTarget(null);
                        executeShellAction(target.action);
                      }
                    : undefined
                }
                onTaskSubmitted={handleTaskSubmitted}
              />
            </section>
            {workspaceView === 'pickup' && (
              <section className="wbx-route-stage" aria-label="文件领取">
                <FilePickup apiFetch={fetchWithAuth} />
              </section>
            )}
            <section
              className="wbx-route-stage"
              hidden={workspaceView !== 'platform-auth'}
              aria-hidden={workspaceView !== 'platform-auth' || undefined}
              aria-label="平台授权与系统账户中心"
            >
              <PlatformAuthCenterPage
                apiFetch={fetchWithAuth}
                active={workspaceView === 'platform-auth'}
                fengshenStatus={fengshenAuthStatus}
                onOpenFengshen={() => setFengshenLoginRequest(value => value + 1)}
                onNavigateToSelf={() => navigateWorkspace('platform-auth')}
                isAdmin={currentUser.role === 'admin'}
                canManageSharedAuth={canManageSharedAuth}
                onToast={(msg, type) => showToast(msg, type || 'info')}
              />
            </section>
            {workspaceView === 'display-adaptation' && (
              <section className="wbx-route-stage" aria-label="跨屏界面适配中心">
                <DisplayAdaptationPage
                  apiFetch={fetchWithAuth}
                  config={displayConfig}
                  screenEnv={screenEnv}
                  sidebarCollapsed={sidebarIsCollapsed}
                  onUpdateConfig={handleUpdateDisplayConfig}
                  onResetDefault={handleResetDisplayConfig}
                  onSetSidebarCollapsed={setSidebarCollapsedPersist}
                  onToast={(msg, type) => showToast(msg, type || 'info')}
                />
              </section>
            )}
            {workspaceView === 'accounts' && currentUser.role === 'admin' && (
              <section className="wbx-route-stage" aria-label="账户与模块权限管理">
                <AccountManagementPage
                  currentUserId={currentUser.id}
                  requestedTab={accountsTabReq.tab}
                  requestedTabVersion={accountsTabReq.version}
                  onAccountsChanged={(nextPending, nextWorkspaces) => {
                    onSessionUpdate(prev =>
                      prev ? { ...prev, pending_count: nextPending, workspaces: nextWorkspaces } : prev,
                    );
                  }}
                  onToast={(msg, type) => showToast(msg, type || 'info')}
                />
              </section>
            )}
            {workspaceView === 'create' &&
              ((taskKind === 'download' && !canCollection) ||
                (taskKind === 'generate' && !canReports) ||
                (taskKind === 'payroll' && !canPayroll)) && (
                <section className="wbx-route-stage" aria-label="模块权限引导">
                  <NoModuleAccessNotice
                    displayName={currentUser.display_name}
                    onOpenHistory={() => navigateWorkspace('history')}
                    onOpenPickup={() => navigateWorkspace('pickup')}
                  />
                </section>
              )}
            <section
              className="wbx-route-stage"
              hidden={workspaceView !== 'create' || taskKind !== 'payroll' || !canPayroll}
              aria-hidden={workspaceView !== 'create' || taskKind !== 'payroll' || !canPayroll || undefined}
              aria-label="兼职薪资核算"
            >
              {(mountedPanels.batches || payrollSubView === 'batches') && (
                <div
                  className="wbx-route-stage"
                  hidden={payrollSubView !== 'batches'}
                  aria-hidden={payrollSubView !== 'batches' || undefined}
                >
                  <CorePage
                    active={workspaceView === 'create' && taskKind === 'payroll' && payrollSubView === 'batches'}
                    onOpenDeductions={(defaultOnly = false) => { setDeductionDefaultOnly(defaultOnly); setPayrollSubView('deductions'); }}
                    onOpenConnections={() => window.dispatchEvent(new CustomEvent('workbench:connections'))}
                    onNavigateDownloadCenter={() => { setTaskKind('download'); navigateWorkspace('create'); }}
                    onNavigateTaskCenter={() => navigateWorkspace('history')}
                    deductionVersion={deductionVersion}
                    appTheme={appTheme}
                    config={{...appConfig,cities:directoryCities}}
                    onConfigChange={(patch) => setAppConfig(prev => ({ ...prev, ...patch }))}
                    runningTask={runningTask}
                    isRiderSourceUploading={isRiderSourceUploading}
                    progress={progress}
                    progressText={progressText}
                    logs={logs}
                    taskQueue={taskQueue}
                    payrollPreparation={payrollPreparation}
                    resumeVersion={payrollResumeVersion}
                    onPreparationChange={setPayrollPreparation}
                    apiFetch={fetchWithAuth}
                    uploadExtracted={(file) => uploadExtractedFilesAndGetPath([{ file, relativePath: file.name }], true)}
                    onRun={(overrides) => void handleRun(overrides)}
                    onUploadFiles={uploadFilesAndExecute}
                    onDownloadRiderSources={downloadRiderSources}
                    onDownloadShangyi={() => void handleRun({ action: 'download_shangyi_employees', sourcePath: '' })}
                    onOpenShangyi={lastShangyiOutput ? () => {
                      triggerUrlDownload(`/api/download?path=${encodeURIComponent(lastShangyiOutput)}&workspace_id=${encodeURIComponent(getWorkspaceId())}`);
                    } : undefined}
                    onOpenRiderSources={lastRiderSourcesOutput ? () => {
                      triggerUrlDownload(`/api/download?path=${encodeURIComponent(lastRiderSourcesOutput)}&workspace_id=${encodeURIComponent(getWorkspaceId())}`);
                    } : undefined}
                    onOpenFengshenLogin={() => setFengshenLoginRequest(value => value + 1)}
                    fengshenAuthStatus={fengshenAuthStatus}
                    lastOutputFolder={lastOutputFolder}
                    lastRunResult={lastRunResult}
                    workspaceId={getWorkspaceId()}
                  />
                </div>
              )}

              {(mountedPanels.deductions || payrollSubView === 'deductions') && (
                <div
                  className="wbx-route-stage"
                  hidden={payrollSubView !== 'deductions'}
                  aria-hidden={payrollSubView !== 'deductions' || undefined}
                >
                  <StationDeductionManager
                    inline
                    platform={(!deductionDefaultOnly && payrollPreparation ? payrollPreparation.mode : appConfig.payrollSourceMode) === 'xiaoxiang' ? 'xiaoxiang' : 'fengshen'}
                    apiFetch={fetchWithAuth}
                    onClose={() => setPayrollSubView('batches')}
                    onSaved={() => setDeductionVersion(value => value + 1)}
                  />
                </div>
              )}

              {(mountedPanels.templates || payrollSubView === 'templates') && (
                <div
                  className="wbx-route-stage"
                  hidden={payrollSubView !== 'templates'}
                  aria-hidden={payrollSubView !== 'templates' || undefined}
                >
                  <SystemTemplatesPanel
                    onNavigatePayroll={() => setPayrollSubView('batches')}
                    onQuickUpload={files => {
                      setPayrollSubView('batches');
                      void uploadFilesAndExecute(
                        files.map(file => ({ file, relativePath: file.name })),
                      );
                    }}
                  />
                </div>
              )}
            </section>
            </div>
          </main>
        </div>
      </div>
      {logDrawerOpen && (
        <WorkbenchDrawer
          title="引擎运行日志终端"
          bodyClassName="wbx-drawer__body--flush"
          onClose={() => setLogDrawerOpen(false)}
        >
          <TerminalPanel
            logs={logs}
            progress={progress}
            progressText={progressText}
            isRunning={isRunning}
            showFooterProgress
            embeddedInDrawer
            onClear={() => setLogs([], 'core')}
          />
        </WorkbenchDrawer>
      )}

      <CommandPaletteModal
        open={cmdkOpen}
        commands={buildShellCommands(
          {
            workspaceView,
            taskKind,
            downloadPlatform,
            payrollSubView,
            reportId: activeReportId,
          },
          {
            sidebarCollapsed: sidebarIsCollapsed,
            isAdmin: currentUser.role === 'admin',
            permissions: currentUser.permissions,
          },
        )}
        onClose={() => setCmdkOpen(false)}
        onExecute={executeShellAction}
      />

      <UploadProgressOverlay status={uploadStatus} appTheme={appTheme} />
      <FengshenLoginModal
        workspaceId={workspaceId}
        downloadAccountId="shared"
        autoOpenEnabled={
          workspaceView === 'history' ||
          (workspaceView === 'create' && taskKind === 'download' && downloadPlatform === 'fengshen') ||
          isRunning
        }
        requestVersion={fengshenLoginRequest}
        eventStatus={fengshenAuthEvent}
        onStatus={setFengshenAuthStatus}
      />

      
      <TaskStatusNotifier
        alerts={taskAlerts}
        onDismiss={key => setTaskAlerts(prev => prev.filter(item => item.key !== key))}
        onOpenTask={alert => openTaskCenterFromCurrent({ focusId: alert.taskId })}
        onOpenDirectory={alert => void handleOpenAlertDirectory(alert)}
        onOpenAuth={system => {
          if (system === 'fengshen') {
            setFengshenLoginRequest(value => value + 1);
          } else {
            setDockOpen(true);
          }
        }}
      />

      {toastMsg && (
        <div className="fixed top-5 right-5 z-[9999] pointer-events-none transition-all animate-in fade-in slide-in-from-top-2">
          <div className={`pointer-events-auto px-4 py-3 rounded-xl border shadow-xl text-xs font-semibold flex items-center gap-2.5 ${
            toastMsg.type === 'error' ? 'bg-rose-50 border-rose-200 text-rose-900' :
            toastMsg.type === 'warn' ? 'bg-amber-50 border-amber-200 text-amber-900' :
            'bg-emerald-50 border-emerald-200 text-emerald-900'
          }`}>
            <span>{toastMsg.type === 'error' ? '✕' : toastMsg.type === 'warn' ? '⚠' : '✓'}</span>
            <span>{toastMsg.text}</span>
            {toastMsg.actionLabel && toastMsg.onAction && (
              <button
                type="button"
                className="ml-1 px-2 py-0.5 rounded-md bg-white/85 border border-current/20 hover:bg-white text-[11px] font-semibold cursor-pointer"
                onClick={() => {
                  const act = toastMsg.onAction;
                  setToastMsg(null);
                  act?.();
                }}
              >
                {toastMsg.actionLabel}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
