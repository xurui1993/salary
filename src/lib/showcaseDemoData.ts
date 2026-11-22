import type { PayrollQueueTask } from './payrollQueue';
import type { DeductionEntry } from '../components/DeductionAmounts';
import {
  CONFIG_RULE_COLUMNS_WITH_THRESHOLDS,
  type ProblemRuleItem,
} from './deductionCategories';
import { filterTaskCenterRecords } from './workbenchFilters';

/* ═══════════════════════════════════════════════════════════════════════════
 * 1. 核算批次（PayrollQueueWorkbench）— 30 条全场景示例数据
 * 覆盖所有状态：preparing / calculating / queued / stopping / waiting_confirmation /
 * waiting_materials / completed / error / cancelled / interrupted
 * 覆盖所有模式：fengshen（闪购自动）/ manual（闪购手动）/ xiaoxiang（小象超市）
 * 覆盖特殊场景：历史批次（legacy）、空审批编号、多日志、自动扣款明细、复核摘要
 * ═══════════════════════════════════════════════════════════════════════════ */

export function buildDemoPayrollTasks(): PayrollQueueTask[] {
  const specs: Array<{
    id: string;
    batch_id?: string;
    approval_code: string;
    mode: 'fengshen' | 'manual' | 'xiaoxiang';
    city: string;
    start: string;
    end: string;
    cycle: string;
    applicants: number;
    status: string;
    progress: number;
    current_action: string;
    elapsed_seconds?: number;
    created_at: string;
    legacy?: boolean;
    logs?: Array<{ time: string; level?: string; message: string }>;
    review_summary?: Record<string, any>;
    automatic_deductions?: Array<{ name: string; amount: number; count: number }>;
  }> = [
    // 1–6: 执行中（calculating / preparing / queued / stopping）
    {
      id: 'demo-pq-01',
      batch_id: 'BATCH-202611-SH01',
      approval_code: 'SP-20261121-001',
      mode: 'fengshen',
      city: '上海',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 186,
      status: 'calculating',
      progress: 74,
      current_action: '正在核对站点配送费与违规扣款明细（138/186 人）',
      elapsed_seconds: 92,
      created_at: '2026-11-21T09:18:00+08:00',
      logs: [
        { time: '09:18:04', level: 'INFO', message: '已解析薪资申请表：上海 · 186 名骑手 · 6 个站点' },
        { time: '09:18:36', level: 'INFO', message: '风神配送费、违规扣款与出勤明细已拉取完成' },
        { time: '09:19:22', level: 'INFO', message: '正在执行站点阶梯单价与问题单关键词扣款匹配' },
      ],
    },
    {
      id: 'demo-pq-02',
      batch_id: 'BATCH-202611-SZ02',
      approval_code: 'SP-20261121-002',
      mode: 'fengshen',
      city: '深圳',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 142,
      status: 'preparing',
      progress: 38,
      current_action: '正在从风神平台拉取 10 月配送费与月度 UB 账单',
      elapsed_seconds: 47,
      created_at: '2026-11-21T09:14:00+08:00',
      logs: [
        { time: '09:14:05', level: 'INFO', message: '模板校验通过：深圳 4 个在营站点' },
        { time: '09:14:28', level: 'INFO', message: '正在同步风神配送费报表（2/4 站点）' },
      ],
    },
    {
      id: 'demo-pq-03',
      batch_id: 'BATCH-202611-BJ03',
      approval_code: 'SP-20261121-003',
      mode: 'xiaoxiang',
      city: '北京',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 96,
      status: 'calculating',
      progress: 56,
      current_action: '正在合并小象超市灯塔出勤与保险扣款',
      elapsed_seconds: 68,
      created_at: '2026-11-21T09:10:00+08:00',
      logs: [
        { time: '09:10:08', level: 'INFO', message: '已自动识别小象超市模板（北京望京/朝阳仓）' },
        { time: '09:10:49', level: 'INFO', message: '灯塔日维度分析与出勤表合并完成，进入薪资核算阶段' },
      ],
    },
    {
      id: 'demo-pq-04',
      approval_code: 'SP-20261121-004',
      mode: 'fengshen',
      city: '广州',
      start: '2026-11-01',
      end: '2026-11-15',
      cycle: '11月上半月',
      applicants: 118,
      status: 'queued',
      progress: 0,
      current_action: '排队等待前序任务释放采集通道（第 1 位）',
      elapsed_seconds: 16,
      created_at: '2026-11-21T09:08:00+08:00',
      logs: [{ time: '09:08:02', level: 'INFO', message: '任务已入队，等待自动拉取风神资料' }],
    },
    {
      id: 'demo-pq-05',
      approval_code: '',
      mode: 'manual',
      city: '东莞',
      start: '2026-11-01',
      end: '2026-11-15',
      cycle: '11月上半月',
      applicants: 64,
      status: 'queued',
      progress: 0,
      current_action: '手动资料包已就绪，排队等待核算进程',
      elapsed_seconds: 9,
      created_at: '2026-11-21T09:05:00+08:00',
      logs: [{ time: '09:05:11', level: 'INFO', message: '已上传手动资料文件夹（含 7 份补充表）' }],
    },
    {
      id: 'demo-pq-06',
      batch_id: 'BATCH-202611-TJ06',
      approval_code: 'SP-20261121-006',
      mode: 'fengshen',
      city: '天津',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 83,
      status: 'stopping',
      progress: 45,
      current_action: '正在安全中止当前拉取请求并保存已完成进度',
      elapsed_seconds: 51,
      created_at: '2026-11-21T09:01:00+08:00',
      logs: [{ time: '09:01:51', level: 'WARN', message: '收到人工停止指令，等待当前批次安全退出' }],
    },

    // 7–11: 待处理（waiting_confirmation / waiting_materials）
    {
      id: 'demo-pq-07',
      batch_id: 'BATCH-202611-NB07',
      approval_code: 'SP-20261121-007',
      mode: 'fengshen',
      city: '宁波',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 109,
      status: 'waiting_confirmation',
      progress: 65,
      current_action: '发现 2 个新增站点尚未配置默认扣款，待确认后继续核算',
      elapsed_seconds: 74,
      created_at: '2026-11-21T08:52:00+08:00',
      logs: [
        { time: '08:52:10', level: 'INFO', message: '资料已全部就绪，进入扣款规则预检' },
        { time: '08:53:24', level: 'WARN', message: '鄞州南部站、北仑保税站缺少安全基金与投诉扣款配置' },
      ],
    },
    {
      id: 'demo-pq-08',
      batch_id: 'BATCH-202611-QZ08',
      approval_code: 'SP-20261121-008',
      mode: 'manual',
      city: '泉州',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 77,
      status: 'waiting_confirmation',
      progress: 70,
      current_action: '手动资料包存在 3 名骑手站点名称差异，请确认归属',
      elapsed_seconds: 58,
      created_at: '2026-11-21T08:45:00+08:00',
      logs: [
        { time: '08:45:12', level: 'INFO', message: '已读取本地文件夹 6 份表格' },
        { time: '08:46:09', level: 'WARN', message: '检测到 3 条站点别名未映射，等待人工确认扣款口径' },
      ],
    },
    {
      id: 'demo-pq-09',
      batch_id: 'BATCH-202611-DL09',
      approval_code: 'SP-20261121-009',
      mode: 'fengshen',
      city: '大连',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 91,
      status: 'waiting_materials',
      progress: 28,
      current_action: '商翼员工资料授权已过期，请重新登录后点击继续准备',
      elapsed_seconds: 34,
      created_at: '2026-11-21T08:38:00+08:00',
      logs: [
        { time: '08:38:04', level: 'INFO', message: '风神配送费、考勤明细已下载完成' },
        { time: '08:38:38', level: 'WARN', message: '商翼会话失效，获取已暂停，等待重新授权后继续' },
      ],
    },
    {
      id: 'demo-pq-10',
      batch_id: 'BATCH-202611-SY10',
      approval_code: '',
      mode: 'xiaoxiang',
      city: '三亚',
      start: '2026-11-01',
      end: '2026-11-15',
      cycle: '11月上半月',
      applicants: 52,
      status: 'waiting_materials',
      progress: 22,
      current_action: '灯塔近 15 日订单明细需要滑块验证，请完成登录校验',
      elapsed_seconds: 29,
      created_at: '2026-11-21T08:31:00+08:00',
      logs: [
        { time: '08:31:05', level: 'INFO', message: '小象超市模板已识别：三亚吉阳/海棠仓' },
        { time: '08:31:34', level: 'WARN', message: '灯塔接口返回验证提示，任务暂停等待人工验证' },
      ],
    },
    {
      id: 'demo-pq-11',
      batch_id: 'BATCH-202611-BD11',
      approval_code: 'SP-20261121-011',
      mode: 'fengshen',
      city: '保定',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 68,
      status: 'waiting_confirmation',
      progress: 68,
      current_action: '问题单关键词命中 9 条高额赔付，待复核扣款金额',
      elapsed_seconds: 63,
      created_at: '2026-11-21T08:20:00+08:00',
      logs: [
        { time: '08:20:45', level: 'WARN', message: '命中「餐损责任·严重漏洒」等 9 笔问题单扣款，等待确认' },
      ],
    },

    // 12–24: 已完成（completed，含不同模式、含空审批编号、含 1 条 legacy 历史批次）
    {
      id: 'demo-pq-12',
      batch_id: 'BATCH-202611-SH12',
      approval_code: 'SP-20261120-101',
      mode: 'fengshen',
      city: '上海',
      start: '2026-10-01',
      end: '2026-10-15',
      cycle: '10月上半月',
      applicants: 204,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 已生成成品薪资表与异常核对单',
      elapsed_seconds: 148,
      created_at: '2026-11-20T18:40:00+08:00',
      logs: [
        { time: '18:40:05', level: 'INFO', message: '开始执行上海 10 月上半月薪资自动核算' },
        { time: '18:42:33', level: 'INFO', message: '成品包已导出：204 名骑手，应发总额 612,480.50 元' },
      ],
    },
    {
      id: 'demo-pq-13',
      batch_id: 'BATCH-202611-SZ13',
      approval_code: 'SP-20261120-102',
      mode: 'fengshen',
      city: '深圳',
      start: '2026-10-01',
      end: '2026-10-15',
      cycle: '10月上半月',
      applicants: 165,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 扣款校验 0 差异',
      elapsed_seconds: 126,
      created_at: '2026-11-20T17:55:00+08:00',
      logs: [{ time: '17:57:06', level: 'INFO', message: '全部 165 名骑手核算完成，成品文件已归档' }],
    },
    {
      id: 'demo-pq-14',
      batch_id: 'BATCH-202611-GZ14',
      approval_code: 'SP-20261120-103',
      mode: 'xiaoxiang',
      city: '广州',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 112,
      status: 'completed',
      progress: 100,
      current_action: '小象超市整月核算完成 · 已输出明细与汇总',
      elapsed_seconds: 114,
      created_at: '2026-11-20T17:12:00+08:00',
      logs: [{ time: '17:13:54', level: 'INFO', message: '小象超市保险费、循环物资使用费与附加险已自动扣减' }],
    },
    {
      id: 'demo-pq-15',
      batch_id: 'BATCH-202611-BJ15',
      approval_code: 'SP-20261120-104',
      mode: 'manual',
      city: '北京',
      start: '2026-10-01',
      end: '2026-10-15',
      cycle: '10月上半月',
      applicants: 134,
      status: 'completed',
      progress: 100,
      current_action: '手动资料包核算完成 · 含 4 笔手工调整备注',
      elapsed_seconds: 89,
      created_at: '2026-11-20T16:30:00+08:00',
      logs: [{ time: '16:31:29', level: 'INFO', message: '手动资料核算完成，结果文件可下载' }],
    },
    {
      id: 'demo-pq-16',
      batch_id: 'BATCH-202611-DG16',
      approval_code: '',
      mode: 'fengshen',
      city: '东莞',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 98,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 待补录 OA 审批编号',
      elapsed_seconds: 105,
      created_at: '2026-11-20T15:48:00+08:00',
      logs: [{ time: '15:49:45', level: 'INFO', message: '核算结果已生成，可在任务行点击补充审批编号' }],
    },
    {
      id: 'demo-pq-17',
      batch_id: 'BATCH-202611-NB17',
      approval_code: 'SP-20261120-106',
      mode: 'fengshen',
      city: '宁波',
      start: '2026-10-16',
      end: '2026-10-31',
      cycle: '10月下半月',
      applicants: 87,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 排除取分离站点',
      elapsed_seconds: 94,
      created_at: '2026-11-20T15:02:00+08:00',
      logs: [{ time: '15:03:34', level: 'INFO', message: '已自动排除 2 个取分离站点，87 名骑手核算完成' }],
    },
    {
      id: 'demo-pq-18',
      batch_id: 'BATCH-202611-QZ18',
      approval_code: 'SP-20261120-107',
      mode: 'fengshen',
      city: '泉州',
      start: '2026-10-16',
      end: '2026-10-31',
      cycle: '10月下半月',
      applicants: 73,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 已生成成品薪资包',
      elapsed_seconds: 81,
      created_at: '2026-11-20T14:25:00+08:00',
      logs: [{ time: '14:26:21', level: 'INFO', message: '泉州 3 个站点全部核验通过' }],
    },
    {
      id: 'demo-pq-19',
      batch_id: 'BATCH-202611-TJ19',
      approval_code: 'SP-20261120-108',
      mode: 'xiaoxiang',
      city: '天津',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 61,
      status: 'completed',
      progress: 100,
      current_action: '小象超市核算完成 · 零异常差异',
      elapsed_seconds: 76,
      created_at: '2026-11-20T13:40:00+08:00',
      logs: [{ time: '13:41:16', level: 'INFO', message: '天津小象仓核算完成，61 人实发金额已核对' }],
    },
    {
      id: 'demo-pq-20',
      batch_id: 'BATCH-202611-DL20',
      approval_code: 'SP-20261119-091',
      mode: 'fengshen',
      city: '大连',
      start: '2026-10-01',
      end: '2026-10-15',
      cycle: '10月上半月',
      applicants: 95,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 已归档至本地结果目录',
      elapsed_seconds: 103,
      created_at: '2026-11-19T19:15:00+08:00',
      logs: [{ time: '19:16:43', level: 'INFO', message: '大连上半月核算完成' }],
    },
    {
      id: 'demo-pq-21',
      batch_id: 'BATCH-202611-SG21',
      approval_code: 'SP-20261119-092',
      mode: 'manual',
      city: '韶关',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 44,
      status: 'completed',
      progress: 100,
      current_action: '手动核算完成 · 已应用确认零扣款站点规则',
      elapsed_seconds: 54,
      created_at: '2026-11-19T18:22:00+08:00',
      logs: [{ time: '18:22:54', level: 'INFO', message: '曲江站按零扣款口径结算完成' }],
    },
    {
      id: 'demo-pq-22',
      batch_id: 'BATCH-202611-TZ22',
      approval_code: 'SP-20261119-093',
      mode: 'fengshen',
      city: '台州',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 79,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 含问题单关键词自动扣款 14 笔',
      elapsed_seconds: 98,
      created_at: '2026-11-19T17:10:00+08:00',
      logs: [{ time: '17:11:38', level: 'INFO', message: '台州整月自动核算完成，成品包已生成' }],
    },
    {
      id: 'demo-pq-23',
      batch_id: 'BATCH-202611-HZ23',
      approval_code: 'SP-20261119-094',
      mode: 'fengshen',
      city: '惠州',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 67,
      status: 'completed',
      progress: 100,
      current_action: '核算完成 · 蓝橙价格档案自动匹配',
      elapsed_seconds: 86,
      created_at: '2026-11-19T16:05:00+08:00',
      logs: [{ time: '16:06:26', level: 'INFO', message: '惠州整月核算完成' }],
    },
    {
      id: 'demo-pq-24',
      batch_id: 'LEGACY-202610-ST24',
      approval_code: 'SP-20261031-801',
      mode: 'fengshen',
      city: '汕头',
      start: '2026-09-01',
      end: '2026-09-30',
      cycle: '9月整月（历史批次）',
      applicants: 82,
      status: 'completed',
      progress: 100,
      current_action: '历史迁移批次已完成归档',
      elapsed_seconds: 132,
      created_at: '2026-11-18T11:30:00+08:00',
      legacy: true,
      logs: [{ time: '11:32:12', level: 'INFO', message: '历史批次记录已只读归档，审批编号于原批次维护' }],
    },

    // 25–30: 异常 / 已结束（error / cancelled / interrupted）
    {
      id: 'demo-pq-25',
      batch_id: 'BATCH-202611-CZ25',
      approval_code: 'SP-20261119-095',
      mode: 'fengshen',
      city: '潮州',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 49,
      status: 'error',
      progress: 42,
      current_action: '',
      elapsed_seconds: 61,
      created_at: '2026-11-19T14:50:00+08:00',
      logs: [
        { time: '14:50:08', level: 'INFO', message: '开始读取潮州薪资申请模板' },
        { time: '14:51:09', level: 'ERROR', message: '蓝橙价格档案缺少 2026-10 潮州湘桥站单价，核算已终止' },
      ],
    },
    {
      id: 'demo-pq-26',
      batch_id: 'BATCH-202611-SY26',
      approval_code: 'SP-20261119-096',
      mode: 'manual',
      city: '三亚',
      start: '2026-10-01',
      end: '2026-10-31',
      cycle: '10月整月',
      applicants: 58,
      status: 'error',
      progress: 18,
      current_action: '上传资料缺少「配送费」工作表，请补全后重新上传',
      elapsed_seconds: 19,
      created_at: '2026-11-19T13:15:00+08:00',
      logs: [{ time: '13:15:19', level: 'ERROR', message: '目录中未识别到配送费明细表（delivery_fee*.xlsx）' }],
    },
    {
      id: 'demo-pq-27',
      batch_id: 'BATCH-202611-SH27',
      approval_code: 'SP-20261118-084',
      mode: 'fengshen',
      city: '上海',
      start: '2026-11-01',
      end: '2026-11-15',
      cycle: '11月上半月',
      applicants: 174,
      status: 'cancelled',
      progress: 33,
      current_action: '用户主动取消（上传了旧版申请模板）',
      elapsed_seconds: 41,
      created_at: '2026-11-18T16:42:00+08:00',
      logs: [{ time: '16:42:41', level: 'WARN', message: '操作员取消该批次，已清理临时缓存' }],
    },
    {
      id: 'demo-pq-28',
      batch_id: 'BATCH-202611-BJ28',
      approval_code: '',
      mode: 'xiaoxiang',
      city: '北京',
      start: '2026-10-16',
      end: '2026-10-31',
      cycle: '10月下半月',
      applicants: 88,
      status: 'cancelled',
      progress: 12,
      current_action: '已停止 · 合并至整月批次统一核算',
      elapsed_seconds: 15,
      created_at: '2026-11-18T15:10:00+08:00',
      logs: [{ time: '15:10:15', level: 'WARN', message: '任务已手动停止' }],
    },
    {
      id: 'demo-pq-29',
      batch_id: 'BATCH-202611-GZ29',
      approval_code: 'SP-20261118-082',
      mode: 'fengshen',
      city: '广州',
      start: '2026-10-16',
      end: '2026-10-31',
      cycle: '10月下半月',
      applicants: 129,
      status: 'interrupted',
      progress: 61,
      current_action: '服务重启导致任务中断，支持重新上传续算',
      elapsed_seconds: 77,
      created_at: '2026-11-18T11:05:00+08:00',
      logs: [{ time: '11:06:22', level: 'WARN', message: '后台进程重启，已完成资料准备，核算阶段中断' }],
    },
    {
      id: 'demo-pq-30',
      batch_id: 'BATCH-202611-BD30',
      approval_code: 'SP-20261117-075',
      mode: 'fengshen',
      city: '保定',
      start: '2026-10-01',
      end: '2026-10-15',
      cycle: '10月上半月',
      applicants: 63,
      status: 'error',
      progress: 55,
      current_action: '风神接口响应超时（重试 3 次失败）',
      elapsed_seconds: 185,
      created_at: '2026-11-17T19:30:00+08:00',
      logs: [
        { time: '19:31:02', level: 'WARN', message: '风神接口第 2 次请求超时，准备重试' },
        { time: '19:33:05', level: 'ERROR', message: '连续 3 次请求超时，请检查风神网络状态后重试' },
      ],
    },
  ];

  const demoStationNames: Record<string, string[]> = {
    上海: ['徐家汇中心站', '陆家嘴金融站', '静安寺商圈站', '张江高科站'],
    深圳: ['南山科技园站', '福田车公庙站', '宝安中心站'],
    北京: ['望京SOHO站', '朝阳大悦城站', '中关村软件园站'],
    广州: ['天河体育西站', '珠江新城站', '白云万达站'],
    东莞: ['南城鸿福站', '东城万达站'],
    天津: ['和平滨江道站', '南开大悦城站'],
    宁波: ['鄞州南部站', '海曙天一站', '北仑保税站'],
    泉州: ['丰泽浦西站', '鲤城中山站'],
    大连: ['中山人民路站', '沙河口西安路站'],
    三亚: ['吉阳迎宾仓', '海棠免税仓'],
    保定: ['竞秀朝阳站', '莲池裕华站'],
    韶关: ['浈江风度站', '曲江马坝站'],
    台州: ['椒江白云站', '路桥银座站'],
    惠州: ['惠城江北站', '惠阳淡水站'],
    汕头: ['龙湖金砂站', '金平长平站'],
    潮州: ['湘桥牌坊站', '枫溪陶瓷站'],
  };

  const amountOverrides: Record<string, number> = {
    'demo-pq-12': 612480.5,
  };

  const nonHalfCycleTypes = ['月结', '周结', '全职', '日结', '月结', '日结'] as const;

  return specs.map((item, idx) => {
    const hasCalculatedAmount = ['completed', 'calculating', 'waiting_confirmation', 'interrupted'].includes(item.status);
    const isHalfMonth = item.cycle.includes('半月');
    const settlementType = isHalfMonth ? '半月结' : nonHalfCycleTypes[idx % nonHalfCycleTypes.length];
    const avgPerRider = item.mode === 'xiaoxiang' ? 3240 : isHalfMonth ? 2960 : 5480;
    const computedAmount = hasCalculatedAmount
      ? (amountOverrides[item.id] ??
        Math.round((item.applicants * avgPerRider + ((idx * 1379) % 4800) + ((idx * 37) % 95) / 100) * 100) / 100)
      : null;

    const stations = demoStationNames[item.city] || [`${item.city}中心站`, `${item.city}高新站`];
    const deductionSources = stations.map((name, sIdx) => ({
      station: { name },
      source:
        item.status === 'waiting_confirmation' && sIdx === stations.length - 1
          ? '新增站点 · 待确认默认口径'
          : sIdx === 0
            ? '站点例外配置（已生效）'
            : '沿用城市默认扣款口径',
    }));

    const reviewObj =
      item.status === 'completed'
        ? {
            version: 1,
            status: 'pending_review' as const,
            batch_id: item.batch_id || item.id,
            city: item.city,
            start: item.start,
            end: item.end,
            metrics: [
              { key: 'applicants', label: '参与核算人数', value: item.applicants, unit: '人', note: '按上传模板有效骑手去重统计' },
              { key: 'no_price', label: '缺单价骑手', value: idx % 4 === 0 ? 2 : 0, unit: '人', note: '未匹配到蓝橙有效价格档位的人数' },
              { key: 'unbound', label: '未绑定账户', value: idx % 5 === 0 ? 1 : 0, unit: '人', note: '风神与发薪收款账户未关联人数' },
              { key: 'intercepted', label: '风险拦截笔数', value: idx % 3 === 0 ? 3 : 0, unit: '笔', note: '含问题单高额赔付与离职扣款复核项' },
            ],
            issues:
              idx % 4 === 0
                ? [
                    { code: 'PRICE_MISSING', label: '存在待核对单价骑手', count: 2, location: 'Sheet「薪资明细」第 42、87 行' },
                  ]
                : [],
            sources: [
              {
                kind: 'delivery_fee',
                label: item.mode === 'xiaoxiang' ? '灯塔出勤与单量表' : '风神配送费与违规扣款',
                status: 'ready',
                files: [{ name: `${item.city}_${item.start}_配送费明细.xlsx`, sha256: `a8f3${idx}9c12e4b0192` }],
              },
            ],
            template: {
              name: `${item.city}_${item.cycle}_${item.mode === 'xiaoxiang' ? '小象' : '兼职'}薪资申请表.xlsx`,
              sha256: `f19d${idx}7b80a31c445`,
            },
            deduction_version: `ded-v202611-${String(idx + 1).padStart(2, '0')}`,
            input_check: '所有必选业务表已对齐周期并完成骑手 ID 交叉校验。',
            money_check: `当前批次应发总额 ¥${(computedAmount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}，导出后请在 Excel / WPS 中重算并复核公式。`,
          }
        : undefined;

    return {
      id: item.id,
      batch_id: item.batch_id || '',
      approval_code: item.approval_code,
      mode: item.mode,
      settlement_type: settlementType,
      amount: computedAmount,
      template_name: `${item.city}_${item.cycle}_${item.mode === 'xiaoxiang' ? '小象' : '兼职'}薪资申请表.xlsx`,
      plan: {
        city: item.city,
        start: item.start,
        end: item.end,
        cycle: item.cycle,
        settlement_type: settlementType,
        applicants: item.applicants,
        amount: computedAmount,
        template: `${item.city}_${item.cycle}_薪资申请表.xlsx`,
      },
      status: item.status,
      progress: item.progress,
      current_action: item.current_action,
      elapsed_seconds: item.elapsed_seconds,
      created_at: item.created_at,
      legacy: item.legacy || false,
      logs: (item.logs || []).map(l => ({
        time: l.time,
        level: l.level,
        text: l.message,
        message: l.message,
      })),
      preparation: {
        id: item.batch_id || item.id,
        mode: item.mode,
        status: item.status,
        pause_reason: item.status === 'waiting_materials' ? item.current_action : undefined,
        automatic_deductions: hasCalculatedAmount ? { sources: deductionSources } : undefined,
        result: reviewObj ? { total_amount: computedAmount, review_summary: reviewObj } : undefined,
      } as any,
      review_summary:
        item.status === 'completed'
          ? {
              city: item.city,
              period: `${item.start} ~ ${item.end}`,
              applicants: item.applicants,
              total_amount: computedAmount,
              matched_riders: item.applicants,
              stations_count: stations.length,
            }
          : undefined,
      demo: true,
    };
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
 * 2. 任务中心（DownloadRecords）— 30 条全场景示例数据
 * 覆盖所有状态：running / queued / waiting_login / waiting_manual / cancelling /
 * success / partial / error / cancelled / interrupted / empty
 * 覆盖所有类型：download / generate / approval / price-export
 * 覆盖所有平台：fengshen / lanorange / baize / benlai / xiaoxiang
 * 覆盖单文件、多文件可展开、source_files 来源文件、price_id 跳转
 * ═══════════════════════════════════════════════════════════════════════════ */

export interface DemoTaskCenterFile {
  id: string;
  name: string;
  bytes: number;
  download_url: string;
  city?: string;
  dataset?: string;
}

export interface DemoTaskCenterRecord {
  id: string;
  kind: 'download' | 'generate' | 'approval' | 'price-export';
  title?: string;
  price_id?: string;
  price_view?: 'approval' | 'price-export';
  status: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  start: string;
  end: string;
  cities: string[];
  datasets: string[];
  total_items: number;
  completed_items: number;
  failed_items: number;
  files: DemoTaskCenterFile[];
  source_files?: DemoTaskCenterFile[];
  has_zip: boolean;
  can_retry: boolean;
  can_cancel: boolean;
  error?: string;
  archived?: boolean;
  demo?: boolean;
}

function makeFile(prefix: string, idx: number, name: string, bytes: number, city?: string, dataset?: string): DemoTaskCenterFile {
  return {
    id: `${prefix}-f${idx}`,
    name,
    bytes,
    download_url: '#demo-file',
    city,
    dataset,
  };
}

export function buildDemoTaskCenterRecords(): DemoTaskCenterRecord[] {
  const now = Date.now();
  const minsAgo = (m: number) => new Date(now - m * 60_000).toISOString();

  return [
    // 1–6: 进行中（running / queued / waiting_login / waiting_manual / cancelling）
    {
      id: 'TC-20261121-001',
      kind: 'download',
      title: '风神 · 上海/深圳/广州 10月配送费与违规扣款',
      status: 'running',
      created_at: minsAgo(6),
      started_at: minsAgo(5),
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '深圳', '广州'],
      datasets: ['delivery_fee', 'penalty', 'attendance_detail'],
      total_items: 9,
      completed_items: 6,
      failed_items: 0,
      files: [
        makeFile('tc01', 1, '上海_202610_配送费明细.xlsx', 1_840_200, '上海', 'delivery_fee'),
        makeFile('tc01', 2, '深圳_202610_配送费明细.xlsx', 1_520_400, '深圳', 'delivery_fee'),
      ],
      has_zip: false,
      can_retry: false,
      can_cancel: true,
      demo: true,
    },
    {
      id: 'TC-20261121-002',
      kind: 'download',
      title: '灯塔 · 北京/天津 11月日维度骑手分析与订单明细',
      status: 'running',
      created_at: minsAgo(11),
      started_at: minsAgo(10),
      start: '2026-11-01',
      end: '2026-11-20',
      cities: ['北京', '天津'],
      datasets: ['rider_daily', 'detail_orders'],
      total_items: 4,
      completed_items: 2,
      failed_items: 0,
      files: [makeFile('tc02', 1, '北京_202611_日维度骑手分析.xlsx', 2_310_800, '北京', 'rider_daily')],
      has_zip: false,
      can_retry: false,
      can_cancel: true,
      demo: true,
    },
    {
      id: 'TC-20261121-003',
      kind: 'download',
      title: '风神 · 宁波/泉州 11月骑手出勤与运单数据',
      status: 'queued',
      created_at: minsAgo(4),
      start: '2026-11-01',
      end: '2026-11-20',
      cities: ['宁波', '泉州'],
      datasets: ['attendance_detail', 'delivery_waybill'],
      total_items: 4,
      completed_items: 0,
      failed_items: 0,
      files: [],
      has_zip: false,
      can_retry: false,
      can_cancel: true,
      demo: true,
    },
    {
      id: 'TC-20261121-004',
      kind: 'download',
      title: '商翼 · 员工资料（全量）同步任务',
      status: 'waiting_login',
      created_at: minsAgo(18),
      started_at: minsAgo(17),
      start: '2026-11-21',
      end: '2026-11-21',
      cities: ['全量'],
      datasets: ['baize_employees'],
      total_items: 1,
      completed_items: 0,
      failed_items: 0,
      files: [],
      has_zip: false,
      can_retry: false,
      can_cancel: true,
      error: '商翼登录态已过期，请点击右上角「平台授权」重新登录后自动恢复。',
      demo: true,
    },
    {
      id: 'TC-20261121-005',
      kind: 'download',
      title: '灯塔 · 广州/东莞 配送客诉与评价明细',
      status: 'waiting_manual',
      created_at: minsAgo(25),
      started_at: minsAgo(24),
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['广州', '东莞'],
      datasets: ['detail_kesu', 'detail_reviews'],
      total_items: 4,
      completed_items: 1,
      failed_items: 0,
      files: [makeFile('tc05', 1, '广州_202610_配送客诉明细.xlsx', 842_000, '广州', 'detail_kesu')],
      has_zip: false,
      can_retry: false,
      can_cancel: true,
      error: '灯塔触发安全滑块验证，请完成人工验证后继续导出。',
      demo: true,
    },
    {
      id: 'TC-20261121-006',
      kind: 'generate',
      title: '业务报表 · 异常跟进（大连/保定）',
      status: 'cancelling',
      created_at: minsAgo(14),
      started_at: minsAgo(13),
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['大连', '保定'],
      datasets: ['abnormal_followup'],
      total_items: 2,
      completed_items: 1,
      failed_items: 0,
      files: [],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },

    // 7–13: 待处理异常态（partial / error / interrupted / empty）
    {
      id: 'TC-20261121-007',
      kind: 'download',
      title: '风神 · 华东 4 城 10月问题单与欺诈单',
      status: 'partial',
      created_at: minsAgo(48),
      started_at: minsAgo(47),
      finished_at: minsAgo(41),
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '宁波', '台州', '泉州'],
      datasets: ['problem', 'fraud'],
      total_items: 8,
      completed_items: 6,
      failed_items: 2,
      files: [
        makeFile('tc07', 1, '上海_202610_问题单汇总.xlsx', 1_120_500, '上海', 'problem'),
        makeFile('tc07', 2, '宁波_202610_问题单汇总.xlsx', 780_200, '宁波', 'problem'),
        makeFile('tc07', 3, '台州_202610_欺诈单.xlsx', 312_000, '台州', 'fraud'),
      ],
      has_zip: true,
      can_retry: true,
      can_cancel: false,
      error: '泉州问题单、上海欺诈单拉取超时，其余 6 项已成功保存，可一键重试失败项。',
      demo: true,
    },
    {
      id: 'TC-20261121-008',
      kind: 'generate',
      title: '业务报表 · 支付绑定核对表（深圳/东莞）',
      status: 'partial',
      created_at: minsAgo(75),
      started_at: minsAgo(74),
      finished_at: minsAgo(69),
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['深圳', '东莞'],
      datasets: ['payment_binding'],
      total_items: 2,
      completed_items: 1,
      failed_items: 1,
      files: [makeFile('tc08', 1, '深圳_202610_支付绑定.xlsx', 945_600, '深圳', 'payment_binding')],
      source_files: [
        makeFile('tc08s', 1, '深圳_骑手风神绑定原始表.xlsx', 612_000, '深圳', 'receive_account'),
      ],
      has_zip: false,
      can_retry: true,
      can_cancel: false,
      error: '东莞站蓝橙骑手档案缺失，生成失败。',
      demo: true,
    },
    {
      id: 'TC-20261121-009',
      kind: 'download',
      title: '本来人力 · 灵工档案全量拉取',
      status: 'error',
      created_at: minsAgo(110),
      started_at: minsAgo(109),
      finished_at: minsAgo(108),
      start: '2026-11-21',
      end: '2026-11-21',
      cities: ['全量'],
      datasets: ['benlai_employees'],
      total_items: 1,
      completed_items: 0,
      failed_items: 1,
      files: [],
      has_zip: false,
      can_retry: true,
      can_cancel: false,
      error: '本来人力导出接口返回 503 服务繁忙，请稍后点击重试。',
      demo: true,
    },
    {
      id: 'TC-20261121-010',
      kind: 'download',
      title: '风神 · 三亚/韶关 10月月度 UB 账单',
      status: 'error',
      created_at: minsAgo(145),
      started_at: minsAgo(144),
      finished_at: minsAgo(142),
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['三亚', '韶关'],
      datasets: ['rider_monthly'],
      total_items: 2,
      completed_items: 0,
      failed_items: 2,
      files: [],
      has_zip: false,
      can_retry: true,
      can_cancel: false,
      error: '当前风神账号缺少三亚、韶关月度 UB 账单导出权限。',
      demo: true,
    },
    {
      id: 'TC-20261120-011',
      kind: 'download',
      title: '灯塔 · 上海/深圳 10月骑手订单明细',
      status: 'interrupted',
      created_at: '2026-11-20T19:40:00+08:00',
      started_at: '2026-11-20T19:40:12+08:00',
      finished_at: '2026-11-20T19:46:05+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '深圳'],
      datasets: ['rider_order_detail'],
      total_items: 2,
      completed_items: 1,
      failed_items: 1,
      files: [makeFile('tc11', 1, '上海_202610_骑手订单明细.xlsx', 4_820_100, '上海', 'rider_order_detail')],
      has_zip: false,
      can_retry: true,
      can_cancel: false,
      error: '任务执行期间工作进程重启导致中断，可重试未完成项。',
      demo: true,
    },
    {
      id: 'TC-20261120-012',
      kind: 'download',
      title: '风神 · 潮州 11月欺诈单巡检',
      status: 'empty',
      created_at: '2026-11-20T18:15:00+08:00',
      started_at: '2026-11-20T18:15:08+08:00',
      finished_at: '2026-11-20T18:15:46+08:00',
      start: '2026-11-01',
      end: '2026-11-20',
      cities: ['潮州'],
      datasets: ['fraud'],
      total_items: 1,
      completed_items: 1,
      failed_items: 0,
      files: [],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      error: '所选日期区间内平台返回 0 条记录，未生成空文件。',
      demo: true,
    },
    {
      id: 'TC-20261120-013',
      kind: 'download',
      title: '风神 · 北京 10月邀请记录全量',
      status: 'cancelled',
      created_at: '2026-11-20T17:20:00+08:00',
      started_at: '2026-11-20T17:20:05+08:00',
      finished_at: '2026-11-20T17:21:14+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['北京'],
      datasets: ['invitation_records'],
      total_items: 1,
      completed_items: 0,
      failed_items: 0,
      files: [],
      has_zip: false,
      can_retry: true,
      can_cancel: false,
      demo: true,
    },

    // 14–30: 已完成（success，覆盖全部 4 种类型与 5 大平台 + 多文件/来源文件/审批单跳转）
    {
      id: 'TC-20261120-014',
      kind: 'download',
      title: '风神 · 上海/深圳/北京/广州 10月配送费与违规扣款',
      status: 'success',
      created_at: '2026-11-20T16:50:00+08:00',
      started_at: '2026-11-20T16:50:06+08:00',
      finished_at: '2026-11-20T16:56:18+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '深圳', '北京', '广州'],
      datasets: ['delivery_fee', 'penalty'],
      total_items: 8,
      completed_items: 8,
      failed_items: 0,
      files: [
        makeFile('tc14', 1, '上海_202610_配送费.xlsx', 2_140_500, '上海', 'delivery_fee'),
        makeFile('tc14', 2, '上海_202610_违规扣款.xlsx', 684_000, '上海', 'penalty'),
        makeFile('tc14', 3, '深圳_202610_配送费.xlsx', 1_785_200, '深圳', 'delivery_fee'),
        makeFile('tc14', 4, '北京_202610_配送费.xlsx', 1_620_400, '北京', 'delivery_fee'),
        makeFile('tc14', 5, '广州_202610_配送费.xlsx', 1_412_900, '广州', 'delivery_fee'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-015',
      kind: 'approval',
      title: '蓝橙价格审批 · 上海/深圳 10月薪资单价批量审批',
      price_id: 'AP-BATCH-20261120-01',
      price_view: 'approval',
      status: 'success',
      created_at: '2026-11-20T16:12:00+08:00',
      started_at: '2026-11-20T16:12:02+08:00',
      finished_at: '2026-11-20T16:13:20+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '深圳'],
      datasets: ['lanorange_summary'],
      total_items: 12,
      completed_items: 12,
      failed_items: 0,
      files: [makeFile('tc15', 1, '价格审批回执_20261120_12单.xlsx', 248_600, '上海')],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-016',
      kind: 'download',
      title: '蓝橙 · 广州/东莞/宁波 10月价格档案汇总',
      status: 'success',
      created_at: '2026-11-20T15:40:00+08:00',
      started_at: '2026-11-20T15:40:04+08:00',
      finished_at: '2026-11-20T15:42:10+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['广州', '东莞', '宁波'],
      datasets: ['lanorange_summary'],
      total_items: 6,
      completed_items: 6,
      failed_items: 0,
      files: [
        makeFile('tc16', 1, '广州_202610_价格档案.xlsx', 512_400, '广州', 'lanorange_summary'),
        makeFile('tc16', 2, '东莞_202610_价格档案.xlsx', 418_200, '东莞', 'lanorange_summary'),
        makeFile('tc16', 3, '宁波_202610_价格档案.xlsx', 389_000, '宁波', 'lanorange_summary'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-017',
      kind: 'generate',
      title: '业务报表 · 异常名单（全授权城市）',
      status: 'success',
      created_at: '2026-11-20T14:55:00+08:00',
      started_at: '2026-11-20T14:55:09+08:00',
      finished_at: '2026-11-20T14:59:42+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['全部城市'],
      datasets: ['abnormal_riders'],
      total_items: 1,
      completed_items: 1,
      failed_items: 0,
      files: [makeFile('tc17', 1, '全城市_202610_异常名单汇总.xlsx', 1_450_000, '全部城市', 'abnormal_riders')],
      source_files: [
        makeFile('tc17s', 1, '风神_全城市骑手信息快照.xlsx', 3_120_000, '全部城市', 'rider_info'),
        makeFile('tc17s', 2, '蓝橙_人事资料汇总.xlsx', 1_890_000, '全部城市', 'lanorange_summary'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-018',
      kind: 'download',
      title: '蓝橙 · 全量资料汇总（10月价格档案 + 人事表）',
      status: 'success',
      created_at: '2026-11-20T14:10:00+08:00',
      started_at: '2026-11-20T14:10:05+08:00',
      finished_at: '2026-11-20T14:13:27+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['全部城市'],
      datasets: ['lanorange_summary'],
      total_items: 3,
      completed_items: 3,
      failed_items: 0,
      files: [
        makeFile('tc18', 1, '蓝橙_202610_价格档案汇总.xlsx', 2_680_400, '全部城市', 'lanorange_summary'),
        makeFile('tc18', 2, '蓝橙_在离职骑手人事档案.xlsx', 1_940_000, '全部城市', 'lanorange_summary'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-019',
      kind: 'download',
      title: '商翼 · 员工资料（全量）备份',
      status: 'success',
      created_at: '2026-11-20T11:30:00+08:00',
      started_at: '2026-11-20T11:30:04+08:00',
      finished_at: '2026-11-20T11:31:15+08:00',
      start: '2026-11-20',
      end: '2026-11-20',
      cities: ['全量'],
      datasets: ['baize_employees'],
      total_items: 1,
      completed_items: 1,
      failed_items: 0,
      files: [makeFile('tc19', 1, '商翼_员工资料全量_20261120.xlsx', 1_238_400, '全量', 'baize_employees')],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-020',
      kind: 'download',
      title: '本来人力 · 灵工档案（全量）备份',
      status: 'success',
      created_at: '2026-11-20T11:25:00+08:00',
      started_at: '2026-11-20T11:25:03+08:00',
      finished_at: '2026-11-20T11:26:09+08:00',
      start: '2026-11-20',
      end: '2026-11-20',
      cities: ['全量'],
      datasets: ['benlai_employees'],
      total_items: 1,
      completed_items: 1,
      failed_items: 0,
      files: [makeFile('tc20', 1, '本来人力_灵工资料全量_20261120.xlsx', 986_200, '全量', 'benlai_employees')],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261120-021',
      kind: 'download',
      title: '灯塔 · 小象超市 10月出勤合并与骑手档案',
      status: 'success',
      created_at: '2026-11-20T10:45:00+08:00',
      started_at: '2026-11-20T10:45:07+08:00',
      finished_at: '2026-11-20T10:48:33+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['北京', '广州', '天津'],
      datasets: ['xiaoxiang_attendance_detail', 'rider_archive'],
      total_items: 6,
      completed_items: 6,
      failed_items: 0,
      files: [
        makeFile('tc21', 1, '灯塔_202610_骑手出勤明细合并.xlsx', 2_015_000, '北京', 'xiaoxiang_attendance_detail'),
        makeFile('tc21', 2, '灯塔_骑手档案快照.xlsx', 842_600, '广州', 'rider_archive'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261119-022',
      kind: 'download',
      title: '风神 · 全城市骑手信息一键快照',
      status: 'success',
      created_at: '2026-11-19T18:05:00+08:00',
      started_at: '2026-11-19T18:05:04+08:00',
      finished_at: '2026-11-19T18:08:51+08:00',
      start: '2026-11-19',
      end: '2026-11-19',
      cities: ['上海', '深圳', '广州', '北京', '天津', '宁波', '泉州', '大连'],
      datasets: ['rider_info'],
      total_items: 8,
      completed_items: 8,
      failed_items: 0,
      files: [
        makeFile('tc22', 1, '上海_骑手信息导出_20261119.xlsx', 912_300, '上海', 'rider_info'),
        makeFile('tc22', 2, '深圳_骑手信息导出_20261119.xlsx', 764_100, '深圳', 'rider_info'),
        makeFile('tc22', 3, '广州_骑手信息导出_20261119.xlsx', 698_000, '广州', 'rider_info'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261119-023',
      kind: 'generate',
      title: '业务报表 · 支付绑定（上海/宁波/泉州）',
      status: 'success',
      created_at: '2026-11-19T16:40:00+08:00',
      started_at: '2026-11-19T16:40:08+08:00',
      finished_at: '2026-11-19T16:43:19+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '宁波', '泉州'],
      datasets: ['payment_binding'],
      total_items: 3,
      completed_items: 3,
      failed_items: 0,
      files: [
        makeFile('tc23', 1, '上海_202610_支付绑定.xlsx', 1_128_000, '上海', 'payment_binding'),
        makeFile('tc23', 2, '宁波_202610_支付绑定.xlsx', 642_000, '宁波', 'payment_binding'),
        makeFile('tc23', 3, '泉州_202610_支付绑定.xlsx', 524_000, '泉州', 'payment_binding'),
      ],
      source_files: [makeFile('tc23s', 1, '风神_骑手风神绑定_10月.xlsx', 980_000, '上海', 'receive_account')],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261119-024',
      kind: 'approval',
      title: '价格审批 · 华北片区 10月薪资审批',
      price_id: 'AP-BATCH-20261119-04',
      price_view: 'approval',
      status: 'success',
      created_at: '2026-11-19T15:20:00+08:00',
      started_at: '2026-11-19T15:20:03+08:00',
      finished_at: '2026-11-19T15:21:08+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['北京', '天津', '保定', '大连'],
      datasets: ['lanorange_summary'],
      total_items: 8,
      completed_items: 8,
      failed_items: 0,
      files: [makeFile('tc24', 1, '价格审批回执_华北8单.xlsx', 196_500, '北京')],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261119-025',
      kind: 'approval',
      title: '价格审批 · 上海/北京 11月上半月单价审批',
      price_id: 'AP-BATCH-20261119-05',
      price_view: 'approval',
      status: 'success',
      created_at: '2026-11-19T14:05:00+08:00',
      started_at: '2026-11-19T14:05:02+08:00',
      finished_at: '2026-11-19T14:06:18+08:00',
      start: '2026-11-01',
      end: '2026-11-15',
      cities: ['上海', '北京'],
      datasets: ['lanorange_summary'],
      total_items: 4,
      completed_items: 4,
      failed_items: 0,
      files: [makeFile('tc25', 1, '价格审批回执_上海北京4单.xlsx', 228_900, '上海')],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261118-026',
      kind: 'download',
      title: '风神 · 东莞/惠州/汕头 物资租用登记快照',
      status: 'success',
      created_at: '2026-11-18T17:30:00+08:00',
      started_at: '2026-11-18T17:30:04+08:00',
      finished_at: '2026-11-18T17:31:52+08:00',
      start: '2026-11-18',
      end: '2026-11-18',
      cities: ['东莞', '惠州', '汕头'],
      datasets: ['goods_rent'],
      total_items: 3,
      completed_items: 3,
      failed_items: 0,
      files: [
        makeFile('tc26', 1, '东莞_物资租用登记_20261118.xlsx', 412_000, '东莞', 'goods_rent'),
        makeFile('tc26', 2, '惠州_物资租用登记_20261118.xlsx', 318_500, '惠州', 'goods_rent'),
        makeFile('tc26', 3, '汕头_物资租用登记_20261118.xlsx', 265_800, '汕头', 'goods_rent'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261118-027',
      kind: 'download',
      title: '风神 · 深圳 10月骑手数据明细（按日聚合）',
      status: 'success',
      created_at: '2026-11-18T15:15:00+08:00',
      started_at: '2026-11-18T15:15:10+08:00',
      finished_at: '2026-11-18T15:21:44+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['深圳'],
      datasets: ['rider_detail'],
      total_items: 1,
      completed_items: 1,
      failed_items: 0,
      files: [makeFile('tc27', 1, '深圳_202610_骑手数据明细.xlsx', 3_420_000, '深圳', 'rider_detail')],
      has_zip: false,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261118-028',
      kind: 'generate',
      title: '业务报表 · 异常跟进（上海/广州）',
      status: 'success',
      created_at: '2026-11-18T11:45:00+08:00',
      started_at: '2026-11-18T11:45:06+08:00',
      finished_at: '2026-11-18T11:48:21+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['上海', '广州'],
      datasets: ['abnormal_followup'],
      total_items: 2,
      completed_items: 2,
      failed_items: 0,
      files: [
        makeFile('tc28', 1, '上海_202610_异常跟进.xlsx', 540_200, '上海', 'abnormal_followup'),
        makeFile('tc28', 2, '广州_202610_异常跟进.xlsx', 462_800, '广州', 'abnormal_followup'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261117-029',
      kind: 'download',
      title: '风神 · 天津/大连 10月骑手风神绑定',
      status: 'success',
      created_at: '2026-11-17T16:20:00+08:00',
      started_at: '2026-11-17T16:20:05+08:00',
      finished_at: '2026-11-17T16:22:18+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['天津', '大连'],
      datasets: ['receive_account'],
      total_items: 2,
      completed_items: 2,
      failed_items: 0,
      files: [
        makeFile('tc29', 1, '天津_202610_骑手风神绑定.xlsx', 385_400, '天津', 'receive_account'),
        makeFile('tc29', 2, '大连_202610_骑手风神绑定.xlsx', 412_100, '大连', 'receive_account'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
    {
      id: 'TC-20261117-030',
      kind: 'download',
      title: '风神 · 宁波/台州 10月配送运单数据（全城送）',
      status: 'success',
      created_at: '2026-11-17T10:15:00+08:00',
      started_at: '2026-11-17T10:15:08+08:00',
      finished_at: '2026-11-17T10:21:04+08:00',
      start: '2026-10-01',
      end: '2026-10-31',
      cities: ['宁波', '台州'],
      datasets: ['delivery_waybill'],
      total_items: 2,
      completed_items: 2,
      failed_items: 0,
      files: [
        makeFile('tc30', 1, '宁波_202610_全城送运单.xlsx', 5_120_600, '宁波', 'delivery_waybill'),
        makeFile('tc30', 2, '台州_202610_全城送运单.xlsx', 3_245_000, '台州', 'delivery_waybill'),
      ],
      has_zip: true,
      can_retry: false,
      can_cancel: false,
      demo: true,
    },
  ];
}

export function queryDemoTaskCenter(
  allRecords: DemoTaskCenterRecord[],
  params: {
    q?: string;
    status?: string;
    system?: string;
    kind?: string;
    from?: string;
    to?: string;
    archivedIds?: Set<string>;
    archivedOnly?: boolean;
    page?: number;
    pageSize?: number;
  },
) {
  const { items, counts } = filterTaskCenterRecords(allRecords, {
    q: params.q,
    status: params.status === 'all' ? '' : params.status,
    system: params.system,
    kind: params.kind,
    from: params.from,
    to: params.to,
    archivedIds: params.archivedIds,
    archivedOnly: params.archivedOnly,
  });
  const pageSize = Math.max(1, params.pageSize || 20);
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(1, params.page || 1), totalPages);
  const startIdx = (safePage - 1) * pageSize;
  const paged = items.slice(startIdx, startIdx + pageSize);
  return {
    items: paged,
    total,
    counts: {
      ...counts,
      archived: (params.archivedIds || new Set()).size,
    },
  };
}

/* ═══════════════════════════════════════════════════════════════════════════
 * 3. 扣款规则（StationDeductionManager）— 30 个站点全场景示例数据（10 城 × 3 站）
 * 覆盖所有城市状态：100%已配 / 部分待配 / 未配城市默认
 * 覆盖所有站点状态：沿用城市默认 / 站点独立例外 / 确认零扣款 / 旧配置待核对 / 待配置
 * 同时支持风神（15 字段 + 问题单关键词）与小象超市（3 字段）
 * ═══════════════════════════════════════════════════════════════════════════ */

type StationScenario = 'inherited' | 'override' | 'zero' | 'pending' | 'legacy';

interface DemoCityBlueprint {
  cityId: string;
  cityName: string;
  cityConfigured: boolean;
  cityRow: Record<string, number | null>;
  xiaoxiangRow: Record<string, number | null>;
  cityProblemRules: ProblemRuleItem[];
  stations: Array<{
    id: string;
    name: string;
    scenario: StationScenario;
    overrideDelta?: Record<string, number | null>;
    xiaoxiangOverride?: Record<string, number | null>;
    problemRules?: ProblemRuleItem[];
  }>;
}

const DEMO_DEDUCTION_BLUEPRINTS: DemoCityBlueprint[] = [
  {
    cityId: '310100',
    cityName: '上海',
    cityConfigured: true,
    cityRow: { 投诉: 50, 差评: 20, 违规虚假: 100, 物流责: 30, 不准时单: 3, 超时: 2, T10: 5, 工具费: 120, 代领费率: 0.06, 安全基金: 6, 安全基金_maxDays: 26, 使用费: 4, 使用费_maxDays: 26, 非蜂卡: 2, 月费: 60 },
    xiaoxiangRow: { 保险费: 8, 循环物资使用费: 4, 附加险: 45 },
    cityProblemRules: [
      { problem_type: '餐损责任', reason_keyword: '严重洒漏', amount: 35 },
      { problem_type: '虚假送达', reason_keyword: '未联系客户', amount: 100 },
    ],
    stations: [
      { id: 'SH-1001', name: '徐家汇中心站', scenario: 'inherited' },
      { id: 'SH-1002', name: '陆家嘴金融站', scenario: 'override', overrideDelta: { 投诉: 60, 差评: 25, 安全基金: 8 }, xiaoxiangOverride: { 保险费: 10 }, problemRules: [{ problem_type: '态度投诉', reason_keyword: '顶撞客户', amount: 80 }] },
      { id: 'SH-1003', name: '张江高科站', scenario: 'inherited' },
    ],
  },
  {
    cityId: '440300',
    cityName: '深圳',
    cityConfigured: true,
    cityRow: { 投诉: 50, 差评: 15, 违规虚假: 80, 物流责: 25, 不准时单: 3, 超时: 2, T10: 4, 工具费: 100, 代领费率: 0.05, 安全基金: 5, 安全基金_maxDays: 25, 使用费: 3, 使用费_maxDays: 25, 非蜂卡: 2, 月费: 50 },
    xiaoxiangRow: { 保险费: 7, 循环物资使用费: 3.5, 附加险: 40 },
    cityProblemRules: [
      { problem_type: '提前点送达', reason_keyword: '超距签收', amount: 50 },
      { problem_type: '配送超时', reason_keyword: '恶意滞留', amount: 30 },
    ],
    stations: [
      { id: 'SZ-2001', name: '南山科技园站', scenario: 'override', overrideDelta: { 违规虚假: 120, T10: 6 }, xiaoxiangOverride: { 附加险: 50 }, problemRules: [{ problem_type: '货损赔付', reason_keyword: '生鲜变质', amount: 60 }] },
      { id: 'SZ-2002', name: '福田车公庙站', scenario: 'inherited' },
      { id: 'SZ-2003', name: '宝安西乡站', scenario: 'zero' },
    ],
  },
  {
    cityId: '440100',
    cityName: '广州',
    cityConfigured: true,
    cityRow: { 投诉: 40, 差评: 15, 违规虚假: 80, 物流责: 20, 不准时单: 2, 超时: 2, T10: 3, 工具费: 90, 代领费率: 0.05, 安全基金: 5, 安全基金_maxDays: 26, 使用费: 3, 使用费_maxDays: 26, 非蜂卡: 1.5, 月费: 45 },
    xiaoxiangRow: { 保险费: 7, 循环物资使用费: 3, 附加险: 38 },
    cityProblemRules: [
      { problem_type: '未穿工服装备', reason_keyword: '未带餐箱', amount: 20 },
    ],
    stations: [
      { id: 'GZ-3001', name: '天河体育西站', scenario: 'inherited' },
      { id: 'GZ-3002', name: '海珠客村站', scenario: 'override', overrideDelta: { 投诉: 50, 工具费: 110 }, xiaoxiangOverride: { 循环物资使用费: 4 } },
      { id: 'GZ-3003', name: '白云嘉禾站', scenario: 'pending' },
    ],
  },
  {
    cityId: '110100',
    cityName: '北京',
    cityConfigured: true,
    cityRow: { 投诉: 60, 差评: 20, 违规虚假: 100, 物流责: 30, 不准时单: 3, 超时: 3, T10: 5, 工具费: 120, 代领费率: 0.06, 安全基金: 6, 安全基金_maxDays: 28, 使用费: 4, 使用费_maxDays: 28, 非蜂卡: 2, 月费: 60 },
    xiaoxiangRow: { 保险费: 8, 循环物资使用费: 4, 附加险: 50 },
    cityProblemRules: [
      { problem_type: '虚假送达', reason_keyword: '拍照模糊', amount: 80 },
      { problem_type: '餐损责任', reason_keyword: '包装破损', amount: 25 },
    ],
    stations: [
      { id: 'BJ-4001', name: '朝阳望京站', scenario: 'inherited' },
      { id: 'BJ-4002', name: '海淀中关村站', scenario: 'override', overrideDelta: { 差评: 30, 安全基金_maxDays: 24 }, problemRules: [{ problem_type: '提前点送达', reason_keyword: '未送达前台', amount: 40 }] },
      { id: 'BJ-4003', name: '通州万达站', scenario: 'pending' },
    ],
  },
  {
    cityId: '120100',
    cityName: '天津',
    cityConfigured: true,
    cityRow: { 投诉: 35, 差评: 15, 违规虚假: 60, 物流责: 20, 不准时单: 2, 超时: 1.5, T10: 3, 工具费: 80, 代领费率: 0.04, 安全基金: 4, 安全基金_maxDays: 25, 使用费: 3, 使用费_maxDays: 25, 非蜂卡: 1, 月费: 40 },
    xiaoxiangRow: { 保险费: 6, 循环物资使用费: 3, 附加险: 35 },
    cityProblemRules: [
      { problem_type: '配送超时', reason_keyword: '无故拒单', amount: 25 },
    ],
    stations: [
      { id: 'TJ-5001', name: '和平滨江道站', scenario: 'inherited' },
      { id: 'TJ-5002', name: '南开大悦城站', scenario: 'inherited' },
      { id: 'TJ-5003', name: '滨海泰达站', scenario: 'zero' },
    ],
  },
  {
    cityId: '441900',
    cityName: '东莞',
    cityConfigured: true,
    cityRow: { 投诉: 40, 差评: 10, 违规虚假: 70, 物流责: 20, 不准时单: 2, 超时: 2, T10: 3, 工具费: 85, 代领费率: 0.05, 安全基金: 5, 安全基金_maxDays: 26, 使用费: 3, 使用费_maxDays: 26, 非蜂卡: 1, 月费: 40 },
    xiaoxiangRow: { 保险费: 6.5, 循环物资使用费: 3, 附加险: 35 },
    cityProblemRules: [],
    stations: [
      { id: 'DG-6001', name: '南城鸿福站', scenario: 'inherited' },
      { id: 'DG-6002', name: '松山湖园区站', scenario: 'override', overrideDelta: { 工具费: 60, 月费: 30 }, xiaoxiangOverride: { 保险费: 6 } },
      { id: 'DG-6003', name: '虎门万达站', scenario: 'legacy' },
    ],
  },
  {
    cityId: '330200',
    cityName: '宁波',
    cityConfigured: true,
    cityRow: { 投诉: 45, 差评: 15, 违规虚假: 80, 物流责: 25, 不准时单: 2.5, 超时: 2, T10: 4, 工具费: 100, 代领费率: 0.05, 安全基金: 5, 安全基金_maxDays: 26, 使用费: 3.5, 使用费_maxDays: 26, 非蜂卡: 1.5, 月费: 50 },
    xiaoxiangRow: { 保险费: 7, 循环物资使用费: 3.5, 附加险: 40 },
    cityProblemRules: [
      { problem_type: '货损赔付', reason_keyword: '饮品倾倒', amount: 20 },
    ],
    stations: [
      { id: 'NB-7001', name: '海曙天一站', scenario: 'inherited' },
      { id: 'NB-7002', name: '鄞州南部站', scenario: 'pending' },
      { id: 'NB-7003', name: '北仑保税站', scenario: 'pending' },
    ],
  },
  {
    cityId: '350500',
    cityName: '泉州',
    cityConfigured: true,
    cityRow: { 投诉: 35, 差评: 10, 违规虚假: 60, 物流责: 20, 不准时单: 2, 超时: 1.5, T10: 3, 工具费: 80, 代领费率: 0.04, 安全基金: 4, 安全基金_maxDays: 25, 使用费: 2.5, 使用费_maxDays: 25, 非蜂卡: 1, 月费: 35 },
    xiaoxiangRow: { 保险费: 6, 循环物资使用费: 2.5, 附加险: 30 },
    cityProblemRules: [
      { problem_type: '态度投诉', reason_keyword: '拒送上楼', amount: 30 },
    ],
    stations: [
      { id: 'QZ-8001', name: '丰泽万达站', scenario: 'inherited' },
      { id: 'QZ-8002', name: '晋江阳光站', scenario: 'override', overrideDelta: { 投诉: 45, 物流责: 25 } },
      { id: 'QZ-8003', name: '石狮服装城站', scenario: 'legacy' },
    ],
  },
  {
    cityId: '210200',
    cityName: '大连',
    cityConfigured: false,
    cityRow: { 投诉: null, 差评: null, 违规虚假: null, 物流责: null, 不准时单: null, 超时: null, T10: null, 工具费: null, 代领费率: null, 安全基金: null, 安全基金_maxDays: null, 使用费: null, 使用费_maxDays: null, 非蜂卡: null, 月费: null },
    xiaoxiangRow: { 保险费: null, 循环物资使用费: null, 附加险: null },
    cityProblemRules: [],
    stations: [
      { id: 'DL-9001', name: '中山青泥洼站', scenario: 'override', overrideDelta: { 投诉: 40, 差评: 15, 违规虚假: 70, 物流责: 20, 不准时单: 2, 超时: 2, T10: 3, 工具费: 90, 代领费率: 0.05, 安全基金: 5, 安全基金_maxDays: 25, 使用费: 3, 使用费_maxDays: 25, 非蜂卡: 1, 月费: 40 }, xiaoxiangOverride: { 保险费: 6.5, 循环物资使用费: 3, 附加险: 35 } },
      { id: 'DL-9002', name: '甘井子华南站', scenario: 'pending' },
      { id: 'DL-9003', name: '高新万达站', scenario: 'pending' },
    ],
  },
  {
    cityId: '130600',
    cityName: '保定',
    cityConfigured: false,
    cityRow: { 投诉: null, 差评: null, 违规虚假: null, 物流责: null, 不准时单: null, 超时: null, T10: null, 工具费: null, 代领费率: null, 安全基金: null, 安全基金_maxDays: null, 使用费: null, 使用费_maxDays: null, 非蜂卡: null, 月费: null },
    xiaoxiangRow: { 保险费: null, 循环物资使用费: null, 附加险: null },
    cityProblemRules: [
      { problem_type: '餐损责任', reason_keyword: '汤品洒漏', amount: 30 },
    ],
    stations: [
      { id: 'BD-9501', name: '莲池万博站', scenario: 'zero' },
      { id: 'BD-9502', name: '竞秀朝阳站', scenario: 'pending' },
      { id: 'BD-9503', name: '高开电谷站', scenario: 'legacy' },
    ],
  },
];

export function buildDemoDeductionData(platform: 'fengshen' | 'xiaoxiang') {
  const columns =
    platform === 'xiaoxiang'
      ? ['保险费', '循环物资使用费', '附加险']
      : [...CONFIG_RULE_COLUMNS_WITH_THRESHOLDS];

  const makeEmptyRow = () =>
    Object.fromEntries(columns.map(col => [col, null as number | null]));
  const makeZeroRow = () =>
    Object.fromEntries(columns.map(col => [col, col.endsWith('_maxDays') ? null : 0]));

  const cities: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }> = [];
  const entries: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }> = [];
  const directoryCities: Array<{ id: string; name: string; station_count: number }> = [];

  for (const bp of DEMO_DEDUCTION_BLUEPRINTS) {
    directoryCities.push({
      id: bp.cityId,
      name: bp.cityName,
      station_count: bp.stations.length,
    });

    const baseRow = platform === 'xiaoxiang' ? { ...bp.xiaoxiangRow } : { ...bp.cityRow };
    cities.push({
      key: `${platform}:${bp.cityId}:*`,
      station: {
        id: '*',
        name: '城市统一扣款',
        city: bp.cityName,
        city_id: bp.cityId,
      },
      row: baseRow,
      configured: bp.cityConfigured,
      zero_confirmed: false,
      edited: false,
      problem_rules: platform === 'fengshen' ? [...bp.cityProblemRules] : [],
    });

    for (const st of bp.stations) {
      let row: Record<string, number | null>;
      let configured = false;
      let zero_confirmed = false;
      let inherited_city = false;
      let station_override = false;
      let legacy = false;

      if (st.scenario === 'inherited') {
        row = { ...baseRow };
        configured = true;
        inherited_city = true;
      } else if (st.scenario === 'override') {
        const delta = platform === 'xiaoxiang' ? st.xiaoxiangOverride : st.overrideDelta;
        row = { ...baseRow, ...(delta || {}) };
        // Ensure override stations have numeric values even if city default is blank
        for (const col of columns) {
          if (!col.endsWith('_maxDays') && (row[col] === null || row[col] === undefined)) {
            row[col] = 0;
          }
        }
        configured = true;
        station_override = true;
      } else if (st.scenario === 'zero') {
        row = makeZeroRow();
        configured = true;
        zero_confirmed = true;
        station_override = true;
      } else if (st.scenario === 'legacy') {
        row = makeEmptyRow();
        row[columns[0]] = platform === 'xiaoxiang' ? 5 : 30;
        configured = false;
        legacy = true;
      } else {
        row = makeEmptyRow();
        configured = false;
      }

      entries.push({
        key: `${platform}:${bp.cityId}:${st.id}`,
        station: {
          id: st.id,
          name: st.name,
          city: bp.cityName,
          city_id: bp.cityId,
        },
        row,
        configured,
        zero_confirmed,
        legacy,
        edited: false,
        inherited_city,
        station_override,
        problem_rules: platform === 'fengshen' ? [...(st.problemRules || [])] : [],
      });
    }
  }

  return {
    profile: {
      platform,
      columns,
      entries,
      cities,
      version: `demo-${platform}-v1`,
    },
    columns,
    cities,
    entries,
    directoryCities,
  };
}

/* ═══════════════════════════════════════════════════════════════════════════
 * 4. 蓝橙批量审批（LanorangeApprovals）— 30 条待审批任务 + 3 批结果回执
 * 覆盖所有场景：可同意（多城市/多账期/多审批节点/多骑手规模）+ 6 种不可提交阻断原因
 * 回执覆盖全部 6 种结果状态：success / failed / uncertain / changed / not_sent / pending
 * ═══════════════════════════════════════════════════════════════════════════ */

export interface DemoApprovalTask {
  id: string;
  businessCode: string;
  cityName: string;
  siteName: string;
  period_start: string;
  period_end: string;
  settle_month: string;
  rider_count: number;
  nodeName: string;
  createByName: string;
  createTime: string;
  reason: string;
  demo?: boolean;
}

export function buildDemoLanorangeApprovals(): DemoApprovalTask[] {
  const rows: Array<Omit<DemoApprovalTask, 'demo'>> = [
    // 1–22: 可直接审批通过（覆盖 10 个城市、2026-10 / 2026-11 两账期、4 种节点）
    { id: 'LO-9001', businessCode: 'LC-202611-0001', cityName: '上海', siteName: '徐家汇中心站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 148, nodeName: '区域经理审批', createByName: '陈志远', createTime: '2026-11-21 09:12', reason: '' },
    { id: 'LO-9002', businessCode: 'LC-202611-0002', cityName: '上海', siteName: '陆家嘴金融站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 132, nodeName: '财务复核', createByName: '林佳宁', createTime: '2026-11-21 09:05', reason: '' },
    { id: 'LO-9003', businessCode: 'LC-202611-0003', cityName: '上海', siteName: '张江高科站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 96, nodeName: '运营主管审批', createByName: '陈志远', createTime: '2026-11-21 08:54', reason: '' },
    { id: 'LO-9004', businessCode: 'LC-202611-0004', cityName: '深圳', siteName: '南山科技园站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 174, nodeName: '城市负责人审核', createByName: '周明轩', createTime: '2026-11-21 08:48', reason: '' },
    { id: 'LO-9005', businessCode: 'LC-202611-0005', cityName: '深圳', siteName: '福田车公庙站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 118, nodeName: '区域经理审批', createByName: '周明轩', createTime: '2026-11-21 08:41', reason: '' },
    { id: 'LO-9006', businessCode: 'LC-202611-0006', cityName: '深圳', siteName: '宝安西乡站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 84, nodeName: '运营主管审批', createByName: '黄思琪', createTime: '2026-11-21 08:30', reason: '' },
    { id: 'LO-9007', businessCode: 'LC-202611-0007', cityName: '广州', siteName: '天河体育西站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 156, nodeName: '财务复核', createByName: '梁嘉豪', createTime: '2026-11-21 08:22', reason: '' },
    { id: 'LO-9008', businessCode: 'LC-202611-0008', cityName: '广州', siteName: '海珠客村站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 109, nodeName: '区域经理审批', createByName: '梁嘉豪', createTime: '2026-11-21 08:16', reason: '' },
    { id: 'LO-9009', businessCode: 'LC-202611-0009', cityName: '广州', siteName: '白云嘉禾站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 73, nodeName: '运营主管审批', createByName: '吴晓彤', createTime: '2026-11-20 19:50', reason: '' },
    { id: 'LO-9010', businessCode: 'LC-202611-0010', cityName: '北京', siteName: '朝阳望京站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 162, nodeName: '城市负责人审核', createByName: '张建国', createTime: '2026-11-20 19:32', reason: '' },
    { id: 'LO-9011', businessCode: 'LC-202611-0011', cityName: '北京', siteName: '海淀中关村站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 127, nodeName: '财务复核', createByName: '张建国', createTime: '2026-11-20 19:18', reason: '' },
    { id: 'LO-9012', businessCode: 'LC-202611-0012', cityName: '北京', siteName: '通州万达站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 68, nodeName: '运营主管审批', createByName: '赵雨晴', createTime: '2026-11-20 18:45', reason: '' },
    { id: 'LO-9013', businessCode: 'LC-202611-0013', cityName: '天津', siteName: '和平滨江道站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 91, nodeName: '区域经理审批', createByName: '孙浩然', createTime: '2026-11-20 18:20', reason: '' },
    { id: 'LO-9014', businessCode: 'LC-202611-0014', cityName: '天津', siteName: '南开大悦城站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 59, nodeName: '运营主管审批', createByName: '孙浩然', createTime: '2026-11-20 17:58', reason: '' },
    { id: 'LO-9015', businessCode: 'LC-202611-0015', cityName: '东莞', siteName: '南城鸿福站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 104, nodeName: '财务复核', createByName: '何俊杰', createTime: '2026-11-20 17:36', reason: '' },
    { id: 'LO-9016', businessCode: 'LC-202611-0016', cityName: '东莞', siteName: '松山湖园区站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 82, nodeName: '区域经理审批', createByName: '何俊杰', createTime: '2026-11-20 17:10', reason: '' },
    { id: 'LO-9017', businessCode: 'LC-202611-0017', cityName: '宁波', siteName: '海曙天一站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 115, nodeName: '城市负责人审核', createByName: '徐晨阳', createTime: '2026-11-20 16:44', reason: '' },
    { id: 'LO-9018', businessCode: 'LC-202611-0018', cityName: '宁波', siteName: '鄞州南部站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 77, nodeName: '运营主管审批', createByName: '徐晨阳', createTime: '2026-11-20 16:20', reason: '' },
    { id: 'LO-9019', businessCode: 'LC-202611-0019', cityName: '泉州', siteName: '丰泽万达站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 89, nodeName: '区域经理审批', createByName: '郑子墨', createTime: '2026-11-20 15:52', reason: '' },
    { id: 'LO-9020', businessCode: 'LC-202611-0020', cityName: '泉州', siteName: '晋江阳光站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 66, nodeName: '财务复核', createByName: '郑子墨', createTime: '2026-11-20 15:30', reason: '' },
    { id: 'LO-9021', businessCode: 'LC-202611-0021', cityName: '大连', siteName: '中山青泥洼站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 93, nodeName: '区域经理审批', createByName: '王博闻', createTime: '2026-11-20 14:55', reason: '' },
    { id: 'LO-9022', businessCode: 'LC-202611-0022', cityName: '保定', siteName: '莲池万博站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 58, nodeName: '运营主管审批', createByName: '高文静', createTime: '2026-11-20 14:22', reason: '' },

    // 23–30: 不可提交阻断（覆盖 6 种真实业务阻断场景）
    { id: 'LO-9023', businessCode: 'LC-202611-0023', cityName: '上海', siteName: '闵行莘庄站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 112, nodeName: '财务复核', createByName: '林佳宁', createTime: '2026-11-20 13:50', reason: '单价存在缺失日期（10-18、10-19），请先补齐' },
    { id: 'LO-9024', businessCode: 'LC-202611-0024', cityName: '深圳', siteName: '龙岗大运站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 95, nodeName: '风控总监复核', createByName: '黄思琪', createTime: '2026-11-20 13:15', reason: '非本人当前审批节点' },
    { id: 'LO-9025', businessCode: 'LC-202611-0025', cityName: '广州', siteName: '番禺万博站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 0, nodeName: '运营主管审批', createByName: '吴晓彤', createTime: '2026-11-20 12:40', reason: '骑手人数为 0，无法提交' },
    { id: 'LO-9026', businessCode: 'LC-202611-0026', cityName: '北京', siteName: '丰台科技园站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 84, nodeName: '区域经理审批', createByName: '赵雨晴', createTime: '2026-11-20 11:55', reason: '关联价格版本已变更，需重新同步' },
    { id: 'LO-9027', businessCode: 'LC-202611-0027', cityName: '宁波', siteName: '北仑保税站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 61, nodeName: '财务复核', createByName: '徐晨阳', createTime: '2026-11-20 11:18', reason: '已超过本账期审批截止时间' },
    { id: 'LO-9028', businessCode: 'LC-202611-0028', cityName: '东莞', siteName: '虎门万达站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 74, nodeName: '城市负责人审核', createByName: '何俊杰', createTime: '2026-11-20 10:42', reason: '存在 3 名异常高价骑手待人工复核' },
    { id: 'LO-9029', businessCode: 'LC-202611-0029', cityName: '大连', siteName: '甘井子华南站', period_start: '2026-10-01', period_end: '2026-10-31', settle_month: '2026-10', rider_count: 53, nodeName: '财务复核', createByName: '王博闻', createTime: '2026-11-20 10:05', reason: '单价存在缺失日期（10-31），请先补齐' },
    { id: 'LO-9030', businessCode: 'LC-202611-0030', cityName: '保定', siteName: '竞秀朝阳站', period_start: '2026-11-01', period_end: '2026-11-15', settle_month: '2026-11', rider_count: 47, nodeName: '风控总监复核', createByName: '高文静', createTime: '2026-11-20 09:30', reason: '非本人当前审批节点' },
  ];

  return rows.map(r => ({ ...r, demo: true }));
}

export function buildDemoApprovalPriceDetail(task: DemoApprovalTask) {
  const sampleRiders = ['张伟', '李强', '王敏', '刘洋', '陈涛', '杨磊', '黄超', '周杰'];
  const count = Math.min(8, Math.max(4, task.rider_count || 4));
  const month = task.settle_month || '2026-10';
  const rows = Array.from({ length: count }, (_, idx) => ({
    rider_name: sampleRiders[idx % sampleRiders.length],
    rider_id: `RD${task.id.replace(/\D/g, '')}${String(idx + 1).padStart(2, '0')}`,
    date: `${month}-${String(Math.min(28, idx * 3 + 1)).padStart(2, '0')}`,
    base_price: (6.2 + (idx % 4) * 0.3).toFixed(2),
    subsidy: (idx % 3 === 0 ? 1.5 : 0.5).toFixed(2),
    total_price: (6.7 + (idx % 4) * 0.3 + (idx % 3 === 0 ? 1.0 : 0)).toFixed(2),
    status: task.reason && idx === count - 1 ? '异常待核' : '正常',
  }));
  return {
    task_id: task.id,
    businessCode: task.businessCode,
    cityName: task.cityName,
    siteName: task.siteName,
    period: `${task.period_start} ~ ${task.period_end}`,
    rider_count: task.rider_count,
    rows,
    columns: ['骑手姓名', '骑手ID', '日期', '基础单价', '补贴', '合计单价', '状态'],
  };
}

export function buildDemoApprovalHistory() {
  return [
    {
      id: 'AP-BATCH-20261120-01',
      status: 'completed',
      created_at: '2026-11-20T16:12:00+08:00',
      finished_at: '2026-11-20T16:13:20+08:00',
      summary: { total: 6, success: 6, failed: 0, uncertain: 0, changed: 0, not_sent: 0, pending: 0 },
      items: [
        { id: 'H-01', businessCode: 'LC-202611-0801', cityName: '上海', siteName: '徐家汇中心站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-02', businessCode: 'LC-202611-0802', cityName: '上海', siteName: '静安大悦城站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-03', businessCode: 'LC-202611-0803', cityName: '深圳', siteName: '南山科技园站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-04', businessCode: 'LC-202611-0804', cityName: '深圳', siteName: '罗湖万象城站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-05', businessCode: 'LC-202611-0805', cityName: '广州', siteName: '天河体育西站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-06', businessCode: 'LC-202611-0806', cityName: '北京', siteName: '朝阳望京站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
      ],
    },
    {
      id: 'AP-BATCH-20261119-04',
      status: 'needs_review',
      created_at: '2026-11-19T15:20:00+08:00',
      finished_at: '2026-11-19T15:21:44+08:00',
      summary: { total: 6, success: 2, failed: 1, uncertain: 1, changed: 1, not_sent: 1, pending: 0 },
      items: [
        { id: 'H-11', businessCode: 'LC-202611-0701', cityName: '北京', siteName: '海淀中关村站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-12', businessCode: 'LC-202611-0702', cityName: '天津', siteName: '和平滨江道站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-13', businessCode: 'LC-202611-0703', cityName: '大连', siteName: '中山青泥洼站', settle_month: '2026-10', status: 'failed', message: '蓝橙接口拒绝：单价超出城市上限阈值' },
        { id: 'H-14', businessCode: 'LC-202611-0704', cityName: '保定', siteName: '莲池万博站', settle_month: '2026-10', status: 'uncertain', message: '提交超时，请前往蓝橙后台核实是否已通过' },
        { id: 'H-15', businessCode: 'LC-202611-0705', cityName: '宁波', siteName: '海曙天一站', settle_month: '2026-10', status: 'changed', message: '审批状态已在蓝橙端被他人更新，已跳过' },
        { id: 'H-16', businessCode: 'LC-202611-0706', cityName: '泉州', siteName: '丰泽万达站', settle_month: '2026-10', status: 'not_sent', message: '因前序节点出现阻断未发送，可重新勾选提交' },
      ],
    },
    {
      id: 'AP-BATCH-20261118-02',
      status: 'partial',
      created_at: '2026-11-18T11:10:00+08:00',
      summary: { total: 3, success: 2, failed: 0, uncertain: 0, changed: 0, not_sent: 0, pending: 1 },
      items: [
        { id: 'H-21', businessCode: 'LC-202611-0601', cityName: '东莞', siteName: '南城鸿福站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-22', businessCode: 'LC-202611-0602', cityName: '东莞', siteName: '松山湖园区站', settle_month: '2026-10', status: 'success', message: '已审批同意' },
        { id: 'H-23', businessCode: 'LC-202611-0603', cityName: '泉州', siteName: '晋江阳光站', settle_month: '2026-10', status: 'pending', message: '等待接口响应中…' },
      ],
    },
  ];
}

/* ═══════════════════════════════════════════════════════════════════════════
 * 5. 待审每日价格导出（LanorangePriceExports）— 示例筛选项与历史导出回执
 * 覆盖：已完成全量导出 + 部分完成（含 1 站失败原因）+ 10 城 30 站权限目录预览
 * ═══════════════════════════════════════════════════════════════════════════ */

export interface DemoPriceExportJob {
  id: string;
  request_id: string;
  status: string;
  created: number;
  message: string;
  completed: number;
  total: number;
  rows: number;
  query: {
    month: string;
    city: string;
    station: string;
    date_from: string;
    date_to: string;
  };
  receipts: {
    city: string;
    station: string;
    period: string;
    version: string;
    status: string;
    row_count: number;
    result: string;
    message: string;
  }[];
  demo?: boolean;
}

export function buildDemoPriceExportData() {
  const cities = DEMO_DEDUCTION_BLUEPRINTS.map(bp => bp.cityName);
  const stations = DEMO_DEDUCTION_BLUEPRINTS.flatMap(bp =>
    bp.stations.map(st => ({ id: st.id, name: st.name, city: bp.cityName })),
  );
  const months = ['2026-11', '2026-10'];
  const nowSec = Math.floor(Date.now() / 1000);

  const exports: DemoPriceExportJob[] = [
    {
      id: 'DEMO-PE-20261120-01',
      request_id: 'demo-req-pe-01',
      status: 'completed',
      created: nowSec - 3600 * 6,
      message: '已完成 2026-10 全部权限站点待审每日价格提取，共导出 1,386 行',
      completed: 10,
      total: 10,
      rows: 1386,
      query: { month: '2026-10', city: '', station: '', date_from: '', date_to: '' },
      receipts: [
        { city: '上海', station: '徐家汇中心站', period: '2026-10-01 ~ 2026-10-31', version: 'v4', status: '审批中', row_count: 186, result: '成功', message: '已取最新版本 v4' },
        { city: '上海', station: '陆家嘴金融站', period: '2026-10-01 ~ 2026-10-31', version: 'v3', status: '待审核', row_count: 142, result: '成功', message: '已取最新版本 v3' },
        { city: '深圳', station: '南山科技园站', period: '2026-10-01 ~ 2026-10-31', version: 'v5', status: '审批中', row_count: 194, result: '成功', message: '已取最新版本 v5' },
        { city: '深圳', station: '福田车公庙站', period: '2026-10-01 ~ 2026-10-31', version: 'v2', status: '待审核', row_count: 136, result: '成功', message: '已取最新版本 v2' },
        { city: '广州', station: '天河体育西站', period: '2026-10-01 ~ 2026-10-31', version: 'v4', status: '审批中', row_count: 168, result: '成功', message: '已取最新版本 v4' },
        { city: '北京', station: '朝阳望京站', period: '2026-10-01 ~ 2026-10-31', version: 'v3', status: '审批中', row_count: 158, result: '成功', message: '已取最新版本 v3' },
        { city: '天津', station: '和平滨江道站', period: '2026-10-01 ~ 2026-10-31', version: 'v2', status: '待审核', row_count: 104, result: '成功', message: '已取最新版本 v2' },
        { city: '东莞', station: '南城鸿福站', period: '2026-10-01 ~ 2026-10-31', version: 'v3', status: '审批中', row_count: 112, result: '成功', message: '已取最新版本 v3' },
        { city: '宁波', station: '海曙天一站', period: '2026-10-01 ~ 2026-10-31', version: 'v2', status: '审批中', row_count: 98, result: '成功', message: '已取最新版本 v2' },
        { city: '泉州', station: '丰泽万达站', period: '2026-10-01 ~ 2026-10-31', version: 'v2', status: '待审核', row_count: 88, result: '成功', message: '已取最新版本 v2' },
      ],
      demo: true,
    },
    {
      id: 'DEMO-PE-20261119-02',
      request_id: 'demo-req-pe-02',
      status: 'partial',
      created: nowSec - 3600 * 28,
      message: '已完成 4/5 个站点周期，大连甘井子华南站缺少有效价格版本',
      completed: 4,
      total: 5,
      rows: 412,
      query: { month: '2026-11', city: '', station: '', date_from: '2026-11-01', date_to: '2026-11-15' },
      receipts: [
        { city: '上海', station: '张江高科站', period: '2026-11-01 ~ 2026-11-15', version: 'v2', status: '审批中', row_count: 118, result: '成功', message: '已取最新版本 v2' },
        { city: '深圳', station: '宝安西乡站', period: '2026-11-01 ~ 2026-11-15', version: 'v2', status: '待审核', row_count: 102, result: '成功', message: '已取最新版本 v2' },
        { city: '广州', station: '白云嘉禾站', period: '2026-11-01 ~ 2026-11-15', version: 'v1', status: '待审核', row_count: 94, result: '成功', message: '已取最新版本 v1' },
        { city: '北京', station: '通州万达站', period: '2026-11-01 ~ 2026-11-15', version: 'v1', status: '审批中', row_count: 98, result: '成功', message: '已取最新版本 v1' },
        { city: '大连', station: '甘井子华南站', period: '2026-11-01 ~ 2026-11-15', version: '', status: '待提交', row_count: 0, result: '失败', message: '蓝橙端尚无 11 月上半月待审价格版本' },
      ],
      demo: true,
    },
  ];

  return {
    options: {
      cities,
      stations,
      months,
      session_version: 'demo-price-export-v1',
    },
    exports,
  };
}

