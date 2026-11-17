import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createDemoApprovalData,
  createDemoDeductionProfile,
  createDemoPayrollQueueTasks,
  createDemoTaskCenterRecords,
  filterApprovalTasks,
  filterPayrollQueueTasks,
  filterTaskCenterRecords,
  getDemoApprovalPriceDetail,
} from '../src/lib/workbenchDemoData';
import { CONFIG_RULE_COLUMNS, summarizeCitiesProgress } from '../src/lib/deductionCategories';

test('demo payroll queue provides 20 batches covering all operational statuses and modes', () => {
  const tasks = createDemoPayrollQueueTasks();
  assert.equal(tasks.length, 20);
  const statuses = new Set(tasks.map(t => t.status));
  for (const required of [
    'completed',
    'calculating',
    'preparing',
    'queued',
    'waiting_confirmation',
    'error',
    'stopping',
    'cancelled',
    'interrupted',
  ]) {
    assert.ok(statuses.has(required), `missing status ${required}`);
  }
  assert.ok(tasks.some(t => t.mode === 'fengshen'));
  assert.ok(tasks.some(t => t.mode === 'manual'));
  assert.ok(tasks.some(t => t.legacy));
  assert.ok(tasks.some(t => t.preparation?.result?.review_summary));

  assert.equal(filterPayrollQueueTasks(tasks, 'all', '').length, 20);
  assert.ok(filterPayrollQueueTasks(tasks, 'active', '').length >= 4);
  assert.ok(filterPayrollQueueTasks(tasks, 'waiting', '').length >= 2);
  assert.ok(filterPayrollQueueTasks(tasks, 'completed', '').length >= 6);
  assert.ok(filterPayrollQueueTasks(tasks, 'issue', '').length >= 4);
  assert.equal(filterPayrollQueueTasks(tasks, 'all', '广州').length, 1);
});

test('demo approval data provides 20 workflows spanning multiple cities, months, blocked reasons, and batches', () => {
  const data = createDemoApprovalData();
  assert.equal(data.rows.length, 20);
  const cities = new Set(data.rows.map(r => r.cityName));
  const months = new Set(data.rows.map(r => r.settle_month));
  assert.ok(cities.size >= 8);
  assert.ok(months.size >= 3);
  assert.ok(data.rows.some(r => Boolean(r.reason)), 'includes blocked/ineligible items');
  assert.ok(data.rows.some(r => r.rider_count === 0), 'includes 0-rider boundary row');
  assert.ok(data.batches.length >= 3);

  const eligible = filterApprovalTasks(data.rows, {
    scopeCities: [],
    scopeMonths: [],
    scopeSite: '',
    eligibility: 'eligible',
  });
  const blocked = filterApprovalTasks(data.rows, {
    scopeCities: [],
    scopeMonths: [],
    scopeSite: '',
    eligibility: 'blocked',
  });
  assert.equal(eligible.length + blocked.length, 20);
  assert.ok(blocked.length >= 3);

  const detail = getDemoApprovalPriceDetail(data.rows[0]);
  assert.ok(detail.columns.length >= 5);
  assert.ok(detail.rows.length >= 3);
});

test('demo task center provides 20 multi-platform records and supports client-side filtering & counts', () => {
  const records = createDemoTaskCenterRecords();
  assert.equal(records.length, 20);
  const kinds = new Set(records.map(r => r.kind));
  for (const reqKind of ['download', 'generate', 'payroll', 'approval', 'price-export']) {
    assert.ok(kinds.has(reqKind), `missing kind ${reqKind}`);
  }
  const statuses = new Set(records.map(r => r.status));
  for (const reqStatus of ['running', 'queued', 'success', 'partial', 'waiting_login', 'waiting_manual', 'error', 'cancelled', 'interrupted', 'empty']) {
    assert.ok(statuses.has(reqStatus), `missing status ${reqStatus}`);
  }

  const allRes = filterTaskCenterRecords(records, {});
  assert.equal(allRes.items.length, 20);
  assert.equal(allRes.counts.all, 20);
  assert.ok(allRes.counts.active >= 3);
  assert.ok(allRes.counts.attention >= 6);
  assert.ok(allRes.counts.success >= 7);

  const xiaoxiangOnly = filterTaskCenterRecords(records, { system: 'xiaoxiang' });
  assert.equal(xiaoxiangOnly.items.length, 3);
});

test('demo deduction profile covers 20 cities and 10+ stations per city across all 13 rule columns', () => {
  const profile = createDemoDeductionProfile();
  assert.equal(profile.cities.length, 20);
  assert.deepEqual(profile.columns, [...CONFIG_RULE_COLUMNS]);
  const summaries = summarizeCitiesProgress(profile.cities, profile.entries, profile.directoryCities);
  assert.equal(summaries.length, 20);
  for (const city of summaries) {
    assert.ok(city.totalStations >= 10, `${city.cityName} has fewer than 10 stations`);
  }
  assert.ok(profile.entries.some(e => e.station_override));
  assert.ok(profile.entries.some(e => e.inherited_city));
  assert.ok(profile.entries.some(e => e.zero_confirmed));
  assert.ok(profile.entries.some(e => !e.configured));
  assert.ok(profile.entries.some(e => e.legacy));
  assert.ok(profile.entries.some(e => e.edited));
});
