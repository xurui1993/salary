import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  extractPayrollAmount,
  formatPayrollAmount,
  payrollCycleLabel,
  payrollPeriodRange,
  payrollTypeTone,
} from '../src/lib/payrollQueue';
import { buildDemoPayrollTasks } from '../src/lib/showcaseDemoData';
import { PayrollQueueTable } from '../src/components/PayrollQueueWorkbench';

test('payrollQueue pure helpers format period, cycle, type tone and amount cleanly', () => {
  assert.equal(payrollPeriodRange({ start: '2026-10-01', end: '2026-10-31' }), '10.01 - 10.31');
  assert.equal(payrollCycleLabel({ cycle: '9月整月（历史批次）' }), '9月整月');
  assert.equal(payrollCycleLabel({ month: '2026-11' }), '11月账期');
  assert.equal(payrollTypeTone('fengshen'), 'auto');
  assert.equal(payrollTypeTone('manual'), 'manual');
  assert.equal(payrollTypeTone('xiaoxiang'), 'xiaoxiang');

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

test('demo payroll tasks provide realistic amounts and drawer details', () => {
  const tasks = buildDemoPayrollTasks();
  const shCompleted = tasks.find(t => t.id === 'demo-pq-12');
  assert.ok(shCompleted);
  assert.equal(extractPayrollAmount(shCompleted), 612480.5);
  assert.ok(shCompleted.preparation?.result?.review_summary?.metrics?.length);
  assert.ok(shCompleted.preparation?.automatic_deductions?.sources?.length);

  const queued = tasks.find(t => t.status === 'queued');
  assert.ok(queued);
  assert.equal(extractPayrollAmount(queued), null);
});

test('PayrollQueueTable renders exact 8 requested columns and detail trigger', () => {
  const tasks = buildDemoPayrollTasks().slice(0, 3);
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
  assert.match(html, /闪购自动/);
  assert.match(html, /小象超市/);
  assert.match(html, /详情/);
  assert.doesNotMatch(html, /pq-expand-toggle|pq-row-detail/);
});
