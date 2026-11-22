import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  buildPayrollProgressPopoverData,
  extractPayrollAmount,
  formatPayrollAmount,
  payrollCycleLabel,
  payrollPeriodRange,
  payrollSettlementType,
  payrollTypeTone,
  resolvePayrollElapsedText,
} from '../src/lib/payrollQueue';
import { buildDemoPayrollTasks } from '../src/lib/showcaseDemoData';
import { PayrollQueueTable } from '../src/components/PayrollQueueWorkbench';

test('payrollQueue pure helpers format period, cycle, type tone, elapsed duration and amount cleanly', () => {
  assert.equal(payrollPeriodRange({ start: '2026-10-01', end: '2026-10-31' }), '10.01-10.31');
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
});

test('demo payroll tasks provide realistic amounts, compact period, elapsed time on all tasks, and all 5 settlement types', () => {
  const tasks = buildDemoPayrollTasks();
  const shCompleted = tasks.find(t => t.id === 'demo-pq-12');
  assert.ok(shCompleted);
  assert.equal(extractPayrollAmount(shCompleted), 612480.5);
  assert.ok(shCompleted.preparation?.result?.review_summary?.metrics?.length);
  assert.ok(shCompleted.preparation?.automatic_deductions?.sources?.length);

  assert.ok(tasks.every(t => resolvePayrollElapsedText(t).length > 0), 'Every demo payroll task must have an elapsed duration');

  const types = new Set(tasks.map(t => payrollSettlementType(t)));
  assert.deepEqual([...types].sort(), ['全职', '半月结', '周结', '日结', '月结'].sort());

  const queued = tasks.find(t => t.status === 'queued');
  assert.ok(queued);
  assert.equal(extractPayrollAmount(queued), null);
});

test('buildPayrollProgressPopoverData returns elapsed timing, progress percentage, and current processing node', () => {
  const tasks = buildDemoPayrollTasks();
  const running = tasks[0];
  const pop = buildPayrollProgressPopoverData(running);
  assert.equal(pop.badgeLabel, '核算中');
  assert.equal(pop.elapsedLabel, '核算耗时');
  assert.equal(pop.elapsedValue, '1分32秒');
  assert.equal(pop.percent, 74);
  assert.ok(pop.currentNode.length > 0);
  assert.ok(pop.metrics.some(m => m.label === '核算范围'));

  const queued = tasks.find(t => t.status === 'queued')!;
  const queuedPop = buildPayrollProgressPopoverData(queued);
  assert.equal(queuedPop.percent, null);
  assert.ok(queuedPop.currentNode.length > 0);
});

test('PayrollQueueTable renders combined status-progress bar with hover popover trigger and removes inline elapsed text', () => {
  const tasks = buildDemoPayrollTasks().slice(0, 6);
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
      onDownload: noop,
      onOpenDirectory: noop,
      onRestore: noop,
      onApproval: async () => {},
    }),
  );

  for (const heading of ['审批编号', '城市', '周期', '类型', '人数', '金额', '核算进度', '操作']) {
    assert.match(html, new RegExp(`>${heading}<`));
  }
  assert.match(html, /10\.01-10\.31/);
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
  assert.match(html, /详情/);
  assert.doesNotMatch(html, /pq-expand-toggle|pq-row-detail/);
});
