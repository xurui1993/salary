import React,{useEffect,useState} from 'react';
import type {AppConfig,LogEntry} from '../types';
import type {RunResult} from './RunResultCard';
import type {PayrollPreparationState} from './PayrollPreparation';
import type {FengshenAuthStatus} from './FengshenLoginModal';
import {FlashPayrollWorkbench} from './FlashPayrollWorkbench';

export interface TaskItem {
  id: string;
  name: string;
  fileCount?: number;
  totalSize?: number;
  estimatedTime?: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  outPath?: string;
  mtime?: number;
  isSalaryBind?: boolean;
}

export type RunOverrides = { action: string; [key: string]: any };

export interface CorePageProps {
  onOpenSettings?: () => void;
  onOpenDeductions: (defaultOnly?: boolean) => void;
  onOpenConnections: () => void;
  onOpenDownloads: () => void;
  onNavigateDownloadCenter?: () => void;
  deductionVersion: number;
  resumeVersion: number;
  appTheme: 'light' | 'dark';
  config: AppConfig;
  onConfigChange: (patch: Partial<AppConfig>) => void;
  runningTask: string | null;
  isRiderSourceUploading: boolean;
  progress: number;
  progressText: string;
  logs: LogEntry[];
  taskQueue: TaskItem[];
  payrollPreparation: PayrollPreparationState | null;
  onPreparationChange: (value: PayrollPreparationState) => void;
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  uploadExtracted: (file: File) => Promise<{ path: string } | null>;
  onRun: (overrides: RunOverrides) => void;
  onUploadFiles: (files: { file: File; relativePath: string }[]) => Promise<void>;
  onDownloadRiderSources: (file: File) => Promise<void>;
  onDownloadShangyi: () => void;
  onOpenShangyi?: () => void;
  onOpenRiderSources?: () => void;
  onOpenFengshenLogin: () => void;
  fengshenAuthStatus?: FengshenAuthStatus | null;
  lastOutputFolder?: string | null;
  lastRunResult: RunResult | null;
  workspaceId: string;
}

export function CorePage(props:CorePageProps) {
  const [newUpload,setNewUpload]=useState(false);
  useEffect(()=>setNewUpload(false),[props.payrollPreparation?.id,props.resumeVersion]);
  const isRunning=props.runningTask==='core'||props.runningTask==='download_rider_sources'||props.runningTask==='download_shangyi_employees'||props.isRiderSourceUploading;
  return <FlashPayrollWorkbench {...props} isRunning={isRunning} payrollPreparation={newUpload?null:props.payrollPreparation} onOtherMode={mode=>{setNewUpload(true);props.onConfigChange({payrollSourceMode:mode,payrollPreparationId:''});}}/>;
}
