export interface Theme {
  name: string;
  runner: string;
  target: string;
  spin_frames: string[];
  icon: string;
  title: string;
  logo: string;
  sub: string;
  kite: string;
  term_head: string;
  log_init: string;
  footer: string;
  lbl_city: string;
  lbl_type: string;
  lbl_config: string;
  lbl_source: string;
  lbl_workspace: string;
  btn_config: string;
  btn_source: string;
  btn_workspace: string;
  btn_run: string;
  btn_run_ing: string;
  btn_success: string;
  btn_error: string;
  tab_task: string;
  tab_output: string;
  btn_add_root: string;
}

export const THEMES: Theme[] = [
  {
    name: 'Aegis',
    runner: '▰',
    target: '▰',
    spin_frames: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
    icon: '🧮',
    title: 'AEGIS 工作流管控端',
    logo: '薪酬核算中心',
    sub: '',
    kite: '◈',
    term_head: '处理进度',
    log_init: '日志初始化成功，等待任务...',
    footer: '系统状态: 最佳 // 上行链路加密',
    lbl_city: '区域设置',
    lbl_type: '任务类型',
    lbl_config: '参数配置文件',
    lbl_source: '源数据目录',
    lbl_workspace: '工作空间',
    btn_config: '选择配置',
    btn_source: '选择目录',
    btn_workspace: '选择工作',
    btn_run: '提交执行',
    btn_run_ing: '正在处理中...',
    btn_success: '执行成功',
    btn_error: '执行失败',
    tab_task: '执行队列',
    tab_output: '输出结果',
    btn_add_root: '挂载新卷',
  },
];
