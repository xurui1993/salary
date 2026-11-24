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

export const PAYROLL_SETTLEMENT_TYPES = ["周结", "半月结", "月结", "全职", "日结"] as const;
export type PayrollSettlementType = (typeof PAYROLL_SETTLEMENT_TYPES)[number];

export function payrollSettlementType(taskOrMode?: PayrollQueueTask | string | null): PayrollSettlementType {
  if (!taskOrMode) return "月结";
  if (typeof taskOrMode === "string") {
    if ((PAYROLL_SETTLEMENT_TYPES as readonly string[]).includes(taskOrMode)) {
      return taskOrMode as PayrollSettlementType;
    }
    if (taskOrMode === "manual") return "半月结";
    if (taskOrMode === "xiaoxiang") return "周结";
    return "月结";
  }
  const explicit = String(
    taskOrMode.settlement_type || taskOrMode.plan?.settlement_type || taskOrMode.plan?.type || "",
  ).trim();
  if ((PAYROLL_SETTLEMENT_TYPES as readonly string[]).includes(explicit)) {
    return explicit as PayrollSettlementType;
  }
  const text = `${taskOrMode.plan?.cycle || ""} ${taskOrMode.template_name || ""}`;
  if (text.includes("日结")) return "日结";
  if (text.includes("周结")) return "周结";
  if (text.includes("全职")) return "全职";
  if (text.includes("半月")) return "半月结";
  if (text.includes("月结") || text.includes("整月")) return "月结";
  return payrollSettlementType(taskOrMode.mode);
}

export function payrollModeName(taskOrMode?: PayrollQueueTask | string | null): PayrollSettlementType {
  return payrollSettlementType(taskOrMode);
}

export function payrollTypeTone(mode: string): "auto" | "manual" | "xiaoxiang" {
  return mode === "manual" || mode === "半月结"
    ? "manual"
    : mode === "xiaoxiang" || mode === "周结"
      ? "xiaoxiang"
      : "auto";
}

export function payrollPeriodShort(value?: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
  return match ? `${match[2]}.${match[3]}` : value || "";
}

export function payrollPeriodRange(plan?: PayrollQueueTask["plan"]) {
  if (!plan) return "";
  const rawStart = (plan.start || "").trim();
  const rawEnd = (plan.end || "").trim();
  const startYear = /^(\d{4})-/.exec(rawStart)?.[1];
  const endYear = /^(\d{4})-/.exec(rawEnd)?.[1];
  const crossYear = Boolean(startYear && endYear && startYear !== endYear);
  const start = crossYear ? rawStart.slice(0, 10).replace(/-/g, ".") : payrollPeriodShort(rawStart);
  const end = crossYear ? rawEnd.slice(0, 10).replace(/-/g, ".") : payrollPeriodShort(rawEnd);
  if (start && end) return start === end ? start : `${start} - ${end}`;
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

/**
 * 解析兼职核算批次的结果生成时间：仅已完成批次返回有效时间戳，未完成返回 null。
 */
export function resolvePayrollGeneratedAt(task?: PayrollQueueTask | null): string | null {
  if (!task || task.status !== "completed") return null;
  const prepResult = task.preparation?.result as Record<string, unknown> | undefined;
  const candidates = [
    task.finished_at,
    task.generated_at,
    prepResult?.finished_at,
    prepResult?.generated_at,
    (task.preparation as Record<string, unknown> | null | undefined)?.finished_at,
    task.updated_at,
    task.created_at,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      const ms = Date.parse(candidate);
      if (Number.isFinite(ms)) return candidate.trim();
    }
    if (typeof candidate === "number" && Number.isFinite(candidate) && candidate > 0) {
      const ms = candidate < 1e12 ? candidate * 1000 : candidate;
      return new Date(ms).toISOString();
    }
  }
  return null;
}

/**
 * 格式化为标准完整生成时间：YYYY-MM-DD HH:mm:ss（北京时间，如 2026-11-24 11:33:01）。
 */
export function formatPayrollDateTime(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "—";
  let date: Date;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return "—";
    date = new Date(value < 1e12 ? value * 1000 : value);
  } else {
    const trimmed = value.trim();
    if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$/.test(trimmed)) {
      return trimmed;
    }
    date = new Date(trimmed);
  }
  if (!Number.isFinite(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type: string) => parts.find(part => part.type === type)?.value || "";
  const hour = get("hour") === "24" ? "00" : get("hour");
  return `${get("year")}-${get("month")}-${get("day")} ${hour}:${get("minute")}:${get("second")}`;
}

export function canPermanentlyDeletePayrollTask(task?: PayrollQueueTask | null): boolean {
  if (!task || !task.status) return false;
  return !["queued", "preparing", "calculating", "stopping"].includes(task.status);
}

export function payrollElapsed(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const value = Math.floor(seconds);
  return value < 60 ? `${value}秒` : `${Math.floor(value / 60)}分${value % 60}秒`;
}

export function resolvePayrollElapsedText(task?: PayrollQueueTask | null, nowMs = Date.now()): string {
  if (!task) return "";
  if (typeof task.elapsed_seconds === "number" && Number.isFinite(task.elapsed_seconds) && task.elapsed_seconds >= 0) {
    return payrollElapsed(task.elapsed_seconds);
  }
  const startMs = task.created_at ? Date.parse(task.created_at) : NaN;
  if (Number.isFinite(startMs)) {
    const endMs = !payrollQueueRunning(task) && task.updated_at ? Date.parse(task.updated_at) : nowMs;
    if (Number.isFinite(endMs) && endMs >= startMs) {
      return payrollElapsed(Math.max(1, Math.floor((endMs - startMs) / 1000)));
    }
  }
  return "";
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

export type PayrollSortKey = "default" | "generated_desc" | "amount_desc" | "applicants_desc" | "elapsed_desc";

export function sortPayrollTasks(tasks: PayrollQueueTask[], sortKey: PayrollSortKey): PayrollQueueTask[] {
  if (sortKey === "default") return tasks;
  const copy = [...tasks];
  if (sortKey === "generated_desc") {
    const toMs = (task: PayrollQueueTask) => {
      const iso = resolvePayrollGeneratedAt(task);
      if (!iso) return -1;
      const ms = Date.parse(iso);
      return Number.isFinite(ms) ? ms : -1;
    };
    copy.sort((a, b) => toMs(b) - toMs(a));
  } else if (sortKey === "amount_desc") {
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

export interface PayrollProgressPopoverData {
  badgeLabel: string;
  tone: "active" | "waiting" | "success" | "error" | "muted";
  percent: number | null;
  elapsedLabel: string;
  elapsedValue: string;
  currentNode: string;
  metrics: Array<{
    label: string;
    value: string;
    tone?: "default" | "accent" | "warn" | "danger" | "success";
  }>;
  footnote?: string;
}

function formatPayrollClock(iso?: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return String(iso);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

const PAYROLL_NODE_FALLBACKS: Record<string, string> = {
  queued: "已进入核算队列，等待分配执行槽位与模板范围解析",
  preparing: "正在齐套拉取关联平台资料并校验字段完整性",
  calculating: "正在匹配站点扣款口径并计算骑手应发与实发薪资",
  stopping: "正在安全中止后台核算流程并保留当前状态",
  waiting_confirmation: "站点扣款口径待人工确认，确认后将自动继续核算",
  waiting_materials: "部分平台资料拉取受阻，处理完成后可自动恢复",
  pending_download: "等待拉取核算所需原始平台数据",
  ready: "核算所需资料已齐套，准备进入薪资计算阶段",
  completed: "全部核算与复核校验已完成，成品包已归档可供下载",
  error: "核算执行遇到异常中断，请点击「查看原因」排查日志",
  cancelled: "核算批次已手动停止，已保留历史操作记录",
  interrupted: "核算执行被意外中断，可在详情抽屉中重新发起",
};

export function buildPayrollProgressPopoverData(
  task: PayrollQueueTask,
  options: {
    nowMs?: number;
    fallbackAction?: string;
  } = {},
): PayrollProgressPopoverData {
  const state = payrollQueueStatus(task.status);
  const tone = (["active", "waiting", "success", "error", "muted"].includes(state.tone)
    ? state.tone
    : "muted") as PayrollProgressPopoverData["tone"];
  const running = payrollQueueRunning(task);
  const rawPct = Number.isFinite(task.progress)
    ? Math.max(0, Math.min(100, Math.round(task.progress)))
    : null;
  const percent =
    running && task.status !== "queued" && rawPct !== null && rawPct > 0
      ? rawPct
      : task.status === "completed"
        ? 100
        : null;

  const elapsedValue = resolvePayrollElapsedText(task, options.nowMs ?? Date.now()) || "—";
  const actionText = String(task.current_action || options.fallbackAction || "").trim();
  const currentNode = actionText || PAYROLL_NODE_FALLBACKS[task.status] || "正在同步批次执行状态";

  const metrics: PayrollProgressPopoverData["metrics"] = [];
  const createdClock = formatPayrollClock(task.created_at);
  if (createdClock) {
    metrics.push({ label: "提交时间", value: createdClock });
  }
  const updatedClock = formatPayrollClock(task.updated_at);
  if (updatedClock && updatedClock !== createdClock) {
    metrics.push({
      label: task.status === "completed" ? "完成时间" : "最近更新",
      value: updatedClock,
    });
  }
  const city = task.plan?.city;
  const applicants = task.plan?.applicants;
  if (city || applicants != null) {
    metrics.push({
      label: "核算范围",
      value: [city || "待识别城市", applicants != null ? `${applicants} 人` : ""].filter(Boolean).join(" · "),
    });
  }
  const modeLabel = payrollModeName(task);
  const periodRange = payrollPeriodRange(task.plan);
  if (periodRange) {
    metrics.push({ label: "结算周期", value: `${modeLabel} · ${periodRange}` });
  }

  const reviewAlert = extractPayrollReviewAlert(task);
  return {
    badgeLabel: state.label,
    tone,
    percent,
    elapsedLabel: "核算耗时",
    elapsedValue,
    currentNode,
    metrics: metrics.slice(0, 4),
    footnote: reviewAlert ? `复核提示：存在 ${reviewAlert.label}，建议点击查看摘要` : undefined,
  };
}

export interface PayrollQueueTask {
  preparation?: PayrollPreparationState | null;
  [key: string]: any;
}