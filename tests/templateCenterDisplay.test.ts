import assert from 'node:assert/strict';
import test from 'node:test';
import {
  INITIAL_TEMPLATE_SEED,
  buildTemplateTableRow,
  filterAndSortTemplateRows,
  getMemoryCachedTemplates,
  setMemoryCachedTemplates,
  validateTemplateFormInput,
} from '../src/lib/templateCenterDisplay';

test('INITIAL_TEMPLATE_SEED provides instant 13 standard templates before network response', () => {
  const initial = getMemoryCachedTemplates();
  assert.equal(initial.templates.length, 13);
  assert.equal(initial.isLoadedFromServer, false);
});

test('buildTemplateTableRow formats fileSizeText alongside template metadata', () => {
  const sanya = buildTemplateTableRow({
    filename: '三亚-template.xlsx',
    business_line: '淘宝闪购',
    scope: '三亚',
    size: 24371,
    header_count: 10,
    available: true,
    builtin: true,
  });
  assert.equal(sanya.cityName, '三亚');
  assert.equal(sanya.regionTag, '华南');
  assert.equal(sanya.businessTag, '淘宝闪购');
  assert.equal(sanya.templateTypeText, '闪购兼职薪资申请表');
  assert.equal(sanya.fileSizeText, '23.8 KB');
  assert.equal(sanya.specAndSizeText, '10 列标准表头 · 23.8 KB');
  assert.equal(sanya.statusLabel, '已校验');
  assert.equal(sanya.sourceBadge, '');

  const xiaoxiang = buildTemplateTableRow({
    filename: '小象-template.xlsx',
    business_line: '美团灯塔',
    scope: '灯塔业务',
    size: 23962,
    header_count: 22,
    available: true,
    builtin: true,
  });
  assert.equal(xiaoxiang.cityName, '小象灯塔');
  assert.equal(xiaoxiang.businessTag, '美团小象');
  assert.equal(xiaoxiang.templateTypeText, '众包/灯塔薪资申请表');
  assert.equal(xiaoxiang.fileSizeText, '23.4 KB');
  assert.equal(xiaoxiang.specAndSizeText, '22 列标准表头 · 23.4 KB');

  const customHangzhou = buildTemplateTableRow({
    filename: '杭州-template.xlsx',
    business_line: '淘宝闪购',
    scope: '杭州',
    size: 6348,
    header_count: 10,
    available: true,
    custom: true,
  });
  assert.equal(customHangzhou.cityName, '杭州');
  assert.equal(customHangzhou.fileSizeText, '6.2 KB');
  assert.equal(customHangzhou.sourceBadge, '自定义');
});

test('filterAndSortTemplateRows filters by category, region, and search query', () => {
  const allRows = filterAndSortTemplateRows(INITIAL_TEMPLATE_SEED, {
    search: '',
    category: 'all',
    regionFilter: 'all',
  });
  assert.equal(allRows.length, 13);

  const southRows = filterAndSortTemplateRows(INITIAL_TEMPLATE_SEED, {
    search: '',
    category: '淘宝闪购',
    regionFilter: 'south',
  });
  assert.equal(southRows.length, 5);
  assert.ok(southRows.every(item => ['广州', '深圳', '东莞', '韶关', '三亚'].includes(item.row.cityName)));

  const xiaoxiangRows = filterAndSortTemplateRows(INITIAL_TEMPLATE_SEED, {
    search: '小象',
    category: 'all',
    regionFilter: 'all',
  });
  assert.equal(xiaoxiangRows.length, 1);
  assert.equal(xiaoxiangRows[0].row.businessTag, '美团小象');
});

test('validateTemplateFormInput validates scope and upload mode requirements', () => {
  assert.match(
    validateTemplateFormInput({ scope: '  ', mode: 'generate', hasFile: false }),
    /请输入城市或模板适用名称/,
  );
  assert.match(
    validateTemplateFormInput({ scope: '../bad', mode: 'generate', hasFile: false }),
    /不可包含特殊路径符号/,
  );
  assert.match(
    validateTemplateFormInput({ scope: '杭州', mode: 'upload', hasFile: false }),
    /请选择需要上传的本地/,
  );
  assert.equal(
    validateTemplateFormInput({ scope: '杭州', mode: 'generate', hasFile: false }),
    '',
  );
  assert.equal(
    validateTemplateFormInput({ scope: '杭州', mode: 'upload', hasFile: true }),
    '',
  );
  setMemoryCachedTemplates(INITIAL_TEMPLATE_SEED, false);
  assert.equal(getMemoryCachedTemplates().isLoadedFromServer, true);
});
