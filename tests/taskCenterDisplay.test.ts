import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildTaskProgressPopoverData,
  buildTaskTimelineSteps,
  canOpenTaskResultDirectory,
  canPermanentlyDeleteTask,
  cleanTaskTitle,
  computeDatePresetRange,
  displayTaskNumber,
  computeTaskDiagnosticNote,
  formatCitiesCompact,
  formatCompactTimestamp,
  formatFileSize,
  formatPeriodCompact,
  formatTaskContentDisplay,
  isTaskRetryable,
  platformTone,
  resolveTaskAuthSystem,
  resolveTaskPrimaryAction,
  sortTaskDisplayRecords,
  summarizeTaskBatchSelection,
} from '../src/lib/taskCenterDisplay';
import { buildDemoTaskCenterRecords } from '../src/lib/showcaseDemoData';

test('displayTaskNumber strips internal kind prefixes and shows the 6-char delivery code', () => {
  assert.equal(displayTaskNumber('approval:789096cc07044f45aabbccddeeff0011'), '789096');
  assert.equal(displayTaskNumber('price-export:0123abcd4567ef890123abcd4567ef89'), '0123AB');
  assert.equal(displayTaskNumber('payroll_789096cc07044f45aabbccddeeff0011'), '789096');
  assert.equal(displayTaskNumber('789096cc07044f45aabbccddeeff0011'), '789096');
  assert.equal(displayTaskNumber(''), '');
});

test('cleanTaskTitle removes redundant leading platform and kind prefixes without altering plain titles', () => {
  assert.equal(
    cleanTaskTitle('风神 · 上海/深圳/广州 10月配送费与违规扣款', '风神', '资料下载'),
    '上海/深圳/广州 10月配送费与违规扣款',
  );
  assert.equal(
    cleanTaskTitle('业务报表 · 异常跟进（大连/保定）', '风神', '业务报表'),
    '异常跟进（大连/保定）',
  );
  assert.equal(
    cleanTaskTitle('蓝橙价格审批 · 上海/深圳 10月薪资单价批量审批', '蓝橙', '价格审批'),
    '上海/深圳 10月薪资单价批量审批',
  );
  assert.equal(cleanTaskTitle('配送费、违规扣款', '风神', '资料下载'), '配送费、违规扣款');
});

test('formatTaskContentDisplay, formatCitiesCompact, formatPeriodCompact, formatCompactTimestamp and permanent delete eligibility work cleanly', () => {
  const labels: Record<string, string> = {
    delivery_fee: '配送费',
    violation: '违规扣款',
    rider_detail: '骑手明细',
    fraud_order: '欺诈单',
  };
  const datasetLabel = (id: string) => labels[id] || id;

  assert.deepEqual(
    formatTaskContentDisplay(
      {
        kind: 'download',
        title: '风神 · 上海/深圳/广州 10月配送费与违规扣款',
        datasets: ['delivery_fee', 'violation'],
        cities: ['上海', '深圳', '广州'],
      },
      { datasetLabel, platformName: '风神', kindLabel: '资料下载' },
    ),
    { short: '配送费、违规扣款', full: '配送费、违规扣款' },
  );
  assert.deepEqual(
    formatTaskContentDisplay(
      {
        kind: 'download',
        title: '风神 · 多表采集',
        datasets: ['delivery_fee', 'violation', 'rider_detail', 'fraud_order'],
        cities: ['上海'],
      },
      { datasetLabel, platformName: '风神', kindLabel: '资料下载' },
    ),
    { short: '配送费、违规扣款 等4项', full: '配送费、违规扣款、骑手明细、欺诈单' },
  );
  assert.equal(
    formatTaskContentDisplay(
      {
        kind: 'approval',
        title: '蓝橙价格审批 · 上海/深圳 10月薪资单价批量审批',
        datasets: [],
        cities: ['上海', '深圳'],
      },
      { datasetLabel, platformName: '蓝橙', kindLabel: '价格审批' },
    ).short,
    '薪资单价批量审批',
  );
  assert.deepEqual(
    formatTaskContentDisplay(
      {
        kind: 'download',
        datasets: ['rider_daily', 'detail_orders'],
        cities: ['北京', '天津'],
      },
      {
        datasetLabel: id =>
          id === 'rider_daily' ? '日维度骑手分析（灯塔）' : '配送订单明细（灯塔）',
        platformName: '灯塔',
        kindLabel: '资料下载',
      },
    ),
    {
      short: '日维度骑手分析、配送订单明细',
      full: '日维度骑手分析（灯塔）、配送订单明细（灯塔）',
    },
  );
  assert.equal(
    formatTaskContentDisplay(
      {
        kind: 'download',
        datasets: ['baize_employees'],
        cities: ['全量'],
      },
      {
        datasetLabel: () => '商翼员工资料（全量）',
        platformName: '商翼',
        kindLabel: '资料下载',
      },
    ).short,
    '员工资料',
  );

  assert.deepEqual(formatCitiesCompact(['上海', '深圳', '广州']), {
    short: '上海等3城',
    full: '上海、深圳、广州',
  });
  assert.deepEqual(formatCitiesCompact(['宁波', '泉州']), {
    short: '宁波、泉州',
    full: '宁波、泉州',
  });
  assert.deepEqual(formatCitiesCompact(['按业务筛选范围']), {
    short: '按筛选范围',
    full: '按业务筛选范围',
  });
  assert.deepEqual(formatCitiesCompact([]), { short: '全部城市', full: '全部城市' });
  assert.deepEqual(formatCitiesCompact([], ['baize_employees']), { short: '全量', full: '全量数据' });

  assert.equal(formatPeriodCompact('2026-10-01', '2026-10-31', ['delivery_fee']).short, '10.01 - 10.31');
  assert.equal(formatPeriodCompact('2026-11-21', '2026-11-21', ['baize_employees']).short, '全量数据');
  assert.equal(formatPeriodCompact('2026-11-21', '2026-11-21', ['rider_archive']).short, '当前快照');
  assert.equal(formatPeriodCompact('', '', [], 'approval').short, '单次审批');
  assert.equal(formatPeriodCompact('', '', [], 'price-export').short, '按筛选范围');

  assert.equal(canPermanentlyDeleteTask({ status: 'success' }), true);
  assert.equal(canPermanentlyDeleteTask({ status: 'error' }), true);
  assert.equal(canPermanentlyDeleteTask({ status: 'cancelled' }), true);
  assert.equal(canPermanentlyDeleteTask({ status: 'running' }), false);
  assert.equal(canPermanentlyDeleteTask({ status: 'queued' }), false);
  assert.equal(canPermanentlyDeleteTask({ status: 'waiting_login' }), false);

  const now = Date.parse('2026-11-21T23:00:00+08:00');
  assert.equal(formatCompactTimestamp('2026-11-21T22:55:00+08:00', now).short, '今天 22:55');
  assert.equal(formatCompactTimestamp('2026-11-20T19:40:00+08:00', now).short, '昨天 19:40');
  assert.equal(formatCompactTimestamp('2026-11-18T14:15:00+08:00', now).short, '11.18 14:15');

  assert.equal(platformTone('风神'), 'fengshen');
  assert.equal(platformTone('灯塔'), 'xiaoxiang');
  assert.equal(platformTone('蓝橙'), 'lanorange');
  assert.equal(platformTone('商翼'), 'payout');
  assert.equal(formatFileSize(1_840_200), '1.8 MB');
  assert.equal(formatFileSize(512_000), '500 KB');
});

test('resolveTaskPrimaryAction converges to a single contextual CTA without duplicating detail button', () => {
  assert.equal(
    resolveTaskPrimaryAction({ status: 'running', kind: 'download', available_files: 2, failed_items: 0 }),
    null,
  );
  assert.equal(
    resolveTaskPrimaryAction({ status: 'queued', kind: 'download', available_files: 0, failed_items: 0 }),
    null,
  );

  assert.equal(
    resolveTaskPrimaryAction({ status: 'waiting_login', kind: 'download', available_files: 0, failed_items: 0 })?.label,
    '去验证',
  );
  assert.equal(
    resolveTaskPrimaryAction({ status: 'partial', kind: 'download', available_files: 3, failed_items: 2 })?.label,
    '处理异常',
  );
  assert.equal(
    resolveTaskPrimaryAction({ status: 'error', kind: 'download', available_files: 0, failed_items: 1 })?.label,
    '查看原因',
  );

  assert.equal(
    resolveTaskPrimaryAction({ status: 'success', kind: 'download', available_files: 5, failed_items: 0 })?.type,
    'download',
  );
  assert.equal(
    resolveTaskPrimaryAction({
      status: 'success',
      kind: 'approval',
      price_id: 'AP-01',
      available_files: 1,
      failed_items: 0,
    })?.type,
    'price',
  );

  assert.equal(
    resolveTaskPrimaryAction({ status: 'success', kind: 'download', available_files: 1, failed_items: 0 }, true)?.type,
    'restore',
  );

  assert.equal(
    canOpenTaskResultDirectory({ status: 'success', kind: 'download', available_files: 3 }),
    true,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'partial', kind: 'download', available_files: 2 }),
    true,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'error', kind: 'download', available_files: 0 }),
    true,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'running', kind: 'download', available_files: 0 }),
    false,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'running', kind: 'download', available_files: 2 }),
    true,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'empty', kind: 'download', available_files: 0 }),
    false,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'success', kind: 'approval', available_files: 0 }),
    true,
  );
  assert.equal(
    canOpenTaskResultDirectory({ status: 'success', kind: 'download', available_files: 3 }, true),
    false,
  );
});

test('computeTaskDiagnosticNote surfaces alerts only for abnormal tasks and buildTaskTimelineSteps covers all demo tasks', () => {
  assert.equal(
    computeTaskDiagnosticNote({ status: 'running', completed_items: 3, total_items: 6, failed_items: 0 }),
    null,
  );
  assert.equal(
    computeTaskDiagnosticNote({ status: 'success', completed_items: 6, total_items: 6, failed_items: 0 }),
    null,
  );
  assert.equal(
    computeTaskDiagnosticNote({
      status: 'error',
      error: '接口返回 503',
      completed_items: 0,
      total_items: 1,
      failed_items: 1,
    })?.tone,
    'error',
  );
  assert.equal(
    computeTaskDiagnosticNote({
      status: 'waiting_login',
      error: '登录态失效',
      completed_items: 0,
      total_items: 1,
      failed_items: 0,
    })?.tone,
    'warn',
  );

  const demo = buildDemoTaskCenterRecords();
  assert.equal(demo.length, 30);
  const problemDemo = demo.find(item => item.id === 'TC-20261121-007');
  assert.ok(problemDemo);
  assert.equal(problemDemo.kind, 'generate');
  assert.deepEqual(problemDemo.datasets, ['problem']);
  for (const item of demo) {
    const steps = buildTaskTimelineSteps(
      {
        ...item,
        files: item.files.map(f => ({ ...f, run_id: item.id, city: f.city || '全量', available: true })),
        available_files: item.files.length,
      },
      '风神',
    );
    assert.ok(steps.length >= 2, `demo task ${item.id} should synthesize at least 2 timeline steps`);
  }
});

test('P0/P1 task helpers: auth system resolution, retryability, date presets, batch summary and sorting', () => {
  assert.equal(resolveTaskAuthSystem({ kind: 'download', datasets: ['baize_employees'] }), 'baize');
  assert.equal(resolveTaskAuthSystem({ kind: 'download', datasets: ['benlai_employees'] }), 'benlai');
  assert.equal(resolveTaskAuthSystem({ kind: 'download', datasets: ['rider_daily'] }), 'xiaoxiang');
  assert.equal(resolveTaskAuthSystem({ kind: 'download', datasets: ['lanorange_summary'] }), 'lanorange');
  assert.equal(resolveTaskAuthSystem({ kind: 'download', datasets: ['delivery_fee'] }), 'fengshen');
  assert.equal(resolveTaskAuthSystem({ kind: 'approval', price_id: 'AP-1', datasets: [] }), 'lanorange');

  assert.equal(isTaskRetryable({ status: 'error', kind: 'download' }), true);
  assert.equal(isTaskRetryable({ status: 'partial', kind: 'generate' }), true);
  assert.equal(isTaskRetryable({ status: 'cancelled', kind: 'download' }), true);
  assert.equal(isTaskRetryable({ status: 'success', kind: 'download' }), false);
  assert.equal(isTaskRetryable({ status: 'error', kind: 'approval' }), false);

  const refMs = Date.parse('2026-11-21T12:00:00+08:00');
  assert.deepEqual(computeDatePresetRange('today', refMs), { from: '2026-11-21', to: '2026-11-21' });
  assert.deepEqual(computeDatePresetRange('7d', refMs), { from: '2026-11-15', to: '2026-11-21' });
  assert.deepEqual(computeDatePresetRange('month', refMs), { from: '2026-11-01', to: '2026-11-21' });

  const summary = summarizeTaskBatchSelection([
    { id: 't1', kind: 'download', status: 'success', available_files: 3 },
    { id: 't2', kind: 'download', status: 'running', available_files: 0 },
    { id: 't3', kind: 'download', status: 'queued', available_files: 0 },
    { id: 't4', kind: 'approval', status: 'success', available_files: 2 },
  ]);
  assert.equal(summary.total, 4);
  assert.deepEqual(summary.downloadableIds, ['t1']);
  assert.equal(summary.downloadableCount, 1);
  assert.equal(summary.skippedDownloadCount, 3);
  assert.deepEqual(summary.activeIds, ['t2', 't3']);
  assert.equal(summary.activeCount, 2);

  const unsorted = [
    { id: 'a', created_at: '2026-11-20T10:00:00+08:00', elapsed_seconds: 60, available_files: 2 },
    { id: 'b', created_at: '2026-11-21T10:00:00+08:00', elapsed_seconds: 300, available_files: 1 },
    { id: 'c', created_at: '2026-11-19T10:00:00+08:00', elapsed_seconds: 120, available_files: 5 },
  ];
  assert.deepEqual(sortTaskDisplayRecords(unsorted, 'created_desc').map(r => r.id), ['b', 'a', 'c']);
  assert.deepEqual(sortTaskDisplayRecords(unsorted, 'elapsed_desc').map(r => r.id), ['b', 'c', 'a']);
  assert.deepEqual(sortTaskDisplayRecords(unsorted, 'files_desc').map(r => r.id), ['c', 'a', 'b']);
});

test('buildTaskProgressPopoverData exposes elapsed timing, item progress, and current processing node', () => {
  const running = buildTaskProgressPopoverData(
    {
      status: 'running',
      created_at: '2026-11-21T21:18:00+08:00',
      updated_at: '2026-11-21T21:24:03+08:00',
      completed_items: 4,
      total_items: 6,
      failed_items: 0,
      available_files: 3,
    },
    {
      statusLabel: '处理中',
      tone: 'active',
      percent: 67,
      elapsedText: '6分03秒',
      platformName: '风神',
      nowMs: Date.parse('2026-11-21T21:25:00+08:00'),
    },
  );
  assert.equal(running.badgeLabel, '处理中');
  assert.equal(running.elapsedLabel, '任务耗时');
  assert.equal(running.elapsedValue, '6分03秒');
  assert.equal(running.percent, 67);
  assert.match(running.currentNode, /风神/);
  assert.match(running.currentNode, /4 \/ 6/);
  assert.ok(running.metrics.some(m => m.label === '子项进度' && m.value === '4 / 6 项'));

  const partial = buildTaskProgressPopoverData(
    {
      status: 'partial',
      created_at: '2026-11-21T20:36:00+08:00',
      updated_at: '2026-11-21T20:42:00+08:00',
      completed_items: 6,
      total_items: 8,
      failed_items: 2,
      available_files: 3,
      error: '泉州问题单拉取超时',
    },
    {
      statusLabel: '部分完成',
      tone: 'waiting',
      percent: null,
      elapsedText: '6分00秒',
      platformName: '风神',
      diagNote: { text: '泉州问题单拉取超时', tone: 'warn' },
      nowMs: Date.parse('2026-11-21T21:25:00+08:00'),
    },
  );
  assert.equal(partial.currentNode, '泉州问题单拉取超时');
  assert.ok(partial.metrics.some(m => m.label === '异常子项' && m.value === '2 项失败'));
});

