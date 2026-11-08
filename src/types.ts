export interface LogEntry {
  id: string;
  time: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS';
  text: string;
}

export interface AppConfig {
  city: string;
  taskType?: string;
  configPath?: string;
  sourcePath: string;
  workspacePath?: string;
  cities: string[];
  taskTypes?: string[];
  payrollSourceMode?: 'fengshen' | 'manual' | 'xiaoxiang';
  payrollPreparationId?: string;
  [key: string]: any;
}

export interface TaskHistoryRecord {
  id: string;
  action?: string;
  actionLabel?: string;
  city?: string;
  name?: string;
  timestamp?: string;
  taskType?: string;
  status: string;
  startTime?: number;
  endTime?: number;
  durationMs?: number;
  outPath?: string;
  resultMsg?: string;
  [key: string]: any;
}
