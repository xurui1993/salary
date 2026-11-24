import React, { useState, useRef, useEffect } from 'react';
import { FileSpreadsheet, UploadCloud } from 'lucide-react';

interface ControlPanelProps {
  onUploadFiles?: (files: { file: File; relativePath: string }[]) => Promise<void>;
  onOpenTemplates?: () => void;
  isRunning?: boolean;
  separationOption?: React.ReactNode;
  collapseAction?: React.ReactNode;
}

/**
 * 统一核算上传区：不再切换手动/自动模式。
 * 拖入模板文件=自动核算；拖入资料文件夹=手动核算；小象模板按文件名自动识别。
 */
export function ControlPanel({ onUploadFiles, onOpenTemplates, isRunning = false, separationOption, collapseAction }: ControlPanelProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState('');
  const templateInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setError(''); setIsDragging(false); }, []);

  const submitFiles = async (files: { file: File; relativePath: string }[]) => {
    if (!files.length) {
      setError('未找到可上传的表格文件。');
      return;
    }
    setError('');
    await onUploadFiles?.(files);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const readDirectoryEntries = async (reader: any): Promise<any[]> => {
    const all: any[] = [];
    while (true) {
      const batch = await new Promise<any[]>((resolve) => reader.readEntries((result: any[]) => resolve(result)));
      if (!batch.length) break;
      all.push(...batch);
    }
    return all;
  };

  const traverseEntry = async (entry: any, path: string, output: { file: File; relativePath: string }[]) => {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve) => entry.file(resolve));
      output.push({ file, relativePath: path + file.name });
      return;
    }
    if (entry.isDirectory) {
      const entries = await readDirectoryEntries(entry.createReader());
      for (const child of entries) {
        await traverseEntry(child, path + entry.name + '/', output);
      }
    }
  };

  const processDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (!onUploadFiles || isRunning) return;
    setError('');
    const output: { file: File; relativePath: string }[] = [];
    const items = Array.from(e.dataTransfer.items || []);
    try {
      for (const item of items) {
        const entry = item.webkitGetAsEntry?.();
        if (entry) await traverseEntry(entry, '', output);
      }
      if (!output.length) {
        for (const file of Array.from(e.dataTransfer.files || [])) {
          output.push({ file, relativePath: file.name });
        }
      }
      await submitFiles(output);
    } catch (dropError) {
      setError(dropError instanceof Error ? dropError.message : '拖入资料解析失败');
    }
  };

  const handleTemplateInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!onUploadFiles || isRunning || !e.target.files) return;
    setError('');
    const files = Array.from(e.target.files).map(file => ({ file, relativePath: file.name }));
    e.target.value = '';
    try {
      await submitFiles(files);
    } catch (inputError) {
      setError(inputError instanceof Error ? inputError.message : '资料上传未完成');
    }
  };

  const handleFolderInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!onUploadFiles || isRunning || !e.target.files) return;
    setError('');
    const files = Array.from(e.target.files).map(file => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }));
    e.target.value = '';
    try {
      await submitFiles(files);
    } catch (inputError) {
      setError(inputError instanceof Error ? inputError.message : '资料上传未完成');
    }
  };

  return (
    <div
      className={`pq-upload wbx-toolbar wbx-payroll__upload ${isDragging ? 'dragging' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={processDrop}
    >
      <input
        ref={templateInputRef}
        type="file"
        className="hidden"
        multiple
        accept=".xlsx"
        onChange={handleTemplateInput}
        aria-label="上传薪资申请表"
      />
      <input
        ref={folderInputRef}
        type="file"
        className="hidden"
        webkitdirectory="true"
        {...({ directory: 'true' } as any)}
        onChange={handleFolderInput}
        aria-label="选择资料文件夹"
      />

      <div className="wbx-payroll__upload-main">
        <div className="pq-upload-copy wbx-payroll__upload-copy">
          <div className="wbx-payroll__upload-icon" aria-hidden="true">
            <UploadCloud size={20} strokeWidth={1.85} />
          </div>
          <div className="wbx-payroll__upload-text">
            <h3>拖入模板文件或资料文件夹</h3>
            <p>
              支持 .xlsx 模板及补充资料 · 自动识别平台
            </p>
          </div>
        </div>

        <div className="pq-upload-actions wbx-payroll__upload-actions">
          {separationOption}
          <div className="wbx-payroll__upload-btn-group">
            <button
              type="button"
              className="wb-primary"
              disabled={isRunning}
              onClick={() => templateInputRef.current?.click()}
            >
              {isRunning ? '正在添加…' : '选择模板'}
            </button>
            <button
              type="button"
              className="wbx-btn"
              disabled={isRunning}
              onClick={() => folderInputRef.current?.click()}
            >
              {isRunning ? '正在添加…' : '选择文件夹'}
            </button>
            {onOpenTemplates && (
              <button
                type="button"
                className="wbx-btn"
                onClick={onOpenTemplates}
              >
                <FileSpreadsheet size={14} aria-hidden="true" />
                <span>标准模板</span>
              </button>
            )}
            {collapseAction}
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