export type PayrollUploadMode = 'fengshen' | 'manual' | 'xiaoxiang';

export interface PayrollUploadEntry<TFile = { name: string }> {
  file: TFile;
  relativePath: string;
}

export interface PayrollUploadGroup<TFile = { name: string }> {
  mode: PayrollUploadMode;
  files: PayrollUploadEntry<TFile>[];
}

function isTemplateFile(name: string) {
  return /\.xlsx$/i.test(name) && name.toLowerCase().includes('template') &&
    !name.startsWith('~$') && !name.startsWith('.');
}

function isXiaoxiangTemplate(name: string) {
  return isTemplateFile(name) && name.includes('小象');
}

function hasFolderPath(relativePath: string) {
  return /[\\/]/.test(relativePath);
}

function nestTemplates<TFile extends { name: string }>(entries: PayrollUploadEntry<TFile>[]): PayrollUploadEntry<TFile>[] {
  return entries.map((entry, index) => ({
    ...entry,
    relativePath: `templates/${String(index + 1).padStart(4, '0')}/${entry.file.name}`,
  }));
}

export function planPayrollUpload<TFile extends { name: string }>(
  files: PayrollUploadEntry<TFile>[],
): PayrollUploadGroup<TFile>[] {
  const templates = files.filter(entry => isTemplateFile(entry.file.name));
  if (!templates.length) throw new Error('请上传文件名含 template 的 .xlsx 薪资申请表');

  const xiaoxiangTemplates = templates.filter(entry => isXiaoxiangTemplate(entry.file.name));
  const normalTemplates = templates.filter(entry => !isXiaoxiangTemplate(entry.file.name));
  const folderNormalTemplates = normalTemplates.filter(entry => hasFolderPath(entry.relativePath));
  const fileNormalTemplates = normalTemplates.filter(entry => !hasFolderPath(entry.relativePath));
  const folderSourceFiles = files.filter(entry => !isTemplateFile(entry.file.name) && hasFolderPath(entry.relativePath));

  if (folderNormalTemplates.length && !folderSourceFiles.length) {
    throw new Error('文件夹内未找到模板及补充资料源文件；自动核算请直接选择模板文件');
  }

  const groups: PayrollUploadGroup<TFile>[] = [];
  if (fileNormalTemplates.length) groups.push({ mode: 'fengshen', files: nestTemplates(fileNormalTemplates) });
  if (folderNormalTemplates.length) groups.push({ mode: 'manual', files: [...folderNormalTemplates, ...folderSourceFiles] });
  if (xiaoxiangTemplates.length) groups.push({ mode: 'xiaoxiang', files: nestTemplates(xiaoxiangTemplates) });
  if (!groups.length) throw new Error('未识别到可提交的核算模板');
  return groups;
}