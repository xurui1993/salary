import React from 'react';

/**
 * 骨架行组件的 props。
 */
export interface SkeletonRowsProps {
  /** 行数：3–5，越界自动收敛到区间内。 */
  rows?: number;
  /** 每行占位块数（含操作列），默认 4。 */
  columns?: number;
  /** 无障碍标签。 */
  label?: string;
}

/** 骨架行数列宽（与 `components.css` 的 `.wbx-skeleton-rows__row` 保持一致）。 */
const MIN_ROWS = 3;
const MAX_ROWS = 5;

/**
 * 表格骨架：3–5 行 shimmer 占位，用于首屏/刷新时替代"空白表格"。
 *
 * @param props 见 {@link SkeletonRowsProps}。
 * @returns 骨架行列表。
 */
export function SkeletonRows({rows = 4, columns = 4, label = '数据加载中'}: SkeletonRowsProps) {
  const rowCount = Math.min(MAX_ROWS, Math.max(MIN_ROWS, Math.trunc(rows)));
  const columnCount = Math.min(6, Math.max(1, Math.trunc(columns)));

  return (
    <div className="wbx-skeleton-rows" role="status" aria-live="polite" aria-label={label}>
      {Array.from({length: rowCount}, (_, rowIndex) => (
        <div className="wbx-skeleton-rows__row" key={`skeleton-row-${rowIndex}`}>
          {Array.from({length: columnCount}, (_, colIndex) => (
            <span
              key={`skeleton-cell-${rowIndex}-${colIndex}`}
              className={`wbx-skeleton ${colIndex === columnCount - 1 ? 'wbx-skeleton--pill' : 'wbx-skeleton--text'}`}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export default SkeletonRows;
