import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterApprovalTasks,
  filterPayrollQueueAdvanced,
  filterPayrollQueueTasks,
  filterTaskCenterRecords,
  type TaskCenterFilterRecord,
} from '../src/lib/workbenchFilters';
import { buildDemoTaskCenterRecords } from '../src/lib/showcaseDemoData';

const payroll = [
  { id: 'a', status: 'queued', mode: 'advance', template_name: '模板A', batch_id: 'b1', approval_code: '', current_action: '', plan: { city: '上海' } },
  { id: 'b', status: 'completed', mode: 'final', template_name: '模板B', batch_id: 'b2', approval_code: 'SP-001', current_action: '', plan: { city: '广州' } },
  { id: 'c', status: 'error', mode: 'advance', template_name: '模板C', batch_id: 'b3', approval_code: '', current_action: '', plan: { city: '北京' } },
] as any[];

test('payroll queue filters by tab, keyword, city, mode and missing approval code', () => {
  assert.equal(filterPayrollQueueTasks(payroll, 'all', '').length, 3);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'active', '').map(t => t.id), ['a']);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'completed', '').map(t => t.id), ['b']);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'issue', '').map(t => t.id), ['c']);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'all', '广州').map(t => t.id), ['b']);

  assert.deepEqual(
    filterPayrollQueueAdvanced(payroll, { tab: 'all', keyword: '', city: '上海' }).map(t => t.id),
    ['a'],
  );
  assert.deepEqual(
    filterPayrollQueueAdvanced(payroll, { tab: 'all', keyword: '', mode: 'advance' }).map(t => t.id),
    ['a', 'c'],
  );
  assert.deepEqual(
    filterPayrollQueueAdvanced(payroll, { tab: 'all', keyword: '', missingApprovalOnly: true }).map(t => t.id),
    ['a', 'c'],
  );
});

const records: TaskCenterFilterRecord[] = [
  {
    id: 'r1', kind: 'payroll', status: 'success', created_at: '2026-11-01T00:00:00',
    cities: ['上海'], datasets: [], files: [],
  },
  {
    id: 'r2', kind: 'download', status: 'error', created_at: '2026-11-02T00:00:00',
    cities: ['广州'], datasets: ['rider_daily'], files: [{ name: '订单.xlsx' }],
  },
  {
    id: 'r3', kind: 'download', status: 'waiting_login', created_at: '2026-11-02T01:00:00',
    cities: ['北京'], datasets: ['baize_employees'], files: [],
  },
  {
    id: 'r4', kind: 'download', status: 'cancelled', created_at: '2026-11-02T02:00:00',
    cities: ['深圳'], datasets: ['delivery_fee'], files: [],
  },
  {
    id: 'r5', kind: 'download', status: 'running', created_at: '2026-11-02T03:00:00',
    cities: ['杭州'], datasets: ['delivery_fee'], files: [],
  },
];

test('task center status tabs are mutually exclusive and sum to all', () => {
  const result = filterTaskCenterRecords(records, {});
  assert.equal(result.counts.all, 5);
  assert.equal(result.counts.active, 1);
  assert.equal(result.counts.attention, 2);
  assert.equal(result.counts.success, 1);
  assert.equal(result.counts.stopped, 1);
  assert.equal(
    result.counts.active + result.counts.attention + result.counts.success + result.counts.stopped,
    result.counts.all,
  );
  assert.deepEqual(filterTaskCenterRecords(records, { status: 'active' }).items.map(r => r.id), ['r5']);
  assert.deepEqual(filterTaskCenterRecords(records, { status: 'attention' }).items.map(r => r.id), ['r2', 'r3']);
  assert.deepEqual(filterTaskCenterRecords(records, { status: 'stopped' }).items.map(r => r.id), ['r4']);
  assert.deepEqual(filterTaskCenterRecords(records, { system: 'xiaoxiang' }).items.map(r => r.id), ['r2']);
  assert.deepEqual(filterTaskCenterRecords(records, { q: '订单' }).items.map(r => r.id), ['r2']);

  // Verify the 30-record demo dataset also partitions cleanly with zero overlap
  const demo = buildDemoTaskCenterRecords();
  const demoRes = filterTaskCenterRecords(demo as TaskCenterFilterRecord[], {});
  assert.equal(
    demoRes.counts.active + demoRes.counts.attention + demoRes.counts.success + demoRes.counts.stopped,
    demoRes.counts.all,
  );
});

test('approval filters separate eligible and blocked rows', () => {
  const rows = [
    { id: 'a1', cityName: '上海', settle_month: '2026-11', reason: '' },
    { id: 'a2', cityName: '广州', settle_month: '2026-11', reason: '缺单价' },
  ];
  assert.deepEqual(
    filterApprovalTasks(rows, { scopeCities: [], scopeMonths: [], scopeSite: '', eligibility: 'eligible' }).map(r => r.id),
    ['a1'],
  );
  assert.deepEqual(
    filterApprovalTasks(rows, { scopeCities: [], scopeMonths: [], scopeSite: '', eligibility: 'blocked' }).map(r => r.id),
    ['a2'],
  );
  assert.equal(filterApprovalTasks(rows, { scopeCities: ['上海'], scopeMonths: [], scopeSite: '' }).length, 1);
});