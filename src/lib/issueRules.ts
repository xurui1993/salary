export type IssueConditionOp =
  | 'eq' | 'neq' | 'contains' | 'not_contains' | 'in' | 'not_in'
  | 'gt' | 'gte' | 'lt' | 'lte' | 'between' | 'is_blank' | 'is_not_blank';

export type IssueConditionValue = string | number | Array<string | number>;

export interface IssueCondition {
  field: string;
  op: IssueConditionOp;
  value?: IssueConditionValue;
  value2?: number;
}

export interface IssueRule {
  id?: string;
  name?: string;
  action: 'exclude' | 'include';
  when: IssueCondition[];
  conditions: IssueCondition[];
}

export interface IssueRulesConfig {
  version: number;
  grace_seconds: number;
  strict_conditions: IssueCondition[];
  rules: IssueRule[];
}

export interface IssueRulesResponse {
  category: string;
  default: IssueRulesConfig;
  cities: Record<string, IssueRulesConfig>;
  fields: string[];
}

export interface IssueRulesPreview {
  before: number;
  after: number;
  delta: number;
  warnings: string[];
  sample_ids: string[];
  sample: { run_id: string; start?: string; end?: string; file: string; rows: number };
}

export const OP_LABELS: Array<{ value: IssueConditionOp; label: string; valueKind: 'none' | 'text' | 'number' | 'list' | 'range' }> = [
  { value: 'eq', label: '等于', valueKind: 'text' },
  { value: 'neq', label: '不等于', valueKind: 'text' },
  { value: 'contains', label: '包含', valueKind: 'text' },
  { value: 'not_contains', label: '不包含', valueKind: 'text' },
  { value: 'in', label: '属于任一', valueKind: 'list' },
  { value: 'not_in', label: '不属于任一', valueKind: 'list' },
  { value: 'gt', label: '大于', valueKind: 'number' },
  { value: 'gte', label: '大于等于', valueKind: 'number' },
  { value: 'lt', label: '小于', valueKind: 'number' },
  { value: 'lte', label: '小于等于', valueKind: 'number' },
  { value: 'between', label: '介于', valueKind: 'range' },
  { value: 'is_blank', label: '为空', valueKind: 'none' },
  { value: 'is_not_blank', label: '不为空', valueKind: 'none' },
];

export function cloneConfig(config: IssueRulesConfig): IssueRulesConfig {
  return JSON.parse(JSON.stringify(config));
}

export function conditionValueKind(op: IssueConditionOp) {
  return OP_LABELS.find(item => item.value === op)?.valueKind ?? 'text';
}

export function emptyCondition(field = ''): IssueCondition {
  return { field, op: 'eq', value: '' };
}

export function emptyRule(action: 'exclude' | 'include'): IssueRule {
  return {
    action,
    name: action === 'exclude' ? '排除规则' : '计入规则',
    when: [],
    conditions: [emptyCondition()],
  };
}

export function conditionToDrafts(condition: IssueCondition): { value: string; value2: string } {
  const kind = conditionValueKind(condition.op);
  if (kind === 'none') return { value: '', value2: '' };
  if (kind === 'list') {
    return { value: Array.isArray(condition.value) ? condition.value.map(String).join('，') : '', value2: '' };
  }
  if (kind === 'range') return { value: String(condition.value ?? ''), value2: String(condition.value2 ?? '') };
  return { value: condition.value === undefined ? '' : String(condition.value), value2: '' };
}

export function draftsToCondition(field: string, op: IssueConditionOp, valueDraft: string, value2Draft: string): IssueCondition {
  const kind = conditionValueKind(op);
  if (kind === 'none') return { field: field.trim(), op };
  if (kind === 'list') {
    const values = valueDraft.split(/[，,]/).map(item => item.trim()).filter(Boolean);
    return { field: field.trim(), op, value: values };
  }
  if (kind === 'range') {
    return { field: field.trim(), op, value: Number(valueDraft), value2: Number(value2Draft) };
  }
  if (kind === 'number') return { field: field.trim(), op, value: Number(valueDraft) };
  return { field: field.trim(), op, value: valueDraft.trim() };
}

export function validateCondition(condition: IssueCondition): string {
  if (!condition.field.trim()) return '判定字段不能为空';
  const kind = conditionValueKind(condition.op);
  if (kind === 'none') return '';
  if (kind === 'list') {
    const values = Array.isArray(condition.value) ? condition.value : [];
    if (!values.length) return '判定值列表不能为空';
    return '';
  }
  if (kind === 'range') {
    if (!Number.isFinite(Number(condition.value)) || !Number.isFinite(Number(condition.value2))) {
      return '区间判定需要两个有效数字';
    }
    return '';
  }
  if (kind === 'number') {
    if (!Number.isFinite(Number(condition.value))) return '判定阈值必须是数字';
    return '';
  }
  if (condition.value === '') return '判定值不能为空';
  return '';
}

export function validateRules(config: IssueRulesConfig): string {
  if (!Number.isInteger(config.grace_seconds) || config.grace_seconds < 0 || config.grace_seconds > 3600) {
    return '宽容时长需为 0-3600 的整数秒';
  }
  for (const condition of config.strict_conditions) {
    const error = validateCondition(condition);
    if (error) return `严格判定条件：${error}`;
  }
  for (const [index, rule] of config.rules.entries()) {
    if (!rule.conditions.length) return `第 ${index + 1} 条规则缺少判定条件`;
    const name = rule.name?.trim() || `第 ${index + 1} 条规则`;
    for (const condition of rule.conditions) {
      const error = validateCondition(condition);
      if (error) return `${name}：${error}`;
    }
    for (const condition of rule.when) {
      const error = validateCondition(condition);
      if (error) return `${name} 触发条件：${error}`;
    }
  }
  return '';
}

export function ruleSummary(rule: IssueRule): string {
  const target = rule.conditions.map(item => item.field).filter(Boolean).slice(0, 3).join('、');
  return `${rule.action === 'exclude' ? '排除' : '计入'}：${target || '未设置条件'}`;
}