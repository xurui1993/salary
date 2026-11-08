import React from 'react';
import type { PayrollPreparationState } from './PayrollPreparation';
const STATUS: Record<string, string> = { ready: '已备齐', omitted: '已确认不使用', pending: '待准备', failed: '待补传或处理' };
export const DataReadinessMatrix = React.memo(function DataReadinessMatrix({ preparation }: { preparation: PayrollPreparationState | null }) {
  if (!preparation) return <div className="wb-notice">上传薪资申请表并完成预检后，这里会显示本批次的真实资料状态。</div>;
  const items = Object.entries(preparation.items);
  const ready = items.filter(([, item]) => item.status === 'ready').length;
  const omitted = items.filter(([, item]) => item.status === 'omitted').length;
  return <section className="wb-card space-y-4" aria-label="本批次资料状态">
    <div className="wb-row wb-space"><div><h3 className="font-bold">{preparation.plan.city} · 本批次资料清单</h3><p className="wb-muted">{preparation.plan.start} 至 {preparation.plan.end} · {preparation.plan.applicants} 条申请</p></div><span className="wb-kind-badge">已备齐 {ready} / {items.length} · 已确认不使用 {omitted}</span></div>
    <p className="wb-muted">根据服务器保存的批次资料更新。商翼资料独立下载，支付绑定按需上传；灯塔资料手动导入。</p>
    <div className="overflow-x-auto"><table className="wb-table w-full"><thead><tr><th>核算资料</th><th>当前状态</th><th>待处理说明</th></tr></thead><tbody>{items.map(([kind, item]) => <tr key={kind}><td>{item.label}</td><td>{STATUS[item.status] || '准备中'}</td><td>{item.status === 'ready' ? '已进入本批次资料快照' : item.status === 'omitted' ? '按本批次确认结果处理' : item.error || '请在资料准备区域补传或处理'}</td></tr>)}</tbody></table></div>
  </section>;
});
