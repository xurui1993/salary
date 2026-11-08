import React from 'react';

export type PayrollReviewSummaryData = any;

export interface RunResult {
  action: string;
  status: 'success' | 'error';
  resultMsg: string;
  outPath?: string;
  finishedAt: number;
  stats?: {
    totalRows?: number;
    validRiders?: number;
    totalPay?: number;
    sheets?: string[];
  };
  review?: PayrollReviewSummaryData;
}

export interface RunResultCardProps {
  result: RunResult | null;
  onDismiss?: () => void;
}

export function RunResultCard({ result }: RunResultCardProps) {
  if (!result) return null;
  return (
    <div className="wb-notice" role="status">
      <strong>{result.status === 'success' ? '执行完成' : '执行异常'}</strong>
      {result.resultMsg ? <span> · {result.resultMsg}</span> : null}
    </div>
  );
}
