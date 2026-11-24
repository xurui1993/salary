export const FLOW_STEPS = ['选择业务', '确认范围', '处理资料', '领取结果'] as const;

const ACTION_STATUSES = new Set([
  'queued',
  'running',
  'waiting_login',
  'waiting_manual',
  'cancelling',
  'preparing',
  'pending_download',
  'waiting_materials',
  'ready',
  'error',
  'partial',
  'interrupted',
]);

export function flowStep(status: string): number {
  if (status === 'success' || status === 'calculated') return 3;
  if (status === 'create') return 0;
  if (status === 'review') return 1;
  return 2;
}

export function needsAction(status: string): boolean {
  return ACTION_STATUSES.has(status);
}

export function prioritizeTasks<T extends { status: string; member_ids?: string[] }>(
  records: T[],
  selectedId?: string,
): T[] {
  const rank = (item: T): number => {
    if (selectedId && item.member_ids?.includes(selectedId)) return 0;
    return needsAction(item.status) ? 1 : 2;
  };
  return records
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index)
    .map(entry => entry.item);
}
