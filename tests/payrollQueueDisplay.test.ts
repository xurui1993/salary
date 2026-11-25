import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  buildPayrollProgressPopoverData,
  canPermanentlyDeletePayrollTask,
  extractPayrollAmount,
  formatPayrollAmount,
  formatPayrollDateTime,
  payrollCycleLabel,
  payrollPeriodRange,
  payrollSettlementType,
  payrollTypeTone,
  resolvePayrollElapsedText,
  resolvePayrollGeneratedAt,
  type PayrollQueueTask,
} from '../src/lib/payrollQueue';
import { filterPayrollQueueAdvanced } from '../src/lib/workbenchFilters';
import { PayrollQueueTable } from '../src/components/PayrollQueueWorkbench';

const SAMPLE_PAYROLL_TASKS: PayrollQueueTask[] = [
  {
    id: 'pq-1',
    status: 'calculating',
    mode: 'fengshen',
    settlement_type: '月结',
    template_name: '上海_10月_月结.xlsx',
    approval_code: 'SP-202610-001',
    progress: 74,
    elapsed_seconds: 92,
    current_action: '正在核对骑手出勤与阶梯单价',
    plan: { city: '上海', start: '2026-10-01', end: '2026-10-31', applicants: 86, cycle: '10月整月' },
  },
  {
    id: 'pq-2',
    status: 'queued',
    mode: 'fengshen',
    settlement_type: '周结',
    template_name: '广州_周结.xlsx',
    approval_code: 'SP-202610-002',
    elapsed_seconds: 12,
    current_action: '排队等待执行',
    plan: { city: '广州', start: '2026-10-01', end: '2026-10-07', applicants: 42 },
  },
  {
    id: 'pq-3',
    status: 'completed',
    mode: 'xiaoxiang',
    settlement_type: '全职',
    batch_id: 'batch-3',
    template_name: '深圳_全职.xlsx',
    approval_code: 'SP-202610-003',
    elapsed_seconds: 118,
    finished_at: '2026-11-24T11:33:01+08:00',
    amount: 612480.5,
    plan: { city: '深圳', start: '2026-10-01', end: '2026-10-31', applicants: 128 },
    review_summary: { issues: ['1 名骑手缺少单价'] },
  },
  {
    id: 'pq-4',
    status: 'waiting_confirmation',
    mode: 'manual',
    settlement_type: '半月结',
    template_name: '北京_半月结.xlsx',
    approval_code: 'SP-202610-004',
    elapsed_seconds: 55,
    plan: { city: '北京', start: '2026-10-01', end: '2026-10-15', applicants: 35 },
  },
  {
    id: 'pq-5',
    status: 'error',
    mode: 'fengshen',
    settlement_type: '日结',
    template_name: '杭州_日结.xlsx',
    approval_code: 'SP-202610-005',
    elapsed_seconds: 40,
    plan: { city: '杭州', start: '2026-10-20', end: '2026-10-20', applicants: 19 },
  },
];

test('payrollQueue pure helpers format period, cycle, type tone, elapsed duration, amount and generated time cleanly', () => {
  assert.equal(payrollPeriodRange({ start: '2026-10-01', end: '2026-10-31' }), '10.01 - 10.31');
  assert.equal(payrollPeriodRange({ start: '2026-10-05', end: '2026-10-05' }), '10.05');
  assert.equal(payrollPeriodRange({ start: '2025-12-16', end: '2026-01-15' }), '2025.12.16 - 2026.01.15');
  assert.equal(payrollCycleLabel({ cycle: '9月整月（历史批次）' }), '9月整月');
  assert.equal(payrollCycleLabel({ month: '2026-11' }), '11月账期');
  assert.equal(payrollTypeTone('fengshen'), 'auto');
  assert.equal(payrollTypeTone('manual'), 'manual');
  assert.equal(payrollTypeTone('xiaoxiang'), 'xiaoxiang');
  assert.equal(payrollSettlementType({ settlement_type: '全职' }), '全职');
  assert.equal(payrollSettlementType({ settlement_type: '日结' }), '日结');
  assert.equal(resolvePayrollElapsedText({ elapsed_seconds: 92 }), '1分32秒');
  assert.equal(resolvePayrollElapsedText({ elapsed_seconds: 47 }), '47秒');

  assert.equal(extractPayrollAmount({ amount: 612480.5 }), 612480.5);
  assert.equal(extractPayrollAmount({ plan: { total_amount: '128,400.25' } }), 128400.25);
  assert.equal(
    extractPayrollAmount({
      preparation: {
        result: {
          review_summary: {
            metrics: [{ key: 'payable_amount', label: '应发总额', value: 98520.4, unit: '元' }],
          },
        },
      } as any,
    }),
    98520.4,
  );
  assert.equal(extractPayrollAmount({ status: 'queued' }), null);
  assert.equal(formatPayrollAmount(612480.5), '612,480.50');
  assert.equal(formatPayrollAmount(null), '—');

  assert.equal(formatPayrollDateTime('2026-11-24T11:33:01+08:00'), '2026-11-24 11:33:01');
  assert.equal(formatPayrollDateTime('2026-11-24T00:05:09+08:00'), '2026-11-24 00:05:09');
  assert.equal(formatPayrollDateTime('2026-11-24 11:33:01'), '2026-11-24 11:33:01');
  assert.equal(formatPayrollDateTime(null), '—');
  assert.equal(
    resolvePayrollGeneratedAt({ status: 'completed', finished_at: '2026-11-24T11:33:01+08:00' }),
    '2026-11-24T11:33:01+08:00',
  );
  assert.equal(resolvePayrollGeneratedAt({ status: 'calculating', created_at: '2026-11-24T11:30:00+08:00' }), null);

  assert.equal(canPermanentlyDeletePayrollTask({ status: 'completed' }), true);
  assert.equal(canPermanentlyDeletePayrollTask({ status: 'error' }), true);
  assert.equal(canPermanentlyDeletePayrollTask({ status: 'cancelled' }), true);
  assert.equal(canPermanentlyDeletePayrollTask({ status: 'queued' }), false);
  assert.equal(canPermanentlyDeletePayrollTask({ status: 'calculating' }), false);
});

test('payroll tasks fixture covers amounts, generated time, compact period, and all 5 settlement types', () => {
  const tasks = SAMPLE_PAYROLL_TASKS;
  const completed = tasks.find(t => t.id === 'pq-3')!;
  assert.equal(extractPayrollAmount(completed), 612480.5);
  assert.equal(formatPayrollDateTime(resolvePayrollGeneratedAt(completed)), '2026-11-24 11:33:01');
  assert.ok(tasks.every(t => resolvePayrollElapsedText(t).length > 0));

  const types = new Set(tasks.map(t => payrollSettlementType(t)));
  assert.deepEqual([...types].sort(), ['全职', '半月结', '周结', '日结', '月结'].sort());

  const queued = tasks.find(t => t.status === 'queued')!;
  assert.equal(extractPayrollAmount(queued), null);
  assert.equal(resolvePayrollGeneratedAt(queued), null);

  const alertRows = filterPayrollQueueAdvanced(tasks, { tab: 'all', keyword: '', alertOnly: true });
  assert.equal(alertRows.length, 1);
});

test('buildPayrollProgressPopoverData returns elapsed timing, progress percentage, and current processing node', () => {
  const running = SAMPLE_PAYROLL_TASKS[0];
  const pop = buildPayrollProgressPopoverData(running);
  assert.equal(pop.badgeLabel, '核算中');
  assert.equal(pop.elapsedLabel, '核算耗时');
  assert.equal(pop.elapsedValue, '1分32秒');
  assert.equal(pop.percent, 74);
  assert.ok(pop.currentNode.length > 0);
  assert.ok(pop.metrics.some(m => m.label === '核算范围'));

  const queued = SAMPLE_PAYROLL_TASKS.find(t => t.status === 'queued')!;
  const queuedPop = buildPayrollProgressPopoverData(queued);
  assert.equal(queuedPop.percent, null);
  assert.ok(queuedPop.currentNode.length > 0);
});

test('PayrollQueueTable renders 生成时间 column, status-progress bar, and archived permanent delete button', () => {
  const tasks = SAMPLE_PAYROLL_TASKS;
  const noop = () => {};
  const html = renderToStaticMarkup(
    React.createElement(PayrollQueueTable, {
      tasks,
      checked: [],
      onSelect: noop,
      onOpenDetail: noop,
      onCheck: noop,
      onCheckAll: noop,
      onStop: noop,
      onRemove: noop,
      onPermanentDelete: noop,
      onDownload: noop,
      onOpenDirectory: noop,
      onRestore: noop,
      onApproval: async () => {},
    }),
  );

  for (const heading of ['审批编号', '城市', '周期', '类型', '人数', '生成时间', '核算进度', '操作']) {
    assert.match(html, new RegExp(`>${heading}<`));
  }
  assert.doesNotMatch(html, />金额</);
  assert.match(html, /2026-11-24 11:33:01/);
  assert.match(html, /10\.01 - 10\.31/);
  assert.doesNotMatch(html, /10月整月\s*·/);
  assert.doesNotMatch(html, /闪购自动/);
  assert.match(html, /月结/);
  assert.match(html, /周结/);
  assert.match(html, /全职/);
  assert.match(html, /半月结/);
  assert.match(html, /日结/);
  assert.match(html, /wbx-pill--has-progress/);
  assert.match(html, /wbx-pill__fill/);
  assert.match(html, /width:74%/);
  assert.match(html, /wbx-pill__pct/);
  assert.match(html, /wbx-status-hover-trigger/);
  assert.doesNotMatch(html, /pq-inline-progress__track/);
  assert.doesNotMatch(html, /pq-elapsed-text/);
  assert.doesNotMatch(html, /pq-detail-trigger|>详情</);
  assert.doesNotMatch(html, /pq-review-alert-btn/);
  assert.doesNotMatch(html, /pq-expand-toggle|pq-row-detail/);

  const archivedHtml = renderToStaticMarkup(
    React.createElement(PayrollQueueTable, {
      tasks: [SAMPLE_PAYROLL_TASKS[2]],
      checked: [],
      hidden: true,
      onSelect: noop,
      onOpenDetail: noop,
      onCheck: noop,
      onCheckAll: noop,
      onStop: noop,
      onRemove: noop,
      onPermanentDelete: noop,
      onDownload: noop,
      onOpenDirectory: noop,
      onRestore: noop,
      onApproval: async () => {},
    }),
  );
  assert.match(archivedHtml, />恢复</);
  assert.match(archivedHtml, /pq-delete-btn/);
  assert.match(archivedHtml, /彻底删除/);
});
