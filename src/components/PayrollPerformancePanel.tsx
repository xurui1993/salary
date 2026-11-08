import React from 'react';

export interface PayrollPerformance {
  preparation_seconds?: number; integrity_seconds?: number; elapsed_seconds?: number; queue_seconds?: number;
  sampled_process_peak_rss_bytes?: number; stages?: Record<string, number>;
  upload?: { server_seconds?: number; extraction_seconds?: number; indexing_seconds?: number };
  source_cache?: { hits: number; misses: number; retained_bytes: number; limit_bytes: number };
}
const LABELS: Record<string, string> = {
  'phase:applications': '解析申请名单', 'phase:source_loading': '加载核算资料', 'phase:matching': '匹配骑手与明细',
  'phase:aggregation': '汇总单量、单价与扣款', 'phase:formatting': '整理公式与格式', 'phase:saving': '保存输出',
  native_guard_seconds: '检查资料读取方式', read_excel_seconds: '读取 Excel 资料', read_csv_seconds: '读取 CSV 资料',
  open_template_seconds: '打开工资模板', write_details_seconds: '生成配送明细表', save_workbooks_seconds: '保存工资表及附表',
};
export function PayrollPerformancePanel({value}: {value?: PayrollPerformance}) {
  if (!value) return null;
  return <details className="wb-performance" aria-label="薪资核算耗时分析"><summary>核算耗时分析</summary>
    <dl>{([
      ['资料准备', value.preparation_seconds], ['快照完整性校验', value.integrity_seconds], ['核算执行（含排队）', value.elapsed_seconds],
      ['等待核算资源', value.queue_seconds], ['上传后服务器整理', value.upload?.server_seconds], ['解包文件', value.upload?.extraction_seconds],
      ['检查上传目录', value.upload?.indexing_seconds],
    ] as [string, number | undefined][]).filter(([,seconds]) => typeof seconds === 'number').map(([label,seconds]) => <div className="wb-row wb-space" key={label}><dt>{label}</dt><dd>{Number(seconds).toFixed(2)} 秒</dd></div>)}
    {Object.entries(value.stages || {}).filter(([key]) => key in LABELS).map(([key,seconds]) => <div className="wb-row wb-space" key={key}><dt>{LABELS[key]}</dt><dd>{Number(seconds).toFixed(2)} 秒</dd></div>)}</dl>
    {value.source_cache && <p className="wb-muted">本批次资料复用 {value.source_cache.hits} 次。</p>}
    {typeof value.sampled_process_peak_rss_bytes === 'number' && <p className="wb-muted">服务进程内存峰值采样 {(value.sampled_process_peak_rss_bytes / 1048576).toFixed(0)} MB。</p>}
    <p className="wb-muted">部分阶段存在包含关系，耗时不可直接相加；内存为服务进程采样，非本批次独占。</p>
  </details>;
}
