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
  error: { label: "任务已结束", tone: "error" },
  cancelled: { label: "已停止", tone: "muted" },
  interrupted: { label: "已中断", tone: "waiting" },
};

export function payrollQueueStatus(status: string) {
  return STATES[status] || { label: "处理中", tone: "muted" };
}

export const payrollQueueRunning = (task: PayrollQueueTask) =>
  ["preparing", "calculating", "stopping"].includes(task.status);

export function payrollModeName(mode: string) {
  return mode === "manual" ? "闪购手动" : mode === "xiaoxiang" ? "小象超市" : "闪购自动";
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

export interface PayrollQueueTask {
  preparation?: PayrollPreparationState | null;
  [key: string]: any;
}