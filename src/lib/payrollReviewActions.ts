// @ts-nocheck
const MONEY = new Set([
  '投诉',
  '差评',
  '违规虚假',
  '物流责',
  '不准时单',
  '超时',
  'T10',
  '工具费',
  '代领费率',
  '安全基金',
  '保险费',
  '使用费',
  '循环物资使用费',
  '附加险',
  '非蜂卡',
  '月费',
]);

export function deductionIssues(entry, columns) {
  const fields = columns.filter(c => {
    const value = entry.row[c];
    if (c.endsWith('_maxDays') && (value === null || value === undefined || value === '')) return false;
    if (c === '招聘来源') return value == null;
    if (!MONEY.has(c) && (typeof value === 'string' || typeof value === 'boolean')) return false;
    return typeof value !== 'number' || !Number.isFinite(value);
  });
  const charged =
    columns.some(c => MONEY.has(c) && typeof entry.row[c] === 'number' && entry.row[c] !== 0) ||
    Boolean(String(entry.row['招聘来源'] || '').replace(/^0(?:\.0)?$/, ''));
  return { fields, zero: !fields.length && !charged && !entry.zero_confirmed };
}

export function applyCityAmounts(entries, cities, columns) {
  return entries.map(entry => {
    const source = cities.find(
      c => c.station.platform === entry.station.platform && c.station.city_id === entry.station.city_id,
    );
    if (!source || !source.edited || (entry.configured && !entry.inherited_city) || entry.edited) return entry;
    const issue = deductionIssues(source, columns);
    if (issue.fields.length || issue.zero) return entry;
    return {
      ...entry,
      inherited_city: true,
      row: { ...entry.row, ...Object.fromEntries(columns.map(c => [c, source.row[c]])) },
      zero_confirmed: source.zero_confirmed,
    };
  });
}

export function nextReviewAction(data, entries, accepted, platform) {
  if (platform === 'fengshen' && data.separation_stations?.length && !data.separation_enabled) {
    return {
      kind: 'separation',
      label: '启用并关联取分离站点',
      hint: '申请名单含取分离站点，先同步真实目录。',
    };
  }
  const count = data.unresolved?.length || 0;
  if (count) {
    return {
      kind: 'links',
      label: `处理站点关联（${count}）`,
      hint: `还有 ${count} 个申请站点需要确认后台归属。`,
    };
  }
  const invalid = entries.filter(e => {
    const issue = deductionIssues(e, data.columns);
    return issue.fields.length || issue.zero;
  });
  if (invalid.length) {
    return {
      kind: 'amounts',
      label: `补齐扣款金额（${invalid.length}站）`,
      hint: '填写空白金额；全零站点需明确确认零扣款。',
    };
  }
  const differences = data.differences?.filter(d => !accepted.includes(d.id)).length || 0;
  if (differences) {
    return {
      kind: 'differences',
      label: `核对归属差异（${differences}项）`,
      hint: '请逐项核实申请与账单的站点差异。',
    };
  }
  return {
    kind: 'execute',
    label: '确认扣款并自动执行',
    hint: '金额及站点归属已就绪，确认后自动获取资料并核算。',
  };
}
