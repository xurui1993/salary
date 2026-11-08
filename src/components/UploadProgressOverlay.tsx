import React from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileArchive,
  FolderSearch,
  Loader2,
  Server,
  UploadCloud,
} from 'lucide-react';

export interface UploadProgressStatus {
  active: boolean;
  stage: 'reading' | 'zipping' | 'uploading' | 'extracting' | 'validating' | 'success';
  fileCount?: number;
  size?: string;
  error?: string;
  percent?: number;
}

export function UploadProgressOverlay({
  status,
}: {
  status: UploadProgressStatus | null;
  appTheme?: 'light' | 'dark';
}) {
  if (!status || !status.active) return null;
  const { stage, fileCount, size, error, percent } = status;
  const steps = [
    {
      id: 'reading',
      label: '检索本地目录',
      description: fileCount === undefined ? '正在扫描目录中...' : `已检索到 ${fileCount} 个文件`,
      icon: FolderSearch,
    },
    {
      id: 'zipping',
      label: '整理上传文件',
      description: size
        ? `文件包大小: ${size}`
        : stage === 'zipping' && typeof percent === 'number'
          ? `正在整理所选文件 ${percent}%`
          : '正在整理所选文件...',
      icon: FileArchive,
    },
    {
      id: 'uploading',
      label: '上传资料',
      description: ['extracting', 'validating', 'success'].includes(stage)
        ? '文件已发送'
        : typeof percent === 'number'
          ? `已发送 ${percent}%`
          : '正在向服务器发送文件...',
      icon: UploadCloud,
    },
    {
      id: 'extracting',
      label: '接收与整理文件',
      description: ['validating', 'success'].includes(stage)
        ? '资料已接收与整理'
        : '等待服务器完成接收、解包与目录检查...',
      icon: Server,
    },
    {
      id: 'validating',
      label: '校验工资模板',
      description: '正在校验申请名单与结算范围...',
      icon: Server,
    },
  ] as const;

  const getStepState = (stepId: string) => {
    const order = ['reading', 'zipping', 'uploading', 'extracting', 'validating', 'success'];
    const currentIdx = order.indexOf(stage);
    const stepIdx = order.indexOf(stepId);
    if (error) {
      return stepId === stage ? 'error' : stepIdx < currentIdx ? 'completed' : 'pending';
    }
    if (currentIdx === -1) return 'pending';
    if (stepIdx < currentIdx) return 'completed';
    if (stepIdx === currentIdx) return 'active';
    return 'pending';
  };

  return (
    <div
      id="upload-progress-overlay"
      className="fixed bottom-6 right-6 z-50 flex items-end justify-end p-2 pointer-events-none"
    >
      <div
        role="dialog"
        aria-label="上传资料进度"
        aria-modal="false"
        className="pointer-events-auto relative w-full min-w-0 max-w-md max-h-[80vh] overflow-y-auto rounded-2xl border p-4 sm:p-5 bg-white shadow-2xl border-slate-200 text-slate-800"
      >
        <div className="flex flex-col items-center text-center mb-8">
          <div className="relative mb-4">
            <div
              className={`w-16 h-16 rounded-2xl flex items-center justify-center border relative ${
                error
                  ? 'bg-rose-50 border-rose-200 text-rose-600'
                  : stage === 'success'
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-600'
                    : 'bg-sky-50 border-sky-200 text-sky-700'
              }`}
            >
              {error ? (
                <AlertCircle className="w-8 h-8" />
              ) : stage === 'success' ? (
                <CheckCircle2 className="w-8 h-8" />
              ) : (
                <Loader2 className="w-8 h-8" />
              )}
            </div>
          </div>
          <h3 className="text-xl font-bold tracking-tight text-slate-900">
            {error ? '处理出错' : stage === 'success' ? '操作成功' : '上传与校验资料'}
          </h3>
          <p className="text-xs text-slate-500 mt-2 max-w-sm">
            {error
              ? '在处理该目录时遇到问题，请检查文件格式或重试。'
              : '正在上传与校验资料，自动识别范围并准备资料、核算。'}
          </p>
        </div>

        <div className="space-y-4 mb-6 relative">
          <div className="absolute left-6.5 top-3 bottom-3 w-0.5 pointer-events-none bg-slate-100" />
          {steps.map(step => {
            const state = getStepState(step.id);
            const Icon = step.icon;
            return (
              <div
                key={step.id}
                aria-current={state === 'active' ? 'step' : undefined}
                className={`flex items-start gap-4 p-3 rounded-xl ${state === 'active' ? 'bg-sky-50' : ''}`}
              >
                <div className="relative z-10 shrink-0">
                  {state === 'completed' ? (
                    <div className="w-6.5 h-6.5 rounded-full bg-emerald-600 text-white flex items-center justify-center">
                      <CheckCircle2 className="w-4 h-4" />
                    </div>
                  ) : state === 'active' ? (
                    <div className="w-6.5 h-6.5 rounded-full bg-sky-700 text-white flex items-center justify-center">
                      <Loader2 className="w-3.5 h-3.5" />
                    </div>
                  ) : state === 'error' ? (
                    <div className="w-6.5 h-6.5 rounded-full bg-rose-600 text-white flex items-center justify-center">
                      <AlertCircle className="w-4 h-4" />
                    </div>
                  ) : (
                    <div className="w-6.5 h-6.5 rounded-full border flex items-center justify-center text-xs font-semibold bg-slate-50 border-slate-200 text-slate-400">
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-sm font-bold ${
                        state === 'completed'
                          ? 'text-emerald-600'
                          : state === 'active'
                            ? 'text-sky-700 font-extrabold'
                            : state === 'error'
                              ? 'text-rose-600'
                              : 'text-slate-500'
                      }`}
                    >
                      {step.label}
                    </span>
                    {state === 'active' && (
                      <span className="text-[10px] uppercase tracking-widest text-sky-700 font-extrabold">
                        进行中
                      </span>
                    )}
                  </div>
                  <p
                    className={`text-xs mt-0.5 truncate ${
                      state === 'active' ? 'text-slate-700' : 'text-slate-500'
                    }`}
                  >
                    {step.description}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {error && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-mono mb-4 overflow-x-auto max-h-24 custom-scrollbar">
            错误日志: {error}
          </div>
        )}
        <div className="text-[11px] text-center mt-4 pt-4 border-t border-slate-100 text-slate-400">
          大文件可能需要更长的上传与校验时间，请等待当前步骤完成。
        </div>
      </div>
    </div>
  );
}
