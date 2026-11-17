import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  applyConfigRuleRows,
  buildConfigExportRows,
  buildDeductionCategories,
  CONFIG_RULE_COLUMNS,
  hasNonZeroDeduction,
  paginateEntries,
  summarizeCitiesProgress,
  visibleColumnsForCategory,
} from '../src/lib/deductionCategories';
import { CityDeductionAmounts } from '../src/components/CityDeductionAmounts';
import { DeductionAmounts, type DeductionEntry } from '../src/components/DeductionAmounts';

function makeEntry(
  cityId: string,
  cityName: string,
  stationId: string,
  stationName: string,
  overrides: Partial<DeductionEntry> = {},
): DeductionEntry {
  const row: Record<string, any> = {
    城市: cityName,
    团队名称: stationName,
    团队ID: stationId,
  };
  for (const col of CONFIG_RULE_COLUMNS) {
    row[col] = null;
  }
  return {
    key: `${cityId}-${stationId}`,
    station: {
      platform: 'fengshen',
      city_id: cityId,
      city: cityName,
      id: stationId,
      name: stationName,
    },
    row,
    configured: false,
    zero_confirmed: false,
    ...overrides,
  };
}

test('buildDeductionCategories organizes the 13 config fields plus extended fields cleanly', () => {
  const cols = [...CONFIG_RULE_COLUMNS, '安全基金_maxDays', '保险费'];
  const categories = buildDeductionCategories(cols);
  assert.deepEqual(
    categories.map(c => c.id),
    ['violation', 'tools', 'fund_monthly', 'extended'],
  );
  assert.deepEqual(categories[0].columns, ['投诉', '差评', '违规虚假', '物流责', '不准时单', '超时', 'T10']);
  assert.deepEqual(categories[1].columns, ['工具费', '代领费率']);
  assert.deepEqual(categories[2].columns, ['安全基金', '使用费', '非蜂卡', '月费']);
  assert.deepEqual(categories[3].columns, ['安全基金_maxDays', '保险费']);

  assert.deepEqual(visibleColumnsForCategory(cols, 'all'), cols);
  assert.deepEqual(visibleColumnsForCategory(cols, 'tools'), ['工具费', '代领费率']);
});

test('summarizeCitiesProgress and paginateEntries handle 15 cities x 12 stations = 180 stations', () => {
  const cities: DeductionEntry[] = [];
  const entries: DeductionEntry[] = [];
  for (let c = 1; c <= 15; c++) {
    const cityId = String(c).padStart(3, '0');
    const cityName = `测试市${c}`;
    cities.push(
      makeEntry(cityId, cityName, '*', '城市统一扣款', {
        configured: c % 2 === 0,
      }),
    );
    for (let s = 1; s <= 12; s++) {
      const stationId = `${cityId}-${String(s).padStart(2, '0')}`;
      entries.push(
        makeEntry(cityId, cityName, stationId, `站点${c}-${s}`, {
          configured: s <= 8,
          station_override: s <= 3,
          inherited_city: s > 3 && s <= 8,
        }),
      );
    }
  }

  const summaries = summarizeCitiesProgress(cities, entries);
  assert.equal(summaries.length, 15);
  assert.equal(summaries[0].totalStations, 12);
  assert.equal(summaries[0].configuredStations, 8);
  assert.equal(summaries[0].pendingStations, 4);
  assert.equal(summaries[0].overrideStations, 3);
  assert.equal(summaries[1].cityDefaultConfigured, true);

  const page1 = paginateEntries(entries, 1, 30);
  assert.equal(page1.total, 180);
  assert.equal(page1.totalPages, 6);
  assert.equal(page1.items.length, 30);
  assert.equal(page1.startIndex, 0);
  assert.equal(page1.endIndex, 30);

  const page6 = paginateEntries(entries, 6, 30);
  assert.equal(page6.page, 6);
  assert.equal(page6.items.length, 30);
  assert.equal(page6.startIndex, 150);
  assert.equal(page6.endIndex, 180);
});

test('applyConfigRuleRows imports city uniform rules and _新专送 normalized station rows matching config.json format', () => {
  const cities = [
    makeEntry('001', '广州市', '*', '城市统一扣款'),
    makeEntry('002', '深圳市', '*', '城市统一扣款'),
  ];
  const entries = [
    makeEntry('001', '广州市', 'st-1', '天河站_新专送'),
    makeEntry('002', '深圳市', 'st-2', '南山站'),
  ];

  const imported = [
    {
      城市: '广州',
      团队名称: '城市统一扣款',
      投诉: 20,
      差评: 10,
      违规虚假: 50,
      物流责: 15,
      不准时单: 5,
      超时: 3,
      T10: 2,
      工具费: 100,
      代领费率: 0.06,
      安全基金: 3,
      使用费: 2,
      非蜂卡: 1,
      月费: 30,
    },
    {
      城市: '深圳市',
      团队名称: '南山站_新专送',
      投诉: 0,
      差评: 0,
      违规虚假: 0,
      物流责: 0,
      不准时单: 0,
      超时: 0,
      T10: 0,
      工具费: 0,
      代领费率: 0,
      安全基金: 0,
      使用费: 0,
      非蜂卡: 0,
      月费: 0,
    },
    {
      城市: '未知城市',
      团队名称: '不存在站',
      投诉: 10,
    },
  ];

  const result = applyConfigRuleRows(imported, cities, entries, [...CONFIG_RULE_COLUMNS]);
  assert.equal(result.matchedCityCount, 1);
  assert.equal(result.matchedStationCount, 1);
  assert.equal(result.unmatchedRows.length, 1);
  assert.equal(result.updatedCities[0].row['投诉'], 20);
  assert.equal(result.updatedCities[0].row['代领费率'], 0.06);
  assert.equal(result.updatedCities[0].zero_confirmed, false);
  assert.equal(result.updatedEntries[1].edited, true);
  assert.equal(result.updatedEntries[1].zero_confirmed, true);

  const exported = buildConfigExportRows(result.updatedCities, result.updatedEntries, [...CONFIG_RULE_COLUMNS]);
  assert.equal(exported[0].城市, '广州市');
  assert.equal(exported[0].团队名称, '城市统一扣款');
  assert.equal(exported[0]['投诉'], 20);
});

test('hasNonZeroDeduction detects non-zero values across all 13 config fields and SSR components render category groups', () => {
  const zeroEntry = makeEntry('001', '广州市', 'st-1', '测试站');
  for (const col of CONFIG_RULE_COLUMNS) {
    zeroEntry.row[col] = 0;
  }
  assert.equal(hasNonZeroDeduction(zeroEntry.row, [...CONFIG_RULE_COLUMNS]), false);

  const feeEntry = makeEntry('001', '广州市', 'st-2', '违规扣款站');
  for (const col of CONFIG_RULE_COLUMNS) {
    feeEntry.row[col] = 0;
  }
  feeEntry.row['投诉'] = 30;
  assert.equal(hasNonZeroDeduction(feeEntry.row, [...CONFIG_RULE_COLUMNS]), true);

  const cityHtml = renderToStaticMarkup(
    React.createElement(CityDeductionAmounts, {
      entries: [makeEntry('001', '广州市', '*', '城市统一扣款')],
      columns: [...CONFIG_RULE_COLUMNS],
      disabled: false,
      onChange: () => {},
      onApplyToStations: () => {},
    }),
  );
  assert.match(cityHtml, /违规与时效扣款/);
  assert.match(cityHtml, /工具与代领费率/);
  assert.match(cityHtml, /保障基金与月费/);
  assert.match(cityHtml, /填充同城待配站点/);

  const tableHtml = renderToStaticMarkup(
    React.createElement(DeductionAmounts, {
      entries: [feeEntry],
      columns: [...CONFIG_RULE_COLUMNS],
      visibleColumns: visibleColumnsForCategory([...CONFIG_RULE_COLUMNS], 'violation'),
      onChange: () => {},
    }),
  );
  assert.match(tableHtml, /违规与时效扣款/);
  assert.match(tableHtml, /投诉/);
  assert.doesNotMatch(tableHtml, /工具费/);
  assert.match(tableHtml, /<input type="checkbox" disabled=""\/>/);
});

import {
  applyProblemRuleRows,
  buildUnifiedConfigWorkbookData,
  classifyImportedWorkbookSheets,
  groupDeductionsByCity,
  summarizeStationRow,
} from '../src/lib/deductionCategories';
import { CityStationAccordionCard } from '../src/components/CityStationAccordionCard';

test('groupDeductionsByCity and summarizeStationRow organize 14 cities x 10+ stations cleanly', () => {
  const cities: DeductionEntry[] = [];
  const entries: DeductionEntry[] = [];
  for (let c = 1; c <= 14; c++) {
    const cityId = String(c).padStart(3, '0');
    const cityName = `城市${c}`;
    const cityRow = makeEntry(cityId, cityName, '*', '城市统一扣款', { configured: true });
    cityRow.row['投诉'] = 20;
    cities.push(cityRow);
    for (let s = 1; s <= 11; s++) {
      const stationId = `${cityId}-${String(s).padStart(2, '0')}`;
      const st = makeEntry(cityId, cityName, stationId, `第${s}站`, {
        configured: s <= 5,
      });
      if (s === 1) st.row['投诉'] = 25;
      entries.push(st);
    }
  }

  const allGroups = groupDeductionsByCity(cities, entries);
  assert.equal(allGroups.length, 14);
  assert.equal(allGroups[0].stations.length, 11);
  assert.equal(allGroups[0].summary.configuredStations, 5);

  const filtered = groupDeductionsByCity(cities, entries, [], {
    stationSearch: '第11站',
    onlyUnconfigured: true,
  });
  assert.equal(filtered.length, 14);
  assert.equal(filtered[0].stations.length, 1);
  assert.equal(filtered[0].stations[0].station.name, '第11站');

  assert.match(summarizeStationRow(entries[0], [...CONFIG_RULE_COLUMNS]), /投诉 25/);
  assert.equal(summarizeStationRow(entries[1], [...CONFIG_RULE_COLUMNS]), '待填写 13 项');

  const cardHtml = renderToStaticMarkup(
    React.createElement(CityStationAccordionCard, {
      group: allGroups[0],
      allEntries: entries,
      columns: [...CONFIG_RULE_COLUMNS],
      activeCategory: 'all',
      visibleColumns: [...CONFIG_RULE_COLUMNS],
      expanded: true,
      expandedStations: new Set([entries[0].key]),
      selectedStations: new Set<string>(),
      disabled: false,
      onToggleCity: () => {},
      onToggleStation: () => {},
      onToggleAllCityStations: () => {},
      onToggleSelectStation: () => {},
      onUpdateCity: () => {},
      onApplyCityToStations: () => {},
      onUpdateStation: () => {},
      onBulkUpdateStations: () => {},
    }),
  );
  assert.match(cardHtml, /城市1/);
  assert.match(cardHtml, /11 个站点/);
  assert.match(cardHtml, /下属站点分组明细/);
  assert.match(cardHtml, /确认本站零扣款/);
});

test('unified Excel workbook helpers build, classify, and apply both item and keyword deduction sheets', () => {
  const cities = [
    makeEntry('001', '广州市', '*', '城市统一扣款', {
      configured: true,
      problem_rules: [{ problem_type: '虚假送达', reason_keyword: '未送达', amount: 50 }],
    } as any),
    makeEntry('002', '深圳市', '*', '城市统一扣款', { configured: true }),
  ];
  cities[0].row['投诉'] = 30;
  const entries = [
    makeEntry('001', '广州市', 'GZ01', '天河体育西站_新专送', {
      configured: true,
      problem_rules: [{ problem_type: '餐损责任', reason_keyword: '洒漏', amount: 25 }],
    } as any),
    makeEntry('002', '深圳市', 'SZ01', '南山科技园站_新专送', { configured: true }),
  ];

  const workbook = buildUnifiedConfigWorkbookData(cities as any, entries as any, [...CONFIG_RULE_COLUMNS]);
  assert.equal(workbook.itemSheetName, '城市与站点扣款项');
  assert.equal(workbook.problemSheetName, '问题单关键词扣款');
  assert.equal(workbook.itemRows.length, 4);
  assert.equal(workbook.problemRows.length, 2);
  assert.equal(workbook.problemRows[0]['问题单类型'], '虚假送达');
  assert.equal(workbook.problemRows[1]['团队名称'], '天河体育西站_新专送');

  const classified = classifyImportedWorkbookSheets([
    { name: '城市与站点扣款项', rows: workbook.itemRows },
    {
      name: '问题单关键词扣款',
      rows: [
        { 城市: '广州', 团队名称: '城市统一扣款', 团队ID: '*', 问题单类型: '虚假送达', 判责原因关键词: '未送达', 单次扣款金额: 80 },
        { 城市: '深圳', 团队名称: '南山科技园站', 问题单类型: '态度投诉', 判责原因关键词: '顶撞顾客', 单次扣款金额: 40 },
        { 城市: '未知', 团队名称: '未知站', 问题单类型: '态度投诉', 判责原因关键词: '', 单次扣款金额: 10 },
      ],
    },
  ]);

  assert.equal(classified.itemRows.length, 4);
  assert.equal(classified.problemRows.length, 3);

  const appliedProblems = applyProblemRuleRows(classified.problemRows, cities as any, entries as any);
  assert.equal(appliedProblems.matchedCityRules, 1);
  assert.equal(appliedProblems.matchedStationRules, 1);
  assert.equal(appliedProblems.unmatchedRows.length, 1);
  assert.equal(appliedProblems.diff.addedCount, 1);
  assert.equal(appliedProblems.diff.updatedCount, 1);
  assert.equal(appliedProblems.diff.removedCount, 1);
  assert.equal((appliedProblems.updatedCities[0] as any).problem_rules[0].amount, 80);
  assert.equal((appliedProblems.updatedEntries[1] as any).problem_rules[0].problem_type, '态度投诉');
});

test('paginateEntries cleanly handles 20-item payroll queue with pageSize 10 and bounds clamping', () => {
  const rows = Array.from({ length: 20 }, (_, i) => ({ id: `pq-${i + 1}` }));
  const p1 = paginateEntries(rows, 1, 10);
  assert.equal(p1.total, 20);
  assert.equal(p1.totalPages, 2);
  assert.equal(p1.items.length, 10);
  assert.equal(p1.items[0].id, 'pq-1');

  const p2 = paginateEntries(rows, 2, 10);
  assert.equal(p2.page, 2);
  assert.equal(p2.items[0].id, 'pq-11');
  assert.equal(p2.items[9].id, 'pq-20');

  const clamped = paginateEntries(rows.slice(0, 5), 3, 10);
  assert.equal(clamped.page, 1);
  assert.equal(clamped.totalPages, 1);
  assert.equal(clamped.items.length, 5);
});

import {
  removeProblemRule,
  resolveCityChipAction,
  toggleGridCityExpansion,
  upsertProblemRule,
} from '../src/lib/deductionCategories';
import { ProblemRuleEditor } from '../src/components/ProblemRuleEditor';

test('upsertProblemRule and removeProblemRule handle add, edit, duplicate/invalid guards, and delete', () => {
  const initial = [
    { problem_type: '餐损责任', reason_keyword: '洒漏', amount: 25 },
  ];

  const added = upsertProblemRule(initial, {
    problem_type: '配送超时',
    reason_keyword: '大雨补贴超时',
    amount: 15,
  });
  assert.equal(added.error, undefined);
  assert.equal(added.rules.length, 2);

  const dup = upsertProblemRule(added.rules, {
    problem_type: '配送超时',
    reason_keyword: '大雨补贴超时',
    amount: 30,
  });
  assert.match(dup.error || '', /已存在相同/);
  assert.equal(dup.rules.length, 2);

  const emptyType = upsertProblemRule(added.rules, {
    problem_type: '  ',
    reason_keyword: 'test',
    amount: 10,
  });
  assert.match(emptyType.error || '', /请填写问题单类型/);

  const badAmount = upsertProblemRule(added.rules, {
    problem_type: '态度投诉',
    reason_keyword: '',
    amount: -5,
  });
  assert.match(badAmount.error || '', /不小于 0/);

  const timeoutIdx = added.rules.findIndex(r => r.problem_type === '配送超时');
  const edited = upsertProblemRule(
    added.rules,
    { problem_type: '配送超时', reason_keyword: '大雨补贴超时', amount: 20 },
    timeoutIdx,
  );
  assert.equal(edited.error, undefined);
  assert.equal(edited.rules[timeoutIdx].amount, 20);

  const deleted = removeProblemRule(edited.rules, 0);
  assert.equal(deleted.length, 1);

  const editorHtml = renderToStaticMarkup(
    React.createElement(ProblemRuleEditor, {
      scopeLabel: '城市问题单关键词',
      rules: edited.rules,
      onChange: () => {},
    }),
  );
  assert.match(editorHtml, /城市问题单关键词/);
  assert.match(editorHtml, /新增规则/);
  assert.match(editorHtml, /大雨补贴超时/);
});

test('toggleGridCityExpansion and resolveCityChipAction handle collapsed-all and city+station expansion', () => {
  const openTwo = toggleGridCityExpansion(new Set(['gz']), 'sz');
  assert.deepEqual(Array.from(openTwo).sort(), ['gz', 'sz']);

  const toggleOff = toggleGridCityExpansion(openTwo, 'gz');
  assert.deepEqual(Array.from(toggleOff), ['sz']);

  const selectCity = resolveCityChipAction('', 'gz');
  assert.equal(selectCity.nextCityFilter, 'gz');
  assert.deepEqual(Array.from(selectCity.nextExpandedCities), ['gz']);

  const switchCity = resolveCityChipAction('gz', 'sz');
  assert.equal(switchCity.nextCityFilter, 'sz');
  assert.deepEqual(Array.from(switchCity.nextExpandedCities), ['sz']);

  const clickAll = resolveCityChipAction('sz', '');
  assert.equal(clickAll.nextCityFilter, '');
  assert.equal(clickAll.nextExpandedCities.size, 0);

  const reclickSameCity = resolveCityChipAction('gz', 'gz');
  assert.equal(reclickSameCity.nextCityFilter, '');
  assert.equal(reclickSameCity.nextExpandedCities.size, 0);
});

import { formatSystemResourceStats } from '../src/lib/workbench';

test('formatSystemResourceStats normalizes CPU and memory usage telemetry and load levels', () => {
  const fallback = formatSystemResourceStats(null);
  assert.equal(fallback.level, 'normal');
  assert.equal(fallback.statusText, '负载正常');
  assert.match(fallback.cpuText, /%/);
  assert.match(fallback.memText, /%/);

  const warn = formatSystemResourceStats({
    sysCpu: 72.4,
    sysMemRatio: 58.1,
    procMem: 214.6,
    cpuCores: 8,
    usedMemGb: 9.3,
    totalMemGb: 16,
  });
  assert.equal(warn.level, 'warn');
  assert.equal(warn.statusText, '负载偏高');
  assert.equal(warn.cpuText, '72.4%');
  assert.equal(warn.procMemMb, 215);
  assert.equal(warn.cpuCores, 8);
  assert.equal(warn.memDetailText, '9.3/16 GB');

  const high = formatSystemResourceStats({
    sysCpu: 89.2,
    sysMemRatio: 91.5,
    procMem: 512,
  });
  assert.equal(high.level, 'high');
  assert.equal(high.statusText, '高负载');
});

