import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, Eye, Plus, RotateCcw, Trash2, X } from 'lucide-react';
import {
  cloneConfig,
  conditionValueKind,
  conditionToDrafts,
  emptyCondition,
  emptyRule,
  OP_LABELS,
  ruleSummary,
  validateRules,
  type IssueCondition,
  type IssueConditionOp,
  type IssueRulesConfig,
  type IssueRulesPreview,
  type IssueRulesResponse,
  type IssueRule,
} from '../lib/issueRules';

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

export interface DraftCondition extends Omit<IssueCondition, 'value' | 'value2'> {
  value: string;
  value2?: string;
}

interface DraftRule extends Omit<IssueRule, 'conditions' | 'when'> {
  conditions: DraftCondition[];
  when: DraftCondition[];
}

export interface DraftConfig extends Omit<IssueRulesConfig, 'rules' | 'strict_conditions'> {
  strict_conditions: DraftCondition[];
  rules: DraftRule[];
  grace_seconds: number;
}

export function toDraft(config: IssueRulesConfig): DraftConfig {
  const convert = (condition: IssueCondition): DraftCondition => {
    const drafts = conditionToDrafts(condition);
    return { ...condition, value: drafts.value, value2: drafts.value2 };
  };
  return {
    ...cloneConfig(config),
    strict_conditions: config.strict_conditions.map(convert),
    rules: config.rules.map(rule => ({
      ...rule,
      conditions: rule.conditions.map(convert),
      when: rule.when.map(convert),
    })),
  };
}

function serializeCondition(condition: DraftCondition): IssueCondition {
  const field = condition.field.trim();
  const kind = conditionValueKind(condition.op);
  if (kind === 'none') return { field, op: condition.op };
  if (kind === 'list') {
    return {
      field,
      op: condition.op,
      value: String(condition.value).split(/[，,]/).map(item => item.trim()).filter(Boolean),
    };
  }
  if (kind === 'range') {
    return { field, op: condition.op, value: Number(condition.value), value2: Number(condition.value2) };
  }
  if (kind === 'number') return { field, op: condition.op, value: Number(condition.value) };
  return { field, op: condition.op, value: condition.value };
}

export function serializeConfig(config: DraftConfig): IssueRulesConfig {
  return {
    version: config.version,
    grace_seconds: Number(config.grace_seconds),
    strict_conditions: config.strict_conditions.map(serializeCondition),
    rules: config.rules.map(rule => ({
      ...rule,
      conditions: rule.conditions.map(serializeCondition),
      when: rule.when.map(serializeCondition),
    })),
  };
}

function ConditionRow({
  condition,
  datalistId,
  disabled,
  onChange,
  onRemove,
}: {
  condition: DraftCondition;
  datalistId: string;
  disabled: boolean;
  onChange: (next: DraftCondition) => void;
  onRemove: () => void;
}) {
  const kind = conditionValueKind(condition.op);
  return (
    <div className="wbx-kw-editor__row issue-rule-condition">
      <input
        type="text"
        list={datalistId}
        className="wb-input wbx-kw-editor__input"
        disabled={disabled}
        aria-label="判定字段"
        placeholder="字段（如：是否二呼单）"
        value={condition.field}
        onChange={e => onChange({ ...condition, field: e.target.value })}
      />
      <select
        className="wb-input issue-rule-op"
        disabled={disabled}
        aria-label="判定运算符"
        value={condition.op}
        onChange={e => onChange({ ...condition, op: e.target.value as IssueConditionOp })}
      >
        {OP_LABELS.map(item => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
      {kind === 'none' ? (
        <span className="wb-muted text-xs">无需填值</span>
      ) : kind === 'range' ? (
        <div className="issue-rule-range">
          <input
            type="text"
            className="wb-input wbx-kw-editor__input"
            disabled={disabled}
            aria-label="判定下限"
            placeholder="下限"
            value={condition.value}
            onChange={e => onChange({ ...condition, value: e.target.value })}
          />
          <span className="wb-muted">~</span>
          <input
            type="text"
            className="wb-input wbx-kw-editor__input"
            disabled={disabled}
            aria-label="判定上限"
            placeholder="上限"
            value={condition.value2 || ''}
            onChange={e => onChange({ ...condition, value2: e.target.value })}
          />
        </div>
      ) : (
        <input
          type="text"
          className="wb-input wbx-kw-editor__input"
          disabled={disabled}
          aria-label="判定值"
          placeholder={kind === 'list' ? '多个值用逗号分隔' : kind === 'number' ? '数字' : '值'}
          value={condition.value}
          onChange={e => onChange({ ...condition, value: e.target.value })}
        />
      )}
      <button
        type="button"
        className="wbx-kw-editor__del"
        disabled={disabled}
        aria-label="删除条件"
        onClick={onRemove}
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

function ConditionList({
  conditions,
  datalistId,
  disabled,
  onChange,
}: {
  conditions: DraftCondition[];
  datalistId: string;
  disabled: boolean;
  onChange: (next: DraftCondition[]) => void;
}) {
  return (
    <div className="issue-rule-conditions">
      {conditions.map((condition, index) => (
        <ConditionRow
          key={index}
          condition={condition}
          datalistId={datalistId}
          disabled={disabled}
          onChange={next => onChange(conditions.map((item, at) => (at === index ? next : item)))}
          onRemove={() => onChange(conditions.filter((_, at) => at !== index))}
        />
      ))}
      <button
        type="button"
        className="wbx-btn wbx-btn--ghost wbx-btn--sm"
        disabled={disabled || conditions.length >= 20}
        onClick={() => onChange([...conditions, { ...emptyCondition(), value: '' } as DraftCondition])}
      >
        <Plus size={12} /> 添加条件
      </button>
    </div>
  );
}

export function IssueRuleEditor({
  open,
  onClose,
  apiFetch,
  cities,
}: {
  open: boolean;
  onClose: () => void;
  apiFetch: Fetcher;
  cities: string[];
}) {
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [data, setData] = useState<IssueRulesResponse | null>(null);
  const [city, setCity] = useState('');
  const [draft, setDraft] = useState<DraftConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<IssueRulesPreview | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [confirmReset, setConfirmReset] = useState(false);
  const datalistId = 'issue-rule-fields';

  const cityOptions = useMemo(() => {
    const configured = data ? Object.keys(data.cities) : [];
    return Array.from(new Set([...(cities || []), ...configured])).sort((left, right) => left.localeCompare(right, 'zh-CN'));
  }, [cities, data]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setLoadError('');
    setMessage('');
    setError('');
    setPreview(null);
    setConfirmReset(false);
    apiFetch('/api/workbench/issue-rules')
      .then(async response => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || '判定规则读取失败');
        if (cancelled) return;
        setData(payload);
        const first = cityOptions[0] || (payload.cities && Object.keys(payload.cities)[0]) || cities?.[0] || '';
        const initial = first || '';
        setCity(initial);
        const config = (initial && payload.cities?.[initial]) || payload.default;
        setDraft(config ? toDraft(config) : null);
        setDirty(false);
      })
      .catch(reason => {
        if (!cancelled) setLoadError(reason instanceof Error ? reason.message : '判定规则读取失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open || !data) return;
    const saved = city ? data.cities[city] : null;
    setDraft(toDraft(saved || data.default));
    setDirty(false);
    setPreview(null);
    setMessage('');
    setError('');
    setConfirmReset(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [city, open]);

  if (!open) return null;

  const currentSaved = data && city ? data.cities[city] : null;
  const updateDraft = (mutate: (next: DraftConfig) => DraftConfig) => {
    if (!draft) return;
    setDraft(mutate(cloneConfig(draft as unknown as IssueRulesConfig) as unknown as DraftConfig));
    setDirty(true);
    setMessage('');
  };

  const configForServer = () => (draft ? serializeConfig(draft) : null);
  const draftError = draft ? validateRules(configForServer() as IssueRulesConfig) : '规则尚未加载';

  const handlePreview = async () => {
    if (!draft || draftError) return;
    setPreviewing(true);
    setError('');
    setMessage('');
    try {
      const response = await apiFetch('/api/workbench/issue-rules/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city, rules: configForServer() }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || '试算失败');
      setPreview(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '试算失败');
    } finally {
      setPreviewing(false);
    }
  };

  const handleSave = async () => {
    if (!draft || draftError) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const response = await apiFetch('/api/workbench/issue-rules', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city, rules: configForServer() }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || '保存失败');
      setData(previous => (previous ? { ...previous, cities: { ...previous.cities, [city]: payload.rules } } : previous));
      setDraft(toDraft(payload.rules));
      setDirty(false);
      setPreview(null);
      setMessage('判定规则已保存，下次问题单生成时生效。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const response = await apiFetch('/api/workbench/issue-rules', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city, reset: true }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || '恢复默认失败');
      setData(previous => {
        if (!previous) return previous;
        const nextCities = { ...previous.cities };
        delete nextCities[city];
        return { ...previous, cities: nextCities };
      });
      setDraft(toDraft(payload.rules));
      setDirty(false);
      setPreview(null);
      setConfirmReset(false);
      setMessage('已恢复默认判定规则。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '恢复默认失败');
    } finally {
      setSaving(false);
    }
  };

  const updateRule = (index: number, next: DraftRule) => {
    updateDraft(current => ({ ...current, rules: current.rules.map((rule, at) => (at === index ? next : rule)) }));
  };

  return (
    <div className="wb-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="issue-rule-title" onClick={onClose}>
      <div className="wbx-modal issue-rule-modal" onClick={event => event.stopPropagation()}>
        <header className="wbx-modal__head">
          <div>
            <h3 id="issue-rule-title">问题单判定规则 · 不准时单</h3>
            <p className="wbx-modal__hint">
              按城市配置判定条件。规则按顺序生效：先排除、再按基础时间逻辑判定、最后计入；字段缺失时仅告警，不影响其他规则。
            </p>
          </div>
          <button type="button" className="wbx-modal__close" aria-label="关闭" onClick={onClose}>
            <X size={16} />
          </button>
        </header>

        <div className="wbx-modal__body issue-rule-body">
          {loading && <p className="wb-muted">正在读取判定规则…</p>}
          {loadError && <p role="alert" className="wbx-kw-editor__error">{loadError}</p>}

          {!loading && !loadError && data && draft && (
            <>
              <datalist id={datalistId}>
                {data.fields.map(field => <option key={field} value={field} />)}
              </datalist>

              <div className="issue-rule-toolbar">
                <label className="issue-rule-city">
                  <span>城市</span>
                  <select className="wb-input" value={city} onChange={event => setCity(event.target.value)}>
                    {cityOptions.map(option => (
                      <option key={option} value={option}>{option}{data.cities[option] ? '（自定义）' : ''}</option>
                    ))}
                  </select>
                </label>
                <span className={`issue-rule-state ${currentSaved ? 'is-custom' : ''}`}>
                  {currentSaved ? '当前为城市自定义规则' : '当前使用系统默认规则'}
                </span>
                {confirmReset ? (
                  <span className="issue-rule-reset-confirm">
                    确认恢复默认？<button type="button" className="wbx-btn wbx-btn--sm" onClick={handleReset} disabled={saving}>确认</button>
                    <button type="button" className="wbx-btn wbx-btn--ghost wbx-btn--sm" onClick={() => setConfirmReset(false)}>取消</button>
                  </span>
                ) : (
                  <button type="button" className="wbx-btn wbx-btn--ghost wbx-btn--sm" disabled={saving} onClick={() => setConfirmReset(true)}>
                    <RotateCcw size={12} /> 恢复默认
                  </button>
                )}
              </div>

              <section className="issue-rule-section">
                <h4>基础判定参数</h4>
                <div className="issue-rule-params">
                  <label>
                    <span>普通单宽容时长（秒）</span>
                    <input
                      type="number"
                      min={0}
                      max={3600}
                      className="wb-input tabular-nums"
                      value={draft.grace_seconds}
                      onChange={event => updateDraft(current => ({ ...current, grace_seconds: Number(event.target.value) }))}
                    />
                  </label>
                  <p className="wb-muted text-xs">超时超过该秒数才计入；严格判定条件命中的订单按超时 0 秒即计入。</p>
                </div>
                <div className="issue-rule-subhead">
                  <span>严格判定条件（命中任一即严格）</span>
                </div>
                <ConditionList
                  conditions={draft.strict_conditions}
                  datalistId={datalistId}
                  disabled={saving}
                  onChange={next => updateDraft(current => ({ ...current, strict_conditions: next }))}
                />
              </section>

              <section className="issue-rule-section">
                <div className="issue-rule-section-head">
                  <h4>排除 / 计入规则</h4>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--ghost wbx-btn--sm"
                      disabled={saving || draft.rules.length >= 50}
                      onClick={() => updateDraft(current => ({ ...current, rules: [...current.rules, emptyRule('exclude') as unknown as DraftRule] }))}
                    >
                      <Plus size={12} /> 排除规则
                    </button>
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--ghost wbx-btn--sm"
                      disabled={saving || draft.rules.length >= 50}
                      onClick={() => updateDraft(current => ({ ...current, rules: [...current.rules, emptyRule('include') as unknown as DraftRule] }))}
                    >
                      <Plus size={12} /> 计入规则
                    </button>
                  </div>
                </div>

                {draft.rules.length === 0 && <p className="wbx-kw-editor__empty">暂无规则，点击右上角新增。</p>}

                {draft.rules.map((rule, index) => (
                  <article key={index} className="issue-rule-card">
                    <div className="issue-rule-card-head">
                      <select
                        className="wb-input issue-rule-action"
                        value={rule.action}
                        disabled={saving}
                        aria-label="规则动作"
                        onChange={event => updateRule(index, { ...rule, action: event.target.value as IssueRule['action'] })}
                      >
                        <option value="exclude">排除</option>
                        <option value="include">计入</option>
                      </select>
                      <input
                        className="wb-input issue-rule-name"
                        value={rule.name || ''}
                        disabled={saving}
                        aria-label="规则名称"
                        placeholder="规则名称"
                        onChange={event => updateRule(index, { ...rule, name: event.target.value })}
                      />
                      <span className="wb-muted text-xs">{ruleSummary(rule as unknown as IssueRule)}</span>
                      <button
                        type="button"
                        className="wbx-kw-editor__del"
                        disabled={saving}
                        aria-label="删除规则"
                        onClick={() => updateDraft(current => ({ ...current, rules: current.rules.filter((_, at) => at !== index) }))}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>

                    {rule.action === 'include' && (
                      <div className="issue-rule-when">
                        <span className="issue-rule-label">触发条件（本批数据存在任一命中行时，本条计入规则才生效；留空表示始终生效）</span>
                        <ConditionList
                          conditions={rule.when}
                          datalistId={datalistId}
                          disabled={saving}
                          onChange={next => updateRule(index, { ...rule, when: next })}
                        />
                      </div>
                    )}

                    <span className="issue-rule-label">判定条件（需全部命中）</span>
                    <ConditionList
                      conditions={rule.conditions}
                      datalistId={datalistId}
                      disabled={saving}
                      onChange={next => updateRule(index, { ...rule, conditions: next })}
                    />
                  </article>
                ))}
              </section>

              {draftError && <p role="alert" className="wbx-kw-editor__error">{draftError}</p>}
              {error && <p role="alert" className="wbx-kw-editor__error">{error}</p>}
              {message && <p className="issue-rule-message"><Check size={13} /> {message}</p>}

              {preview && (
                <section className="issue-rule-preview">
                  <h4>试算结果</h4>
                  <p className="wb-muted text-xs">
                    样本：任务 {preview.sample.run_id.slice(0, 6).toUpperCase()} · {preview.sample.start} 至 {preview.sample.end} · {preview.sample.rows} 行运单
                  </p>
                  <div className="issue-rule-preview-grid">
                    <span>当前规则 <b className="tabular-nums">{preview.before}</b> 条</span>
                    <span>新规则 <b className="tabular-nums">{preview.after}</b> 条</span>
                    <span className={preview.delta === 0 ? '' : preview.delta > 0 ? 'is-up' : 'is-down'}>
                      变化 <b className="tabular-nums">{preview.delta > 0 ? `+${preview.delta}` : preview.delta}</b> 条
                    </span>
                  </div>
                  {preview.warnings.length > 0 && (
                    <p className="issue-rule-warning">
                      <AlertTriangle size={13} /> 样本缺少字段：{preview.warnings.join('、')}，引用这些字段的规则未生效。
                    </p>
                  )}
                </section>
              )}
            </>
          )}
        </div>

        <footer className="wbx-modal__foot issue-rule-foot">
          <button type="button" className="wbx-btn wbx-btn--ghost" onClick={onClose}>关闭</button>
          <button
            type="button"
            className="wbx-btn"
            disabled={!draft || !!draftError || previewing || saving || !city}
            onClick={handlePreview}
          >
            <Eye size={13} /> {previewing ? '试算中…' : '试算预览'}
          </button>
          <button
            type="button"
            className="wbx-btn wbx-btn--primary"
            disabled={!draft || !!draftError || !dirty || saving || !city}
            onClick={handleSave}
          >
            <Check size={13} /> {saving ? '保存中…' : '保存规则'}
          </button>
        </footer>
      </div>
    </div>
  );
}