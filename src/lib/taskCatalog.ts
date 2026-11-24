export const GENERATOR_IDS = ['payment_binding', 'abnormal_followup', 'abnormal_riders', 'problem'] as const;

export const TASK_KIND_LABELS: Record<TaskKind, string> = {
  download: '资料下载',
  generate: '业务表生成',
  payroll: '兼职薪资核算',
};

const generatorIds = new Set<string>(GENERATOR_IDS);

export function registerGeneratorIds(ids: string[]) {
  for (const id of ids) generatorIds.add(id);
}

export const isGenerator = (id: string): boolean => generatorIds.has(id);

export const inferTaskKind = (datasets: string[]): 'download' | 'generate' =>
  datasets.some(isGenerator) ? 'generate' : 'download';

export function initialTaskKind(): TaskKind {
  if (typeof window === 'undefined') return 'download';
  if (new URLSearchParams(window.location.search).has('batch')) return 'payroll';
  try {
    const previous = localStorage.getItem('workbench_task_kind');
    if (previous === 'payroll' || previous === 'generate') return previous;
  } catch {
    // ignore storage read errors
  }
  return 'download';
}

export type TaskKind = 'download' | 'generate' | 'payroll';
