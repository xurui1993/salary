import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud } from 'lucide-react';

interface ControlPanelProps {
  payrollSourceMode?: 'manual' | 'fengshen' | 'xiaoxiang';
  onUploadFiles?: (files: { file: File; relativePath: string }[]) => Promise<void>;
  onOpenTemplates?: () => void;
  isRunning?: boolean;
  separationOption?: React.ReactNode;
}

/**
 * 兼职核算上传区：仅负责拖拽 / 点选上传与模式说明。
 * 模式切换、辅助下载工具、认证入口由 CorePage 承担；执行态展示由 ExecutionCockpit 承担。
 */
export function ControlPanel({ payrollSourceMode = 'fengshen', onUploadFiles, onOpenTemplates, isRunning = false, separationOption }: ControlPanelProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState('');
  const automatic = payrollSourceMode === 'fengshen' || payrollSourceMode === 'xiaoxiang';
  const fileInputRef = useRef<HTMLInputElement>(null);
  const multiFileInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setError(''); setIsDragging(false); }, [payrollSourceMode]);
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const processDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    if (!onUploadFiles || isRunning) return;
    setError('');
    if (automatic) {
      const items = Array.from(e.dataTransfer.items || []);
      if (items.some(item => item.webkitGetAsEntry?.()?.isDirectory)) {
        setError('自动核算仅支持上传申请表文件，请勿拖入文件夹。');
        return;
      }
      const files = Array.from(e.dataTransfer.files);
      await onUploadFiles(files.map(file => ({file, relativePath:file.name})));
      return;
    }

    const rawItems = Array.from(e.dataTransfer.items || []);
    if (!rawItems.some(item => item.webkitGetAsEntry?.()?.isDirectory)) {
      setError('手动上传仅支持上传资料目录，请直接拖入文件夹或点击「选择文件夹」。');
      return;
    }

    const items = e.dataTransfer.items;
    const filesToUpload: { file: File; relativePath: string }[] = [];

    const traverseFileTree = async (item: any, path?: string) => {
      path = path || "";
      if (item.isFile) {
        const file = await new Promise<File>((resolve) => item.file(resolve));
        filesToUpload.push({ file, relativePath: path + file.name });
      } else if (item.isDirectory) {
        const dirReader = item.createReader();
        const readAllEntries = async () => {
          let allEntries: any[] = [];
          let entries: any[] = [];
          do {
            entries = await new Promise<any[]>((resolve) => {
              dirReader.readEntries((result: any[]) => resolve(result));
            });
            allEntries = allEntries.concat(entries);
          } while (entries.length > 0);
          return allEntries;
        };
        const entries = await readAllEntries();
        for (const entry of entries) {
          await traverseFileTree(entry, path + item.name + "/");
        }
      }
    };

    if (items) {
      for (let i = 0; i < items.length; i++) {
        const item = items[i].webkitGetAsEntry();
        if (item) {
          await traverseFileTree(item);
        }
      }
    }

    if (filesToUpload.length > 0) {
      await onUploadFiles(filesToUpload);
    }
  };

  const handleClick = () => {
    if (isRunning) return;
    if (automatic) {
      multiFileInputRef.current?.click();
    } else {
      fileInputRef.current?.click();
    }
  };

  const handleFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!onUploadFiles || !e.target.files || isRunning) return;
    setError('');
    const files = e.target.files;
    const filesToUpload: { file: File; relativePath: string }[] = [];
    for (let i = 0; i < files.length; i++) {
      filesToUpload.push({
        file: files[i],
        relativePath: files[i].webkitRelativePath || files[i].name,
      });
    }
    e.target.value = '';
    if (filesToUpload.length > 0) {
      await onUploadFiles(filesToUpload);
    }
  };

  return (
    <div
      className={`pq-upload wbx-toolbar wbx-payroll__upload ${isDragging ? 'dragging' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={processDrop}
    >
      {!automatic && (
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          webkitdirectory="true"
          {...({ directory: 'true' } as any)}
          onChange={handleFileInput}
          aria-label="选择资料文件夹"
        />
      )}
      <input
        ref={multiFileInputRef}
        type="file"
        className="hidden"
        multiple
        accept={automatic ? '.xlsx' : '.xlsx,.xls,.csv,.txt'}
        onChange={handleFileInput}
        aria-label={automatic ? '上传薪资申请表' : '模板及补充资料'}
      />

      <div className="wbx-payroll__upload-main">
        <div className="pq-upload-copy wbx-payroll__upload-copy">
          <div className="wbx-payroll__upload-icon">
            <UploadCloud size={24} />
          </div>
          <div className="wbx-payroll__upload-text">
            <h3>{automatic ? '上传薪资申请表（自动核算）' : '上传资料目录（手动上传）'}</h3>
            <p>
              {automatic
                ? '拖拽或点选 1 份或多份含 template 的 .xlsx 文件，自动拉取风神与蓝橙源表并执行算薪。'
                : '仅支持拖入或选择包含标准模板与本地补充源表的整个资料文件夹。'}
            </p>
            <div className="wbx-payroll__upload-hints">
              {automatic ? (
                <>
                  <span>支持多份 .xlsx 并发入队</span>
                  <span>自动齐套风神 / 蓝橙源表</span>
                  <span>行内展开全链路核验日志</span>
                </>
              ) : (
                <>
                  <span>支持整资料目录拖拽上传</span>
                  <span>自动核验本地补充源表</span>
                  <span>站点独立扣款优先应用</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="pq-upload-actions wbx-payroll__upload-actions">
          {separationOption}
          <div className="wbx-payroll__upload-btn-group">
            {automatic ? (
              <button
                type="button"
                className="wb-primary"
                disabled={isRunning}
                onClick={handleClick}
              >
                {isRunning ? '正在添加…' : '选择模板'}
              </button>
            ) : (
              <button
                type="button"
                className="wb-primary"
                disabled={isRunning}
                onClick={() => fileInputRef.current?.click()}
              >
                {isRunning ? '正在添加…' : '选择文件夹'}
              </button>
            )}
            {onOpenTemplates && (
              <button
                type="button"
                className="wbx-btn wbx-btn--ghost"
                onClick={onOpenTemplates}
              >
                标准模板
              </button>
            )}
          </div>
        </div>
      </div>

      {error && (
        <p className="wb-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

