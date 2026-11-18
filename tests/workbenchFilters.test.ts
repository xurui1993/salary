import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterApprovalTasks,
  filterPayrollQueueTasks,
  filterTaskCenterRecords,
  type TaskCenterFilterRecord,
} from '../src/lib/workbenchFilters';

const payroll = [
  { id: 'a', status: 'queued', template_name: '模板A', batch_id: 'b1', current_action: '', plan: { city: '上海' } },
  { id: 'b', status: 'completed', template_name: '模板B', batch_id: 'b2', current_action: '', plan: { city: '广州' } },
  { id: 'c', status: 'error', template_name: '模板C', batch_id: 'b3', current_action: '', plan: { city: '北京' } },
] as any[];

test('payroll queue filters by tab and keyword', () => {
  assert.equal(filterPayrollQueueTasks(payroll, 'all', '').length, 3);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'active', '').map(t => t.id), ['a']);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'completed', '').map(t => t.id), ['b']);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'issue', '').map(t => t.id), ['c']);
  assert.deepEqual(filterPayrollQueueTasks(payroll, 'all', '广州').map(t => t.id), ['b']);
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
];

test('task center filters by status, platform and keyword', () => {
  assert.equal(filterTaskCenterRecords(records, {}).items.length, 2);
  assert.deepEqual(filterTaskCenterRecords(records, { status: 'attention' }).items.map(r => r.id), ['r2']);
  assert.deepEqual(filterTaskCenterRecords(records, { system: 'xiaoxiang' }).items.map(r => r.id), ['r2']);
  assert.deepEqual(filterTaskCenterRecords(records, { q: '订单' }).items.map(r => r.id), ['r2']);
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