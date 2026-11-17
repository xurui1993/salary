import React, { useEffect, useId, useState } from 'react';
import { Plus, Tag, Trash2, Check, X } from 'lucide-react';
import {
  COMMON_PROBLEM_TYPES,
  removeProblemRule,
  upsertProblemRule,
  type ProblemRuleItem,
} from '../lib/deductionCategories';

interface ProblemRuleRowProps {
  index: number;
  rule: ProblemRuleItem;
  disabled: boolean;
  datalistId: string;
  onCommit: (index: number, nextRule: ProblemRuleItem) => boolean;
  onDelete: (index: number) => void;
}

function ProblemRuleRow({
  index,
  rule,
  disabled,
  datalistId,
  onCommit,
  onDelete,
}: ProblemRuleRowProps) {
  const [typeDraft, setTypeDraft] = useState(rule.problem_type);
  const [keywordDraft, setKeywordDraft] = useState(rule.reason_keyword || '');
  const [amountDraft, setAmountDraft] = useState(String(rule.amount));

  useEffect(() => {
    setTypeDraft(rule.problem_type);
    setKeywordDraft(rule.reason_keyword || '');
    setAmountDraft(String(rule.amount));
  }, [rule.problem_type, rule.reason_keyword, rule.amount]);

  const tryCommit = (nextType = typeDraft, nextKw = keywordDraft, nextAmt = amountDraft) => {
    const trimmedType = nextType.trim();
    const trimmedKw = nextKw.trim();
    const numericAmt = nextAmt === '' ? NaN : Number(nextAmt);
    if (
      trimmedType === rule.problem_type &&
      trimmedKw === (rule.reason_keyword || '') &&
      numericAmt === rule.amount
    ) {
      return;
    }
    const ok = onCommit(index, {
      problem_type: nextType,
      reason_keyword: nextKw,
      amount: numericAmt,
    });
    if (!ok) {
      setTypeDraft(rule.problem_type);
      setKeywordDraft(rule.reason_keyword || '');
      setAmountDraft(String(rule.amount));
    }
  };

  return (
    <div className="wbx-kw-editor__row">
      <input
        type="text"
        list={datalistId}
        className="wb-input wbx-kw-editor__input"
        disabled={disabled}
        aria-label={`第${index + 1}条问题单类型`}
        placeholder="问题单类型"
        value={typeDraft}
        onChange={e => setTypeDraft(e.target.value)}
        onBlur={() => tryCommit()}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            tryCommit();
          }
        }}
      />
      <input
        type="text"
        className="wb-input wbx-kw-editor__input"
        disabled={disabled}
        aria-label={`第${index + 1}条判责关键词`}
        placeholder="判责关键词（留空整类）"
        value={keywordDraft}
        onChange={e => setKeywordDraft(e.target.value)}
        onBlur={() => tryCommit()}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            tryCommit();
          }
        }}
      />
      <div className="wbx-kw-editor__amount-wrap">
        <input
          type="number"
          step="any"
          min="0"
          className="wb-input tabular-nums wbx-kw-editor__amount"
          disabled={disabled}
          aria-label={`第${index + 1}条扣款金额`}
          placeholder="0"
          value={amountDraft}
          onChange={e => {
            const raw = e.target.value;
            setAmountDraft(raw);
            if (raw !== '') {
              const num = Number(raw);
              if (Number.isFinite(num) && num >= 0 && num !== rule.amount) {
                onCommit(index, {
                  problem_type: typeDraft,
                  reason_keyword: keywordDraft,
                  amount: num,
                });
              }
            }
          }}
          onBlur={() => tryCommit()}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault();
              tryCommit();
            }
          }}
        />
        <span className="wbx-kw-editor__unit">元</span>
      </div>
      <button
        type="button"
        className="wbx-kw-editor__del"
        disabled={disabled}
        title="删除此条关键词扣款规则"
        aria-label={`删除关键词规则 ${rule.problem_type}${rule.reason_keyword ? ` ${rule.reason_keyword}` : ''}`}
        onClick={() => onDelete(index)}
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

export function ProblemRuleEditor({
  scopeLabel,
  rules,
  disabled = false,
  onChange,
}: {
  scopeLabel: string;
  rules: ProblemRuleItem[];
  disabled?: boolean;
  onChange: (nextRules: ProblemRuleItem[]) => void;
}) {
  const datalistId = useId();
  const [adding, setAdding] = useState(false);
  const [newType, setNewType] = useState('');
  const [newKeyword, setNewKeyword] = useState('');
  const [newAmount, setNewAmount] = useState('');
  const [error, setError] = useState('');

  const handleAdd = () => {
    setError('');
    const result = upsertProblemRule(rules, {
      problem_type: newType,
      reason_keyword: newKeyword,
      amount: newAmount === '' ? NaN : Number(newAmount),
    });
    if (result.error) {
      setError(result.error);
      return;
    }
    onChange(result.rules);
    setNewType('');
    setNewKeyword('');
    setNewAmount('');
    setAdding(false);
  };

  const handleCommitRow = (index: number, nextRule: ProblemRuleItem) => {
    setError('');
    const result = upsertProblemRule(rules, nextRule, index);
    if (result.error) {
      setError(result.error);
      return false;
    }
    onChange(result.rules);
    return true;
  };

  const handleDeleteRow = (index: number) => {
    setError('');
    onChange(removeProblemRule(rules, index));
  };

  return (
    <div className="wbx-kw-editor">
      <datalist id={datalistId}>
        {COMMON_PROBLEM_TYPES.map(item => (
          <option key={item} value={item} />
        ))}
      </datalist>

      <div className="wbx-kw-editor__head">
        <div className="wbx-kw-editor__title">
          <Tag size={13} aria-hidden="true" />
          <span>{scopeLabel}</span>
          <span className="wbx-kw-editor__count tabular-nums">{rules.length} 条</span>
          <small className="wbx-kw-editor__hint">支持直接修改类型、关键词与单次金额；关键词留空则整类适用</small>
        </div>
        {!adding && (
          <button
            type="button"
            className="wbx-btn wbx-btn--sm wbx-kw-editor__add-trigger"
            disabled={disabled}
            onClick={() => {
              setError('');
              setAdding(true);
            }}
          >
            <Plus size={13} />
            新增规则
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="wbx-kw-editor__error">
          {error}
        </p>
      )}

      {rules.length > 0 && (
        <div className="wbx-kw-editor__list">
          {rules.map((rule, index) => (
            <ProblemRuleRow
              key={`${rule.problem_type}-${rule.reason_keyword}-${index}`}
              index={index}
              rule={rule}
              disabled={disabled}
              datalistId={datalistId}
              onCommit={handleCommitRow}
              onDelete={handleDeleteRow}
            />
          ))}
        </div>
      )}

      {adding ? (
        <div className="wbx-kw-editor__add-row">
          <input
            type="text"
            list={datalistId}
            className="wb-input wbx-kw-editor__input"
            disabled={disabled}
            aria-label="新增问题单类型"
            placeholder="问题单类型（如：虚假送达）"
            value={newType}
            onChange={e => setNewType(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAdd();
              } else if (e.key === 'Escape') {
                setAdding(false);
                setError('');
              }
            }}
          />
          <input
            type="text"
            className="wb-input wbx-kw-editor__input"
            disabled={disabled}
            aria-label="新增判责原因关键词"
            placeholder="判责关键词（留空整类）"
            value={newKeyword}
            onChange={e => setNewKeyword(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAdd();
              } else if (e.key === 'Escape') {
                setAdding(false);
                setError('');
              }
            }}
          />
          <div className="wbx-kw-editor__amount-wrap">
            <input
              type="number"
              step="any"
              min="0"
              className="wb-input tabular-nums wbx-kw-editor__amount"
              disabled={disabled}
              aria-label="新增扣款金额"
              placeholder="金额"
              value={newAmount}
              onChange={e => setNewAmount(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAdd();
                } else if (e.key === 'Escape') {
                  setAdding(false);
                  setError('');
                }
              }}
            />
            <span className="wbx-kw-editor__unit">元</span>
          </div>
          <div className="wbx-kw-editor__add-actions">
            <button
              type="button"
              className="wbx-btn wbx-btn--primary wbx-btn--sm"
              disabled={disabled}
              onClick={handleAdd}
            >
              <Check size={13} />
              确认添加
            </button>
            <button
              type="button"
              className="wbx-btn wbx-btn--ghost wbx-btn--sm"
              disabled={disabled}
              onClick={() => {
                setAdding(false);
                setNewType('');
                setNewKeyword('');
                setNewAmount('');
                setError('');
              }}
            >
              <X size={13} />
              取消
            </button>
          </div>
        </div>
      ) : (
        rules.length === 0 && (
          <p className="wbx-kw-editor__empty">
            暂无专属关键词规则，点击右上角「新增规则」可按问题单类型与关键词动态设置扣款金额。
          </p>
        )
      )}
    </div>
  );
}
