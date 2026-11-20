import type { PayrollQueueTask } from './payrollQueue';

export type PayrollQueueFilterTab = 'all' | 'active' | 'waiting' | 'completed' | 'issue';

export function filterPayrollQueueTasks(
  tasks: PayrollQueueTask[],
  filterTab: PayrollQueueFilterTab,
  keyword: string,
): PayrollQueueTask[] {
  const q = keyword.trim().toLowerCase();
  return tasks.filter(task => {
    if (filterTab === 'active' && !['queued', 'preparing', 'calculating', 'stopping'].includes(task.status)) {
      return false;
    }
    if (filterTab === 'waiting' && !['waiting_confirmation', 'waiting_materials'].includes(task.status)) {
      return false;
    }
    if (filterTab === 'completed' && task.status !== 'completed') {
      return false;
    }
    if (filterTab === 'issue' && !['error', 'cancelled', 'interrupted'].includes(task.status)) {
      return false;
    }
    if (!q) return true;
    const hay = `${task.template_name || ''} ${task.plan?.city || ''} ${task.batch_id || ''} ${task.current_action || ''}`.toLowerCase();
    return hay.includes(q);
  });
}

export interface TaskCenterFilterRecord {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  cities: string[];
  datasets: string[];
  title?: string;
  files: { name: string }[];
}

export function filterTaskCenterRecords<T extends TaskCenterFilterRecord>(
  records: T[],
  params: {
    q?: string;
    status?: string;
    system?: string;
    kind?: string;
    from?: string;
    to?: string;
    archivedIds?: Set<string>;
    archivedOnly?: boolean;
  },
): {
  items: T[];
  counts: Record<string, number>;
} {
  const archivedIds = params.archivedIds || new Set<string>();
  const q = (params.q || '').trim().toLowerCase();
  const baseVisible = records.filter(r => (params.archivedOnly ? archivedIds.has(r.id) : !archivedIds.has(r.id)));

  const activeSet = new Set(['queued', 'running', 'waiting_login', 'waiting_manual', 'cancelling', 'preparing', 'stopping']);
  const attentionSet = new Set(['waiting_login', 'waiting_manual', 'partial', 'error', 'interrupted', 'empty']);

  const counts = {
    all: baseVisible.length,
    active: baseVisible.filter(r => activeSet.has(r.status)).length,
    attention: baseVisible.filter(r => attentionSet.has(r.status)).length,
    success: baseVisible.filter(r => r.status === 'success').length,
  };

  const inferSys = (r: TaskCenterFilterRecord) => {
    if (r.kind === 'approval' || r.kind === 'price-export') return ['lanorange'];
    if (r.kind === 'payroll') return ['fengshen', 'lanorange'];
    const out: string[] = [];
    for (const id of r.datasets) {
      if (id === 'baize_employees') out.push('baize');
      else if (id === 'benlai_employees') out.push('benlai');
      else if (id === 'lanorange_summary') out.push('lanorange');
      else if (['rider_daily', 'rider_archive', 'detail_orders', 'detail_kesu', 'detail_reviews', 'rider_order_detail', 'xiaoxiang_attendance_detail'].includes(id)) out.push('xiaoxiang');
      else out.push('fengshen');
    }
    return out;
  };

  const items = baseVisible.filter(r => {
    if (params.status === 'active' && !activeSet.has(r.status)) return false;
    if (params.status === 'attention' && !attentionSet.has(r.status)) return false;
    if (params.status === 'success' && r.status !== 'success') return false;
    if (params.kind && r.kind !== params.kind) return false;
    if (params.system && !inferSys(r).includes(params.system)) return false;
    const createdDay = (r.created_at || '').slice(0, 10);
    if (params.from && createdDay && createdDay < params.from) return false;
    if (params.to && createdDay && createdDay > params.to) return false;
    if (q) {
      const hay = [
        r.id,
        r.title || '',
        r.cities.join(' '),
        r.datasets.join(' '),
        ...r.files.map(f => f.name),
      ]
        .join(' ')
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  return { items, counts };
}

export type ApprovalEligibilityFilter = 'all' | 'eligible' | 'blocked';

export function filterApprovalTasks<
  T extends {
    businessCode?: string;
    id: string;
    cityName?: string;
    siteName?: string;
    nodeName?: string;
    createByName?: string;
    period_start?: string;
    settle_month?: string;
    reason: string;
  },
>(
  rows: T[],
  params: {
    scopeCities: string[];
    scopeMonths: string[];
    scopeSite: string;
    eligibility?: ApprovalEligibilityFilter;
    keyword?: string;
  },
): T[] {
  const q = (params.keyword || '').trim().toLowerCase();
  const eligibility = params.eligibility || 'all';
  return rows.filter(r => {
    if (params.scopeCities.length && !params.scopeCities.includes(r.cityName || '')) return false;
    if (
      params.scopeMonths.length &&
      !params.scopeMonths.includes((r.settle_month || r.period_start || '').slice(0, 7))
    ) {
      return false;
    }
    if (params.scopeSite && JSON.stringify([r.cityName, r.siteName]) !== params.scopeSite) {
      return false;
    }
    if (eligibility === 'eligible' && r.reason) return false;
    if (eligibility === 'blocked' && !r.reason) return false;
    if (q) {
      const hay = `${r.businessCode || ''} ${r.id} ${r.cityName || ''} ${r.siteName || ''} ${r.nodeName || ''} ${r.createByName || ''} ${r.reason || ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}