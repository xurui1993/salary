# 业务资料留存、模板与核算复核

## 业务资料不会因时间过期而自动删除

服务启动及定时任务不再依据目录修改时间清理 `data`、`uploads`。任务中心的“移出列表”仍只整理显示，原始资料、核算批次、文件索引与成品保留。

## 备份与恢复

使用项目虚拟环境，先关闭系统服务。维护工具持有与服务共用的启动锁，避免备份期间重新启动服务。

```powershell
.\.venv\Scripts\python.exe scripts/business_backup.py plan
.\.venv\Scripts\python.exe scripts/business_backup.py backup --destination runtime/business_backups --apply
.\.venv\Scripts\python.exe scripts/business_backup.py verify --snapshot runtime/business_backups/实际备份目录
```

默认只预览；`--apply` 才执行备份或恢复。备份覆盖项目内 `data`、`uploads`、`outputs`、`system_templates`、任务库、内部工作资料及平台会话。锁、未完成临时文件和 SQLite 日志文件列入明确的排除清单；SQLite 通过备份接口生成一致快照并检查完整性。每个文件记录字节数与 SHA256，完整验证后才发布备份；失败现场留在 `.partial` 目录，不标记为完整备份。

如果部署设置了项目外的生成目录或其他外部业务目录，须另行纳入备份计划；工具不会猜测并扫描其他磁盘。备份含敏感业务资料与会话，应放在受控位置，不提交 GitHub。Windows 加密会话不保证在其他用户或电脑上直接恢复登录。

恢复只能写入一个**尚不存在的新目录**，原业务目录不会被覆盖：

```powershell
.\.venv\Scripts\python.exe scripts/business_backup.py restore --snapshot runtime/business_backups/实际备份目录 --target runtime/recovered_business
.\.venv\Scripts\python.exe scripts/business_backup.py restore --snapshot runtime/business_backups/实际备份目录 --target runtime/recovered_business --apply
```

恢复前验证备份，复制后逐文件再次校验。确认资料、数据库和配置后，维护人员可在停服状态下规划切换；恢复业务资料与回退程序代码是两件独立操作。

## 模板

`backend/template_library.py` 登记当前13份模板及适用业务。仅允许下载登记且存在、结构有效的原模板；缺失或损坏明确报错，不从 `data` 回退，不自动生成示例模板，也不修复或覆盖原件。

模板中心展示实际内容标识。它是文件 SHA256 的短标识，不是业务审核版本。新增或替换模板需要先验证其申请名单结构和适用范围，再维护登记信息。用户上传申请表仍沿用既有城市、期间、骑手ID及业务资料检查，不更改工资规则。

## 核算复核

新核算保留统一复核摘要，页面显示“已生成·待人工复核”。摘要列出申请记录、申请骑手ID去重数、引擎原统计、无单价、未绑定、拦截记录、完全相同的申请行及本次明确不提供的资料。缺少统计显示“未统计”，不推断为零。

申请记录数、去重骑手数和引擎处理实体数口径不同，不相减推断“漏人”；配送导入记录数不作为去重完成单量。重复申请仅提示原文件和行位置，不自动删除。异常沿用工作簿中的明细表，摘要同时记录来源文件校验值、申请模板及扣款快照内容标识。

新核算将“核算复核清单”直接写入工资表，保留原类别并新增提供方，状态显示中文，校验码只存内部批次记录。成品仅含工资表和蓝橙无单价&未绑名单两份 Excel。历史独立复核文件保持保留；重新打开历史批次可查看已保存摘要，旧批次没有摘要时明确提示，不补造统计。

运行前输入哈希验证只证明采用了已保存的输入。生成完成、统计为零或文件校验通过均不代表业务验收、公式重算完成或已经发薪，仍需使用 Excel/WPS 重算并人工核对金额与业务范围。
