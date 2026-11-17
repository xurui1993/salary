import type { PayrollQueueTask } from './payrollQueue';
import type { DeductionEntry } from '../components/DeductionAmounts';
import { CONFIG_RULE_COLUMNS } from './deductionCategories';

export interface DemoTaskCenterFile {
  id: string;
  run_id: string;
  name: string;
  city: string;
  bytes: number;
  available: boolean;
  unavailable_reason?: string;
}

export interface DemoTaskCenterRecord {
  id: string;
  kind: string;
  title?: string;
  price_id?: string;
  batch_id?: string;
  output?: string;
  cities: string[];
  datasets: string[];
  start: string;
  end: string;
  status: string;
  created_at: string;
  files: DemoTaskCenterFile[];
  source_files?: DemoTaskCenterFile[];
  available_files: number;
  failed_items: number;
  completed_items: number;
  total_items: number;
  member_ids: string[];
  attempts: { id: string; status: string }[];
  action_run_id: string;
  summary_issue?: boolean;
  elapsed_seconds?: number;
  updated_at?: string;
}

export interface DemoApprovalTask {
  id: string;
  business_id: string;
  businessCode?: string;
  businessTitle?: string;
  cityName?: string;
  siteName?: string;
  nodeName?: string;
  createByName?: string;
  createTime?: string;
  period_start?: string;
  period_end?: string;
  rider_count?: number;
  settle_month?: string;
  revision: string;
  reason: string;
}

export interface DemoApprovalPrice {
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[];
  remark: string;
  version?: number;
  version_change?: string;
}

export interface DemoApprovalBatch {
  id: string;
  actor_label: string;
  status: string;
  created: number;
  counts: Record<string, number>;
  items: {
    task: DemoApprovalTask;
    status: string;
    status_label: string;
    message: string;
  }[];
}

export function createDemoPayrollQueueTasks(): PayrollQueueTask[] {
  const buildReview = (
    batchId: string,
    city: string,
    start: string,
    end: string,
    templateName: string,
    applicants: number,
    noPrice: number,
    unbound: number,
    intercepted: number,
    options?: {
      issues?: { code: string; label: string; count?: number; location?: string; rows?: { row: number; same_as: number }[] }[];
      exportError?: string;
    },
  ) => ({
    version: 2,
    status: 'pending_review' as const,
    batch_id: batchId,
    city,
    start,
    end,
    metrics: [
      { key: 'applicants', label: '申请人数', value: applicants, unit: '人', note: '按标准申请表去重后实际纳入核算的人数' },
      { key: 'no_price', label: '无匹配单价', value: noPrice, unit: '人', note: '蓝橙兼职协议未覆盖或已过期的骑手' },
      { key: 'unbound', label: '未绑定站/卡', value: unbound, unit: '人', note: '风神绑定与支付卡校验存在缺口' },
      { key: 'intercepted', label: '拦截扣款复核', value: intercepted, unit: '项', note: '触发异常或高额扣款阈值需人工复核' },
    ],
    issues: options?.issues ?? [],
    sources: [
      { kind: 'delivery_fee', label: '风神配送费账单', status: 'ready', files: [{ name: `${city}_配送费明细.xlsx`, sha256: 'a84c91f20e3d' }] },
      { kind: 'attendance_detail', label: '骑手出勤明细', status: 'ready', files: [{ name: `${city}_出勤汇总.xlsx`, sha256: 'b19d204ca871' }] },
      { kind: 'lanorange_price', label: '蓝橙兼职单价档案', status: 'ready', files: [{ name: `${city}_兼职协议单价.xlsx`, sha256: 'e52019ba441f' }] },
    ],
    template: { name: templateName, sha256: `9f30c2a4${batchId.slice(-4)}` },
    deduction_version: 'cfg20261115a1',
    input_check: '已校验工作表字段、站点归属、出勤天数与重复申请行。',
    money_check: '请于 Excel / WPS 重新打开工作簿后按 Ctrl+Alt+F9 复核实发金额与扣款合计数。',
    export_error: options?.exportError,
  });

  const makeRow = (vals: Partial<Record<(typeof CONFIG_RULE_COLUMNS)[number], number>>) => {
    const base: Record<string, number> = {};
    for (const col of CONFIG_RULE_COLUMNS) {
      base[col] = vals[col] ?? 0;
    }
    return base;
  };

  return [
    {
      id: 'demo-pq-01',
      batch_id: 'batch-demo-01',
      mode: 'fengshen',
      template_name: '广州-11月上半月兼职算薪_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 142,
      current_action: '核算成品与复核摘要已生成，可直接打包下载',
      created_at: '2026-11-16T09:12:00+08:00',
      plan: { city: '广州', start: '2026-11-01', end: '2026-11-15', applicants: 148 },
      logs: [
        { time: '2026-11-16T09:12:05+08:00', level: 'INFO', text: '完成模板解析：识别广州 6 个站点共 148 名兼职骑手' },
        { time: '2026-11-16T09:13:02+08:00', level: 'INFO', text: '已自动拉取风神配送费、出勤明细、违规扣款及蓝橙单价档案' },
        { time: '2026-11-16T09:14:22+08:00', level: 'INFO', text: '核算工作簿生成完成，待人工核对 2 项预警提醒' },
        { time: '2026-11-16T09:14:22+08:00', level: 'DEBUG', text: '[timing] fetch=54.2s merge=18.4s write_xlsx=9.1s total=142.0s' },
      ],
      preparation: {
        id: 'batch-demo-01',
        mode: 'fengshen',
        status: 'calculated',
        automatic_deductions: {
          sources: [
            { station: { id: 'GZ01', name: '天河体育中心站_新专送' }, source: '站点独立规则' },
            { station: { id: 'GZ02', name: '海珠客村站_新专送' }, source: '沿用广州默认' },
            { station: { id: 'GZ03', name: '番禺市桥核心站_新专送' }, source: '站点独立规则' },
            { station: { id: 'GZ04', name: '白云嘉禾望岗站_新专送' }, source: '沿用广州默认' },
          ],
        },
        result: {
          review_summary: buildReview(
            'batch-demo-01',
            '广州',
            '2026-11-01',
            '2026-11-15',
            '广州-11月上半月兼职算薪_template.xlsx',
            148,
            2,
            1,
            3,
            {
              issues: [
                {
                  code: 'duplicate_rows',
                  label: '发现申请表疑似重复记录',
                  count: 1,
                  location: 'Sheet1 第 44 行与第 19 行身份证尾号及站点重复',
                  rows: [{ row: 44, same_as: 19 }],
                },
                {
                  code: 'no_price',
                  label: '2 名骑手未匹配到 11 月兼职协议单价',
                  count: 2,
                  location: '番禺市桥核心站_新专送（已标黄待填单价）',
                },
              ],
            },
          ),
        },
      } as any,
    },
    {
      id: 'demo-pq-02',
      batch_id: 'batch-demo-02',
      mode: 'fengshen',
      template_name: '深圳-11月上半月全区兼职算薪_template.xlsx',
      status: 'calculating',
      progress: 74,
      elapsed_seconds: 68,
      current_action: '正在核对南山、福田 236 名骑手超时阶梯扣款与补贴规则',
      created_at: '2026-11-16T09:38:00+08:00',
      plan: { city: '深圳', start: '2026-11-01', end: '2026-11-15', applicants: 236 },
      logs: [
        { time: '2026-11-16T09:38:04+08:00', level: 'INFO', text: '完成 深圳 9 个站点申请表去重与身份映射（236 人）' },
        { time: '2026-11-16T09:38:41+08:00', level: 'INFO', text: '云端齐套资料就绪：配送费 18,420 条 / 出勤 3,190 条' },
        { time: '2026-11-16T09:39:08+08:00', level: 'INFO', text: '正在应用站点独立扣款规则并写入明细页（175 / 236）' },
      ],
    },
    {
      id: 'demo-pq-03',
      batch_id: 'batch-demo-03',
      mode: 'fengshen',
      template_name: '佛山-11月禅城顺德兼职算薪_template.xlsx',
      status: 'preparing',
      progress: 38,
      elapsed_seconds: 29,
      current_action: '正在并发拉取风神违规扣款与蓝橙最新价格档案…',
      created_at: '2026-11-16T09:40:10+08:00',
      plan: { city: '佛山', start: '2026-11-01', end: '2026-11-15', applicants: 92 },
      logs: [
        { time: '2026-11-16T09:40:12+08:00', level: 'INFO', text: '已解析模板：佛山 4 个站点，账期 2026-11-01 ~ 2026-11-15' },
        { time: '2026-11-16T09:40:28+08:00', level: 'INFO', text: '风神配送费拉取完成，正在等待问题单分类合并' },
      ],
    },
    {
      id: 'demo-pq-04',
      batch_id: 'batch-demo-04',
      mode: 'fengshen',
      template_name: '东莞-11月虎门长安大区算薪_template.xlsx',
      status: 'queued',
      progress: 0,
      current_action: '排队等待云端采集槽位（队列第 1 位）',
      created_at: '2026-11-16T09:41:00+08:00',
      plan: { city: '东莞', start: '2026-11-01', end: '2026-11-15', applicants: 115 },
      logs: [
        { time: '2026-11-16T09:41:02+08:00', level: 'INFO', text: '模板已加入并发队列，已锁定排除取分离站点范围' },
      ],
    },
    {
      id: 'demo-pq-05',
      batch_id: 'batch-demo-05',
      mode: 'manual',
      template_name: '惠州-10月全月手动资料目录核验_template.xlsx',
      status: 'waiting_confirmation',
      progress: 55,
      elapsed_seconds: 44,
      current_action: '检测到 3 个未配置扣款站点与 2 项站点名称差异，待人工确认',
      created_at: '2026-11-16T08:50:00+08:00',
      plan: { city: '惠州', start: '2026-10-01', end: '2026-10-31', applicants: 64 },
      logs: [
        { time: '2026-11-16T08:50:10+08:00', level: 'INFO', text: '已识别本地目录中 5 份补充源表（配送费/出勤/违规/问题单/单价）' },
        { time: '2026-11-16T08:50:44+08:00', level: 'WARN', text: '惠阳淡水南站、大亚湾万达站尚未配置默认扣款金额，暂停等待人工确认' },
      ],
    },
    {
      id: 'demo-pq-06',
      batch_id: 'batch-demo-06',
      mode: 'fengshen',
      template_name: '珠海-骑手信息导出验证触发_template.xlsx',
      status: 'calculating',
      progress: 46,
      elapsed_seconds: 51,
      current_action: '正在等待风神骑手信息导出滑块/短信验证码验证…',
      created_at: '2026-11-16T09:32:00+08:00',
      plan: { city: '珠海', start: '2026-11-01', end: '2026-11-15', applicants: 58 },
      logs: [
        { time: '2026-11-16T09:32:10+08:00', level: 'INFO', text: '风神账号触发风控二次验证，等待人工完成验证码校验' },
      ],
      preparation: {
        id: 'batch-demo-06',
        mode: 'fengshen',
        status: 'preparing',
        execution: {
          waiting_login: true,
          waiting_verification: true,
        },
      } as any,
    },
    {
      id: 'demo-pq-07',
      batch_id: 'batch-demo-07',
      mode: 'fengshen',
      template_name: '中山-10月全月异常中断算薪_template.xlsx',
      status: 'error',
      progress: 32,
      elapsed_seconds: 39,
      current_action: '风神违规扣款账单导出返回 401（会话失效），需重新登录风神后重试',
      created_at: '2026-11-16T08:20:00+08:00',
      plan: { city: '中山', start: '2026-10-01', end: '2026-10-31', applicants: 47 },
      logs: [
        { time: '2026-11-16T08:20:05+08:00', level: 'INFO', text: '开始准备中山 10 月全月算薪源表' },
        { time: '2026-11-16T08:20:39+08:00', level: 'ERROR', text: '拉取违规扣款接口返回登录态已过期（HTTP 401），已中止本批次' },
        { time: '2026-11-16T08:20:39+08:00', level: 'DEBUG', text: 'AuthSessionExpiredError: fengshen cookie stale after 14h' },
      ],
    },
    {
      id: 'demo-pq-08',
      batch_id: 'batch-demo-08',
      mode: 'manual',
      template_name: '江门-手动停止中止确认_template.xlsx',
      status: 'stopping',
      progress: 61,
      elapsed_seconds: 47,
      current_action: '收到停止指令，正在安全收尾并释放临时工作簿锁…',
      created_at: '2026-11-16T09:36:00+08:00',
      plan: { city: '江门', start: '2026-10-16', end: '2026-10-31', applicants: 31 },
      logs: [
        { time: '2026-11-16T09:36:08+08:00', level: 'INFO', text: '已开始执行江门手动资料核算' },
        { time: '2026-11-16T09:36:45+08:00', level: 'WARN', text: '用户触发停止任务请求，等待当前站点写入事务退出' },
      ],
    },
    {
      id: 'demo-pq-09',
      batch_id: 'batch-demo-09',
      mode: 'fengshen',
      template_name: '汕头-重复上传已取消批次_template.xlsx',
      status: 'cancelled',
      progress: 12,
      elapsed_seconds: 11,
      current_action: '操作员主动取消，已保留原始模板文件',
      created_at: '2026-11-15T17:45:00+08:00',
      plan: { city: '汕头', start: '2026-10-01', end: '2026-10-15', applicants: 29 },
      logs: [
        { time: '2026-11-15T17:45:11+08:00', level: 'WARN', text: '检测到同账期已有较新模板，操作员取消本批次执行' },
      ],
    },
    {
      id: 'demo-pq-10',
      batch_id: 'batch-demo-10',
      mode: 'fengshen',
      template_name: '上海-10月浦东徐汇全区兼职算薪_template.xlsx',
      status: 'interrupted',
      progress: 64,
      elapsed_seconds: 118,
      current_action: '服务维护曾中断执行，源表缓存已保留，可重新提交接续',
      created_at: '2026-11-15T16:10:00+08:00',
      plan: { city: '上海', start: '2026-10-01', end: '2026-10-31', applicants: 312 },
      logs: [
        { time: '2026-11-15T16:11:58+08:00', level: 'WARN', text: '工作进程意外退出，已完成 8 个站点配送费本地缓存' },
      ],
    },
    {
      id: 'demo-pq-11',
      batch_id: 'batch-demo-11',
      mode: 'manual',
      legacy: true,
      template_name: '北京-10月朝阳海淀历史归档复核_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 195,
      current_action: '历史核算批次已完成（支持行内单独下载与复核）',
      created_at: '2026-11-05T14:22:00+08:00',
      plan: { city: '北京', start: '2026-10-01', end: '2026-10-31', applicants: 189 },
      logs: [
        { time: '2026-11-05T14:25:15+08:00', level: 'INFO', text: '历史批次核验归档完成，共输出 189 人结算表与扣款汇总清单' },
      ],
      preparation: {
        id: 'batch-demo-11',
        mode: 'manual',
        status: 'calculated',
        result: {
          review_summary: buildReview(
            'batch-demo-11',
            '北京',
            '2026-10-01',
            '2026-10-31',
            '北京-10月朝阳海淀历史归档复核_template.xlsx',
            189,
            0,
            0,
            0,
          ),
        },
      } as any,
    },
    {
      id: 'demo-pq-12',
      batch_id: 'batch-demo-12',
      mode: 'fengshen',
      template_name: '杭州-西湖滨江余杭萧山多商圈兼职大额激励与违规复核超长模板名称测试_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 164,
      current_action: '204 名骑手兼职汇总表已生成（含超长文件名省略号与浮窗提示适配）',
      created_at: '2026-11-15T11:30:00+08:00',
      plan: { city: '杭州', start: '2026-10-01', end: '2026-10-31', applicants: 204 },
      logs: [
        { time: '2026-11-15T11:32:44+08:00', level: 'INFO', text: '多商圈长模板名称批次算薪完成，0 项结构异常' },
      ],
      preparation: {
        id: 'batch-demo-12',
        mode: 'fengshen',
        status: 'calculated',
        result: {
          review_summary: buildReview(
            'batch-demo-12',
            '杭州',
            '2026-10-01',
            '2026-10-31',
            '杭州-西湖滨江余杭萧山多商圈兼职大额激励与违规复核超长模板名称测试_template.xlsx',
            204,
            1,
            0,
            2,
          ),
        },
      } as any,
    },
    {
      id: 'demo-pq-13',
      batch_id: 'batch-demo-13',
      mode: 'manual',
      template_name: '宁波-10月全站零扣款专项激励_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 54,
      current_action: '已确认全站零扣款口径并导出实发清单',
      created_at: '2026-11-14T16:40:00+08:00',
      plan: { city: '宁波', start: '2026-10-01', end: '2026-10-31', applicants: 42 },
      logs: [
        { time: '2026-11-14T16:40:54+08:00', level: 'INFO', text: '宁波全部 10 个站点沿用已确认零扣款规则，计算无差异' },
      ],
      preparation: {
        id: 'batch-demo-13',
        mode: 'manual',
        status: 'calculated',
        automatic_deductions: {
          sources: [
            { station: { id: 'NB01', name: '鄞州万达站_新专送' }, source: '已确认零扣款' },
            { station: { id: 'NB02', name: '海曙天一广场站_新专送' }, source: '已确认零扣款' },
          ],
        },
      } as any,
    },
    {
      id: 'demo-pq-14',
      batch_id: 'batch-demo-14',
      mode: 'fengshen',
      template_name: '苏州-11月取分离站点归属待确认_template.xlsx',
      status: 'waiting_confirmation',
      progress: 48,
      elapsed_seconds: 35,
      current_action: '发现 2 个取分离站点需手工指定归属团队，确认后自动继续',
      created_at: '2026-11-16T09:05:00+08:00',
      plan: { city: '苏州', start: '2026-11-01', end: '2026-11-15', applicants: 83 },
      logs: [
        { time: '2026-11-16T09:05:35+08:00', level: 'WARN', text: '园区湖东取离站、姑苏观前专送站存在归属歧义，等待人工映射' },
      ],
    },
    {
      id: 'demo-pq-15',
      batch_id: 'batch-demo-15',
      mode: 'manual',
      template_name: '南京-缺勤源表校验失败目录_template.xlsx',
      status: 'error',
      progress: 10,
      elapsed_seconds: 6,
      current_action: '本地文件夹缺少「骑手出勤明细」工作簿，请补充后重新上传目录',
      created_at: '2026-11-15T10:15:00+08:00',
      plan: { city: '南京', start: '2026-10-01', end: '2026-10-31', applicants: 0 },
      logs: [
        { time: '2026-11-15T10:15:06+08:00', level: 'ERROR', text: '目录预检未通过：未识别到 *出勤* 明细表，且申请人数读取为 0' },
      ],
    },
    {
      id: 'demo-pq-16',
      batch_id: 'batch-demo-16',
      mode: 'manual',
      template_name: '成都-高新天府手动补齐算薪队列_template.xlsx',
      status: 'queued',
      progress: 0,
      current_action: '本地资料目录预检通过，等待上一个手动批次完成写入',
      created_at: '2026-11-16T09:41:20+08:00',
      plan: { city: '成都', start: '2026-11-01', end: '2026-11-15', applicants: 76 },
      logs: [
        { time: '2026-11-16T09:41:20+08:00', level: 'INFO', text: '本地源表 6/6 项齐套校验通过，正在排队执行' },
      ],
    },
    {
      id: 'demo-pq-17',
      batch_id: 'batch-demo-17',
      mode: 'fengshen',
      template_name: '厦门-10月思明湖里兼职月结_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 88,
      current_action: '核算完成，无缺价与未绑定异常',
      created_at: '2026-11-13T15:18:00+08:00',
      plan: { city: '厦门', start: '2026-10-01', end: '2026-10-31', applicants: 61 },
      logs: [
        { time: '2026-11-13T15:19:28+08:00', level: 'INFO', text: '厦门 61 名骑手算薪一次性通过复核校验' },
      ],
      preparation: {
        id: 'batch-demo-17',
        mode: 'fengshen',
        status: 'calculated',
        result: {
          review_summary: buildReview(
            'batch-demo-17',
            '厦门',
            '2026-10-01',
            '2026-10-31',
            '厦门-10月思明湖里兼职月结_template.xlsx',
            61,
            0,
            0,
            0,
          ),
        },
      } as any,
    },
    {
      id: 'demo-pq-18',
      batch_id: 'batch-demo-18',
      mode: 'fengshen',
      template_name: '泉州-9月丰泽晋江补发复核_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 79,
      current_action: '补发差额工作簿与问题单扣款清单已打包就绪',
      created_at: '2026-11-10T11:02:00+08:00',
      plan: { city: '泉州', start: '2026-09-01', end: '2026-09-30', applicants: 53 },
      logs: [
        { time: '2026-11-10T11:03:19+08:00', level: 'INFO', text: '历史补发批次已生成完成' },
      ],
    },
    {
      id: 'demo-pq-19',
      batch_id: 'batch-demo-19',
      mode: 'fengshen',
      template_name: '天津-等待蓝橙授权拉取单价_template.xlsx',
      status: 'waiting_confirmation',
      progress: 25,
      elapsed_seconds: 19,
      current_action: '需先登录蓝橙平台授权读取兼职价格协议后继续核算',
      created_at: '2026-11-16T09:28:00+08:00',
      plan: { city: '天津', start: '2026-11-01', end: '2026-11-15', applicants: 94 },
      logs: [
        { time: '2026-11-16T09:28:19+08:00', level: 'WARN', text: '蓝橙授权状态未就绪，挂起等待平台登录完成' },
      ],
      preparation: {
        id: 'batch-demo-19',
        mode: 'fengshen',
        status: 'preparing',
        execution: {
          waiting_login: true,
          waiting_verification: false,
        },
      } as any,
    },
    {
      id: 'demo-pq-20',
      batch_id: 'batch-demo-20',
      mode: 'fengshen',
      template_name: '三亚-10月旅游旺季夜间补贴算薪_template.xlsx',
      status: 'completed',
      progress: 100,
      elapsed_seconds: 63,
      current_action: '算薪完成（含 1 项公式重算提醒，请核对复核摘要）',
      created_at: '2026-11-12T18:05:00+08:00',
      plan: { city: '三亚', start: '2026-10-01', end: '2026-10-31', applicants: 38 },
      logs: [
        { time: '2026-11-12T18:06:03+08:00', level: 'INFO', text: '三亚旺季夜间补贴结算表已导出（38 人）' },
      ],
      preparation: {
        id: 'batch-demo-20',
        mode: 'fengshen',
        status: 'calculated',
        result: {
          review_summary: buildReview(
            'batch-demo-20',
            '三亚',
            '2026-10-01',
            '2026-10-31',
            '三亚-10月旅游旺季夜间补贴算薪_template.xlsx',
            38,
            0,
            1,
            1,
            {
              exportError: '检测到「代领费率」有 1 位骑手为手工覆写值，请核对实发栏位后打款。',
            },
          ),
        },
      } as any,
    },
  ];
}

export function createDemoApprovalData(): {
  actor_label: string;
  session_version: string;
  rows: DemoApprovalTask[];
  batches: DemoApprovalBatch[];
} {
  const specs: Array<{
    code: string;
    city: string;
    site: string;
    start: string;
    end: string;
    month: string;
    riders: number | undefined;
    creator: string;
    time: string;
    node: string;
    reason?: string;
    rev?: string;
  }> = [
    { code: 'LC-GZ-202611-001', city: '广州', site: '天河体育中心核心商圈直营站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 86, creator: '陈晓敏', time: '2026-11-16 09:12', node: '区域运营主管审批' },
    { code: 'LC-GZ-202611-002', city: '广州', site: '海珠客村琶洲站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 64, creator: '林家豪', time: '2026-11-16 09:05', node: '城市财务价格复核' },
    { code: 'LC-GZ-202610-003', city: '广州', site: '番禺市桥广场站_新专送', start: '2026-10-01', end: '2026-10-31', month: '2026-10', riders: 112, creator: '陈晓敏', time: '2026-11-15 18:30', node: '华南区兼职终审' },
    { code: 'LC-GZ-202611-004', city: '广州', site: '白云嘉禾望岗站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 49, creator: '张伟杰', time: '2026-11-15 17:40', node: '区域运营主管审批', reason: '价格版本已由发起人变更（v2→v3），需退回重审' },
    { code: 'LC-SZ-202611-005', city: '深圳', site: '南山科技园高新站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 148, creator: '周子涵', time: '2026-11-16 08:55', node: '城市运营总监审批' },
    { code: 'LC-SZ-202611-006', city: '深圳', site: '福田华强北车公庙站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 93, creator: '周子涵', time: '2026-11-16 08:40', node: '城市财务价格复核' },
    { code: 'LC-SZ-202610-007', city: '深圳', site: '宝安西乡坪洲站_新专送', start: '2026-10-01', end: '2026-10-31', month: '2026-10', riders: 77, creator: '吴志远', time: '2026-11-15 16:15', node: '区域运营主管审批' },
    { code: 'LC-SZ-202611-008', city: '深圳', site: '龙岗布吉大芬站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 38, creator: '吴志远', time: '2026-11-15 15:20', node: '人力合规会签', reason: '当前节点非本人账号审批权限' },
    { code: 'LC-FS-202611-009', city: '佛山', site: '禅城祖庙岭南天地站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 55, creator: '梁宇轩', time: '2026-11-16 08:15', node: '区域运营主管审批' },
    { code: 'LC-FS-202610-010', city: '佛山', site: '顺德大良清晖园站_新专送', start: '2026-10-01', end: '2026-10-31', month: '2026-10', riders: 68, creator: '梁宇轩', time: '2026-11-14 19:02', node: '城市财务价格复核' },
    { code: 'LC-FS-202609-011', city: '佛山', site: '南海桂城千灯湖站_新专送', start: '2026-09-16', end: '2026-09-30', month: '2026-09', riders: 24, creator: '黄思琪', time: '2026-11-12 11:45', node: '历史补发审批' },
    { code: 'LC-DG-202611-012', city: '东莞', site: '南城鸿福路口站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 82, creator: '何俊杰', time: '2026-11-16 07:50', node: '城市运营总监审批' },
    { code: 'LC-DG-202610-013', city: '东莞', site: '虎门万达广场站_新专送', start: '2026-10-01', end: '2026-10-31', month: '2026-10', riders: 0, creator: '何俊杰', time: '2026-11-15 14:10', node: '城市财务价格复核', reason: '该提审单骑手明细为 0 人，暂不可批量同意' },
    { code: 'LC-HZ-202611-014', city: '惠州', site: '惠城江北华贸站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 41, creator: '罗文博', time: '2026-11-15 16:55', node: '区域运营主管审批' },
    { code: 'LC-HZ-202610-015', city: '惠州', site: '惠阳淡水开城大道站_新专送', start: '2026-10-01', end: '2026-10-31', month: '2026-10', riders: 33, creator: '罗文博', time: '2026-11-14 15:30', node: '城市财务价格复核' },
    { code: 'LC-SH-202611-016', city: '上海', site: '浦东陆家嘴世纪大道站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 126, creator: '沈佳妮', time: '2026-11-16 09:01', node: '华东大区价格终审' },
    { code: 'LC-SH-202610-017', city: '上海', site: '徐汇漕河泾开发区核心调度站_新专送', start: '2026-10-01', end: '2026-10-31', month: '2026-10', riders: 97, creator: '沈佳妮', time: '2026-11-15 11:20', node: '城市运营总监审批' },
    { code: 'LC-HZU-202611-018', city: '杭州', site: '西湖文三路黄龙站_新专送', start: '2026-11-01', end: '2026-11-15', month: '2026-11', riders: 72, creator: '徐子墨', time: '2026-11-16 08:30', node: '区域运营主管审批' },
    { code: 'LC-HZU-202609-019', city: '杭州', site: '滨江星光大道物联网站_新专送', start: '2026-09-01', end: '2026-09-30', month: '2026-09', riders: 18, creator: '徐子墨', time: '2026-11-10 10:15', node: '历史补发审批' },
    { code: 'LC-CD-202610-020', city: '成都', site: '高新天府三街软件园站_新专送', start: '2026-10-16', end: '2026-10-31', month: '2026-10', riders: 58, creator: '唐雨桐', time: '2026-11-15 17:05', node: '西南片区负责人审批' },
  ];

  const rows: DemoApprovalTask[] = specs.map((item, idx) => ({
    id: `demo-apr-${String(idx + 1).padStart(2, '0')}`,
    business_id: `biz-${item.code}`,
    businessCode: item.code,
    businessTitle: `${item.city}·${item.site} 兼职单价提审`,
    cityName: item.city,
    siteName: item.site,
    nodeName: item.node,
    createByName: item.creator,
    createTime: item.time,
    period_start: item.start,
    period_end: item.end,
    rider_count: item.riders,
    settle_month: item.month,
    revision: item.rev || `v${(idx % 3) + 1}`,
    reason: item.reason || '',
  }));

  const batches: DemoApprovalBatch[] = [
    {
      id: 'demo-apr-batch-01',
      actor_label: '演示审批专员（华南/华东区）',
      status: 'partial',
      created: Math.floor(Date.parse('2026-11-16T08:30:00+08:00') / 1000),
      counts: { success: 4, failed: 1, changed: 1, uncertain: 0, not_sent: 0, pending: 0 },
      items: [
        { task: rows[0], status: 'success', status_label: '已同意', message: '官方节点「区域运营主管审批」已提交通过' },
        { task: rows[4], status: 'success', status_label: '已同意', message: '官方节点「城市运营总监审批」已提交通过' },
        { task: rows[8], status: 'success', status_label: '已同意', message: '官方节点「区域运营主管审批」已提交通过' },
        { task: rows[15], status: 'success', status_label: '已同意', message: '官方节点「华东大区价格终审」已提交通过' },
        { task: rows[3], status: 'changed', status_label: '版本变化', message: '提交前校验发现发起人修订了价格附件（v2 -> v3），已安全跳过' },
        { task: rows[12], status: 'failed', status_label: '已拒绝/校验未过', message: '官方校验返回：站点兼职协议有效人数为 0，不支持同意' },
      ],
    },
    {
      id: 'demo-apr-batch-02',
      actor_label: '演示审批专员（华南/华东区）',
      status: 'completed',
      created: Math.floor(Date.parse('2026-11-15T18:10:00+08:00') / 1000),
      counts: { success: 5, failed: 0, changed: 0, uncertain: 0, not_sent: 0, pending: 0 },
      items: [
        { task: rows[1], status: 'success', status_label: '已同意', message: '已完成城市财务价格复核' },
        { task: rows[2], status: 'success', status_label: '已同意', message: '已完成华南区兼职终审' },
        { task: rows[5], status: 'success', status_label: '已同意', message: '已完成城市财务价格复核' },
        { task: rows[9], status: 'success', status_label: '已同意', message: '已完成顺德区财务复核' },
        { task: rows[16], status: 'success', status_label: '已同意', message: '已完成上海徐汇站价格终审' },
      ],
    },
    {
      id: 'demo-apr-batch-03',
      actor_label: '演示审批专员（华南/华东区）',
      status: 'needs_review',
      created: Math.floor(Date.parse('2026-11-15T14:00:00+08:00') / 1000),
      counts: { success: 2, failed: 0, changed: 0, uncertain: 1, not_sent: 0, pending: 0 },
      items: [
        { task: rows[6], status: 'success', status_label: '已同意', message: '审批回执已确认' },
        { task: rows[11], status: 'success', status_label: '已同意', message: '审批回执已确认' },
        { task: rows[13], status: 'uncertain', status_label: '待核实', message: '请求已发出但蓝橙网关超时未返回，请点击“核实待确认结果”查证' },
      ],
    },
  ];

  return {
    actor_label: '演示审批专员（华南/华东区）',
    session_version: 'demo-sv-20261116',
    rows,
    batches,
  };
}

export function getDemoApprovalPriceDetail(task: DemoApprovalTask): DemoApprovalPrice {
  const count = Math.max(3, Math.min(28, task.rider_count || 6));
  const surnames = ['张', '李', '王', '陈', '刘', '黄', '周', '吴', '徐', '赵'];
  const given = ['志伟', '俊杰', '敏敏', '子涵', '海涛', '嘉诚', '思雨', '文博', '晓明', '宇轩'];
  const seedNum = task.id.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0);

  const rows = Array.from({ length: count }, (_, idx) => {
    const basePrice = 6.2 + ((seedNum + idx) % 5) * 0.4;
    const distanceBonus = 1.5 + ((idx * 3) % 4) * 0.5;
    const nightSubsidy = idx % 3 === 0 ? 2.0 : 0.5;
    return {
      rider_name: `${surnames[(seedNum + idx) % surnames.length]}${given[(idx * 3) % given.length]}`,
      rider_id: `R${202600 + ((seedNum + idx * 17) % 9000)}`,
      tier: idx % 2 === 0 ? '阶梯 A 档（高频晚高峰）' : '阶梯 B 档（常规全时段）',
      base_price: basePrice.toFixed(2),
      distance_bonus: distanceBonus.toFixed(2),
      night_subsidy: nightSubsidy.toFixed(2),
      est_orders: 140 + ((seedNum + idx * 13) % 210),
    };
  });

  return {
    columns: [
      { key: 'rider_name', label: '骑手姓名' },
      { key: 'rider_id', label: '骑手ID' },
      { key: 'tier', label: '执行价格档位' },
      { key: 'base_price', label: '基础单价(元)' },
      { key: 'distance_bonus', label: '远距离补贴(元)' },
      { key: 'night_subsidy', label: '夜间补贴(元)' },
      { key: 'est_orders', label: '周期预计单量' },
    ],
    rows,
    remark: task.reason
      ? `系统预警：${task.reason}`
      : `${task.cityName} · ${task.siteName} 本期兼职协议定价一致，无超标异常值。`,
    version: Number(task.revision.replace(/\D/g, '')) || 1,
    version_change: task.reason?.includes('变更') ? '由 v2 变更为 v3' : undefined,
  };
}

export function createDemoTaskCenterRecords(): DemoTaskCenterRecord[] {
  return [
    {
      id: 'demo-tc-01',
      kind: 'download',
      title: '配送费、违规扣款与骑手出勤明细采集',
      cities: ['广州', '深圳', '佛山'],
      datasets: ['delivery_fee', 'penalty', 'attendance_detail'],
      start: '2026-11-01',
      end: '2026-11-15',
      status: 'running',
      created_at: '2026-11-16T09:38:00+08:00',
      elapsed_seconds: 134,
      files: [
        { id: 'f01', run_id: 'run-demo-01', name: '广州_2026-11上半月_配送费.xlsx', city: '广州', bytes: 2450120, available: true },
        { id: 'f02', run_id: 'run-demo-01', name: '深圳_2026-11上半月_配送费.xlsx', city: '深圳', bytes: 3120400, available: true },
      ],
      available_files: 2,
      failed_items: 0,
      completed_items: 6,
      total_items: 9,
      member_ids: ['run-demo-01'],
      attempts: [{ id: 'run-demo-01', status: 'running' }],
      action_run_id: 'run-demo-01',
    },
    {
      id: 'demo-tc-02',
      kind: 'download',
      title: '风神问题单与欺诈单全城风控对账',
      cities: ['上海', '杭州', '宁波', '苏州'],
      datasets: ['problem', 'fraud'],
      start: '2026-11-01',
      end: '2026-11-15',
      status: 'queued',
      created_at: '2026-11-16T09:40:20+08:00',
      elapsed_seconds: 18,
      files: [],
      available_files: 0,
      failed_items: 0,
      completed_items: 0,
      total_items: 8,
      member_ids: ['run-demo-02'],
      attempts: [{ id: 'run-demo-02', status: 'queued' }],
      action_run_id: 'run-demo-02',
    },
    {
      id: 'demo-tc-03',
      kind: 'download',
      title: '月度 UB 账单与骑手风神绑定',
      cities: ['广州', '深圳', '东莞', '惠州', '佛山'],
      datasets: ['rider_monthly', 'receive_account'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'success',
      created_at: '2026-11-16T08:45:00+08:00',
      elapsed_seconds: 216,
      files: [
        { id: 'f03a', run_id: 'run-demo-03', name: '10月_5城合并_风神UB账单.xlsx', city: '广州', bytes: 4820190, available: true },
        { id: 'f03b', run_id: 'run-demo-03', name: '10月_5城合并_骑手绑定快照.xlsx', city: '深圳', bytes: 1920300, available: true },
        { id: 'f03c', run_id: 'run-demo-03', name: '东莞_10月_风神UB账单.xlsx', city: '东莞', bytes: 1340110, available: true },
      ],
      source_files: [
        { id: 'sf03a', run_id: 'run-demo-03', name: '原始回执_广州UB_raw.csv', city: '广州', bytes: 980120, available: true },
      ],
      available_files: 3,
      failed_items: 0,
      completed_items: 10,
      total_items: 10,
      member_ids: ['run-demo-03'],
      attempts: [{ id: 'run-demo-03', status: 'success' }],
      action_run_id: 'run-demo-03',
    },
    {
      id: 'demo-tc-04',
      kind: 'download',
      title: '骑手数据明细断点补采（华南二区）',
      cities: ['中山', '珠海', '江门'],
      datasets: ['rider_detail', 'rider_info'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'partial',
      created_at: '2026-11-16T08:12:00+08:00',
      elapsed_seconds: 175,
      files: [
        { id: 'f04a', run_id: 'run-demo-04', name: '中山_骑手数据明细.xlsx', city: '中山', bytes: 1240000, available: true },
        { id: 'f04b', run_id: 'run-demo-04', name: '珠海_骑手信息导出.xlsx', city: '珠海', bytes: 640200, available: true },
        { id: 'f04c', run_id: 'run-demo-04', name: '江门_骑手数据明细.xlsx', city: '江门', bytes: 0, available: false, unavailable_reason: '风神网关超时未生成' },
      ],
      available_files: 2,
      failed_items: 1,
      completed_items: 5,
      total_items: 6,
      member_ids: ['run-demo-04'],
      attempts: [
        { id: 'run-demo-04-a', status: 'error' },
        { id: 'run-demo-04', status: 'partial' },
      ],
      action_run_id: 'run-demo-04',
      summary_issue: true,
    },
    {
      id: 'demo-tc-05',
      kind: 'download',
      title: '风神全城骑手信息实时快照',
      cities: ['广州', '深圳', '佛山', '东莞'],
      datasets: ['rider_info'],
      start: '2026-11-16',
      end: '2026-11-16',
      status: 'waiting_login',
      created_at: '2026-11-16T09:20:00+08:00',
      elapsed_seconds: 92,
      files: [],
      available_files: 0,
      failed_items: 0,
      completed_items: 1,
      total_items: 4,
      member_ids: ['run-demo-05'],
      attempts: [{ id: 'run-demo-05', status: 'waiting_login' }],
      action_run_id: 'run-demo-05',
    },
    {
      id: 'demo-tc-06',
      kind: 'download',
      title: '蓝橙全量人事档案与兼职价格同步',
      cities: ['广州', '深圳', '佛山', '东莞', '惠州', '上海'],
      datasets: ['lanorange_summary', 'rider_info'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'success',
      created_at: '2026-11-15T19:05:00+08:00',
      elapsed_seconds: 164,
      files: [
        { id: 'f06a', run_id: 'run-demo-06', name: '蓝橙_全量在职离职人事档案_20261115.xlsx', city: '广州', bytes: 6340000, available: true },
        { id: 'f06b', run_id: 'run-demo-06', name: '蓝橙_10月兼职协议价格总览.xlsx', city: '深圳', bytes: 2890120, available: true },
      ],
      available_files: 2,
      failed_items: 0,
      completed_items: 2,
      total_items: 2,
      member_ids: ['run-demo-06'],
      attempts: [{ id: 'run-demo-06', status: 'success' }],
      action_run_id: 'run-demo-06',
    },
    {
      id: 'demo-tc-07',
      kind: 'download',
      title: '商翼员工与本来人力灵工双平台全量导出',
      cities: ['广州', '深圳', '上海', '北京'],
      datasets: ['baize_employees', 'benlai_employees'],
      start: '2026-11-15',
      end: '2026-11-15',
      status: 'success',
      created_at: '2026-11-15T17:30:00+08:00',
      elapsed_seconds: 89,
      files: [
        { id: 'f07a', run_id: 'run-demo-07', name: '商翼_全量员工银行卡与绑定花名册.xlsx', city: '广州', bytes: 5120000, available: true },
        { id: 'f07b', run_id: 'run-demo-07', name: '本来人力_灵工结算签约档案.xlsx', city: '上海', bytes: 3240800, available: true },
      ],
      available_files: 2,
      failed_items: 0,
      completed_items: 2,
      total_items: 2,
      member_ids: ['run-demo-07'],
      attempts: [{ id: 'run-demo-07', status: 'success' }],
      action_run_id: 'run-demo-07',
    },
    {
      id: 'demo-tc-08',
      kind: 'download',
      title: '发薪平台商翼档案定时重采',
      cities: ['全国授权区域'],
      datasets: ['baize_employees'],
      start: '2026-11-16',
      end: '2026-11-16',
      status: 'running',
      created_at: '2026-11-16T09:42:00+08:00',
      elapsed_seconds: 48,
      files: [],
      available_files: 0,
      failed_items: 0,
      completed_items: 1,
      total_items: 2,
      member_ids: ['run-demo-08'],
      attempts: [{ id: 'run-demo-08', status: 'running' }],
      action_run_id: 'run-demo-08',
    },
    {
      id: 'demo-tc-09',
      kind: 'download',
      title: '灯塔日维度骑手分析与配送客诉明细',
      cities: ['杭州', '宁波'],
      datasets: ['rider_daily', 'detail_kesu', 'detail_reviews'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'success',
      created_at: '2026-11-15T15:10:00+08:00',
      elapsed_seconds: 245,
      files: [
        { id: 'f09a', run_id: 'run-demo-09', name: '杭州_宁波_10月灯塔日维度骑手分析.xlsx', city: '杭州', bytes: 7450000, available: true },
        { id: 'f09b', run_id: 'run-demo-09', name: '杭州_宁波_10月配送客诉差评明细.xlsx', city: '宁波', bytes: 1950400, available: true },
      ],
      available_files: 2,
      failed_items: 0,
      completed_items: 6,
      total_items: 6,
      member_ids: ['run-demo-09'],
      attempts: [{ id: 'run-demo-09', status: 'success' }],
      action_run_id: 'run-demo-09',
    },
    {
      id: 'demo-tc-10',
      kind: 'download',
      title: '灯塔配送订单明细与出勤合并（超时重跑）',
      cities: ['南京', '苏州'],
      datasets: ['detail_orders', 'xiaoxiang_attendance_detail'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'interrupted',
      created_at: '2026-11-15T12:18:00+08:00',
      elapsed_seconds: 312,
      files: [
        { id: 'f10a', run_id: 'run-demo-10', name: '南京_灯塔配送订单明细_part1.csv', city: '南京', bytes: 11200000, available: true },
      ],
      available_files: 1,
      failed_items: 1,
      completed_items: 2,
      total_items: 4,
      member_ids: ['run-demo-10'],
      attempts: [{ id: 'run-demo-10', status: 'interrupted' }],
      action_run_id: 'run-demo-10',
    },
    {
      id: 'demo-tc-11',
      kind: 'download',
      title: '灯塔骑手全量档案快照',
      cities: ['成都', '厦门', '泉州'],
      datasets: ['rider_archive'],
      start: '2026-11-14',
      end: '2026-11-14',
      status: 'success',
      created_at: '2026-11-14T20:15:00+08:00',
      elapsed_seconds: 76,
      files: [
        { id: 'f11a', run_id: 'run-demo-11', name: '灯塔_全量在职骑手档案快照_20261114.xlsx', city: '成都', bytes: 3780000, available: true },
      ],
      available_files: 1,
      failed_items: 0,
      completed_items: 3,
      total_items: 3,
      member_ids: ['run-demo-11'],
      attempts: [{ id: 'run-demo-11', status: 'success' }],
      action_run_id: 'run-demo-11',
    },
    {
      id: 'demo-tc-12',
      kind: 'generate',
      title: '骑手支付绑定与异常骑手跟进专项报表',
      cities: ['广州', '深圳', '佛山', '东莞'],
      datasets: ['payment_binding', 'abnormal_followup'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'success',
      created_at: '2026-11-15T10:35:00+08:00',
      elapsed_seconds: 128,
      files: [
        { id: 'f12a', run_id: 'run-demo-12', name: '专项_骑手支付绑定交叉核对表.xlsx', city: '广州', bytes: 1580000, available: true },
        { id: 'f12b', run_id: 'run-demo-12', name: '专项_异常骑手跟进处置清单.xlsx', city: '深圳', bytes: 890000, available: true },
      ],
      available_files: 2,
      failed_items: 0,
      completed_items: 2,
      total_items: 2,
      member_ids: ['run-demo-12'],
      attempts: [{ id: 'run-demo-12', status: 'success' }],
      action_run_id: 'run-demo-12',
    },
    {
      id: 'demo-tc-13',
      kind: 'generate',
      title: '异常骑手整理全城汇总报表',
      cities: ['全部城市'],
      datasets: ['abnormal_riders'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'error',
      created_at: '2026-11-14T16:40:00+08:00',
      elapsed_seconds: 54,
      files: [],
      available_files: 0,
      failed_items: 1,
      completed_items: 0,
      total_items: 1,
      member_ids: ['run-demo-13'],
      attempts: [{ id: 'run-demo-13', status: 'error' }],
      action_run_id: 'run-demo-13',
    },
    {
      id: 'demo-tc-14',
      kind: 'payroll',
      batch_id: 'batch-demo-01',
      title: '广州-11月上半月兼职薪资核算交付包',
      cities: ['广州'],
      datasets: ['payroll'],
      start: '2026-11-01',
      end: '2026-11-15',
      status: 'success',
      created_at: '2026-11-16T09:14:22+08:00',
      elapsed_seconds: 142,
      files: [
        { id: 'f14a', run_id: 'run-demo-14', name: '广州-11月上半月兼职算薪_成品交付包.zip', city: '广州', bytes: 3420000, available: true },
      ],
      available_files: 1,
      failed_items: 0,
      completed_items: 1,
      total_items: 1,
      member_ids: ['run-demo-14'],
      attempts: [{ id: 'run-demo-14', status: 'success' }],
      action_run_id: 'run-demo-14',
    },
    {
      id: 'demo-tc-15',
      kind: 'payroll',
      batch_id: 'batch-demo-05',
      title: '惠州-10月全月兼职算薪（待人工确认扣款）',
      cities: ['惠州'],
      datasets: ['payroll'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'waiting_manual',
      created_at: '2026-11-16T08:50:44+08:00',
      elapsed_seconds: 268,
      files: [],
      available_files: 0,
      failed_items: 0,
      completed_items: 0,
      total_items: 1,
      member_ids: ['run-demo-15'],
      attempts: [{ id: 'run-demo-15', status: 'waiting_manual' }],
      action_run_id: 'run-demo-15',
    },
    {
      id: 'demo-tc-16',
      kind: 'payroll',
      batch_id: 'batch-demo-07',
      title: '中山-10月全月兼职算薪（源表拉取失败）',
      cities: ['中山'],
      datasets: ['payroll'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'error',
      created_at: '2026-11-16T08:20:39+08:00',
      elapsed_seconds: 39,
      files: [],
      available_files: 0,
      failed_items: 1,
      completed_items: 0,
      total_items: 1,
      member_ids: ['run-demo-16'],
      attempts: [{ id: 'run-demo-16', status: 'error' }],
      action_run_id: 'run-demo-16',
    },
    {
      id: 'demo-tc-17',
      kind: 'approval',
      price_id: 'demo-apr-batch-01',
      title: '蓝橙兼职价格工作流批量审批回执（6条）',
      cities: ['广州', '深圳', '佛山', '东莞', '上海'],
      datasets: ['lanorange_summary'],
      start: '2026-11-01',
      end: '2026-11-15',
      status: 'partial',
      created_at: '2026-11-16T08:30:12+08:00',
      elapsed_seconds: 63,
      files: [
        { id: 'f17a', run_id: 'run-demo-17', name: '蓝橙价格审批回执_20261116.csv', city: '广州', bytes: 42800, available: true },
      ],
      available_files: 1,
      failed_items: 1,
      completed_items: 5,
      total_items: 6,
      member_ids: ['run-demo-17'],
      attempts: [{ id: 'run-demo-17', status: 'partial' }],
      action_run_id: 'run-demo-17',
    },
    {
      id: 'demo-tc-18',
      kind: 'price-export',
      price_id: 'demo-price-exp-01',
      title: '蓝橙待审每日价格纵表透视导出（14城）',
      cities: ['广州', '深圳', '佛山', '东莞', '上海', '杭州'],
      datasets: ['lanorange_summary'],
      start: '2026-11-01',
      end: '2026-11-15',
      status: 'success',
      created_at: '2026-11-15T21:10:00+08:00',
      elapsed_seconds: 105,
      files: [
        { id: 'f18a', run_id: 'run-demo-18', name: '蓝橙待审每日价格汇总_20261115.xlsx', city: '广州', bytes: 2150400, available: true },
      ],
      available_files: 1,
      failed_items: 0,
      completed_items: 1,
      total_items: 1,
      member_ids: ['run-demo-18'],
      attempts: [{ id: 'run-demo-18', status: 'success' }],
      action_run_id: 'run-demo-18',
    },
    {
      id: 'demo-tc-19',
      kind: 'download',
      title: '风神物资租用登记与绑定排查（已取消）',
      cities: ['天津', '三亚'],
      datasets: ['goods_rent', 'receive_account'],
      start: '2026-10-01',
      end: '2026-10-31',
      status: 'cancelled',
      created_at: '2026-11-13T11:05:00+08:00',
      elapsed_seconds: 27,
      files: [],
      available_files: 0,
      failed_items: 0,
      completed_items: 0,
      total_items: 4,
      member_ids: ['run-demo-19'],
      attempts: [{ id: 'run-demo-19', status: 'cancelled' }],
      action_run_id: 'run-demo-19',
    },
    {
      id: 'demo-tc-20',
      kind: 'download',
      title: '蓝橙单日变更补采核对（无新增记录）',
      cities: ['泉州'],
      datasets: ['invitation_records'],
      start: '2026-11-15',
      end: '2026-11-15',
      status: 'empty',
      created_at: '2026-11-15T22:00:00+08:00',
      elapsed_seconds: 19,
      files: [],
      available_files: 0,
      failed_items: 0,
      completed_items: 1,
      total_items: 1,
      member_ids: ['run-demo-20'],
      attempts: [{ id: 'run-demo-20', status: 'empty' }],
      action_run_id: 'run-demo-20',
    },
  ];
}

export interface DemoDeductionProfilePayload {
  version: number;
  columns: string[];
  cities: DeductionEntry[];
  entries: DeductionEntry[];
  directoryCities: Array<{ id: string; name: string; station_count: number }>;
}

export function createDemoDeductionProfile(): DemoDeductionProfilePayload {
  const columns = [...CONFIG_RULE_COLUMNS];

  const cityDefs: Array<{
    id: string;
    name: string;
    stationNames: string[];
    cityDefaultMode: 'configured' | 'zero' | 'pending';
    stationMix: 'all_ready' | 'mixed' | 'all_zero' | 'all_pending';
    baseAmounts: Partial<Record<(typeof CONFIG_RULE_COLUMNS)[number], number>>;
  }> = [
    {
      id: '440100',
      name: '广州',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 200, 物流责: 30, 不准时单: 5, 超时: 3, T10: 10, 工具费: 150, 代领费率: 0.06, 安全基金: 3, 使用费: 2, 非蜂卡: 5, 月费: 60 },
      stationNames: ['天河体育中心站_新专送', '海珠客村站_新专送', '番禺市桥站_新专送', '白云嘉禾站_新专送', '越秀北京路站_新专送', '荔湾上下九站_新专送', '黄埔科学城站_新专送', '增城新塘站_新专送', '花都广场站_新专送', '南沙金洲站_新专送', '天河五山站_新专送', '白云同和站_新专送'],
    },
    {
      id: '440300',
      name: '深圳',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 60, 差评: 25, 违规虚假: 200, 物流责: 35, 不准时单: 6, 超时: 4, T10: 12, 工具费: 180, 代领费率: 0.06, 安全基金: 3, 使用费: 2.5, 非蜂卡: 5, 月费: 80 },
      stationNames: ['南山科技园站_新专送', '福田华强北站_新专送', '宝安西乡站_新专送', '龙岗布吉站_新专送', '龙华民治站_新专送', '罗湖东门站_新专送', '南山蛇口站_新专送', '福田车公庙站_新专送', '光明凤凰城站_新专送', '盐田沙头角站_新专送', '坪山中心站_新专送', '宝安沙井站_新专送'],
    },
    {
      id: '440600',
      name: '佛山',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 50, 差评: 15, 违规虚假: 150, 物流责: 25, 不准时单: 4, 超时: 2, T10: 8, 工具费: 120, 代领费率: 0.05, 安全基金: 2, 使用费: 2, 非蜂卡: 3, 月费: 50 },
      stationNames: ['禅城祖庙站_新专送', '顺德大良站_新专送', '南海桂城站_新专送', '南海千灯湖站_新专送', '顺德容桂站_新专送', '三水西南站_新专送', '高明荷城站_新专送', '禅城石湾站_新专送', '南海狮山站_新专送', '顺德北滘站_新专送', '禅城张槎站_新专送'],
    },
    {
      id: '441900',
      name: '东莞',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 180, 物流责: 30, 不准时单: 5, 超时: 3, T10: 10, 工具费: 150, 代领费率: 0.05, 安全基金: 3, 使用费: 2, 非蜂卡: 5, 月费: 60 },
      stationNames: ['南城鸿福站_新专送', '东城世博站_新专送', '虎门万达站_新专送', '长安万科站_新专送', '厚街康乐站_新专送', '松山湖园区站_新专送', '寮步香市站_新专送', '常平振兴站_新专送', '塘厦花园街站_新专送', '凤岗永盛站_新专送', '大朗松佛站_新专送'],
    },
    {
      id: '441300',
      name: '惠州',
      cityDefaultMode: 'pending',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 40, 差评: 15, 违规虚假: 150, 物流责: 20, 不准时单: 4, 超时: 2, T10: 8, 工具费: 100, 代领费率: 0.05, 安全基金: 2, 使用费: 1.5, 非蜂卡: 3, 月费: 40 },
      stationNames: ['惠城江北站_新专送', '惠城麦地站_新专送', '惠阳淡水站_新专送', '大亚湾万达站_新专送', '仲恺陈江站_新专送', '博罗罗阳站_新专送', '惠东平山站_新专送', '惠城水口站_新专送', '惠城河南岸站_新专送', '仲恺沥林站_新专送'],
    },
    {
      id: '310100',
      name: '上海',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 80, 差评: 30, 违规虚假: 300, 物流责: 40, 不准时单: 8, 超时: 5, T10: 15, 工具费: 200, 代领费率: 0.06, 安全基金: 3, 使用费: 3, 非蜂卡: 5, 月费: 90 },
      stationNames: ['浦东陆家嘴站_新专送', '徐汇漕河泾站_新专送', '静安南京西路站_新专送', '黄浦人广站_新专送', '闵行莘庄站_新专送', '长宁中山公园站_新专送', '普陀环球港站_新专送', '虹口四川北路站_新专送', '杨浦五角场站_新专送', '宝山万达站_新专送', '松江万达站_新专送', '嘉定新城站_新专送'],
    },
    {
      id: '110100',
      name: '北京',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 80, 差评: 30, 违规虚假: 250, 物流责: 40, 不准时单: 7, 超时: 4, T10: 12, 工具费: 180, 代领费率: 0.06, 安全基金: 3, 使用费: 3, 非蜂卡: 5, 月费: 85 },
      stationNames: ['朝阳三里屯站_新专送', '海淀中关村站_新专送', '朝阳望京站_新专送', '海淀五道口站_新专送', '西城金融街站_新专送', '东城王府井站_新专送', '丰台科技园站_新专送', '通州万达站_新专送', '大兴亦庄站_新专送', '昌平回龙观站_新专送', '石景山万达站_新专送'],
    },
    {
      id: '330100',
      name: '杭州',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 60, 差评: 20, 违规虚假: 200, 物流责: 30, 不准时单: 5, 超时: 3, T10: 10, 工具费: 150, 代领费率: 0.06, 安全基金: 3, 使用费: 2, 非蜂卡: 4, 月费: 60 },
      stationNames: ['西湖黄龙站_新专送', '滨江物联网站_新专送', '余杭未来科技城站_新专送', '拱墅武林门站_新专送', '上城湖滨站_新专送', '萧山万象汇站_新专送', '钱塘下沙站_新专送', '临平银泰站_新专送', '西湖城西站_新专送', '滨江彩虹城站_新专送', '余杭良渚站_新专送'],
    },
    {
      id: '330200',
      name: '宁波',
      cityDefaultMode: 'zero',
      stationMix: 'all_zero',
      baseAmounts: {},
      stationNames: ['鄞州万达站_新专送', '海曙天一站_新专送', '江北来福士站_新专送', '镇海吾悦站_新专送', '北仑银泰站_新专送', '鄞州南部商务站_新专送', '奉化万达站_新专送', '慈溪爱琴海站_新专送', '余姚万达站_新专送', '海曙高桥站_新专送'],
    },
    {
      id: '320100',
      name: '南京',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 180, 物流责: 25, 不准时单: 5, 超时: 3, T10: 10, 工具费: 140, 代领费率: 0.05, 安全基金: 3, 使用费: 2, 非蜂卡: 4, 月费: 55 },
      stationNames: ['鼓楼新街口站_新专送', '建邺河西站_新专送', '玄武珠江路站_新专送', '秦淮夫子庙站_新专送', '雨花台软件谷站_新专送', '江宁百家湖站_新专送', '栖霞仙林站_新专送', '浦口江北站_新专送', '鼓楼龙江站_新专送', '江宁东山站_新专送', '建邺奥体站_新专送'],
    },
    {
      id: '320500',
      name: '苏州',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 180, 物流责: 25, 不准时单: 5, 超时: 3, T10: 10, 工具费: 150, 代领费率: 0.05, 安全基金: 3, 使用费: 2, 非蜂卡: 4, 月费: 60 },
      stationNames: ['园区湖东站_新专送', '姑苏观前站_新专送', '高新区狮山站_新专送', '园区湖西站_新专送', '吴中木渎站_新专送', '相城高铁站_新专送', '吴江太湖新城站_新专送', '昆山玉山站_新专送', '常熟方塔站_新专送', '张家港杨舍站_新专送'],
    },
    {
      id: '510100',
      name: '成都',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 50, 差评: 15, 违规虚假: 150, 物流责: 20, 不准时单: 4, 超时: 2, T10: 8, 工具费: 120, 代领费率: 0.05, 安全基金: 2, 使用费: 2, 非蜂卡: 3, 月费: 50 },
      stationNames: ['高新天府三街站_新专送', '锦江春熙路站_新专送', '武侯桐梓林站_新专送', '青羊宽窄巷站_新专送', '成华建设路站_新专送', '金牛万达站_新专送', '天府新区华阳站_新专送', '双流东升站_新专送', '龙泉驿万达站_新专送', '温江光华站_新专送', '郫都犀浦站_新专送'],
    },
    {
      id: '350200',
      name: '厦门',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 180, 物流责: 30, 不准时单: 5, 超时: 3, T10: 10, 工具费: 150, 代领费率: 0.05, 安全基金: 3, 使用费: 2, 非蜂卡: 4, 月费: 60 },
      stationNames: ['思明中山路站_新专送', '思明软件园站_新专送', '湖里万达站_新专送', '湖里SM广场站_新专送', '集美万达站_新专送', '海沧阿罗海站_新专送', '同安乐海站_新专送', '翔安汇景站_新专送', '思明莲坂站_新专送', '湖里五缘湾站_新专送'],
    },
    {
      id: '350500',
      name: '泉州',
      cityDefaultMode: 'pending',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 40, 差评: 15, 违规虚假: 150, 物流责: 20, 不准时单: 4, 超时: 2, T10: 8, 工具费: 110, 代领费率: 0.05, 安全基金: 2, 使用费: 1.5, 非蜂卡: 3, 月费: 45 },
      stationNames: ['丰泽浦西万达站_新专送', '鲤城西街站_新专送', '晋江万达站_新专送', '石狮泰禾站_新专送', '南安成功站_新专送', '丰泽城东站_新专送', '洛江万安站_新专送', '晋江池店站_新专送', '惠安螺城站_新专送', '丰泽领SHOW站_新专送'],
    },
    {
      id: '120100',
      name: '天津',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 200, 物流责: 30, 不准时单: 5, 超时: 3, T10: 10, 工具费: 140, 代领费率: 0.06, 安全基金: 3, 使用费: 2, 非蜂卡: 4, 月费: 60 },
      stationNames: ['和平滨江道站_新专送', '南开大悦城站_新专送', '河西万象城站_新专送', '河东爱琴海站_新专送', '河北意风区站_新专送', '滨海泰达站_新专送', '西青大学城站_新专送', '津南吾悦站_新专送', '武清佛罗伦萨站_新专送', '北辰永旺站_新专送'],
    },
    {
      id: '440400',
      name: '珠海',
      cityDefaultMode: 'configured',
      stationMix: 'all_ready',
      baseAmounts: { 投诉: 50, 差评: 20, 违规虚假: 180, 物流责: 25, 不准时单: 5, 超时: 3, T10: 10, 工具费: 130, 代领费率: 0.05, 安全基金: 3, 使用费: 2, 非蜂卡: 4, 月费: 50 },
      stationNames: ['香洲华发商都站_新专送', '香洲拱北站_新专送', '香洲吉大站_新专送', '香洲前山站_新专送', '横琴励骏站_新专送', '斗门大信站_新专送', '金湾航空新城站_新专送', '高新唐家湾站_新专送', '香洲柠溪站_新专送', '香洲夏湾站_新专送'],
    },
    {
      id: '442000',
      name: '中山',
      cityDefaultMode: 'pending',
      stationMix: 'all_pending',
      baseAmounts: {},
      stationNames: ['东区利和广场站_新专送', '石岐大信站_新专送', '西区天悦城站_新专送', '火炬太阳城站_新专送', '小榄百汇站_新专送', '古镇利和站_新专送', '三乡大润发站_新专送', '坦洲汇昌站_新专送', '南区悦来站_新专送', '黄圃新丰站_新专送'],
    },
    {
      id: '440700',
      name: '江门',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 45, 差评: 15, 违规虚假: 150, 物流责: 20, 不准时单: 4, 超时: 2, T10: 8, 工具费: 100, 代领费率: 0.05, 安全基金: 2, 使用费: 1.5, 非蜂卡: 3, 月费: 45 },
      stationNames: ['蓬江汇悦城站_新专送', '蓬江万达站_新专送', '江海广场站_新专送', '新会美吉特站_新专送', '台山昌大昌站_新专送', '开平东汇城站_新专送', '鹤山广场站_新专送', '恩平锦江站_新专送', '蓬江地王站_新专送', '新会冈州站_新专送'],
    },
    {
      id: '440500',
      name: '汕头',
      cityDefaultMode: 'configured',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 40, 差评: 15, 违规虚假: 150, 物流责: 20, 不准时单: 4, 超时: 2, T10: 8, 工具费: 100, 代领费率: 0.05, 安全基金: 2, 使用费: 1.5, 非蜂卡: 3, 月费: 40 },
      stationNames: ['龙湖苏宁站_新专送', '金平万达站_新专送', '龙湖群光站_新专送', '澄海奥飞站_新专送', '潮阳卜蜂站_新专送', '濠江中信站_新专送', '金平小公园站_新专送', '龙湖东海岸站_新专送', '潮南峡山站_新专送', '金平东厦站_新专送'],
    },
    {
      id: '460200',
      name: '三亚',
      cityDefaultMode: 'zero',
      stationMix: 'mixed',
      baseAmounts: { 投诉: 30, 差评: 10, 违规虚假: 100, 物流责: 15, 不准时单: 3, 超时: 2, T10: 5, 工具费: 80, 代领费率: 0.04, 安全基金: 2, 使用费: 1, 非蜂卡: 2, 月费: 30 },
      stationNames: ['吉阳大东海站_新专送', '天涯海月广场站_新专送', '吉阳海棠湾站_新专送', '吉阳亚龙湾站_新专送', '天涯凤凰站_新专送', '崖州中心站_新专送', '育才旅游站_新专送', '吉阳迎宾路站_新专送', '天涯红沙站_新专送', '天涯三亚湾站_新专送'],
    },
  ];

  const makeBlankRow = () => Object.fromEntries(columns.map(col => [col, null]));
  const makeZeroRow = () => Object.fromEntries(columns.map(col => [col, 0]));
  const makeConfiguredRow = (base: Record<string, number>, delta = 0) =>
    Object.fromEntries(
      columns.map(col => {
        const v = base[col] ?? 0;
        if (col === '代领费率') return [col, v];
        return [col, v > 0 ? Math.max(0, v + delta) : 0];
      }),
    );

  const cities: DeductionEntry[] = [];
  const entries: DeductionEntry[] = [];
  const directoryCities: Array<{ id: string; name: string; station_count: number }> = [];

  cityDefs.forEach((cityDef, cityIdx) => {
    const baseFull = Object.fromEntries(columns.map(c => [c, cityDef.baseAmounts[c as (typeof CONFIG_RULE_COLUMNS)[number]] ?? 0]));
    const cityRow =
      cityDef.cityDefaultMode === 'zero'
        ? makeZeroRow()
        : cityDef.cityDefaultMode === 'pending'
          ? makeBlankRow()
          : baseFull;

    const cityProblems =
      cityIdx % 3 === 0
        ? [
            { problem_type: '虚假送达', reason_keyword: '未送达点完成', amount: 50 },
            { problem_type: '态度投诉', reason_keyword: '服务纠纷', amount: 30 },
          ]
        : [];

    cities.push({
      key: `fengshen:city:${cityDef.id}`,
      station: { platform: 'fengshen', city_id: cityDef.id, city: cityDef.name, id: '*', name: '城市统一扣款' },
      configured: cityDef.cityDefaultMode !== 'pending',
      legacy: cityIdx === 13,
      zero_confirmed: cityDef.cityDefaultMode === 'zero',
      edited: false,
      row: cityRow,
      problem_rules: cityProblems,
    } as any);

    directoryCities.push({
      id: cityDef.id,
      name: cityDef.name,
      station_count: cityDef.stationNames.length,
    });

    cityDef.stationNames.forEach((stationName, stIdx) => {
      const stationId = `${cityDef.id.slice(0, 4)}${String(stIdx + 1).padStart(2, '0')}`;
      const isOverride =
        (cityDef.stationMix === 'all_ready' && stIdx < 3) ||
        (cityDef.stationMix === 'mixed' && stIdx < 2) ||
        (cityDef.name === '三亚' && stIdx < 2);
      const isZeroCity = cityDef.stationMix === 'all_zero' || (cityDef.name === '三亚' && !isOverride);
      const isPending =
        cityDef.stationMix === 'all_pending' ||
        (cityDef.stationMix === 'mixed' && stIdx >= cityDef.stationNames.length - 3 && cityDef.name !== '三亚');
      const isLegacy = cityIdx === 2 && stIdx === 8 || cityIdx === 13 && stIdx >= 4 && stIdx < 7;
      const isEditedDraft = cityIdx === 3 && stIdx === 2;

      let row: Record<string, any>;
      let configured = true;
      let inherited_city = false;
      let station_override = false;
      let zero_confirmed = false;
      let legacy = isLegacy;

      if (isPending || isLegacy) {
        row = makeBlankRow();
        configured = false;
      } else if (isOverride) {
        row = makeConfiguredRow(baseFull, (stIdx + 1) * 5);
        station_override = true;
      } else if (isZeroCity) {
        row = makeZeroRow();
        zero_confirmed = true;
        inherited_city = cityDef.cityDefaultMode === 'zero';
      } else if (cityDef.cityDefaultMode === 'pending') {
        row = makeConfiguredRow(baseFull, 0);
        station_override = true;
      } else {
        row = { ...cityRow };
        inherited_city = true;
      }

      const stProblems =
        stIdx === 0 && cityIdx < 6
          ? [{ problem_type: '餐损责任', reason_keyword: '洒漏超时', amount: 25 }]
          : [];

      entries.push({
        key: `fengshen:station:${stationId}`,
        station: {
          platform: 'fengshen',
          city_id: cityDef.id,
          city: cityDef.name,
          id: stationId,
          name: stationName,
        },
        configured,
        legacy,
        inherited_city,
        station_override,
        zero_confirmed,
        edited: isEditedDraft,
        row,
        problem_rules: stProblems,
      } as any);
    });
  });

  return {
    version: 20261116,
    columns,
    cities,
    entries,
    directoryCities,
  };
}

export type PayrollQueueFilterTab = 'all' | 'active' | 'waiting' | 'completed' | 'issue';

export function filterPayrollQueueTasks(
  tasks: PayrollQueueTask[],
  filterTab: PayrollQueueFilterTab,
  keyword: string,
): PayrollQueueTask[] {
  const q = keyword.trim().toLowerCase();
  return tasks.filter(task => {
    if (filterTab === 'active' && !['queued', 'preparing', 'calculating', 'stopping'].includes(task.status)) {
      return false;
    }
    if (filterTab === 'waiting' && task.status !== 'waiting_confirmation') {
      return false;
    }
    if (filterTab === 'completed' && task.status !== 'completed') {
      return false;
    }
    if (filterTab === 'issue' && !['error', 'cancelled', 'interrupted'].includes(task.status)) {
      return false;
    }
    if (!q) return true;
    const hay = `${task.template_name || ''} ${task.plan?.city || ''} ${task.batch_id || ''} ${task.current_action || ''}`.toLowerCase();
    return hay.includes(q);
  });
}

export function filterTaskCenterRecords(
  records: DemoTaskCenterRecord[],
  params: {
    q?: string;
    status?: string;
    system?: string;
    kind?: string;
    from?: string;
    to?: string;
    archivedIds?: Set<string>;
    archivedOnly?: boolean;
  },
): {
  items: DemoTaskCenterRecord[];
  counts: Record<string, number>;
} {
  const archivedIds = params.archivedIds || new Set<string>();
  const q = (params.q || '').trim().toLowerCase();
  const baseVisible = records.filter(r => (params.archivedOnly ? archivedIds.has(r.id) : !archivedIds.has(r.id)));

  const activeSet = new Set(['queued', 'running', 'waiting_login', 'waiting_manual', 'cancelling', 'preparing', 'stopping']);
  const attentionSet = new Set(['waiting_login', 'waiting_manual', 'partial', 'error', 'interrupted', 'empty']);

  const counts = {
    all: baseVisible.length,
    active: baseVisible.filter(r => activeSet.has(r.status)).length,
    attention: baseVisible.filter(r => attentionSet.has(r.status)).length,
    success: baseVisible.filter(r => r.status === 'success').length,
  };

  const inferSys = (r: DemoTaskCenterRecord) => {
    if (r.kind === 'approval' || r.kind === 'price-export') return ['lanorange'];
    if (r.kind === 'payroll') return ['fengshen', 'lanorange'];
    const out: string[] = [];
    for (const id of r.datasets) {
      if (id === 'baize_employees') out.push('baize');
      else if (id === 'benlai_employees') out.push('benlai');
      else if (id === 'lanorange_summary') out.push('lanorange');
      else if (['rider_daily', 'rider_archive', 'detail_orders', 'detail_kesu', 'detail_reviews', 'rider_order_detail', 'xiaoxiang_attendance_detail'].includes(id)) out.push('xiaoxiang');
      else out.push('fengshen');
    }
    return out;
  };

  const items = baseVisible.filter(r => {
    if (params.status === 'active' && !activeSet.has(r.status)) return false;
    if (params.status === 'attention' && !attentionSet.has(r.status)) return false;
    if (params.status === 'success' && r.status !== 'success') return false;
    if (params.kind && r.kind !== params.kind) return false;
    if (params.system && !inferSys(r).includes(params.system)) return false;
    const createdDay = (r.created_at || '').slice(0, 10);
    if (params.from && createdDay && createdDay < params.from) return false;
    if (params.to && createdDay && createdDay > params.to) return false;
    if (q) {
      const hay = [
        r.id,
        r.title || '',
        r.cities.join(' '),
        r.datasets.join(' '),
        ...r.files.map(f => f.name),
      ]
        .join(' ')
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  return { items, counts };
}

export type ApprovalEligibilityFilter = 'all' | 'eligible' | 'blocked';

export function filterApprovalTasks<
  T extends {
    businessCode?: string;
    id: string;
    cityName?: string;
    siteName?: string;
    nodeName?: string;
    createByName?: string;
    period_start?: string;
    settle_month?: string;
    reason: string;
  },
>(
  rows: T[],
  params: {
    scopeCities: string[];
    scopeMonths: string[];
    scopeSite: string;
    eligibility?: ApprovalEligibilityFilter;
    keyword?: string;
  },
): T[] {
  const q = (params.keyword || '').trim().toLowerCase();
  const eligibility = params.eligibility || 'all';
  return rows.filter(r => {
    if (params.scopeCities.length && !params.scopeCities.includes(r.cityName || '')) return false;
    if (
      params.scopeMonths.length &&
      !params.scopeMonths.includes((r.settle_month || r.period_start || '').slice(0, 7))
    ) {
      return false;
    }
    if (params.scopeSite && JSON.stringify([r.cityName, r.siteName]) !== params.scopeSite) {
      return false;
    }
    if (eligibility === 'eligible' && r.reason) return false;
    if (eligibility === 'blocked' && !r.reason) return false;
    if (q) {
      const hay = `${r.businessCode || ''} ${r.id} ${r.cityName || ''} ${r.siteName || ''} ${r.nodeName || ''} ${r.createByName || ''} ${r.reason || ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

