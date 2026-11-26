import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReportBuilder } from '../src/components/ReportBuilder';
import {
  applyBatchBindingPlatform,
  applyCityBindingPlatform,
  buildGenerateBatchPayloads,
  buildRecentReportMonths,
  buildReportMonthChunks,
  buildUnifiedSubmissionPayloads,
  computeOrderWindowBounds,
  deriveSelectedMonthsFromRange,
  groupCitiesByBindingPlatform,
  isWithinOrderWindow,
  mergeAvailableReports,
  monthBounds,
  partitionCitiesByBindingPlatform,
  reportRange,
  selectReportMonthRange,
  summarizeBindingPlatforms,
  summarizeSelectedReportsScope,
  toggleReportMonthSelection,
  toggleReportSelection,
  type ReportDefinition,
} from '../src/lib/reportBuilder';
import { isGenerator, registerGeneratorIds } from '../src/lib/taskCatalog';

const monthly: ReportDefinition = {
  id: 'payment_binding',
  label: '支付绑定',
  scope: 'city_month',
  description: '生成支付绑定表',
  systems: ['风神', '蓝橙', '商翼', '本来人力'],
  sources: ['来源'],
  station_rule: 'separation',
};

const followup: ReportDefinition = {
  id: 'abnormal_followup',
  label: '异常跟进',
  scope: 'city_month',
  description: '以支付绑定为基准生成异常跟进表',
  systems: ['风神', '蓝橙', '商翼'],
  sources: ['跟进来源'],
  station_rule: 'separation',
};

const globalReportDef: ReportDefinition = {
  id: 'abnormal_riders',
  label: '异常名单',
  scope: 'all',
  description: '整理蓝橙全量异常名单资料',
  systems: ['蓝橙'],
  sources: ['蓝橙来源'],
  station_rule: 'none',
};

test('binding platform overrides only attach to binding reports and selected cities', () => {
  const payloads = buildGenerateBatchPayloads(
    [monthly, followup, globalReportDef],
    ['上海', '广州'],
    '2026-11-01',
    '2026-11-30',
    '2026-11-23',
    {
      excludeSeparation: true,
      bindingPlatforms: { 上海: '商翼', 北京: '本来人力' },
    },
  );
  const binding = payloads.find(payload => payload.generation_target === 'payment_binding');
  const follow = payloads.find(payload => payload.generation_target === 'abnormal_followup');
  const global = payloads.find(payload => payload.generation_target === 'abnormal_riders');
  assert.deepEqual(binding?.binding_platforms, { 上海: '商翼' });
  assert.deepEqual(follow?.binding_platforms, { 上海: '商翼' });
  assert.equal(global?.binding_platforms, undefined);
});

test('report periods preserve whole months, leap years and cross-year bounds', () => {
  assert.deepEqual(reportRange(monthly, '2024-02-12', '2024-02-20', '2026-10-31'), {
    start: '2024-02-01',
    end: '2024-02-29',
    months: 1,
  });
  assert.deepEqual(reportRange(monthly, '2025-12-15', '2026-01-01', '2026-10-31'), {
    start: '2025-12-01',
    end: '2026-01-31',
    months: 2,
  });
  assert.deepEqual(monthBounds('2026-02'), {
    start: '2026-02-01',
    end: '2026-02-28',
  });
});

test('current month requests never send future dates and invalid ranges cannot submit', () => {
  assert.deepEqual(reportRange(monthly, '2026-10-01', '2026-10-31', '2026-10-20'), {
    start: '2026-10-01',
    end: '2026-10-20',
    months: 1,
  });
  for (const [start, end] of [
    ['', '2026-10-01'],
    ['2026-02-30', '2026-03-01'],
    ['2026-10-01', '2026-09-01'],
    ['2026-11-01', '2026-11-30'],
  ]) {
    assert.equal(reportRange(monthly, start, end, '2026-10-20'), null);
  }
  assert.equal(
    reportRange({ ...monthly, scope: 'city_range' }, '2026-10-01', '2026-10-21', '2026-10-20'),
    null,
  );
});

test('buildRecentReportMonths and multi-month selection restrict choices to recent 3 months and split non-contiguous chunks', () => {
  const recent = buildRecentReportMonths('2026-11-15', 3);
  assert.deepEqual(
    recent.map(m => [m.month, m.shortTag, m.start, m.end]),
    [
      ['2026-11', '本月', '2026-11-01', '2026-11-15'],
      ['2026-10', '上月', '2026-10-01', '2026-10-31'],
      ['2026-09', '前2月', '2026-09-01', '2026-09-30'],
    ],
  );

  const allowed = recent.map(m => m.month);
  assert.deepEqual(
    deriveSelectedMonthsFromRange('2026-09-01', '2026-10-31', allowed),
    ['2026-09', '2026-10'],
  );

  let selected = toggleReportMonthSelection(['2026-10'], '2026-11', allowed);
  assert.deepEqual(selected, ['2026-10', '2026-11']);
  selected = toggleReportMonthSelection(selected, '2026-09', allowed);
  assert.deepEqual(selected, ['2026-09', '2026-10', '2026-11']);
  selected = toggleReportMonthSelection(selected, '2026-10', allowed);
  assert.deepEqual(selected, ['2026-09', '2026-11']);

  assert.deepEqual(buildReportMonthChunks(['2026-09', '2026-10'], '2026-11-15'), [
    { months: ['2026-09', '2026-10'], start: '2026-09-01', end: '2026-10-31' },
  ]);
  assert.deepEqual(buildReportMonthChunks(['2026-09', '2026-11'], '2026-11-15'), [
    { months: ['2026-09'], start: '2026-09-01', end: '2026-09-30' },
    { months: ['2026-11'], start: '2026-11-01', end: '2026-11-15' },
  ]);

  assert.deepEqual(
    selectReportMonthRange('2026-10-01', '2026-10-31', '2026-11', 'single', allowed, '2026-11-15'),
    { start: '2026-11-01', end: '2026-11-15' },
  );
  assert.equal(
    selectReportMonthRange('2026-10-01', '2026-10-31', '2026-08', 'single', allowed, '2026-11-15'),
    null,
  );
});

test('monthly report renders multi-select dropdown, flat inline cities, Fengshen-style exclude_separation checkbox, and multi-select 3-month box without continuous range toggle', () => {
  const html = renderToStaticMarkup(React.createElement(ReportBuilder, props(monthly)));
  assert.match(html, /aria-haspopup="listbox"/);
  assert.match(html, /aria-label="选择业务报表"/);
  assert.match(html, /aria-labelledby="report-city-label"/);
  assert.match(html, /aria-labelledby="report-month-label"/);
  assert.match(html, /wb-date-rule-bar/);
  assert.match(html, /type="checkbox" aria-label="排除取分离站点"/);
  assert.match(html, /（不勾选则下载全部站点）/);
  assert.match(html, /全选近3月/);
  assert.doesNotMatch(html, /连续跨月|rb-mode-switch|rb-station-grid|仅取分离站点/);
  assert.match(html, /绑定平台配置（可选）/);
  assert.match(html, /aria-label="从天津商翼删除上海"/);
  assert.doesNotMatch(html, /rb-city-trigger|rb-city-picker/);
  assert.match(html, /上海/);
  assert.match(html, /2026年10月/);
  assert.match(html, /2026年09月/);
  assert.match(html, /2026年08月/);
  assert.doesNotMatch(html, /2026年07月/);
  assert.doesNotMatch(html, /aria-label="报表开始月份"|aria-label="报表结束月份"/);
  assert.doesNotMatch(html, /<details[^>]*open/);
});

test('global report displays real fixed scope without misleading city or date selectors', () => {
  const globalReport: ReportDefinition = {
    ...monthly,
    id: 'abnormal_riders',
    scope: 'all',
    station_rule: 'none',
  };
  const html = renderToStaticMarkup(React.createElement(ReportBuilder, props(globalReport)));
  assert.match(html, /全部授权城市/);
  assert.match(html, /不按日期筛选/);
  assert.doesNotMatch(
    html,
    /aria-labelledby="report-month-label"|aria-labelledby="report-city-label"|aria-label="报表站点范围"/,
  );
  assert.deepEqual(reportRange(globalReport, 'invalid', 'invalid', '2026-10-31'), {
    start: '',
    end: '',
    months: 0,
  });
});

test('multi-report and multi-month selection renders selected chips and builds independent backend payloads with exclude_separation', () => {
  const ordered = ['payment_binding', 'abnormal_followup', 'abnormal_riders'];
  let ids = toggleReportSelection(['payment_binding'], 'abnormal_riders', ordered);
  assert.deepEqual(ids, ['payment_binding', 'abnormal_riders']);
  ids = toggleReportSelection(ids, 'abnormal_followup', ordered);
  assert.deepEqual(ids, ['payment_binding', 'abnormal_followup', 'abnormal_riders']);

  const summary = summarizeSelectedReportsScope(
    [monthly, globalReportDef],
    '2026-09-01',
    '2026-11-15',
    '2026-11-15',
    ['2026-09', '2026-11'],
  );
  assert.equal(summary.needsCity, true);
  assert.equal(summary.needsDate, true);
  assert.equal(summary.needsSeparation, true);
  assert.equal(summary.allGlobal, false);
  assert.equal(summary.contiguousMonths, false);
  assert.equal(summary.monthChunks.length, 2);
  assert.deepEqual(summary.systems, ['风神', '蓝橙', '商翼', '本来人力']);

  const nonContiguousPayloads = buildGenerateBatchPayloads(
    [monthly, globalReportDef],
    ['上海', '广州'],
    '2026-09-01',
    '2026-11-15',
    '2026-11-15',
    { excludeSeparation: false, selectedMonths: ['2026-09', '2026-11'] },
  );
  assert.deepEqual(nonContiguousPayloads, [
    {
      task_kind: 'generate',
      generation_target: 'payment_binding',
      datasets: ['payment_binding'],
      cities: ['上海', '广州'],
      start: '2026-09-01',
      end: '2026-09-30',
      exclude_separation: false,
    },
    {
      task_kind: 'generate',
      generation_target: 'payment_binding',
      datasets: ['payment_binding'],
      cities: ['上海', '广州'],
      start: '2026-11-01',
      end: '2026-11-15',
      exclude_separation: false,
    },
    {
      task_kind: 'generate',
      generation_target: 'abnormal_riders',
      datasets: ['abnormal_riders'],
      cities: ['全部城市'],
      start: '2026-11-15',
      end: '2026-11-15',
      lanorange_full_delivery: true,
    },
  ]);

  const multiHtml = renderToStaticMarkup(
    React.createElement(ReportBuilder, {
      ...props(monthly),
      reports: [monthly, followup, globalReportDef],
      selectedIds: ['payment_binding', 'abnormal_followup'],
      onSelectIds: () => {},
      selectedMonths: ['2026-08', '2026-10'],
      excludeSeparation: false,
    }),
  );
  assert.match(multiHtml, /已选 2 \/ 3 项/);
  assert.match(multiHtml, /批量生成 2 份报表/);
  assert.match(multiHtml, /全部站点（含取分离）/);
  assert.match(multiHtml, /2026-08、2026-10/);
  assert.match(multiHtml, /分 4 批/);
});

test('server-registered reports can be classified without modifying page code', () => {
  registerGeneratorIds(['future-business-report']);
  assert.equal(isGenerator('future-business-report'), true);
  const future: ReportDefinition = { ...monthly, id: 'future-business-report', label: '新业务报表' };
  assert.match(renderToStaticMarkup(React.createElement(ReportBuilder, props(future))), /新业务报表/);
});

test('buildUnifiedSubmissionPayloads partitions raw Fengshen downloads and generated reports into backend-compliant batches', () => {
  const baseRawSelection = {
    task_kind: 'download' as const,
    cities: ['上海', '广州'],
    datasets: ['delivery_fee'],
    start: '2026-10-01',
    end: '2026-10-31',
    exclude_separation: true,
  };

  // 1. Single payment_binding report for one month -> 1 generate payload
  const singleReportPayloads = buildUnifiedSubmissionPayloads({
    selectedDatasets: ['payment_binding'],
    availableGenerators: [monthly, followup, globalReportDef],
    rawSelection: { ...baseRawSelection, datasets: [] },
    rawMonthChunks: [{ months: ['2026-10'], start: '2026-10-01', end: '2026-10-31' }],
    isMultiBatchRawMonth: false,
    cities: ['上海', '广州'],
    start: '2026-10-01',
    end: '2026-10-31',
    today: '2026-11-15',
    excludeSeparation: true,
    selectedMonths: ['2026-10'],
    isGeneratorFn: id => ['payment_binding', 'abnormal_followup', 'abnormal_riders'].includes(id),
  });
  assert.deepEqual(singleReportPayloads, [
    {
      task_kind: 'generate',
      generation_target: 'payment_binding',
      datasets: ['payment_binding'],
      cities: ['上海', '广州'],
      start: '2026-10-01',
      end: '2026-10-31',
      exclude_separation: true,
    },
  ]);

  // 2. Standalone abnormal_riders -> single global generate payload regardless of selected cities
  const globalOnlyPayloads = buildUnifiedSubmissionPayloads({
    selectedDatasets: ['abnormal_riders'],
    availableGenerators: [monthly, followup, globalReportDef],
    rawSelection: { ...baseRawSelection, cities: [], datasets: [] },
    rawMonthChunks: [],
    isMultiBatchRawMonth: false,
    cities: [],
    start: '2026-11-01',
    end: '2026-11-15',
    today: '2026-11-15',
    excludeSeparation: true,
    isGeneratorFn: id => ['payment_binding', 'abnormal_followup', 'abnormal_riders'].includes(id),
  });
  assert.deepEqual(globalOnlyPayloads, [
    {
      task_kind: 'generate',
      generation_target: 'abnormal_riders',
      datasets: ['abnormal_riders'],
      cities: ['全部城市'],
      start: '2026-11-15',
      end: '2026-11-15',
      lanorange_full_delivery: true,
    },
  ]);

  // 3. Mixed ['delivery_fee', 'payment_binding', 'abnormal_riders'] across non-contiguous ['2026-09', '2026-11']
  // -> 2 raw download payloads + 2 payment_binding generate payloads + 1 abnormal_riders generate payload = 5 payloads
  const mixedPayloads = buildUnifiedSubmissionPayloads({
    selectedDatasets: ['delivery_fee', 'payment_binding', 'abnormal_riders'],
    availableGenerators: [monthly, followup, globalReportDef],
    rawSelection: baseRawSelection,
    rawMonthChunks: [
      { months: ['2026-09'], start: '2026-09-01', end: '2026-09-30' },
      { months: ['2026-11'], start: '2026-11-01', end: '2026-11-15' },
    ],
    isMultiBatchRawMonth: true,
    cities: ['上海', '广州'],
    start: '2026-09-01',
    end: '2026-11-15',
    today: '2026-11-15',
    excludeSeparation: true,
    selectedMonths: ['2026-09', '2026-11'],
    isGeneratorFn: id => ['payment_binding', 'abnormal_followup', 'abnormal_riders'].includes(id),
  });
  assert.deepEqual(mixedPayloads, [
    {
      task_kind: 'download',
      cities: ['上海', '广州'],
      datasets: ['delivery_fee'],
      start: '2026-09-01',
      end: '2026-09-30',
      exclude_separation: true,
    },
    {
      task_kind: 'download',
      cities: ['上海', '广州'],
      datasets: ['delivery_fee'],
      start: '2026-11-01',
      end: '2026-11-15',
      exclude_separation: true,
    },
    {
      task_kind: 'generate',
      generation_target: 'payment_binding',
      datasets: ['payment_binding'],
      cities: ['上海', '广州'],
      start: '2026-09-01',
      end: '2026-09-30',
      exclude_separation: true,
    },
    {
      task_kind: 'generate',
      generation_target: 'payment_binding',
      datasets: ['payment_binding'],
      cities: ['上海', '广州'],
      start: '2026-11-01',
      end: '2026-11-15',
      exclude_separation: true,
    },
    {
      task_kind: 'generate',
      generation_target: 'abnormal_riders',
      datasets: ['abnormal_riders'],
      cities: ['全部城市'],
      start: '2026-11-15',
      end: '2026-11-15',
      lanorange_full_delivery: true,
    },
  ]);
});

test('mergeAvailableReports keeps canonical frontend labels even when backend sends legacy names', () => {
  const merged = mergeAvailableReports([
    {
      id: 'payment_binding',
      label: '骑手支付绑定',
      scope: 'city_month',
      description: '旧描述',
      systems: ['风神'],
      sources: ['源表A'],
      station_rule: 'separation',
    },
    {
      id: 'abnormal_followup',
      label: '异常骑手跟进',
      scope: 'city_month',
      description: '旧描述',
      systems: ['风神'],
      sources: ['源表B'],
      station_rule: 'separation',
    },
    {
      id: 'abnormal_riders',
      label: '异常骑手整理',
      scope: 'all',
      description: '旧描述',
      systems: ['蓝橙'],
      sources: ['源表C'],
      station_rule: 'none',
    },
    {
      id: 'problem',
      label: '问题单',
      scope: 'city_range',
      description: '问题单旧描述',
      systems: ['风神'],
      sources: ['源表D'],
      station_rule: 'separation',
    },
  ]);
  assert.deepEqual(
    merged.map(item => [item.id, item.label]),
    [
      ['payment_binding', '支付绑定'],
      ['abnormal_followup', '异常跟进'],
      ['abnormal_riders', '异常名单'],
      ['problem', '问题单'],
    ],
  );
  assert.deepEqual(merged[0].sources, ['源表A']);
  assert.deepEqual(merged[3].sources, ['源表D']);
});

function props(report: ReportDefinition) {
  const noop = () => {};
  return {
    reports: [report],
    selectedId: report.id,
    onSelect: noop,
    cities: [{ id: '1', name: '上海' }],
    selectedCities: [],
    onCities: noop,
    start: '2026-09-01',
    end: '2026-09-30',
    today: '2026-10-31',
    onStart: noop,
    onEnd: noop,
    excludeSeparation: true,
    onExcludeSeparation: noop,
    locked: false,
    creating: false,
    disabled: true,
    submitLabel: '生成报表',
    onSubmit: noop,
    uncertain: false,
    duplicate: false,
    recollect: false,
    onRecollect: noop,
    refreshing: false,
    onRefreshCities: noop,
  };
}

test('binding platform helpers handle single updates, batch updates, auto clearing, and ordered summaries', () => {
  let state = applyCityBindingPlatform({}, '上海', '商翼');
  assert.deepEqual(state, { 上海: '商翼' });

  state = applyBatchBindingPlatform(state, ['广州', '深圳'], '本来人力');
  assert.deepEqual(state, { 上海: '商翼', 广州: '本来人力', 深圳: '本来人力' });

  state = applyCityBindingPlatform(state, '广州', '');
  assert.deepEqual(state, { 上海: '商翼', 深圳: '本来人力' });

  const summary = summarizeBindingPlatforms(state, ['北京', '上海', '广州', '深圳']);
  assert.equal(summary.configuredCount, 2);
  assert.deepEqual(summary.entries, [
    { city: '上海', platform: '商翼' },
    { city: '深圳', platform: '本来人力' },
  ]);
  assert.equal(summary.previewText, '上海→商翼、深圳→本来人力');

  const grouped = groupCitiesByBindingPlatform(
    [
      { id: '1', name: '北京' },
      { id: '2', name: '上海' },
      { id: '3', name: '广州' },
      { id: '4', name: '深圳' },
    ],
    state,
  );
  assert.deepEqual(
    grouped.benlai.map(c => c.name),
    ['深圳'],
  );
  assert.deepEqual(
    grouped.shangyi.map(c => c.name),
    ['上海'],
  );
  assert.deepEqual(
    grouped.auto.map(c => c.name),
    ['北京', '广州'],
  );

  const partitioned = partitionCitiesByBindingPlatform(
    [
      { id: '1', name: '北京' },
      { id: '2', name: '上海' },
      { id: '3', name: '广州' },
      { id: '4', name: '深圳' },
    ],
    state,
  );
  // Cities not in 本来人力 are shown on the right (天津商翼)
  assert.deepEqual(
    partitioned.benlai.map(c => c.name),
    ['深圳'],
  );
  assert.deepEqual(
    partitioned.shangyi.map(c => c.name),
    ['北京', '上海', '广州'],
  );

  const cleared = applyBatchBindingPlatform(state, ['上海', '深圳'], '');
  assert.deepEqual(cleared, {});

  const html = renderToStaticMarkup(
    React.createElement(ReportBuilder, {
      ...props(monthly),
      cities: [
        { id: '1', name: '上海' },
        { id: '2', name: '广州' },
        { id: '3', name: '宁波' },
      ],
      selectedCities: ['广州'],
      bindingPlatforms: { 广州: '本来人力' },
    }),
  );
  // Always expanded, no auto-detection section, no city dropdown buttons, left non-displayed cities shown on right
  assert.doesNotMatch(html, /class="rb-bind-body" hidden/);
  assert.doesNotMatch(html, /自动判定/);
  assert.doesNotMatch(html, /恢复全部自动/);
  assert.doesNotMatch(html, /aria-label="广州 绑定平台"/);
  assert.match(html, /本来人力 1 城/);
  assert.match(html, /天津商翼 2 城/);
  assert.match(html, /aria-label="本来人力绑定城市"/);
  assert.match(html, /aria-label="天津商翼绑定城市"/);
  assert.match(html, /aria-label="新增城市到本来人力"/);
  assert.match(html, /aria-label="新增城市到天津商翼"/);
  assert.match(html, /aria-label="从本来人力删除广州"/);
  assert.match(html, /aria-label="从天津商翼删除上海"/);
  assert.match(html, /aria-label="从天津商翼删除宁波"/);
  assert.match(html, /已勾 1 城设为/);
  assert.match(html, /is-platform-shangyi/);
  assert.match(html, /is-platform-benlai/);
});

test('problem city_range report preserves exact dates, order window bounds, refresh_history, and renders date range UI', () => {
  const problemDef: ReportDefinition = {
    id: 'problem',
    label: '问题单',
    scope: 'city_range',
    description: '采集风神问题单并输出汇总与明细',
    systems: ['风神'],
    sources: ['风神问题单'],
    station_rule: 'separation',
  };

  assert.deepEqual(computeOrderWindowBounds('2026-11-24', 60), {
    earliest: '2026-09-26',
    latest: '2026-11-24',
  });
  assert.equal(isWithinOrderWindow('2026-09-26', '2026-11-24', '2026-11-24', 60), true);
  assert.equal(isWithinOrderWindow('2026-09-25', '2026-11-24', '2026-11-24', 60), false);

  const summary = summarizeSelectedReportsScope(
    [problemDef],
    '2026-11-10',
    '2026-11-20',
    '2026-11-24',
    ['2026-10', '2026-11'],
  );
  assert.equal(summary.effectiveScope, 'city_range');
  assert.equal(summary.monthChunks.length, 0);
  assert.deepEqual(summary.range, { start: '2026-11-10', end: '2026-11-20', months: 0 });
  assert.equal(summary.needsSeparation, true);

  const payloads = buildGenerateBatchPayloads(
    [problemDef],
    ['上海'],
    '2026-11-10',
    '2026-11-20',
    '2026-11-24',
    {
      excludeSeparation: true,
      refreshHistory: true,
      selectedMonths: ['2026-10', '2026-11'],
    },
  );
  assert.deepEqual(payloads, [
    {
      task_kind: 'generate',
      generation_target: 'problem',
      datasets: ['problem'],
      cities: ['上海'],
      start: '2026-11-10',
      end: '2026-11-20',
      exclude_separation: true,
      refresh_history: true,
    },
  ]);

  const html = renderToStaticMarkup(
    React.createElement(ReportBuilder, {
      ...props(problemDef),
      singleReportMode: true,
      selectedCities: ['上海'],
      start: '2026-11-10',
      end: '2026-11-20',
      today: '2026-11-24',
      refreshHistory: true,
      orderWindowDays: 90,
      platformStatuses: [{ id: 'fengshen', name: '风神', connected: false, onConnect: () => {} }],
    }),
  );
  assert.match(html, /业务日期/);
  assert.match(html, /近7天/);
  assert.match(html, /近90天/);
  assert.match(html, /本月至今/);
  assert.match(html, /2026-11-10 ~ 2026-11-20/);
  assert.match(html, /共 11 天/);
  assert.match(html, /type="checkbox" aria-label="排除取分离站点"/);
  assert.match(html, /type="checkbox" aria-label="强制重采历史日期问题单"/);
  assert.match(html, /去登录/);
  assert.doesNotMatch(html, /wbx-report-item__idx/);
  assert.doesNotMatch(html, /2026年10月/);

  const expiredHtml = renderToStaticMarkup(
    React.createElement(ReportBuilder, {
      ...props(problemDef),
      singleReportMode: true,
      selectedCities: ['上海'],
      start: '2026-08-01',
      end: '2026-08-20',
      today: '2026-11-24',
      orderWindowDays: 90,
      disabled: false,
    }),
  );
  assert.match(expiredHtml, /role="alert"/);
  assert.match(expiredHtml, /2026-08-27 至 2026-11-24/);
});

test('problem report exposes the issue-rule entry only when wired and only for the problem report', () => {
  const problem: ReportDefinition = {
    ...monthly,
    id: 'problem',
    label: '问题单',
    scope: 'city_range',
    station_rule: 'separation',
  };
  const withEntry = renderToStaticMarkup(
    React.createElement(ReportBuilder, { ...props(problem), onOpenIssueRules: () => {} }),
  );
  assert.match(withEntry, /判定规则/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(ReportBuilder, props(problem))), /判定规则/);
  assert.doesNotMatch(
    renderToStaticMarkup(React.createElement(ReportBuilder, { ...props(monthly), onOpenIssueRules: () => {} })),
    /判定规则/,
  );
});
