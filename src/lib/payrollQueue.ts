import type { PayrollPreparationState } from "../components/PayrollPreparation";

export function hasFullPayrollPreparation(value: any): value is PayrollPreparationState {
  return !!value && !!value.items && Array.isArray(value.jobs);
}

const STATES: Record<string, { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "muted" },
  preparing: { label: "准备资料", tone: "active" },
  calculating: { label: "核算中", tone: "active" },
  stopping: { label: "正在停止", tone: "muted" },
  waiting_confirmation: { label: "待确认扣款", tone: "waiting" },
  waiting_materials: { label: "获取已暂停", tone: "waiting" },
  pending_download: { label: "待准备资料", tone: "muted" },
  ready: { label: "资料已就绪", tone: "success" },
  completed: { label: "已完成", tone: "success" },
  error: { label: "核算失败", tone: "error" },
  cancelled: { label: "已停止", tone: "muted" },
  interrupted: { label: "已中断", tone: "waiting" },
};

export function payrollQueueStatus(status: string) {
  return STATES[status] || { label: "处理中", tone: "muted" };
}

export const payrollQueueRunning = (task: PayrollQueueTask) =>
  ["queued", "preparing", "calculating", "stopping"].includes(task.status);

export function payrollModeName(mode: string) {
  return mode === "manual" ? "闪购手动" : mode === "xiaoxiang" ? "小象超市" : "闪购自动";
}

export function payrollTypeTone(mode: string): "auto" | "manual" | "xiaoxiang" {
  return mode === "manual" ? "manual" : mode === "xiaoxiang" ? "xiaoxiang" : "auto";
}

export function payrollPeriodShort(value?: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
  return match ? `${match[2]}.${match[3]}` : value || "";
}

export function payrollPeriodRange(plan?: PayrollQueueTask["plan"]) {
  if (!plan) return "";
  const start = payrollPeriodShort(plan.start);
  const end = payrollPeriodShort(plan.end);
  if (start && end) return `${start} - ${end}`;
  return start || end || "";
}

export function payrollCycleLabel(plan?: PayrollQueueTask["plan"]) {
  if (!plan) return "";
  const raw = String(plan.cycle || "").replace(/[（(]历史批次[）)]/g, "").trim();
  if (raw) return raw;
  const monthMatch = /^(\d{4})-(\d{2})/.exec(plan.month || plan.start || "");
  return monthMatch ? `${Number(monthMatch[2])}月账期` : "";
}

export function extractPayrollAmount(task?: PayrollQueueTask | null): number | null {
  if (!task) return null;
  const prepResult = task.preparation?.result as Record<string, unknown> | undefined;
  const directCandidates = [
    task.amount,
    task.total_amount,
    task.payable_amount,
    task.plan?.amount,
    task.plan?.total_amount,
    prepResult?.total_amount,
    prepResult?.payable_amount,
    task.review_summary?.total_amount,
    task.review_summary?.payable_amount,
  ];
  for (const candidate of directCandidates) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate;
    }
    if (typeof candidate === "string" && candidate.trim() !== "") {
      const parsed = Number(candidate.replace(/[,¥￥\s]/g, ""));
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  const metrics = task.preparation?.result?.review_summary?.metrics;
  if (Array.isArray(metrics)) {
    const match = metrics.find(
      (m: any) =>
        m &&
        typeof m.value === "number" &&
        Number.isFinite(m.value) &&
        (["total_amount", "payable_amount", "amount", "gross_pay"].includes(m.key) ||
          /应发|实发|总额|金额/.test(String(m.label || "")))
    );
    if (match) return match.value;
  }
  return null;
}

export function formatPayrollAmount(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) {
    return "—";
  }
  return amount.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function payrollElapsed(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const value = Math.floor(seconds);
  return value < 60 ? `${value}秒` : `${Math.floor(value / 60)}分${value % 60}秒`;
}

export function legacyPayrollTask(value: any, logs: any[] = [], progress = 0, action = ""): PayrollQueueTask {
  const status =
    value.status === "calculated"
      ? "completed"
      : value.status === "pending_download"
        ? "queued"
        : value.mode !== "fengshen" && ["ready", "awaiting_confirmation"].includes(value.status)
          ? "waiting_confirmation"
          : value.status;
  return {
    id: "legacy_" + value.id,
    batch_id: value.id,
    mode: value.mode,
    template_name: value.plan.template || `${value.plan.city}-template.xlsx`,
    plan: value.plan,
    status,
    progress,
    current_action: action || value.pause_reason || "",
    created_at: value.created_at,
    preparation: value,
    logs: [...(value.execution_logs || []), ...logs],
    legacy: true,
  };
}

export interface PayrollReviewAlert {
  count: number;
  label: string;
}

/**
 * 提取已完成批次的复核预警数量（如单价缺失、超额扣款、风控提示），便于在列表行直接暴露高风险批次。
 */
export function extractPayrollReviewAlert(task?: PayrollQueueTask | null): PayrollReviewAlert | null {
  if (!task || task.status !== "completed") return null;
  const review = task.preparation?.result?.review_summary || task.review_summary;
  if (!review) return null;

  const listAlerts = [
    ...(Array.isArray(review.alerts) ? review.alerts : []),
    ...(Array.isArray(review.warnings) ? review.warnings : []),
    ...(Array.isArray(review.issues) ? review.issues : []),
  ].filter(Boolean);
  if (listAlerts.length > 0) {
    return { count: listAlerts.length, label: `${listAlerts.length} 项预警` };
  }

  const metrics = Array.isArray(review.metrics) ? review.metrics : [];
  let warningCount = 0;
  for (const m of metrics) {
    if (!m) continue;
    const isWarnTone = m.tone === "warn" || m.tone === "warning" || m.tone === "error" || m.tone === "danger";
    const isRiskLabel = /缺单价|未绑定|拦截|缺失|异常|预警|未匹配|风险/.test(String(m.label || ""));
    const num = typeof m.value === "number" ? m.value : Number(String(m.value ?? "").replace(/[^\d.-]/g, ""));
    if ((isWarnTone || isRiskLabel) && Number.isFinite(num) && num > 0) {
      warningCount += Math.round(num);
    }
  }
  if (warningCount > 0) {
    return { count: warningCount, label: `${warningCount} 项预警` };
  }
  return null;
}

export interface PayrollQueueSummary {
  count: number;
  applicants: number;
  amount: number;
  amountBatchCount: number;
  waitingCount: number;
  issueCount: number;
  missingApprovalCount: number;
  reviewAlertCount: number;
}

export function summarizePayrollTasks(tasks: PayrollQueueTask[]): PayrollQueueSummary {
  let applicants = 0;
  let amount = 0;
  let amountBatchCount = 0;
  let waitingCount = 0;
  let issueCount = 0;
  let missingApprovalCount = 0;
  let reviewAlertCount = 0;

  for (const task of tasks) {
    if (typeof task.plan?.applicants === "number" && Number.isFinite(task.plan.applicants)) {
      applicants += task.plan.applicants;
    }
    const amt = extractPayrollAmount(task);
    if (amt !== null) {
      amount += amt;
      amountBatchCount += 1;
    }
    if (["waiting_confirmation", "waiting_materials"].includes(task.status)) waitingCount += 1;
    if (["error", "cancelled", "interrupted"].includes(task.status)) issueCount += 1;
    if (!task.legacy && !(task.approval_code || "").trim()) missingApprovalCount += 1;
    if (extractPayrollReviewAlert(task)) reviewAlertCount += 1;
  }

  return {
    count: tasks.length,
    applicants,
    amount,
    amountBatchCount,
    waitingCount,
    issueCount,
    missingApprovalCount,
    reviewAlertCount,
  };
}

export type PayrollSortKey = "default" | "amount_desc" | "applicants_desc" | "elapsed_desc";

export function sortPayrollTasks(tasks: PayrollQueueTask[], sortKey: PayrollSortKey): PayrollQueueTask[] {
  if (sortKey === "default") return tasks;
  const copy = [...tasks];
  if (sortKey === "amount_desc") {
    copy.sort((a, b) => (extractPayrollAmount(b) ?? -1) - (extractPayrollAmount(a) ?? -1));
  } else if (sortKey === "applicants_desc") {
    copy.sort((a, b) => (b.plan?.applicants ?? -1) - (a.plan?.applicants ?? -1));
  } else if (sortKey === "elapsed_desc") {
    copy.sort((a, b) => (b.elapsed_seconds ?? 0) - (a.elapsed_seconds ?? 0));
  }
  return copy;
}

/**
 * 上传前检测是否存在与队列中在途/已完成批次同名的模板文件，用于重复上传提醒。
 */
export function detectDuplicateUploadNames(
  incomingNames: string[],
  existingTasks: PayrollQueueTask[],
): string[] {
  const existingSet = new Set(
    existingTasks
      .filter(t => !["cancelled", "error"].includes(t.status))
      .map(t => String(t.template_name || "").trim().toLowerCase())
      .filter(Boolean),
  );
  const duplicates: string[] = [];
  for (const raw of incomingNames) {
    const base = raw.split(/[\\/]/).pop()?.trim() || "";
    if (base && existingSet.has(base.toLowerCase()) && !duplicates.includes(base)) {
      duplicates.push(base);
    }
  }
  return duplicates;
}

export interface PayrollQueueTask {
  preparation?: PayrollPreparationState | null;
  [key: string]: any;
}