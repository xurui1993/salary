import React from 'react';
import { SIDEBAR_BRAND, SIDEBAR_BRAND_HINT } from '../lib/appMeta';

export interface BrandLogoProps {
  collapsed?: boolean;
  onClick?: () => void;
}

/**
 * 系统原生简约标识 —— 精密账表与汇聚流线单色线框徽标
 * 与浅色工作台线条、字阶与品牌宝石蓝体系高度统一，去除暗底渐变与彩色光效。
 */
export function BrandLogo({ collapsed = false, onClick }: BrandLogoProps) {
  return (
    <button
      type="button"
      className={`wbx-brand-logo${collapsed ? ' is-collapsed' : ''}`}
      onClick={onClick}
      title={`${SIDEBAR_BRAND} · ${SIDEBAR_BRAND_HINT}`}
      aria-label={SIDEBAR_BRAND}
    >
      <span className="wbx-brand-logo__mark" aria-hidden="true">
        <svg
          width="30"
          height="30"
          viewBox="0 0 30 30"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="wbx-brand-logo__svg"
        >
          <rect
            x="1"
            y="1"
            width="28"
            height="28"
            rx="7.5"
            fill="#F8FAFC"
            stroke="#CBD5E1"
            strokeWidth="1.2"
          />
          <rect
            x="6.5"
            y="7.5"
            width="7"
            height="6.5"
            rx="1.6"
            stroke="#0F172A"
            strokeWidth="1.5"
          />
          <rect
            x="16.5"
            y="7.5"
            width="7"
            height="6.5"
            rx="1.6"
            stroke="#026AA2"
            strokeWidth="1.5"
          />
          <rect
            x="6.5"
            y="16.5"
            width="7"
            height="6"
            rx="1.6"
            stroke="#64748B"
            strokeWidth="1.5"
          />
          <path
            d="M16.5 19.5H23.5M20 16.5V22.5"
            stroke="#026AA2"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </span>
      {!collapsed && (
        <span className="wbx-brand-logo__wordmark">
          <strong className="wbx-brand-logo__title">{SIDEBAR_BRAND}</strong>
          <small className="wbx-brand-logo__sub">{SIDEBAR_BRAND_HINT}</small>
        </span>
      )}
    </button>
  );
}
