import React from 'react';
import type {LucideIcon} from 'lucide-react';

/**
 * 空态动作。一屏最多 2 个（架构 §7.3：1–2 动作）。
 */
export interface EmptyStateAction {
  /** 按钮文案。 */
  label: string;
  /** 视觉层级：默认 `secondary`。 */
  tone?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** 点击回调。 */
  onClick: () => void;
  /** 可选图标（14–16px 线性图标）。 */
  icon?: LucideIcon;
  /** 是否禁用。 */
  disabled?: boolean;
}

/**
 * 统一空态组件的 props。
 */
export interface EmptyStateProps {
  /** 24px 线性图标（lucide 组件）。 */
  icon: LucideIcon;
  /** 可选标题（不超过 12 字）。 */
  title?: string;
  /** 空态原因，**不得超过 30 字**（超出由调用方压缩，不在此静默截断）。 */
  description: string;
  /**
   * 可选：说明与动作之间的引导内容（步骤清单 / 补充提示）。
   * 只承载「怎么开始」的短文案，不承载表单控件。
   */
  hint?: React.ReactNode;
  /** 1–2 个动作；超过 2 个只取前 2 个。 */
  actions?: EmptyStateAction[];
}

/**
 * 空态允许的最大动作数。
 *
 * T4 起由 2 放宽到 3：核算批次空态需要「上传申请表 / 打开模板中心 / 查看历史批次」
 * 三条并列出口，截断会丢掉唯一的回到任务中心的入口。超出上限仍然截断，不产生滚动。
 */
const MAX_ACTIONS = 3;

/**
 * 统一空态：单卡结构（禁止卡套卡），图标 24px，原因一行居中，动作横排。
 *
 * @param props 见 {@link EmptyStateProps}。
 * @returns 空态单卡。
 */
export function EmptyState({icon: Icon, title, description, hint, actions = []}: EmptyStateProps) {
  const visibleActions = actions.slice(0, MAX_ACTIONS);

  return (
    <div className="wbx-empty" role="status">
      <span className="wbx-empty__icon" aria-hidden="true">
        <Icon size={24} strokeWidth={1.75} />
      </span>
      {title ? <p className="wbx-empty__title">{title}</p> : null}
      <p className="wbx-empty__reason">{description}</p>
      {hint ? <div className="wbx-empty__hint">{hint}</div> : null}
      {visibleActions.length > 0 && (
        <div className="wbx-empty__actions">
          {visibleActions.map(action => {
            const ActionIcon = action.icon;
            const modifier = action.tone && action.tone !== 'secondary' ? ` wbx-btn--${action.tone}` : '';
            return (
              <button
                key={action.label}
                type="button"
                className={`wbx-btn${modifier}`}
                disabled={action.disabled}
                onClick={action.onClick}
              >
                {ActionIcon ? <ActionIcon size={14} /> : null}
                <span>{action.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default EmptyState;
