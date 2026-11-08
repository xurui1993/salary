export function restorePayrollSourceMode(config: { payrollSourceMode?: string }): 'fengshen' | 'manual' | 'xiaoxiang' {
  return config.payrollSourceMode === 'xiaoxiang'
    ? 'xiaoxiang'
    : config.payrollSourceMode === 'manual'
      ? 'manual'
      : 'fengshen';
}
