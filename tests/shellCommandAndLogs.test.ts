import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildShellCommands,
  filterShellCommands,
  getActiveNavGroup,
  getBreadcrumbModel,
  getCurrentQuickTargetId,
  getPlatformChannelStatus,
  getRailIndex,
  recordRecentTarget,
  sanitizeStoredTargets,
  togglePinnedTarget,
} from '../src/lib/shellNav';
import {
  countLogLevels,
  filterLogEntries,
  formatLogsForExport,
  getLogLevelLabel,
  highlightMatchSegments,
  normalizeLogEntries,
  normalizeLogLevel,
} from '../src/lib/logInspector';

test('getActiveNavGroup maps workspace views and task kinds to the expected primary nav group', () => {
  assert.equal(getActiveNavGroup({ workspaceView: 'create', taskKind: 'download' }), 'collection');
  assert.equal(getActiveNavGroup({ workspaceView: 'create', taskKind: 'generate' }), 'reports');
  assert.equal(getActiveNavGroup({ workspaceView: 'create', taskKind: 'payroll' }), 'payroll');
  assert.equal(getActiveNavGroup({ workspaceView: 'approval', taskKind: 'download' }), 'payroll');
  assert.equal(getActiveNavGroup({ workspaceView: 'history', taskKind: 'download' }), 'history');
});

test('getBreadcrumbModel provides interactive sibling switchers for collection, reports, and payroll (including 价格审批)', () => {
  const collection = getBreadcrumbModel({
    workspaceView: 'create',
    taskKind: 'download',
    downloadPlatform: 'lanorange',
    payrollSubView: 'batches',
  });
  assert.equal(collection.moduleLabel, '数据采集');
  assert.equal(collection.viewLabel, '蓝橙数据');
  assert.equal(collection.siblings.length, 4);
  assert.equal(collection.siblings.find(s => s.active)?.id, 'lanorange');

  const reports = getBreadcrumbModel({
    workspaceView: 'create',
    taskKind: 'generate',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
    reportId: 'abnormal_followup',
  });
  assert.equal(reports.moduleLabel, '业务报表');
  assert.equal(reports.viewLabel, '异常跟进');
  assert.equal(reports.siblings.length, 4);
  assert.equal(reports.siblings.find(s => s.active)?.id, 'abnormal_followup');

  const payroll = getBreadcrumbModel({
    workspaceView: 'create',
    taskKind: 'payroll',
    downloadPlatform: 'fengshen',
    payrollSubView: 'deductions',
  });
  assert.equal(payroll.moduleLabel, '薪资核算');
  assert.equal(payroll.viewLabel, '扣款配置');
  assert.equal(payroll.siblings.length, 4);
  assert.equal(payroll.siblings.find(s => s.active)?.id, 'deductions');

  const approval = getBreadcrumbModel({
    workspaceView: 'approval',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  });
  assert.equal(approval.moduleLabel, '薪资核算');
  assert.equal(approval.viewLabel, '价格审批');
  assert.equal(approval.siblings.length, 4);

  const history = getBreadcrumbModel({
    workspaceView: 'history',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  });
  assert.equal(history.viewLabel, '任务中心');
  assert.equal(history.siblings.length, 2);
  assert.equal(history.siblings.find(s => s.active)?.id, 'history');

  const pickup = getBreadcrumbModel({
    workspaceView: 'pickup',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  });
  assert.equal(pickup.viewLabel, '文件领取');
  assert.equal(pickup.siblings.find(s => s.active)?.id, 'pickup');
  assert.equal(getCurrentQuickTargetId({ workspaceView: 'pickup', taskKind: 'download', downloadPlatform: 'fengshen', payrollSubView: 'batches' }), 'workspace:pickup');
});

test('buildShellCommands and filterShellCommands support Chinese, English, and pinyin initials', () => {
  const commands = buildShellCommands(
    {
      workspaceView: 'create',
      taskKind: 'download',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
    },
    { sidebarCollapsed: false },
  );
  assert.ok(commands.length >= 11);
  assert.equal(commands.find(c => c.id === 'nav-fengshen')?.active, true);
  assert.equal(commands.find(c => c.id === 'act-toggle-sidebar')?.label, '收起为极简命令轨');

  const byPinyin = filterShellCommands(commands, 'kk');
  assert.equal(byPinyin[0]?.id, 'nav-payroll-deductions');

  const byChinese = filterShellCommands(commands, '小象');
  assert.equal(byChinese[0]?.id, 'nav-xiaoxiang');

  const byLog = filterShellCommands(commands, 'log');
  assert.equal(byLog[0]?.id, 'act-log-drawer');

  const byReport = filterShellCommands(commands, '问题单');
  assert.equal(byReport[0]?.id, 'nav-report-problem');
  assert.equal(byReport[0]?.group, '业务报表');

  const empty = filterShellCommands(commands, '不存在的指令xyz');
  assert.equal(empty.length, 0);
});

test('Dual-Rail helpers compute kinetic rail indices, quick target IDs, and pin/recent lists', () => {
  assert.equal(getRailIndex('collection'), 0);
  assert.equal(getRailIndex('reports'), 1);
  assert.equal(getRailIndex('payroll'), 2);
  assert.equal(getRailIndex('approval'), 3);
  assert.equal(getRailIndex('history'), 4);

  assert.equal(
    getCurrentQuickTargetId({
      workspaceView: 'create',
      taskKind: 'download',
      downloadPlatform: 'payout',
      payrollSubView: 'batches',
    }),
    'platform:payout',
  );
  assert.equal(
    getCurrentQuickTargetId({
      workspaceView: 'create',
      taskKind: 'generate',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
      reportId: 'abnormal_riders',
    }),
    'report:abnormal_riders',
  );
  assert.equal(
    getCurrentQuickTargetId({
      workspaceView: 'create',
      taskKind: 'generate',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
      reportId: 'problem',
    }),
    'report:problem',
  );
  assert.equal(
    getCurrentQuickTargetId({
      workspaceView: 'create',
      taskKind: 'payroll',
      downloadPlatform: 'fengshen',
      payrollSubView: 'templates',
    }),
    'payroll:templates',
  );
  assert.equal(
    getCurrentQuickTargetId({
      workspaceView: 'approval',
      taskKind: 'download',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
    }),
    'workspace:approval',
  );
  assert.equal(
    getCurrentQuickTargetId({
      workspaceView: 'history',
      taskKind: 'download',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
    }),
    'workspace:history',
  );

  const sanitized = sanitizeStoredTargets(
    ['platform:fengshen', 'invalid:id', 'payroll:deductions', 'platform:fengshen', 'workspace:approval', 'platform:xiaoxiang', 'payroll:templates'],
    4,
  );
  assert.deepEqual(sanitized, ['platform:fengshen', 'payroll:deductions', 'workspace:approval', 'platform:xiaoxiang']);

  const pinned1 = togglePinnedTarget([], 'payroll:deductions', 4);
  assert.deepEqual(pinned1, ['payroll:deductions']);
  const pinned2 = togglePinnedTarget(pinned1, 'workspace:approval', 4);
  assert.deepEqual(pinned2, ['workspace:approval', 'payroll:deductions']);
  const unpinned = togglePinnedTarget(pinned2, 'payroll:deductions', 4);
  assert.deepEqual(unpinned, ['workspace:approval']);
  const capped = togglePinnedTarget(
    ['platform:fengshen', 'platform:lanorange', 'platform:payout', 'platform:xiaoxiang'],
    'payroll:deductions',
    4,
  );
  assert.deepEqual(capped, ['payroll:deductions', 'platform:fengshen', 'platform:lanorange', 'platform:payout']);

  const recent1 = recordRecentTarget(['platform:fengshen', 'payroll:batches'], 'payroll:deductions', 3);
  assert.deepEqual(recent1, ['payroll:deductions', 'platform:fengshen', 'payroll:batches']);
  const recentDedup = recordRecentTarget(recent1, 'platform:fengshen', 3);
  assert.deepEqual(recentDedup, ['platform:fengshen', 'payroll:deductions', 'payroll:batches']);
});

test('getPlatformChannelStatus resolves single platforms and aggregates baize + benlai for payout', () => {
  const fengshen = getPlatformChannelStatus('fengshen', {
    fengshen: { state: 'ready' },
  });
  assert.equal(fengshen.tone, 'ready');

  const payoutBothReady = getPlatformChannelStatus('payout', {
    baize: { state: 'ready' },
    benlai: { state: 'ready' },
  });
  assert.equal(payoutBothReady.tone, 'ready');
  assert.equal(payoutBothReady.statusText, '商翼/本来均已连');

  const payoutPartial = getPlatformChannelStatus('payout', {
    baize: { state: 'ready' },
    benlai: { state: 'idle' },
  });
  assert.equal(payoutPartial.tone, 'ready');
  assert.equal(payoutPartial.statusText, '1/2 通道已连接');

  const payoutWarn = getPlatformChannelStatus('payout', {
    baize: { state: 'login_required' },
    benlai: { state: 'idle' },
  });
  assert.equal(payoutWarn.tone, 'warn');
});

test('normalizeLogLevel and normalizeLogEntries handle missing metadata and semantic prefixes', () => {
  assert.equal(normalizeLogLevel('ERROR', 'fail'), 'ERROR');
  assert.equal(normalizeLogLevel('WARNING', 'warn'), 'WARN');
  assert.equal(normalizeLogLevel('INFO', '[ERROR] 引擎断开'), 'ERROR');
  assert.equal(normalizeLogLevel('INFO', '任务完成！已保存至 output.xlsx'), 'SUCCESS');
  assert.equal(normalizeLogLevel('SYSTEM', '初始化完成'), 'INFO');

  const normalized = normalizeLogEntries([
    { text: '系统准备就绪', level: 'INFO' },
    { id: '2', time: '10:01:02', level: 'WARN', text: '跳过空城市' },
    { id: '3', time: '10:01:05', level: 'ERROR', text: '网络连接超时' },
    { id: '4', time: '10:01:09', level: 'SUCCESS', text: '核算表导出完成' },
  ]);

  assert.equal(normalized[0].id, 'log-0');
  assert.equal(normalized[0].time, '--:--:--');
  const counts = countLogLevels(normalized);
  assert.deepEqual(counts, { ALL: 4, INFO: 1, SUCCESS: 1, WARN: 1, ERROR: 1 });
  assert.equal(getLogLevelLabel('ERROR'), '异常');
  assert.equal(getLogLevelLabel('SUCCESS'), '完成');
});

test('filterLogEntries, highlightMatchSegments, and formatLogsForExport work cleanly', () => {
  const entries = normalizeLogEntries([
    { id: 'a', time: '09:30:00', level: 'INFO', text: '正在拉取宁波配送费' },
    { id: 'b', time: '09:30:12', level: 'ERROR', text: '宁波站登录态已失效' },
    { id: 'c', time: '09:30:18', level: 'SUCCESS', text: '杭州账单校验通过' },
  ]);

  const errorsOnly = filterLogEntries(entries, { level: 'ERROR', query: '宁波' });
  assert.equal(errorsOnly.length, 1);
  assert.equal(errorsOnly[0].id, 'b');

  const segments = highlightMatchSegments('宁波站登录态已失效', '登录态');
  assert.deepEqual(segments, [
    { text: '宁波站', match: false },
    { text: '登录态', match: true },
    { text: '已失效', match: false },
  ]);

  const exported = formatLogsForExport(errorsOnly, '处理中');
  assert.match(exported, /# 当前状态: 处理中/);
  assert.match(exported, /\[09:30:12\] \[ERROR  \] 宁波站登录态已失效/);
});
