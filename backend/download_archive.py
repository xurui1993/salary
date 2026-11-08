"""Stable, Windows-safe archive names and human-readable download receipts."""

import datetime as dt
import os
from pathlib import Path
import re
import uuid
from lanorange_catalog import DATASETS as LANORANGE_DATASETS, months_contiguous, platform_months


BEIJING = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
ARCHIVE_VERSION = 1
LABELS = {
    'invitation_records':'邀请记录','invitation_summary':'邀请记录汇总','attendance_detail':'骑手出勤明细',
    'baize_employees': '白泽员工资料',
    'rider_daily': '日维度骑手分析',
    'detail_orders': '配送订单明细',
    'detail_kesu': '配送客诉明细',
    'detail_reviews': '配送评价明细',
    'rider_archive': '骑手档案',
    'rider_order_detail': '骑手订单明细',
    'xiaoxiang_attendance_detail': '骑手出勤明细',
    'lanorange_summary': '蓝橙资料汇总',
    "delivery_fee": "配送费", "penalty": "违规扣款",
    "rider_monthly": "风神骑手月度UB账单", "fraud": "欺诈单", "problem": "问题单",
    "delivery_waybill": "运单数据",
    "receive_account": "骑手风神绑定", "rider_detail": "骑手数据明细", "rider_info": "骑手信息",
    "payment_binding": "骑手支付绑定", "goods_rent": "物资租用登记",
    "abnormal_followup": "异常骑手跟进", "abnormal_riders": "异常骑手整理",
    **{key: '蓝橙' + value[0] for key, value in LANORANGE_DATASETS.items()},
}
MONTHLY = frozenset({"rider_monthly", "receive_account", "abnormal_followup"})
# 生成工作簿按「城市 + 业务月份 + 名称 + 生成日期MMDD」命名。
WORKBOOK_TITLES = {"abnormal_followup": "异常骑手跟进明细表",
                   "abnormal_riders": "异常骑手整理明细表"}
_MONTHLY_WORKBOOKS = MONTHLY | {"payment_binding"}
_NO_PERIOD_WORKBOOKS = frozenset({"rider_info", "goods_rent", "invitation_records", "invitation_summary",
                                   "lanorange_summary", "abnormal_riders", "baize_employees", "rider_archive"}) | frozenset(LANORANGE_DATASETS)
_DETAIL_WORKBOOKS = frozenset({"detail_orders", "detail_kesu", "detail_reviews"})
_RANGE_WORKBOOKS = frozenset({"rider_order_detail", "xiaoxiang_attendance_detail"})
_EXCEL_SUFFIXES = frozenset({".xlsx", ".xls"})
STATUSES = {"queued": "排队中", "running": "执行中", "waiting_login": "等待登录",
            "cancelling": "取消中", "cancelled": "已取消", "success": "已完成",
            "partial": "部分完成", "error": "失败", "interrupted": "服务重启中断"}
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)
_PRIVATE = re.compile(
    r"https?://|wss?://|[A-Za-z]:[\\/]|\\\\|(?<!\d)1[3-9]\d{9}(?!\d)|"
    r"(?<!\d)\d{17}[\dXx](?!\d)|\b(?:token|cookie|authorization|password|secret|sms_code)\s*[=:]", re.I)


def archive_component(value):
    """Reject unsafe city/path labels rather than silently merging two names."""
    if (not isinstance(value, str) or not value or len(value) > 80
            or value in (".", "..") or value[-1:] in (" ", ".")
            or value != value.strip() or _RESERVED.match(value)
            or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"/\\|?*' for char in value)):
        raise ValueError("归档名称含无效路径字符，请检查城市配置")
    return value


def beijing_time(value=None):
    if value is None:
        value = dt.datetime.now(dt.timezone.utc)
    elif isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("归档时间必须包含时区")
    return value.astimezone(BEIJING)


def archive_relative_dir(run_id, created_at, cities, label=None):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("归档任务标识无效")
    if (not isinstance(cities, list) or not cities or len(set(cities)) != len(cities)):
        raise ValueError("归档城市无效")
    for city in cities:
        archive_component(city)
    created = beijing_time(created_at)
    city_label = cities[0] if len(cities) == 1 else f"{len(cities)}个城市"
    if label is not None:
        archive_component(label)
    folder = f"{created:%Y%m%d_%H%M%S}_{label + '_' if label else ''}{city_label}_{run_id[:6].upper()}"
    return f"{created:%Y-%m}/{folder}"


def delivery_label(datasets):
    """交付目录的业务名：仅数据集名称，不含平台前缀。"""
    names = [LABELS.get(key, key).replace('蓝橙', '').replace('风神', '') for key in datasets[:2]]
    return ('_'.join(names) + ('等' if len(datasets) > 2 else ''))[:65]


def delivery_folder_label(datasets, start, created_at):
    """结果文件夹：业务月份 + 资料名称 + 北京时间 YYMMDDHHMMSS。"""
    moment = beijing_time(created_at)
    if datasets and all(key in _NO_PERIOD_WORKBOOKS for key in datasets):
        month = moment.month
    else:
        try:
            month = dt.date.fromisoformat(str(start)[:10]).month
        except (TypeError, ValueError):
            month = moment.month
    name = delivery_label(datasets)
    stamp = f"{moment:%y%m%d%H%M%S}"
    return f"{month}月{name}"[:65 - len(stamp)].rstrip('_ ') + stamp


def task_archive_label(datasets):
    def dataset_group(key):
        if key == 'baize_employees': return 'baize'
        if key in ('rider_daily','detail_orders','detail_kesu','detail_reviews','rider_archive',
                   'rider_order_detail','xiaoxiang_attendance_detail'): return 'xiaoxiang'
        return 'lanorange' if key.startswith('lanorange_') or key == 'abnormal_riders' else 'fengshen'
    platforms = {'fengshen':'风神', 'lanorange':'蓝橙', 'baize':'商翼', 'xiaoxiang':'灯塔'}
    groups = list(dict.fromkeys(platforms[dataset_group(key)] for key in datasets))
    names = [LABELS.get(key, key).replace('蓝橙', '').replace('风神', '') for key in datasets[:2]]
    return archive_component(('_'.join(groups) + '_' + '、'.join(names) + ('等' if len(datasets)>2 else ''))[:65])


def write_task_checklist(directory, run):
    """Human-readable receipt; metadata only, no workbook contents."""
    import csv
    import tempfile
    root = Path(directory)
    handle, temporary = tempfile.mkstemp(prefix='.checklist_', suffix='.tmp', dir=root)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['任务编号','生成时间','城市','资料','实际范围开始','实际范围结束','状态','文件','字节数','SHA256'])
            for item in run.get('items', []):
                files = [file for file in run.get('files', []) if all(file.get(key)==item.get(key) for key in ('city','dataset','start','end'))]
                for file in files or [{}]:
                    writer.writerow([run['id'],_display_time(run['created_at']),item['city'],LABELS.get(item['dataset'],item['dataset']),*artifact_scope(item),STATUSES.get(item['status'],item['status']),file.get('relative_path',''),file.get('bytes',''),file.get('sha256','')])
            for file in run.get('files', []):
                if file.get('artifact_role') == 'summary':
                    writer.writerow([run['id'],_display_time(run['created_at']),file['city'],LABELS.get(file['dataset'],file['dataset']),file.get('start',''),file.get('end',''),'已生成汇总',file.get('relative_path',''),file.get('bytes',''),file.get('sha256','')])
        os.replace(temporary, root / '任务清单.csv')
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def artifact_scope(item):
    key = item.get('dataset', '')
    if key in LANORANGE_DATASETS or key in ('lanorange_summary','abnormal_riders','baize_employees','invitation_records'):
        return '全量', ''
    if key in ('rider_info','goods_rent','rider_archive'):
        return '当前快照', ''
    return item.get('start',''), item.get('end','')


def _generation_mmdd(stamp=None):
    if stamp is None:
        value = beijing_time()
    elif isinstance(stamp, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
            value = dt.date.fromisoformat(stamp)
        else:
            value = beijing_time(stamp)
    elif isinstance(stamp, dt.datetime):
        value = beijing_time(stamp)
    elif isinstance(stamp, dt.date):
        value = stamp
    else:
        raise ValueError("归档日期无效")
    return f"{value:%m%d}"


def _month_label(months):
    if len(months) == 1:
        return months[0]
    if months_contiguous(months):
        return months[0] + '至' + months[-1]
    return '、'.join(months)


def archive_filename(city, dataset, start, end, suffix=".csv", stamp=None, variant=None, months=None):
    archive_component(city)
    if dataset not in LABELS:
        raise ValueError("归档资料类型无效")
    # Never turn a CSV into an XLSX merely by changing its extension.
    if not isinstance(suffix, str) or suffix.lower() not in (".csv", ".xlsx", ".xls"):
        raise ValueError("归档文件格式无效")
    if suffix.lower() in _EXCEL_SUFFIXES:
        try:
            first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except (TypeError, ValueError):
            raise ValueError("归档资料周期无效") from None
        if first > last:
            raise ValueError("归档资料周期无效")
        title = WORKBOOK_TITLES.get(dataset, LABELS[dataset])
        if variant is None and dataset == 'lanorange_batch_quit' and city != '全部城市':
            variant = '城市批次原表'
        if variant is not None:
            archive_component(variant)
            marker = f"（{variant}）"
        else:
            marker = ""
        generated = _generation_mmdd(stamp)
        if dataset in _MONTHLY_WORKBOOKS:
            if (first.year, first.month) != (last.year, last.month):
                raise ValueError("月度资料必须逐月归档")
            return f"{city}{first.month}月{title}{marker}{generated}{suffix}"
        if dataset == 'rider_daily':
            if first != last:
                return f"{title}{first.isoformat()}-{last.isoformat()}{marker}{suffix}"
            return f"{title}{first.isoformat()}{marker}{suffix}"
        if dataset == 'rider_archive':
            return f"灯塔骑手档案{generated}{suffix}"
        if dataset == 'delivery_waybill':
            # 运单数据按「名称_城市_起止日期」命名；合并成品 city 为「多城市」。
            if first != last:
                return f"{title}_{city}_{first.isoformat()}至{last.isoformat()}{marker}{suffix}"
            return f"{title}_{city}_{first.isoformat()}{marker}{suffix}"
        if dataset in _RANGE_WORKBOOKS:
            # 通知附件合并成品按「名称_起_止」命名，日期为附件数据日期口径。
            if first != last:
                return f"{title}_{first.isoformat()}_{last.isoformat()}{marker}{suffix}"
            return f"{title}_{first.isoformat()}{marker}{suffix}"
        if dataset in _DETAIL_WORKBOOKS:
            title = LABELS[dataset]
            if first != last:
                return f"{first.isoformat()}-{last.isoformat()}{title}{marker}{suffix}"
            return f"{first.isoformat()}{title}{marker}{suffix}"
        if dataset in _NO_PERIOD_WORKBOOKS:
            if dataset == 'lanorange_part_price' and months:
                # 价格档案按月筛选时文件名标注月份，避免与全量成品混淆。
                return f"{city}{title}{marker}{_month_label(months)}_{generated}{suffix}"
            return f"{city}{title}{marker}{generated}{suffix}"
        return f"{city}{title}{first.isoformat()}至{last.isoformat()}{marker}_{generated}{suffix}"
    if dataset in LANORANGE_DATASETS or dataset == 'lanorange_summary':
        period = '城市批次原表' if dataset == 'lanorange_batch_quit' and city != '全部城市' else '全量'
    elif dataset in ("rider_info", "goods_rent"):
        period = "快照"
    else:
        first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if first > last:
            raise ValueError("归档资料周期无效")
        if dataset in MONTHLY:
            if (first.year, first.month) != (last.year, last.month):
                raise ValueError("月度资料必须逐月归档")
            period = f"{first.year}-{first.month:02d}"
        else:
            period = f"{first.isoformat()}至{last.isoformat()}"
    # CSV 保留业务周期命名：明细导出需要明确的日期区间，且不属于生成工作簿。
    return f"{city}_{LABELS[dataset]}_{period}{suffix}"


def _text(value, fallback="未记录"):
    if not isinstance(value, str) or not value.strip():
        return fallback
    value = value.replace("\r", " ").replace("\n", " ").replace("\x00", " ")
    if _PRIVATE.search(value):
        return "部分诊断信息已隐藏"
    return value[:2000]


def _display_time(value):
    try:
        return beijing_time(value).strftime("%Y-%m-%d %H:%M:%S") if value else "未记录"
    except (ValueError, TypeError, OverflowError):
        return "未记录"


def write_download_summary(run_dir, run):
    """Write a receipt without business rows, session data, or absolute paths.

    The caller is responsible for authenticating ownership and resolving the
    registered run directory before calling. Existing receipts are atomically
    refreshed, while business files and the original manifest are untouched.
    """
    directory = Path(run_dir)
    if directory.is_symlink():
        raise ValueError("归档目录不支持链接")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "下载说明.txt"
    if target.is_symlink():
        raise ValueError("下载说明不支持链接")
    run_id = run.get("id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("归档任务标识无效")
    cities = [_text(city) for city in run.get("cities", [])]
    lines = ["风神下载中心 - 下载说明", "时间标准：北京时间（Asia/Shanghai，UTC+08:00）",
             f"任务编号：{run_id[:6].upper()}（完整编号：{run_id}）",
             f"任务状态：{STATUSES.get(run.get('status'), '未知')}",
             f"创建时间：{_display_time(run.get('created_at'))}",
             f"说明生成时间：{_display_time(dt.datetime.now(dt.timezone.utc))}",
             f"城市：{'、'.join(cities)}",
             f"申请日期：{_text(run.get('start'))} 至 {_text(run.get('end'))}"]
    if run.get("archive_version"):
        lines.append(f"归档目录：{_text(run.get('archive_relative_dir'))}")
    else:
        lines.append("归档目录：历史任务原目录，原文件名保持不变")
    recovery = run.get("recovery_of")
    if isinstance(recovery, str) and re.fullmatch(r"[0-9a-f]{32}", recovery):
        lines.append(f"恢复自原任务：{recovery}；仅查询、下载原导出，没有重新提交导出")
    retry = run.get("retry_of")
    if isinstance(retry, str) and re.fullmatch(r"[0-9a-f]{32}", retry):
        lines.append(f"分项续作自原任务：{retry}；只处理所选失败项，已提交资料仅查询原导出")
    lines.extend(["", "资料范围与结果："])
    for item in run.get("items", []):
        dataset = item.get("dataset")
        label = LABELS.get(dataset, "未知资料")
        if dataset == 'invitation_records':
            period = f"{_text(item.get('city'))}商家全部可见站点的邀请记录；不按活动、创建人或日期筛选，全分页读取"
        elif dataset == 'attendance_detail':
            period = f"{_text(item.get('city'))}商家全部可见团队；{_text(item.get('start'))} 至 {_text(item.get('end'))}，按段导出并合并"
        elif dataset in LANORANGE_DATASETS:
            scope = '所选城市' if run.get('lanorange_by_city') else '全部城市'
            months = platform_months(run, dataset)
            period = f'账号权限内原始资料（{scope}、全部状态、' + ('日期 ' + '、'.join(months) if months else '不按日期筛选') + '）'
            if run.get('lanorange_full_delivery'):
                if months:
                    period = ('账号全部可访问数据（全部状态；平台导出日期 '
                              + '、'.join(months) + '；原始导出保留）')
                else:
                    period='账号全部可访问数据（全部状态、不按日期筛选；平台原表优先，系统合并文件明确标注，未完整不发布）'
            if dataset == 'lanorange_batch_quit' and run.get('lanorange_by_city'):
                period += '；平台批次原表可能含跨城市骑手，汇总按记录城市归属筛选'
        elif dataset == 'rider_archive':
            period = '全部站点骑手当前快照（导出时刻数据；手机号/身份证为明文，照片以链接提供）'
        elif dataset in ('rider_order_detail', 'xiaoxiang_attendance_detail'):
            period = (f'{_text(item.get("start"))} 至 {_text(item.get("end"))} 通知附件合并'
                      '（按附件数据日期筛选，按日期+骑手id去重，保留较新通知）')
        elif dataset in ("rider_info", "goods_rent"):
            period = ("当前人员快照（所选日期不是历史人员范围）" if dataset == "rider_info"
                      else "当前全历史快照（不按租用日期筛选；站点按「是否含取分离」勾选过滤）")
        elif dataset == 'abnormal_riders':
            period = '账号全部可访问数据（全部状态、不按日期筛选）整理生成；含异常汇总/蓝橙骑手档案/汇总'
        elif dataset in MONTHLY:
            period = f"{_text(item.get('start'))[:7]} 整月"
        else:
            period = f"{_text(item.get('start'))} 至 {_text(item.get('end'))}"
        line = f"- {_text(item.get('city'))} | {label} | {period} | {STATUSES.get(item.get('status'), '未知')}"
        if item.get("error"):
            line += f" | 原因：{_text(item['error'])}"
        lines.append(line)
    if run.get("error"):
        lines.extend(["", "任务提示：" + _text(run["error"])])
    files = run.get("files", [])
    lines.extend(["", f"已验证成品文件：{len(files)} 个"])
    for entry in files:
        lines.append(f"- {_text(entry.get('city'))} / {_text(entry.get('name'))}")
        if isinstance(entry.get("bytes"), int):
            lines.append(f"  大小：{entry['bytes']} 字节")
        digest = entry.get("sha256")
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            lines.append(f"  SHA-256：{digest}")
    lines.extend(["", ("归档规则：结果/城市目录存放成品，来源目录存放关联资料；原始资料目录保留平台原件及诊断。" if run.get('result_layout') == 2 else "归档规则：所有城市成品统一存放在任务目录，文件名标注城市；原始资料及诊断存放在原始资料/城市目录。"),
                  "月度资料按覆盖的每个月分别下载整月；骑手信息为下载时的当前快照。",
                  "生成工作簿名称含城市、业务周期、资料名称和生成日期 MMDD；任务目录名另含发布时间与任务编号，不同任务互不覆盖。",
                  "浏览器另存文件的目录由访问者设备决定。", "本下载任务不执行薪资核算。", ""])
    temporary = directory / (".下载说明_" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8-sig", newline="") as stream:
            stream.write("\r\n".join(lines))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
