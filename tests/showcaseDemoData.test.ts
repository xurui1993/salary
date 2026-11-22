import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildDemoApprovalHistory,
  buildDemoApprovalPriceDetail,
  buildDemoDeductionData,
  buildDemoLanorangeApprovals,
  buildDemoPayrollTasks,
  buildDemoPriceExportData,
  buildDemoTaskCenterRecords,
  queryDemoTaskCenter,
} from '../src/lib/showcaseDemoData.ts';
import { filterApprovalTasks, filterPayrollQueueTasks } from '../src/lib/workbenchFilters.ts';
import { summarizeCitiesProgress } from '../src/lib/deductionCategories.ts';

test('核算批次示例数据：精确 30 条并覆盖全部状态与模式场景', () => {
  const tasks = buildDemoPayrollTasks();
  assert.equal(tasks.length, 30);

  const statuses = new Set(tasks.map(t => t.status));
  for (const required of [
    'calculating',
    'preparing',
    'queued',
    'stopping',
    'waiting_confirmation',
    'waiting_materials',
    'completed',
    'error',
    'cancelled',
    'interrupted',
  ]) {
    assert.ok(statuses.has(required), `missing payroll status: ${required}`);
  }

  const modes = new Set(tasks.map(t => t.mode));
  assert.deepEqual([...modes].sort(), ['fengshen', 'manual', 'xiaoxiang']);
  assert.ok(tasks.some(t => t.legacy === true), 'should include legacy batch');
  assert.ok(tasks.some(t => !(t.approval_code || '').trim()), 'should include empty approval_code');

  assert.ok(filterPayrollQueueTasks(tasks, 'active', '').length > 0);
  assert.ok(filterPayrollQueueTasks(tasks, 'waiting', '').length > 0);
  assert.ok(filterPayrollQueueTasks(tasks, 'completed', '').length > 0);
  assert.ok(filterPayrollQueueTasks(tasks, 'issue', '').length > 0);
  assert.equal(filterPayrollQueueTasks(tasks, 'all', 'SP-20261121-001').length, 1);
  const firstLog = tasks[0].logs?.[0] as { time?: string; text?: string } | undefined;
  assert.ok(firstLog?.text && !firstLog.text.startsWith(firstLog.time || '09:'), 'log text should not duplicate timestamp prefix');
});

test('任务中心示例数据：精确 30 条并覆盖全部状态、类型、平台与分页查询', () => {
  const records = buildDemoTaskCenterRecords();
  assert.equal(records.length, 30);

  const statuses = new Set(records.map(r => r.status));
  for (const required of [
    'running',
    'queued',
    'waiting_login',
    'waiting_manual',
    'cancelling',
    'success',
    'partial',
    'error',
    'cancelled',
    'interrupted',
    'empty',
  ]) {
    assert.ok(statuses.has(required), `missing task center status: ${required}`);
  }

  const kinds = new Set(records.map(r => r.kind));
  assert.deepEqual([...kinds].sort(), ['approval', 'download', 'generate', 'price-export']);

  const page1 = queryDemoTaskCenter(records, { status: 'all', page: 1, pageSize: 20 });
  const page2 = queryDemoTaskCenter(records, { status: 'all', page: 2, pageSize: 20 });
  assert.equal(page1.total, 30);
  assert.equal(page1.items.length, 20);
  assert.equal(page2.items.length, 10);
  assert.ok(page1.counts.active > 0);
  assert.ok(page1.counts.attention > 0);
  assert.ok(page1.counts.success > 0);

  for (const sys of ['fengshen', 'lanorange', 'baize', 'benlai', 'xiaoxiang']) {
    const res = queryDemoTaskCenter(records, { system: sys, page: 1, pageSize: 30 });
    assert.ok(res.total > 0, `missing platform coverage for ${sys}`);
  }
});

test('扣款规则示例数据：精确 30 站覆盖风神与小象全部配置状态与关键词规则', () => {
  const fs = buildDemoDeductionData('fengshen');
  assert.equal(fs.entries.length, 30);
  assert.equal(fs.cities.length, 10);
  assert.equal(fs.columns.length, 15);

  assert.ok(fs.entries.some(e => e.inherited_city), 'should include inherited_city');
  assert.ok(fs.entries.some(e => e.station_override && !e.zero_confirmed), 'should include station_override');
  assert.ok(fs.entries.some(e => e.zero_confirmed), 'should include zero_confirmed');
  assert.ok(fs.entries.some(e => e.legacy), 'should include legacy');
  assert.ok(fs.entries.some(e => !e.configured && !e.legacy), 'should include pending');

  const summaries = summarizeCitiesProgress(fs.cities, fs.entries, fs.directoryCities);
  assert.equal(summaries.length, 10);
  assert.ok(summaries.some(s => s.pendingStations === 0 && s.cityDefaultConfigured), 'should have 100% done city');
  assert.ok(summaries.some(s => s.pendingStations > 0 && s.configuredStations > 0), 'should have partial city');
  assert.ok(summaries.some(s => !s.cityDefaultConfigured), 'should have unconfigured city default');

  const totalProblemRules =
    fs.cities.reduce((n, c) => n + (c.problem_rules?.length || 0), 0) +
    fs.entries.reduce((n, e) => n + (e.problem_rules?.length || 0), 0);
  assert.ok(totalProblemRules >= 10, 'should include rich city + station problem keyword rules');

  const xx = buildDemoDeductionData('xiaoxiang');
  assert.equal(xx.entries.length, 30);
  assert.equal(xx.columns.length, 3);
});

test('蓝橙批量审批示例数据：精确 30 条待审批 + 全状态结果回执', () => {
  const approvals = buildDemoLanorangeApprovals();
  assert.equal(approvals.length, 30);

  const eligible = filterApprovalTasks(approvals, { scopeCities: [], scopeMonths: [], scopeSite: '', eligibility: 'eligible' });
  const blocked = filterApprovalTasks(approvals, { scopeCities: [], scopeMonths: [], scopeSite: '', eligibility: 'blocked' });
  assert.ok(eligible.length >= 20);
  assert.ok(blocked.length >= 6);
  assert.equal(eligible.length + blocked.length, 30);

  const distinctReasons = new Set(blocked.map(b => b.reason.split('（')[0]));
  assert.ok(distinctReasons.size >= 5, 'should cover diverse block reasons');

  const price = buildDemoApprovalPriceDetail(approvals[0]);
  assert.ok(price.rows.length > 0);

  const history = buildDemoApprovalHistory();
  assert.equal(history.length, 3);
  const itemStatuses = new Set(history.flatMap(b => b.items.map(i => i.status)));
  for (const s of ['success', 'failed', 'uncertain', 'changed', 'not_sent', 'pending']) {
    assert.ok(itemStatuses.has(s), `missing receipt status: ${s}`);
  }
});

test('待审每日价格导出示例数据：提供 10 城 30 站筛选目录及已完成/部分完成双态回执', () => {
  const demo = buildDemoPriceExportData();
  assert.equal(demo.options.cities.length, 10);
  assert.equal(demo.options.stations.length, 30);
  assert.ok(demo.options.months.length >= 2);
  assert.equal(demo.exports.length, 2);
  assert.ok(demo.exports.some(e => e.status === 'completed' && e.receipts.length >= 10));
  assert.ok(demo.exports.some(e => e.status === 'partial' && e.receipts.some(r => r.result === '失败')));
});

