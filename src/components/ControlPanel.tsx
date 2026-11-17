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
    multiFileInputRef.current?.click();
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

  return <div className={`pq-upload wbx-toolbar wbx-payroll__upload ${isDragging ? 'dragging' : ''}`} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={processDrop}>
    {!automatic && <input ref={fileInputRef} type="file" className="hidden" webkitdirectory="true" {...({ directory: 'true' } as any)} onChange={handleFileInput} aria-label="选择资料文件夹" />}
    <input ref={multiFileInputRef} type="file" className="hidden" multiple accept={automatic?'.xlsx':'.xlsx,.xls,.csv,.txt'} onChange={handleFileInput} aria-label={automatic?'上传薪资申请表':'模板及补充资料'} />
    <div className="pq-upload-copy wbx-payroll__upload-copy"><UploadCloud size={24}/><div><h3>{automatic ? '添加核算模板' : '添加模板与核算资料'}</h3>
    <p>{payrollSourceMode === 'xiaoxiang' ? '拖拽小象 .xlsx template 到此处，自动下载灯塔与价格档案并执行。' : automatic ? '拖拽 .xlsx 标准模板到此处，支持多份并按顺序自动执行。' : '上传多个 template 及其资料，按模板所在目录建立任务。'}</p></div></div>
    <div className="pq-upload-actions wbx-payroll__upload-actions">
      {separationOption}
      <button type="button" className="wb-primary" disabled={isRunning} onClick={handleClick}>{isRunning?'正在添加…':automatic?'选择模板':'选择文件'}</button>
      {!automatic && <button type="button" className="wb-button" disabled={isRunning} onClick={() => fileInputRef.current?.click()}>选择文件夹</button>}
      {onOpenTemplates && <button type="button" className="wbx-btn wbx-btn--primary" onClick={onOpenTemplates}>标准模板</button>}
    </div>
    {error && <p className="wb-error" role="alert">{error}</p>}
  </div>;
}
