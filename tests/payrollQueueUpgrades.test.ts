import test from 'node:test';
import assert from 'node:assert/strict';
import {
  detectDuplicateUploadNames,
  extractPayrollReviewAlert,
  payrollQueueRunning,
  payrollQueueStatus,
  sortPayrollTasks,
  summarizePayrollTasks,
  type PayrollQueueTask,
} from '../src/lib/payrollQueue';

test('payrollQueueStatus labels error clearly and payrollQueueRunning includes queued for cancellation', () => {
  assert.equal(payrollQueueStatus('error').label, '核算失败');
  assert.equal(payrollQueueStatus('queued').label, '排队中');
  assert.equal(payrollQueueRunning({ status: 'queued' }), true);
  assert.equal(payrollQueueRunning({ status: 'preparing' }), true);
  assert.equal(payrollQueueRunning({ status: 'calculating' }), true);
  assert.equal(payrollQueueRunning({ status: 'waiting_confirmation' }), false);
  assert.equal(payrollQueueRunning({ status: 'completed' }), false);
  assert.equal(payrollQueueRunning({ status: 'error' }), false);
});

test('extractPayrollReviewAlert surfaces issues and risk metrics on completed batches', () => {
  const cleanTask: PayrollQueueTask = {
    id: 'p1',
    status: 'completed',
    review_summary: {
      metrics: [{ label: '核算人数', value: '82 人' }],
    },
  };
  assert.equal(extractPayrollReviewAlert(cleanTask), null);

  const issueTask: PayrollQueueTask = {
    id: 'p2',
    status: 'completed',
    review_summary: {
      issues: ['2 名骑手缺少单价', '1 人未绑定银行卡'],
    },
  };
  const issueAlert = extractPayrollReviewAlert(issueTask);
  assert.ok(issueAlert);
  assert.equal(issueAlert.count, 2);
  assert.equal(issueAlert.label, '2 项预警');

  const metricTask: PayrollQueueTask = {
    id: 'p3',
    status: 'completed',
    review_summary: {
      metrics: [
        { label: '缺单价骑手', value: '3 人' },
        { label: '未绑定账户', value: '1 人' },
      ],
    },
  };
  const metricAlert = extractPayrollReviewAlert(metricTask);
  assert.ok(metricAlert);
  assert.equal(metricAlert.count, 4);
  assert.equal(metricAlert.label, '4 项预警');

  const runningTask: PayrollQueueTask = { ...issueTask, status: 'running' };
  assert.equal(extractPayrollReviewAlert(runningTask), null);
});

test('summarizePayrollTasks, sortPayrollTasks, and detectDuplicateUploadNames work accurately on demo and custom tasks', () => {
  const tasks: PayrollQueueTask[] = [
    {
      id: 't1',
      status: 'completed',
      template_name: '上海-预支.xlsx',
      approval_code: 'SP-001',
      elapsed_seconds: 120,
      finished_at: '2026-11-24T11:33:01+08:00',
      plan: { city: '上海', applicants: 40, total_amount: 12000.5 },
      review_summary: { issues: ['1 名骑手缺单价'] },
    },
    {
      id: 't2',
      status: 'running',
      template_name: '深圳-全额.xlsx',
      approval_code: '',
      elapsed_seconds: 30,
      plan: { city: '深圳', applicants: 100, total_amount: 58000 },
    },
    {
      id: 't3',
      status: 'error',
      template_name: '广州-预支.xlsx',
      approval_code: '',
      elapsed_seconds: 480,
      plan: { city: '广州', applicants: 25 },
    },
  ];

  const summary = summarizePayrollTasks(tasks);
  assert.equal(summary.count, 3);
  assert.equal(summary.applicants, 165);
  assert.equal(summary.amount, 70000.5);
  assert.equal(summary.amountBatchCount, 2);
  assert.equal(summary.reviewAlertCount, 1);
  assert.equal(summary.missingApprovalCount, 2);
  assert.equal(summary.issueCount, 1);

  assert.deepEqual(sortPayrollTasks(tasks, 'default').map(t => t.id), ['t1', 't2', 't3']);
  assert.deepEqual(sortPayrollTasks(tasks, 'generated_desc').map(t => t.id), ['t1', 't2', 't3']);
  assert.deepEqual(sortPayrollTasks(tasks, 'amount_desc').map(t => t.id), ['t2', 't1', 't3']);
  assert.deepEqual(sortPayrollTasks(tasks, 'applicants_desc').map(t => t.id), ['t2', 't1', 't3']);
  assert.deepEqual(sortPayrollTasks(tasks, 'elapsed_desc').map(t => t.id), ['t3', 't1', 't2']);

  assert.deepEqual(
    detectDuplicateUploadNames(['上海-预支.xlsx', '北京-新批次.xlsx', '深圳-全额.xlsx', '广州-预支.xlsx'], tasks),
    ['上海-预支.xlsx', '深圳-全额.xlsx'],
  );
});
