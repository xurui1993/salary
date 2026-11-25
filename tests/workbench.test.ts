import assert from 'node:assert/strict';
import test from 'node:test';
import {
  validateDeductionRows,
  connectionLabel,
  connectionSummary,
  SYSTEM_META,
  computeBillingPeriodRange,
  computeLighthousePeriodRange,
  buildRecentMonths,
  computeMonthSelectionRange,
  BUILTIN_DOWNLOAD_SCENARIOS,
  inferDatasetSystemTag,
  GENERATION_REPORT_CARDS,
  PAYROLL_MODE_CARDS,
  extractDeductionColumns,
  classifyTemplateCategory,
  getWorkbenchBreadcrumb,
  getPayrollSidebarBadge,
  SIDEBAR_NAV_GROUPS,
  SIDEBAR_FOOTER_ITEM,
  getHeaderModuleContext,
  getPlatformStatusCluster,
  computeDownloadCapsuleState,
  filterNotificationTasks,
  type NotificationTaskItem,
  toggleNotificationFilterTab,
  getStageHeaderMeta,
  getPlatformCardBadge,
  getDatasetCardMeta,
  buildCalendarMonthGrid,
  buildCalendarYearMonths,
  formatDateTriggerMeta,
  computeDateRangeSpanDays,
  advanceCalendarRangeSelection,
  isLanorangeCityName,
  sortCitiesWithLanorangeFirst,
  buildExecutionRailSummary,
  toggleMultiMonthSelection,
  areMonthsContiguous,
  buildMultiMonthRunRanges,
  FENGSHEN_DATASET_CATEGORIES,
  filterFengshenDatasetsByCategory,
  countFengshenDatasetsByCategory,
  PRIMARY_NAV_ITEMS,
  COLLECTION_SUB_VIEWS,
  PAYROLL_SUB_VIEWS,
  getPrimaryHeaderContext,
} from '../src/lib/workbench';
import { DOWNLOAD_PLATFORMS } from '../src/lib/downloadModules';
import { toggleDownloadDataset, selectionKey } from '../src/lib/downloadCenterLogic';

test('connection summary distinguishes signed-out, saved, unknown and validated sessions', () => {
  assert.equal(connectionSummary([{state:'signed_out'},{state:'saved'}]),'需连接');
  assert.equal(connectionSummary([{state:'ready'},{offline:true,state:'ready'}]),'状态未知');
  assert.equal(connectionSummary([{state:'ready'},{state:'ready'}]),'连接正常');
  assert.equal(connectionSummary([{state:'ready'},{state:'starting'}]),'连接中');
  assert.equal(connectionSummary([{state:'ready'},{state:'waiting_login'}]),'需验证');
});
import { isDownloadProxyPath } from '../server/downloadProxy.ts';

test('deduction editing preserves identifiers, custom columns and keyword flags', () => {
  const rows = [{ 城市: '测试城', 团队名称: '测试站', 团队ID: '00123', 投诉: 5, 投诉_isKw: true, 说明: '保留' }];
  assert.equal(validateDeductionRows(rows), rows);
  assert.equal(rows[0].团队ID, '00123');
  assert.throws(() => validateDeductionRows([rows[0], rows[0]]), /重复/);
  assert.throws(() => validateDeductionRows([{ ...rows[0], 投诉: NaN }]), /有效数字/);
  assert.throws(() => validateDeductionRows([{ 团队名称: '站点' }]), /城市/);
});

test('saved sessions remain unverified and network errors are not logged-out states', () => {
  assert.equal(connectionLabel('saved'), '待验证');
  assert.equal(connectionLabel('ready'), '已连接');
  assert.equal(connectionLabel('planned'), '待接入');
  assert.equal(connectionLabel('refreshing'), '检查中');
  assert.equal(connectionLabel('waiting_login'), '需要验证');
  assert.equal(connectionLabel('error'), '连接异常');
});

test('workbench writes preserve browser origin through the authenticated proxy', () => {
  assert.equal(isDownloadProxyPath('/api/workbench/deductions'), true);
  assert.equal(isDownloadProxyPath('/api/workbench/batches/abc/deductions'), true);
  assert.equal(isDownloadProxyPath('/api/workbench-other'), false);
});

test('source metadata separates Xiaoxiang online download from manual payroll and keeps Baize standalone', () => {
  assert.deepEqual(
    SYSTEM_META.map(item => item.label),
    ['风神', '蓝橙', '商翼', '灯塔', '本来人力', '灯塔手动'],
  );
  assert.equal(SYSTEM_META.find(item => item.key === 'lanorange')?.businessLine, '原雷神');
  assert.match(SYSTEM_META.find(item => item.key === 'dengta')!.description, /手动上传/);
  assert.match(SYSTEM_META.find(item => item.key === 'baize')!.description, /独立下载/);
});

test('billing period presets compute accurate start and end dates across month boundaries', () => {
  assert.deepEqual(computeBillingPeriodRange('last_full_month', '2026-03-18'), {
    start: '2026-02-01',
    end: '2026-02-28',
    label: '上月整月',
  });
  assert.deepEqual(computeBillingPeriodRange('last_full_month', '2026-01-10'), {
    start: '2025-12-01',
    end: '2025-12-31',
    label: '上月整月',
  });
  assert.deepEqual(computeBillingPeriodRange('current_first_half', '2026-05-22'), {
    start: '2026-05-01',
    end: '2026-05-15',
    label: '本月1-15日',
  });
  assert.deepEqual(computeBillingPeriodRange('last_second_half', '2026-05-22'), {
    start: '2026-04-16',
    end: '2026-04-30',
    label: '上月16-月末',
  });
  assert.deepEqual(computeBillingPeriodRange('current_month_to_date', '2026-05-22'), {
    start: '2026-05-01',
    end: '2026-05-22',
    label: '本月至今',
  });
});

test('buildRecentMonths and computeMonthSelectionRange resolve 12 months and current/historical date boundaries', () => {
  const months = buildRecentMonths('2026-11-08', 12);
  assert.equal(months.length, 12);
  assert.equal(months[0], '2026-11');
  assert.equal(months[1], '2026-10');
  assert.equal(months[11], '2025-12');

  assert.deepEqual(computeMonthSelectionRange('2026-11', '2026-11-08'), {
    start: '2026-11-01',
    end: '2026-11-08',
  });
  assert.deepEqual(computeMonthSelectionRange('2026-11', '2026-11-08', { capAtYesterday: true }), {
    start: '2026-11-01',
    end: '2026-11-07',
  });
  assert.deepEqual(computeMonthSelectionRange('2026-11', '2026-11-01', { capAtYesterday: true }), {
    start: '2026-11-01',
    end: '2026-11-01',
  });
  assert.deepEqual(computeMonthSelectionRange('2026-10', '2026-11-08', { capAtYesterday: true }), {
    start: '2026-10-01',
    end: '2026-10-31',
  });
  assert.deepEqual(computeMonthSelectionRange('2026-10', '2026-11-08'), {
    start: '2026-10-01',
    end: '2026-10-31',
  });
  assert.deepEqual(computeMonthSelectionRange('2026-02', '2026-11-08'), {
    start: '2026-02-01',
    end: '2026-02-28',
  });
  assert.deepEqual(computeMonthSelectionRange('2024-02', '2026-11-08'), {
    start: '2024-02-01',
    end: '2024-02-29',
  });
});

test('lighthouse period presets stay within yesterday and expose blocked future halves', () => {
  assert.deepEqual(computeLighthousePeriodRange('last_full_month', '2026-11-02'), {
    start: '2026-10-01',
    end: '2026-10-31',
    label: '上月整月',
    blocked: false,
  });
  assert.deepEqual(computeLighthousePeriodRange('last_second_half', '2026-11-02'), {
    start: '2026-10-16',
    end: '2026-10-31',
    label: '上月16-月末',
    blocked: false,
  });
  assert.deepEqual(computeLighthousePeriodRange('current_first_half', '2026-11-02'), {
    start: '2026-11-01',
    end: '2026-11-01',
    label: '本月1-15日',
    blocked: true,
  });
  assert.deepEqual(computeLighthousePeriodRange('current_first_half', '2026-11-16'), {
    start: '2026-11-01',
    end: '2026-11-15',
    label: '本月1-15日',
    blocked: false,
  });
  assert.deepEqual(computeLighthousePeriodRange('current_month_to_date', '2026-11-02'), {
    start: '2026-11-01',
    end: '2026-11-01',
    label: '本月至今',
    blocked: false,
  });
  assert.equal(computeLighthousePeriodRange('current_month_to_date', '2026-11-01').blocked, true);
});

test('built-in scenario presets and dataset system attribution map to 2-char system names', () => {
  assert.equal(BUILTIN_DOWNLOAD_SCENARIOS.length, 3);
  const monitor = BUILTIN_DOWNLOAD_SCENARIOS.find(s => s.id === 'shangou_daily_monitor');
  assert.deepEqual(monitor?.datasets, ['rider_detail', 'fraud']);
  assert.equal(inferDatasetSystemTag('delivery_fee'), '风神');
  assert.equal(inferDatasetSystemTag('lanorange_rider_profile'), '蓝橙');
  assert.equal(inferDatasetSystemTag('shangyi_employees'), '商翼');
  assert.equal(inferDatasetSystemTag('delivery_fee', 'xiaoxiang'), '灯塔');
  assert.equal(inferDatasetSystemTag('rider_daily'), '灯塔');
});

test('report generation cards and payroll mode cards expose structured metadata and localized labels', () => {
  assert.equal(GENERATION_REPORT_CARDS.length, 4);
  assert.deepEqual(
    GENERATION_REPORT_CARDS.map(item => item.id),
    ['payment_binding', 'abnormal_followup', 'abnormal_riders', 'problem'],
  );
  assert.equal(PAYROLL_MODE_CARDS.length, 3);
  assert.ok(PAYROLL_MODE_CARDS.every(card => !card.subtitle.toLowerCase().includes('template')));
});

test('extractDeductionColumns collects ordered numeric columns across sites while excluding reserved fields', () => {
  const rows: import('../src/lib/workbench').DeductionRow[] = [
    { 城市: '宁波', 团队名称: '海曙站', 团队ID: '001', 投诉: 50, 投诉_isKw: true, 差评: 20, 说明: '备注' },
    { 城市: '杭州', 团队名称: '西湖站', 投诉: 30, 迟到: 10 },
  ];
  assert.deepEqual(extractDeductionColumns(rows), {
    metaColumns: ['城市', '团队名称', '团队ID'],
    deductionColumns: ['投诉', '差评', '迟到'],
  });
});

test('classifyTemplateCategory categorizes templates by business line and payroll usage', () => {
  assert.equal(classifyTemplateCategory('美团小象兼职薪资核算.xlsx').tag, '美团小象');
  assert.equal(classifyTemplateCategory('淘宝闪购风神配送费模板.xlsx').tag, '淘宝闪购');
  assert.equal(classifyTemplateCategory('通用考勤导出表.xlsx').tag, '通用模板');
});

test('breadcrumb and sidebar status helpers reflect active view and batch state', () => {
  assert.equal(getWorkbenchBreadcrumb('create', 'download').title, '资料下载采集');
  assert.equal(getWorkbenchBreadcrumb('create', 'generate').title, '业务报表生成');
  assert.equal(getWorkbenchBreadcrumb('create', 'payroll').title, '兼职薪资结算');
  assert.equal(getWorkbenchBreadcrumb('history', 'download').title, '任务与产出中心');

  assert.equal(getPayrollSidebarBadge('calculated', false)?.label, '已出表');
  assert.equal(getPayrollSidebarBadge('calculating', true)?.tone, 'active');
  assert.equal(getPayrollSidebarBadge(undefined, false), null);
});

test('sidebar navigation converges into 2 groups with concise 4-character labels and puts 任务中心 in the footer slot', () => {
  assert.deepEqual(
    SIDEBAR_NAV_GROUPS.map(group => group.title),
    ['数据采集', '核算与业务'],
  );
  assert.deepEqual(
    DOWNLOAD_PLATFORMS.map(platform => platform.navLabel),
    ['风神数据', '蓝橙数据', '发薪平台', '小象灯塔'],
  );
  assert.deepEqual(
    SIDEBAR_NAV_GROUPS[1].items.map(item => item.label),
    ['兼职核算', '价格审批', '扣款配置', '模板中心'],
  );
  assert.equal(SIDEBAR_FOOTER_ITEM.label, '任务中心');
  const allItems = [...SIDEBAR_NAV_GROUPS.flatMap(group => group.items), SIDEBAR_FOOTER_ITEM];
  assert.deepEqual(
    allItems.map(item => item.label),
    ['风神数据', '蓝橙数据', '发薪平台', '小象灯塔', '兼职核算', '价格审批', '扣款配置', '模板中心', '任务中心'],
  );
  assert.ok(allItems.every(item => item.label.length === 4), 'Every sidebar item label should be exactly 4 Chinese characters');
  const iconSet = new Set(allItems.map(item => item.iconKey));
  assert.equal(iconSet.size, allItems.length, 'Every sidebar item must have a distinct semantic icon');
});

test('Scheme B header context and multi-platform status cluster map module groups and 4-source dot states', () => {
  assert.deepEqual(getHeaderModuleContext('create', 'download', 'fengshen', false), {
    groupLabel: '数据采集',
    title: '风神数据',
    subtitle: '按城市与账期采集配送费、违规扣款、UB账单与考勤源表',
    iconKey: 'compass',
  });
  assert.equal(getHeaderModuleContext('create', 'download', 'payout', false).title, '发薪平台');
  assert.equal(getHeaderModuleContext('create', 'generate', 'fengshen', false).groupLabel, '业务报表');
  assert.equal(getHeaderModuleContext('history', 'download', 'fengshen', true).groupLabel, '任务记录');

  const cluster = getPlatformStatusCluster(
    {
      fengshen: { state: 'ready' },
      lanorange: { state: 'waiting_login' },
      baize: { state: 'starting', busy: true },
      xiaoxiang: { state: 'signed_out' },
    },
    null,
  );
  assert.deepEqual(
    cluster.map(item => [item.shortLabel, item.tone, item.statusText]),
    [
      ['风神', 'ready', '已连接'],
      ['蓝橙', 'warn', '需要验证'],
      ['商翼', 'busy', '连接中'],
      ['灯塔', 'idle', '未连接'],
      ['本来', 'idle', '未连接'],
    ],
  );
});

const SAMPLE_NOTIFICATIONS: NotificationTaskItem[] = [
  {
    id: 'n_fengshen_active',
    title: '风神采集中 · 宁波等3城',
    scopeText: '宁波、杭州、上海 · 配送费、违规扣款',
    periodText: '2026-09-01 ~ 2026-09-30',
    systemTag: '风神',
    kind: 'download',
    status: 'running',
    progress: 65,
    phaseText: '正在导出并合并城市账单分片',
    availableFiles: 0,
    platformKey: 'fengshen',
    createdAt: '刚刚',
  },
  {
    id: 'n_fengshen_ready',
    title: '闪购月度核算包 · 深圳、广州',
    scopeText: '深圳、广州 · 配送费 + 月度UB账单 + 骑手绑定',
    periodText: '2026-09-01 ~ 2026-09-30',
    systemTag: '风神',
    kind: 'download',
    status: 'completed',
    progress: 100,
    phaseText: '已完成校验与归档',
    availableFiles: 2,
    claimed: false,
    platformKey: 'fengshen',
    createdAt: '10 分钟前',
  },
  {
    id: 'n_shangyi_ready',
    title: '商翼员工资料（全量）',
    scopeText: '全部城市 · 商翼系统全量员工原始档案',
    periodText: '全量快照',
    systemTag: '商翼',
    kind: 'download',
    status: 'completed',
    progress: 100,
    phaseText: '已完成全量导出',
    availableFiles: 1,
    claimed: false,
    platformKey: 'baize',
    createdAt: '25 分钟前',
  },
  {
    id: 'n_lanorange_failed',
    title: '蓝橙骑手档案 · 导出异常',
    scopeText: '全部站点 · 蓝橙全量骑手原始档案',
    periodText: '全量快照',
    systemTag: '蓝橙',
    kind: 'download',
    status: 'failed',
    availableFiles: 0,
    claimed: false,
    platformKey: 'lanorange',
    createdAt: '30 分钟前',
    phaseText: '导出请求超时，请在任务中心重试或检查配置',
  },
];

test('Scheme 1 download notification capsule computes running, blocked, completed, and idle states', () => {
  const seed = SAMPLE_NOTIFICATIONS;
  const runningState = computeDownloadCapsuleState(seed);
  assert.equal(runningState.mode, 'running');
  assert.equal(runningState.tone, 'active');
  assert.equal(runningState.label, '风神采集中 · 宁波等3城 (65%)');
  assert.equal(runningState.unclaimedFileCount, 3);

  const completedOnly = seed.filter(item => item.status === 'completed');
  const completedState = computeDownloadCapsuleState(completedOnly);
  assert.equal(completedState.mode, 'completed');
  assert.equal(completedState.tone, 'ready');
  assert.equal(completedState.label, '下载已完成 · 3 份文件待领取');

  const blockedState = computeDownloadCapsuleState([
    ...completedOnly,
    {
      id: 'b1',
      title: '风神登录过期',
      scopeText: '宁波',
      systemTag: '风神',
      kind: 'download',
      status: 'blocked',
      availableFiles: 0,
    },
  ]);
  assert.equal(blockedState.mode, 'blocked');
  assert.equal(blockedState.tone, 'warn');
  assert.equal(blockedState.label, '1 项任务等待登录验证');

  const allClaimed = completedOnly.map(item => ({ ...item, claimed: true }));
  const idleState = computeDownloadCapsuleState(allClaimed);
  assert.equal(idleState.mode, 'idle');
  assert.equal(idleState.tone, 'idle');
  assert.equal(idleState.label, '下载通知 · 2');
});

test('notification popover header pills switch between downloading, completed, failed, and all tasks', () => {
  const seed = SAMPLE_NOTIFICATIONS;
  assert.equal(filterNotificationTasks(seed, 'all').length, 4);
  assert.deepEqual(
    filterNotificationTasks(seed, 'downloading').map(item => item.id),
    ['n_fengshen_active'],
  );
  assert.deepEqual(
    filterNotificationTasks(seed, 'completed').map(item => item.id),
    ['n_fengshen_ready', 'n_shangyi_ready'],
  );
  assert.deepEqual(
    filterNotificationTasks(seed, 'failed').map(item => item.id),
    ['n_lanorange_failed'],
  );

  assert.equal(toggleNotificationFilterTab('all', 'downloading'), 'downloading');
  assert.equal(toggleNotificationFilterTab('downloading', 'completed'), 'completed');
  assert.equal(toggleNotificationFilterTab('completed', 'failed'), 'failed');
  assert.equal(toggleNotificationFilterTab('failed', 'failed'), 'all');
  assert.equal(toggleNotificationFilterTab('downloading', 'downloading'), 'all');
});

test('Scheme A stage header meta maps platform download and report generation local tabs', () => {
  assert.deepEqual(getStageHeaderMeta('download', 'fengshen', 'create'), {
    title: '风神下载',
    createTabLabel: '新建下载',
    historyTabLabel: '本模块记录',
    subtitle: '选择所需资料，再确认处理范围。',
  });
  assert.equal(getStageHeaderMeta('download', 'payout', 'create').title, '发薪平台');
  assert.equal(getStageHeaderMeta('download', 'xiaoxiang', 'create').title, '灯塔下载');
  assert.equal(getStageHeaderMeta('generate', undefined, 'create').createTabLabel, '生成报表');
  assert.match(getStageHeaderMeta('download', 'fengshen', 'history').subtitle, /采集任务进度/);
});

test('Scheme A platform card badge computes ready, warn, busy, and idle states', () => {
  assert.deepEqual(getPlatformCardBadge({ state: 'ready' }), { label: '已连接', tone: 'ready' });
  assert.deepEqual(getPlatformCardBadge({ state: 'waiting_login', busy: true }), { label: '需验证', tone: 'warn' });
  assert.deepEqual(getPlatformCardBadge({ state: 'saved' }), { label: '需验证', tone: 'warn' });
  assert.deepEqual(getPlatformCardBadge({ state: 'starting', busy: true }), { label: '连接中', tone: 'busy' });
  assert.deepEqual(getPlatformCardBadge({ state: 'ready' }, 'logout'), { label: '退出中', tone: 'busy' });
  assert.deepEqual(getPlatformCardBadge({ state: 'ready' }, 'verify'), { label: '验证中', tone: 'busy' });
  assert.deepEqual(getPlatformCardBadge({ state: 'signed_out' }), { label: '未登录', tone: 'idle' });
  assert.deepEqual(getPlatformCardBadge({ offline: true }), { label: '连接不可用', tone: 'idle' });
});

test('getDatasetCardMeta provides scopeTag, tone, and business description for datasets across all 4 systems', () => {
  const delivery = getDatasetCardMeta('delivery_fee', '配送费');
  assert.equal(delivery.scopeTag, '城市·账期');
  assert.equal(delivery.tone, 'city');
  assert.ok(delivery.desc.length >= 8);

  const monthly = getDatasetCardMeta('rider_monthly', '风神骑手月度 UB 账单');
  assert.equal(monthly.title, '月度 UB 账单');
  assert.equal(monthly.scopeTag, '城市·按月');
  assert.equal(monthly.tone, 'monthly');

  const merchant = getDatasetCardMeta('invitation_records', '邀请记录（全量）');
  assert.equal(merchant.title, '邀请记录');
  assert.equal(merchant.scopeTag, '城市·全量');
  assert.equal(merchant.tone, 'city');

  const lanorange = getDatasetCardMeta('lanorange_rider_archive', '骑手档案');
  assert.equal(lanorange.scopeTag, '全城·全量');
  assert.equal(lanorange.tone, 'full');

  const baize = getDatasetCardMeta('baize_employees', '白泽员工资料（全量）');
  assert.equal(baize.title, '商翼员工资料');
  assert.equal(baize.scopeTag, '全站·全量');
  assert.equal(baize.tone, 'full');

  const xiaoxiang = getDatasetCardMeta('rider_daily', '日维度骑手分析（小象灯塔）');
  assert.equal(xiaoxiang.title, '日维度骑手分析');
  assert.equal(xiaoxiang.scopeTag, '全城·日期');
  assert.equal(xiaoxiang.tone, 'lighthouse');

  const paymentBinding = getDatasetCardMeta('payment_binding', '支付绑定（生成表）');
  assert.equal(paymentBinding.title, '支付绑定');
  assert.equal(paymentBinding.scopeTag, '生成·按月');
  assert.equal(paymentBinding.tone, 'monthly');

  const abnormalFollowup = getDatasetCardMeta('abnormal_followup', '异常跟进（生成表）');
  assert.equal(abnormalFollowup.title, '异常跟进');
  assert.equal(abnormalFollowup.scopeTag, '生成·按月');
  assert.equal(abnormalFollowup.tone, 'monthly');

  const abnormalRiders = getDatasetCardMeta('abnormal_riders', '异常名单（生成表）');
  assert.equal(abnormalRiders.title, '异常名单');
  assert.equal(abnormalRiders.scopeTag, '生成·全量');
  assert.equal(abnormalRiders.tone, 'full');
});

test('buildCalendarMonthGrid and datepicker helpers compute 42 Monday-first cells, range states, and weekday tags', () => {
  // October 2026: Oct 1 is Thursday -> grid starts on Monday 2026-09-28
  const grid = buildCalendarMonthGrid(2026, 10, {
    selectedDate: '2026-10-01',
    todayDate: '2026-10-31',
    rangeStart: '2026-10-01',
    rangeEnd: '2026-10-15',
    minDate: '2026-08-01',
    maxDate: '2026-10-30',
  });
  assert.equal(grid.length, 42);
  assert.equal(grid[0].dateStr, '2026-09-28');
  assert.equal(grid[0].inCurrentMonth, false);

  const oct1 = grid.find(c => c.dateStr === '2026-10-01')!;
  assert.equal(oct1.inCurrentMonth, true);
  assert.equal(oct1.isSelected, true);
  assert.equal(oct1.isRangeStart, true);
  assert.equal(oct1.isInRange, true);

  const oct10 = grid.find(c => c.dateStr === '2026-10-10')!;
  assert.equal(oct10.isInRange, true);
  assert.equal(oct10.isWeekend, true);

  const oct31 = grid.find(c => c.dateStr === '2026-10-31')!;
  assert.equal(oct31.isToday, true);
  assert.equal(oct31.isDisabled, true);

  const months = buildCalendarYearMonths(2026, {
    selectedMonth: '2026-09',
    todayMonth: '2026-10',
    rangeStartMonth: '2026-08',
    rangeEndMonth: '2026-10',
    maxMonth: '2026-10',
  });
  assert.equal(months.length, 12);
  assert.equal(months[8].isSelected, true);
  assert.equal(months[9].isCurrentMonth, true);
  assert.equal(months[10].isDisabled, true);

  assert.deepEqual(formatDateTriggerMeta('2026-10-01', 'date'), {
    primaryText: '2026-10-01',
    badgeText: '周四',
    isEmpty: false,
  });
  assert.deepEqual(formatDateTriggerMeta('2026-10', 'month'), {
    primaryText: '2026年10月',
    badgeText: '10月',
    isEmpty: false,
  });
  assert.equal(computeDateRangeSpanDays('2026-10-01', '2026-10-31'), 31);
});

test('buildExecutionRailSummary formats scope rows without duplicate date hints when ready', () => {
  const xiaoxiangReady = buildExecutionRailSummary({
    datasetsCount: 1,
    cities: [],
    start: '2026-10-01',
    end: '2026-10-30',
    noCity: true,
    noDate: false,
    archiveOnly: false,
    xiaoxiangDated: true,
    xiaoxiangOnly: true,
    blueOnly: false,
    baizeOnly: false,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 1,
    submitReady: true,
  });
  assert.equal(xiaoxiangReady.cityLabel, '账号全量（未选城市）');
  assert.equal(xiaoxiangReady.periodText, '2026-10-01 ~ 10-30');
  assert.equal(xiaoxiangReady.periodSpanBadge, '共 30 天');
  assert.equal(xiaoxiangReady.thirdRowLabel, '交付规格');
  assert.equal(xiaoxiangReady.thirdRowValue, '按账期合并导出');
  assert.equal(xiaoxiangReady.blockerHint, '');

  const benlaiSnapshot = buildExecutionRailSummary({
    datasetsCount: 1,
    cities: [],
    start: '2026-11-15',
    end: '2026-11-15',
    noCity: true,
    noDate: true,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    benlaiOnly: true,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 1,
    submitReady: true,
  });
  assert.equal(benlaiSnapshot.cityLabel, '全部站点（本来人力全量）');
  assert.equal(benlaiSnapshot.periodText, '全量实时快照');
  assert.equal(benlaiSnapshot.thirdRowLabel, '交付规格');
  assert.equal(benlaiSnapshot.thirdRowValue, '单份全量原表');
  assert.equal(benlaiSnapshot.listFooterText, '本来人力全量灵工档案 · 签约城市实时读取');

  const fengshenMulti = buildExecutionRailSummary({
    datasetsCount: 9,
    cities: ['上海', '广州', '宁波', '深圳', '杭州', '苏州', '南京', '温州', '嘉兴', '金华'],
    start: '2026-09-16',
    end: '2026-09-30',
    noCity: false,
    noDate: false,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 90,
    submitReady: true,
  });
  assert.equal(fengshenMulti.cityLabel, '上海、广州、宁波 等 10 城');
  assert.equal(fengshenMulti.periodText, '2026-09-16 ~ 09-30');
  assert.equal(fengshenMulti.periodSpanBadge, '共 15 天');
  assert.equal(fengshenMulti.thirdRowLabel, '站点规则');
  assert.equal(fengshenMulti.thirdRowValue, '排除取分离');
  const scopeInput={datasetsCount:1,cities:['深圳'],start:'2026-10-01',end:'2026-10-15',noCity:false,noDate:false,archiveOnly:false,xiaoxiangDated:false,xiaoxiangOnly:false,blueOnly:false,baizeOnly:false,merchantOnly:false,merchantSnapshotOnly:false,merchantDateValid:true,validDates:true,includeSeparation:false,subitemCount:1,submitReady:true};
  assert.equal(buildExecutionRailSummary({...scopeInput,excludeSeparation:false}).thirdRowValue,'全部站点（含取分离）');
  assert.equal(buildExecutionRailSummary({...scopeInput,excludeSeparation:true}).thirdRowValue,'排除取分离');
  assert.equal(fengshenMulti.listFooterText, '已选 9 类资料 · 预计 90 个采集子项');
  assert.equal(fengshenMulti.blockerHint, '');

  const unready = buildExecutionRailSummary({
    ...fengshenMulti,
    datasetsCount: 0,
    cities: ['上海'],
    start: '2026-09-16',
    end: '2026-09-30',
    noCity: false,
    noDate: false,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 0,
    submitReady: false,
  });
  assert.equal(unready.blockerHint, '请先在左侧勾选需要采集的资料');
});

test('single-calendar range selection advances start and end steps and auto-orders reversed clicks', () => {
  const step1 = advanceCalendarRangeSelection('2026-11-01', '2026-11-08', '2026-11-03', 'start');
  assert.deepEqual(step1, {
    start: '2026-11-03',
    end: '2026-11-03',
    nextStep: 'end',
    completed: false,
  });

  const step2Normal = advanceCalendarRangeSelection(step1.start, step1.end, '2026-11-07', step1.nextStep);
  assert.deepEqual(step2Normal, {
    start: '2026-11-03',
    end: '2026-11-07',
    nextStep: 'start',
    completed: true,
  });

  const step2Reversed = advanceCalendarRangeSelection('2026-11-06', '2026-11-06', '2026-11-02', 'end');
  assert.deepEqual(step2Reversed, {
    start: '2026-11-02',
    end: '2026-11-06',
    nextStep: 'start',
    completed: true,
  });

  assert.deepEqual(formatDateTriggerMeta('2026-11-03', 'range', '请选择日期范围', '2026-11-03', '2026-11-07'), {
    primaryText: '2026-11-03 至 2026-11-07',
    badgeText: '共 5 天',
    isEmpty: false,
  });
});

test('sortCitiesWithLanorangeFirst places Lanorange partner cities first while preserving enabled priority', () => {
  assert.equal(isLanorangeCityName('深圳'), true);
  assert.equal(isLanorangeCityName('深圳市'), true);
  assert.equal(isLanorangeCityName('佛山市'), false);

  const cities = [
    { id: 'c1', name: '佛山市', disabled: false },
    { id: 'c2', name: '中山市', disabled: false },
    { id: 'c3', name: '深圳市', disabled: false },
    { id: 'c4', name: '广州市', disabled: false },
    { id: 'c5', name: '东莞市', disabled: true },
    { id: 'c6', name: '珠海市', disabled: true },
  ];
  const sorted = sortCitiesWithLanorangeFirst(cities);
  assert.deepEqual(
    sorted.map(item => item.name),
    ['深圳市', '广州市', '东莞市', '佛山市', '中山市', '珠海市'],
  );
});

test('buildExecutionRailSummary supports Lanorange multi-city selection and Baize persistent execution rail', () => {
  const lanorangeSelectedCities = buildExecutionRailSummary({
    datasetsCount: 2,
    cities: ['上海', '深圳'],
    start: '2026-10-01',
    end: '2026-10-31',
    noCity: true,
    noDate: false,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: true,
    baizeOnly: false,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 4,
    submitReady: true,
  });
  assert.equal(lanorangeSelectedCities.cityLabel, '上海、深圳');
  assert.equal(lanorangeSelectedCities.periodText, '2026-10-01 ~ 10-31');
  assert.equal(lanorangeSelectedCities.periodSpanBadge, '共 31 天');
  assert.equal(lanorangeSelectedCities.thirdRowLabel, '交付规格');
  assert.equal(lanorangeSelectedCities.thirdRowValue, '每类 1 份汇总表');

  const baizeSummary = buildExecutionRailSummary({
    datasetsCount: 1,
    cities: [],
    start: '2026-11-08',
    end: '2026-11-08',
    noCity: true,
    noDate: true,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: true,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 1,
    submitReady: true,
  });
  assert.equal(baizeSummary.cityLabel, '全部站点（商翼全量）');
  assert.equal(baizeSummary.periodText, '全量实时快照');
  assert.equal(baizeSummary.periodSpanBadge, '不限账期');
  assert.equal(baizeSummary.thirdRowLabel, '交付规格');
  assert.equal(baizeSummary.thirdRowValue, '单份全量原表');
});

test('multi-month selection toggles, detects continuity, and builds Fengshen/Xiaoxiang/Lanorange run ranges', () => {
  const allowed = ['2026-11', '2026-10', '2026-09'];

  // Toggle adds chronologically and refuses to uncheck the sole remaining month
  assert.deepEqual(toggleMultiMonthSelection(['2026-11'], '2026-10', allowed), ['2026-10', '2026-11']);
  assert.deepEqual(toggleMultiMonthSelection(['2026-10', '2026-11'], '2026-09', allowed), ['2026-09', '2026-10', '2026-11']);
  assert.deepEqual(toggleMultiMonthSelection(['2026-10', '2026-11'], '2026-11', allowed), ['2026-10']);
  assert.deepEqual(toggleMultiMonthSelection(['2026-10'], '2026-10', allowed), ['2026-10']);
  assert.deepEqual(toggleMultiMonthSelection(['2026-11'], '2026-08', allowed), ['2026-11']);

  assert.equal(areMonthsContiguous(['2026-10', '2026-11']), true);
  assert.equal(areMonthsContiguous(['2025-12', '2026-01']), true);
  assert.equal(areMonthsContiguous(['2026-09', '2026-11']), false);

  // Fengshen contiguous months merge into 1 run; non-contiguous months split into 2 runs
  const fengshenContiguous = buildMultiMonthRunRanges(['2026-10', '2026-11'], '2026-11-15');
  assert.deepEqual(fengshenContiguous, [
    { months: ['2026-10', '2026-11'], start: '2026-10-01', end: '2026-11-15' },
  ]);

  const fengshenGapped = buildMultiMonthRunRanges(['2026-09', '2026-11'], '2026-11-15');
  assert.deepEqual(fengshenGapped, [
    { months: ['2026-09'], start: '2026-09-01', end: '2026-09-30' },
    { months: ['2026-11'], start: '2026-11-01', end: '2026-11-15' },
  ]);

  // Xiaoxiang caps today at yesterday (11-14) and splits whenever merged span > 31 days
  const xiaoxiangMulti = buildMultiMonthRunRanges(['2026-10', '2026-11'], '2026-11-15', {
    capAtYesterday: true,
    maxDaysPerRun: 31,
  });
  assert.deepEqual(xiaoxiangMulti, [
    { months: ['2026-10'], start: '2026-10-01', end: '2026-10-31' },
    { months: ['2026-11'], start: '2026-11-01', end: '2026-11-14' },
  ]);

  // Execution rail summary reflects multi-month contiguous, gapped, and Lanorange selections
  const baseRailInput = {
    datasetsCount: 1,
    cities: ['上海'],
    start: '2026-10-01',
    end: '2026-11-15',
    selectedMonths: ['2026-10', '2026-11'],
    noCity: false,
    noDate: false,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 1,
    submitReady: true,
  };
  const fengshenRailContig = buildExecutionRailSummary(baseRailInput);
  assert.equal(fengshenRailContig.periodText, '2026-10-01 ~ 11-15');
  assert.equal(fengshenRailContig.periodSpanBadge, '2个月 · 46天');

  const fengshenRailGapped = buildExecutionRailSummary({
    ...baseRailInput,
    start: '2026-09-01',
    end: '2026-11-15',
    selectedMonths: ['2026-09', '2026-11'],
  });
  assert.equal(fengshenRailGapped.periodText, '2026-09、2026-11');
  assert.equal(fengshenRailGapped.periodSpanBadge, '共 2 个月');

  const lanorangeMultiRail = buildExecutionRailSummary({
    ...baseRailInput,
    cities: [],
    blueOnly: true,
    noCity: true,
    selectedMonths: ['2026-10', '2026-11'],
  });
  assert.equal(lanorangeMultiRail.periodText, '2026-10、2026-11');
  assert.equal(lanorangeMultiRail.periodSpanBadge, '共 2 个月');
});

test('Fengshen 全部资料 category filter excludes extracted 业务报表 and preserves raw dataset counts', () => {
  const sampleDatasets = [
    { id: 'delivery_fee' },
    { id: 'penalty' },
    { id: 'rider_monthly' },
    { id: 'receive_account' },
    { id: 'rider_detail' },
    { id: 'attendance_detail' },
    { id: 'invitation_records' },
    { id: 'fraud' },
    { id: 'delivery_waybill' },
    { id: 'rider_info' },
    { id: 'goods_rent' },
  ];
  assert.equal(FENGSHEN_DATASET_CATEGORIES[0].label, '全部资料');
  assert.equal(FENGSHEN_DATASET_CATEGORIES.some(c => c.label === '专项报表' || c.label === '业务报表'), false);
  assert.equal(countFengshenDatasetsByCategory(sampleDatasets, 'all'), 11);
  assert.deepEqual(
    filterFengshenDatasetsByCategory(sampleDatasets, 'settlement').map(d => d.id),
    ['delivery_fee', 'penalty', 'rider_monthly', 'receive_account'],
  );
  assert.equal(countFengshenDatasetsByCategory(sampleDatasets, 'orders'), 2);
  assert.equal(countFengshenDatasetsByCategory(sampleDatasets, 'attendance'), 3);
  assert.equal(countFengshenDatasetsByCategory(sampleDatasets, 'profile'), 2);
});

test('payout module multi-selects baize and benlai together and computes dual-batch rail summary', () => {
  const step1 = toggleDownloadDataset([], 'baize_employees');
  assert.deepEqual(step1, ['baize_employees']);
  const step2 = toggleDownloadDataset(step1, 'benlai_employees');
  assert.deepEqual(step2, ['baize_employees', 'benlai_employees']);
  const step3 = toggleDownloadDataset(step2, 'baize_employees');
  assert.deepEqual(step3, ['benlai_employees']);
  assert.equal(
    selectionKey({ cities: [], datasets: ['baize_employees', 'benlai_employees'], start: '', end: '' }),
    selectionKey({ cities: ['深圳'], datasets: ['benlai_employees', 'baize_employees'], start: '2026-10-01', end: '2026-10-01' }),
  );

  const dualRail = buildExecutionRailSummary({
    datasetsCount: 2,
    cities: [],
    start: '2026-11-15',
    end: '2026-11-15',
    noCity: true,
    noDate: true,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    benlaiOnly: false,
    payoutOnly: true,
    payoutBoth: true,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 2,
    submitReady: true,
  });
  assert.equal(dualRail.cityLabel, '全站全城（商翼 + 本来）');
  assert.equal(dualRail.thirdRowValue, '2 份独立原表');
  assert.equal(dualRail.listFooterText, '已选双发薪平台 · 自动拆分为 2 批独立采集');

  const emptyPayoutRail = buildExecutionRailSummary({
    datasetsCount: 0,
    cities: [],
    start: '2026-11-15',
    end: '2026-11-15',
    noCity: true,
    noDate: true,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    benlaiOnly: false,
    payoutOnly: true,
    payoutBoth: false,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 0,
    submitReady: false,
  });
  assert.equal(emptyPayoutRail.blockerHint, '请先在左侧选择至少 1 个发薪平台');

  const abnormalRidersRail = buildExecutionRailSummary({
    datasetsCount: 1,
    cities: [],
    start: '2026-11-15',
    end: '2026-11-15',
    noCity: true,
    noDate: true,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    benlaiOnly: false,
    abnormalRidersOnly: true,
    generatedCount: 1,
    rawCount: 0,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    subitemCount: 1,
    submitReady: true,
  });
  assert.equal(abnormalRidersRail.cityLabel, '全部城市（全量）');
  assert.equal(abnormalRidersRail.periodText, '全量最新档案');
  assert.equal(abnormalRidersRail.periodSpanBadge, '不限账期');
  assert.equal(abnormalRidersRail.thirdRowValue, '1 份全城整理表');
  assert.equal(abnormalRidersRail.listFooterText, '异常名单 · 固定全城全量导出');

  const mixedRail = buildExecutionRailSummary({
    datasetsCount: 2,
    cities: ['上海'],
    start: '2026-11-01',
    end: '2026-11-15',
    selectedMonths: ['2026-11'],
    noCity: false,
    noDate: false,
    archiveOnly: false,
    xiaoxiangDated: false,
    xiaoxiangOnly: false,
    blueOnly: false,
    baizeOnly: false,
    generatedCount: 1,
    rawCount: 1,
    merchantOnly: false,
    merchantSnapshotOnly: false,
    merchantDateValid: true,
    validDates: true,
    includeSeparation: false,
    excludeSeparation: true,
    subitemCount: 2,
    submitReady: true,
  });
  assert.equal(mixedRail.listFooterText, '已选 1 类资料 + 1 份报表 · 将自动分批提交');
});

test('flat 2-module primary navigation and embedded sub-view headers reflect updated layout', () => {
  assert.deepEqual(
    PRIMARY_NAV_ITEMS.map(item => item.label),
    ['数据采集', '薪资核算'],
  );
  assert.deepEqual(
    COLLECTION_SUB_VIEWS.map(item => item.label),
    ['新建采集', '任务中心'],
  );
  assert.deepEqual(
    PAYROLL_SUB_VIEWS.map(item => item.label),
    ['兼职核算', '扣款配置', '模板中心'],
  );

  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'create', taskKind: 'download', downloadPlatform: 'fengshen' }).title,
    '风神数据',
  );
  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'create', taskKind: 'generate', downloadPlatform: 'fengshen' }).groupLabel,
    '业务报表',
  );
  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'history', taskKind: 'download', downloadPlatform: 'fengshen' }).title,
    '任务中心',
  );
  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'create', taskKind: 'payroll', downloadPlatform: 'fengshen', payrollSubView: 'batches' }).title,
    '兼职核算',
  );
  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'create', taskKind: 'payroll', downloadPlatform: 'fengshen', payrollSubView: 'deductions' }).title,
    '扣款配置',
  );
  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'create', taskKind: 'payroll', downloadPlatform: 'fengshen', payrollSubView: 'templates' }).title,
    '标准模板中心',
  );
  assert.equal(
    getPrimaryHeaderContext({ workspaceView: 'approval', taskKind: 'payroll', downloadPlatform: 'fengshen' }).title,
    '价格审批',
  );
});





