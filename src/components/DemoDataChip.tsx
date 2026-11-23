import React from 'react';

interface DemoDataChipProps {
  /** Whether demo data is currently active on this view */
  demoActive: boolean;
  /** Whether the user can re-enable demo data (unauthenticated & no live records) */
  canShowDemo: boolean;
  /** Toggle handler to hide or show demo data */
  onToggle: () => void;
  /** Optional tooltip hint */
  hint?: string;
}

/**
 * Compact, subtle toolbar indicator for frontend preview/demo datasets.
 * Automatically disappears once the user signs in to a real platform or live backend records exist.
 */
export function DemoDataChip({
  demoActive,
  canShowDemo,
  onToggle,
  hint = '当前展示前端测试示例数据，完成真实平台登录后自动切换为后台实时数据',
}: DemoDataChipProps) {
  if (demoActive) {
    return (
      <span className="wbx-demo-group" data-demo-active="true" title={hint}>
        <span className="wbx-demo-badge">示例数据</span>
        <button
          type="button"
          className="wbx-btn wbx-btn--sm"
          onClick={onToggle}
        >
          隐藏示例
        </button>
      </span>
    );
  }

  if (canShowDemo) {
    return (
      <button
        type="button"
        className="wbx-btn wbx-btn--sm"
        title="加载前端测试示例数据以预览完整交互效果"
        onClick={onToggle}
      >
        显示示例
      </button>
    );
  }

  return null;
}
