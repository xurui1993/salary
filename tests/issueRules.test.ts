import assert from 'node:assert/strict';
import test from 'node:test';
import {
  conditionToDrafts,
  draftsToCondition,
  emptyRule,
  OP_LABELS,
  validateCondition,
  validateRules,
  type IssueRulesConfig,
} from '../src/lib/issueRules';
import { serializeConfig, toDraft } from '../src/components/IssueRuleEditor';

const baseConfig: IssueRulesConfig = {
  version: 1,
  grace_seconds: 480,
  strict_conditions: [{ field: '运单类型', op: 'eq', value: '预订单' }],
  rules: [
    {
      id: 'exclude-second-call',
      name: '二呼单且未超骑手T不计入',
      action: 'exclude',
      when: [],
      conditions: [
        { field: '是否二呼单', op: 'eq', value: '是' },
        { field: '是否超骑手T', op: 'eq', value: '否' },
      ],
    },
    {
      id: 'include-sanya',
      name: '三亚大润发计入',
      action: 'include',
      when: [{ field: '站点名称', op: 'contains', value: '三亚' }],
      conditions: [{ field: '站点名称', op: 'contains', value: '大润发' }],
    },
  ],
};

test('issue rule draft round-trip keeps numeric, list and range values', () => {
  const config: IssueRulesConfig = {
    ...baseConfig,
    rules: [
      { action: 'exclude', when: [], conditions: [{ field: '超时分钟', op: 'gte', value: 10 }] },
      { action: 'exclude', when: [], conditions: [{ field: '站点名称', op: 'in', value: ['广州站', '深圳站'] }] },
      {
        action: 'exclude',
        when: [],
        conditions: [{ field: '超时分钟', op: 'between', value: 5, value2: 10 }],
      },
    ],
  };
  const restored = serializeConfig(toDraft(config));
  assert.deepEqual(restored.rules[0].conditions[0], { field: '超时分钟', op: 'gte', value: 10 });
  assert.deepEqual(restored.rules[1].conditions[0], { field: '站点名称', op: 'in', value: ['广州站', '深圳站'] });
  assert.deepEqual(restored.rules[2].conditions[0], { field: '超时分钟', op: 'between', value: 5, value2: 10 });
});

test('condition drafts parse Chinese and English list separators', () => {
  assert.deepEqual(draftsToCondition('站点名称', 'in', '广州站，深圳站, 三亚站', '').value, ['广州站', '深圳站', '三亚站']);
  assert.deepEqual(conditionToDrafts({ field: '站点名称', op: 'in', value: ['广州站', '深圳站'] }), {
    value: '广州站，深圳站',
    value2: '',
  });
});

test('client validation mirrors server requirements', () => {
  assert.equal(validateCondition({ field: '', op: 'eq', value: 'x' }), '判定字段不能为空');
  assert.equal(validateCondition({ field: '站点名称', op: 'eq', value: '' }), '判定值不能为空');
  assert.equal(validateCondition({ field: '超时分钟', op: 'gt', value: 'abc' }), '判定阈值必须是数字');
  assert.equal(validateCondition({ field: '超时分钟', op: 'between', value: 1, value2: 'x' as unknown as number }), '区间判定需要两个有效数字');
  assert.equal(validateCondition({ field: '站点名称', op: 'is_blank' }), '');
  assert.equal(validateRules({ ...baseConfig, grace_seconds: -1 }), '宽容时长需为 0-3600 的整数秒');
  assert.equal(validateRules({ ...baseConfig, rules: [{ action: 'exclude', when: [], conditions: [] }] }), '第 1 条规则缺少判定条件');
  assert.equal(validateRules({ ...baseConfig, rules: [emptyRule('exclude')] }), '排除规则：判定字段不能为空');
  assert.equal(validateRules(baseConfig), '');
});

test('every operator exposes an editor value kind', () => {
  for (const op of OP_LABELS) {
    assert.ok(['none', 'text', 'number', 'list', 'range'].includes(op.valueKind), op.value);
  }
});