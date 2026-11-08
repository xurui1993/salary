"""Template-driven, isolated inputs for part-time Fengshen payroll."""

import asyncio
import csv
from dataclasses import asdict, dataclass
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import unquote
import uuid
import zipfile

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string
from openpyxl.utils.datetime import from_excel

from fengshen_bill import (
    BILL_URL, RIDER_BILL_URL, BillCollectionError, BillPageCollector, BillRequest,
    MonthlyBillPageCollector, MonthlyBillRequest, atomic_json, safe_operation_failure, validate_profile,
)
from fengshen_orders import OrderPageCollector, WAYBILL_URL, date_batches, validate_order_profile
from order_sources import prepare_order_files
from collection_errors import collection_failure

ROOT = Path(__file__).resolve().parent.parent
CITY_FILE = Path(__file__).with_name("fengshen_cities.json")
MANUAL_TYPES = ("价格档案", "骑手支付绑定")
ID_COLUMNS = {"账单ID", "骑手ID", "代理商ID", "骑手所属站点ID"}
TEXT_COLUMNS = ID_COLUMNS | {
    "骑手姓名", "骑手所属站点名称", "账单周期", "推送出账时间", "在职时间",
    "基础薪资方案名称ID", "扣款方案名称ID", "账单状态", "代扣代付计税方式",
    "其他加项原因（如填写了其他加项，则此项必填）",
    "其他减项原因（如填写了其他减项，则此项必填）",
}
COLLECTION_LOCK = threading.Lock()
MAX_FILE_BYTES = 4 * 1024 ** 3
# 日账单按块解压和逐行校验，单文件上限独立于上传和内存读取限制。
MAX_DAILY_FILE_BYTES = 4 * 1024 ** 3
MAX_DAILY_ARCHIVE_BYTES = 10 * 1024 ** 3
# UB 成品格式规格，逐项取自用户确认的样例附件。
UB_HEADER_FILL = PatternFill("solid", fgColor="FFFCE4D3")
UB_FONT = Font(name="微软雅黑", size=10, color="FF000000")
UB_ALIGNMENT = Alignment(horizontal="center", vertical="center")
UB_ROW_HEIGHT = 16.5
UB_FORMATTED_WIDTHS = {
    "A": 57.5, "B": 16.125, "C": 8.0, "D": 9.5, "E": 13.375, "F": 22.0, "G": 8.25,
    "H": 11.375, "I": 40.625, "J": 27.5, "K": 35.875, "L": 25.125, "M": 21.5,
    "N": 13.125, "O": 29.375, "P": 24.0, "Q": 13.125, "R": 9.625, "S": 11.375,
    "U": 8.5, "X": 8.0, "Y": 8.5, "AC": 12.375, "AD": 8.0, "AE": 11.375,
    "AF": 8.0, "AG": 9.625, "AH": 8.0, "AJ": 11.375, "AK": 8.0, "AL": 16.125,
    "AM": 8.0, "AN": 40.25, "AO": 14.25, "AP": 15.0, "AQ": 22.75, "AR": 18.625,
    "AT": 16.125, "AU": 16.5, "AV": 18.625, "AX": 8.0, "AY": 15.0, "AZ": 9.5,
    "BA": 8.0, "BB": 40.25, "BC": 47.375, "BD": 49.25, "BE": 20.375, "BF": 16.75,
    "BG": 8.0, "BH": 11.375, "BI": 9.625, "BJ": 6.375, "BK": 9.5, "BL": 9.0,
}
NUMBER_TEXT = re.compile(r"[+-]?(?:\d+\.\d+|\d+|\.\d+)")


class SourceError(BillCollectionError):
    pass


def label(value):
    return re.sub(r"\s+", "", str(value or ""))


def identifier(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        raise SourceError("编号不能为布尔值")
    if isinstance(value, float):
        if not value.is_integer() or abs(value) >= 10 ** 15:
            raise SourceError("编号存在浮点精度风险，请提供文本编号")
        return str(int(value))
    text = str(value).strip()
    return re.sub(r"\.0$", "", text) if re.fullmatch(r"\d+\.0", text) else text


def parse_date(value, epoch=None):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and epoch:
        parsed = from_excel(value, epoch)
        if isinstance(parsed, dt.datetime):
            return parsed.date()
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?", text)
    try:
        if match:
            return dt.date(*(int(x) for x in match.groups()))
    except ValueError:
        pass
    raise SourceError("日期缺失或格式错误，应包含完整年月日")


def money(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
        if not number.is_finite():
            raise InvalidOperation
        return format(number, "f")
    except InvalidOperation:
        raise SourceError("金额或单量字段包含非数值内容") from None


@dataclass(frozen=True)
class TemplatePlan:
    city: str
    agency_id: str
    start: str
    end: str
    month: str
    cycle: str
    template: str
    applicants: int


def read_template(path, cities=None, require_agency=True):
    if cities is None:
        try:
            from fengshen_city_catalog import all_cities
            cities = all_cities()
        except Exception:
            cities = json.loads(CITY_FILE.read_text(encoding="utf-8"))
    from payroll_performance import cached_plan
    return cached_plan(path, (tuple(sorted(cities.items())), require_agency),
                       lambda: _read_template_checked(path, cities, require_agency))


def _read_template_checked(path, cities, require_agency):
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise SourceError("template 工作簿无法读取或已损坏") from None
    try:
        if "申请名单" not in workbook.sheetnames:
            raise SourceError("template 缺少申请名单子表")
        sheet = workbook["申请名单"]
        sheet.reset_dimensions()
        rows = iter(sheet.iter_rows(values_only=True))
        headers = [label(v) for v in next(rows, ())]
        required = ("业务城市", "骑手ID", "开始日期", "结束日期", "结算类型")
        if any(headers.count(h) != 1 for h in required):
            raise SourceError("申请名单必须包含唯一的业务城市、骑手ID、开始日期、结束日期、结算类型列")
        indexes = {h: headers.index(h) for h in required}
        records = []
        for row_num, row in enumerate(rows, 2):
            if not any(v is not None and str(v).strip() for v in row):
                continue
            values = {k: row[i] if i < len(row) else None for k, i in indexes.items()}
            try:
                if not identifier(values["骑手ID"]) or not label(values["业务城市"]) or not label(values["结算类型"]):
                    raise SourceError("城市、骑手ID、结算类型不能为空")
                start = parse_date(values["开始日期"], workbook.epoch)
                end = parse_date(values["结束日期"], workbook.epoch)
                if start > end or start.strftime("%Y-%m") != end.strftime("%Y-%m"):
                    raise SourceError("申请日期倒置或跨月")
                records.append((label(values["业务城市"]), label(values["结算类型"]), start, end))
            except (SourceError, ValueError) as exc:
                raise SourceError(f"申请名单第 {row_num} 行：{exc}") from None
        if not records:
            raise SourceError("申请名单没有有效申请记录")
        if len({r[0] for r in records}) != 1 or len({r[1] for r in records}) != 1:
            raise SourceError("一个 template 只能包含一个业务城市和一个结算类型")
        start, end = min(r[2] for r in records), max(r[3] for r in records)
        if start.strftime("%Y-%m") != end.strftime("%Y-%m"):
            raise SourceError("一个 template 的结算周期不能跨月")
        city = records[0][0]
        agency = str(cities.get(city, ""))
        if require_agency and not re.fullmatch(r"\d{1,20}", agency):
            raise SourceError(f"业务城市 {city} 未配置固定物流合作商编号")
        return TemplatePlan(city, agency, start.isoformat(), end.isoformat(), start.strftime("%Y-%m"),
                            records[0][1], Path(path).name, len(records))
    finally:
        workbook.close()


def owned_upload(source, workspace, root=ROOT):
    wid = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fa5]", "", unquote(workspace or ""))
    if not wid:
        raise SourceError("缺少工作区标识，请从系统上传入口提交资料")
    owner = (Path(root) / "uploads" / wid).resolve()
    path = Path(source).resolve()
    if not path.is_dir() or not path.is_relative_to(owner):
        raise SourceError("自动采集仅接受本工作区本次上传的资料目录")
    relative = path.relative_to(owner)
    if not relative.parts or not relative.parts[0].startswith("upload_"):
        raise SourceError("请重新上传 template 和补充资料，不复用已准备的账单目录")
    return path, owner


def source_files(folder):
    files = []
    for path in Path(folder).rglob("*"):
        if not path.is_file() or path.name.startswith(("~", ".")):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(Path(folder).resolve()):
            raise SourceError("上传资料中存在越界文件")
        if path.suffix.lower() in (".xlsx", ".xls", ".csv"):
            files.append(path)
    return files


def inspect_source(folder, require_agency=True):
    files = source_files(folder)
    templates = [p for p in files if "template" in p.name.lower()]
    if len(templates) != 1 or templates[0].suffix.lower() != ".xlsx":
        raise SourceError("本次自动采集必须上传一个且仅一个 .xlsx template")
    plan = read_template(templates[0], require_agency=require_agency)
    manual = {kind: [p for p in files if kind in p.name and p not in templates] for kind in MANUAL_TYPES}
    return plan, templates[0], manual


def validate_manual(path, kind):
    signatures = {
        "价格档案": {"骑手id", "价格"},
        "骑手支付绑定": {"骑手id", "绑定情况"},
        "欺诈单": {"骑手id", "运单id", "欺诈是否成立"},
        "问题单": {"骑手id", "运单号", "类型"},
    }
    def matches(rows):
        return any(signatures[kind].issubset({label(v).lower() for v in row}) for row in rows)
    try:
        if path.suffix.lower() == ".xlsx":
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                valid = False
                for sheet in workbook:
                    sheet.reset_dimensions()
                    if matches(sheet.iter_rows(min_row=1, max_row=10, values_only=True)):
                        valid = True
                        break
            finally:
                workbook.close()
        elif path.suffix.lower() == ".csv":
            valid = False
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    with path.open(encoding=encoding, newline="") as source:
                        from itertools import islice
                        valid = matches(islice(csv.reader(source), 10))
                    if valid:
                        break
                except UnicodeDecodeError:
                    continue
        else:
            import pandas as pd
            with pd.ExcelFile(path, engine="calamine") as workbook:
                valid = any(matches(workbook.parse(sheet, header=None, nrows=10).values.tolist()) for sheet in workbook.sheet_names)
        if not valid:
            raise SourceError(f"{kind} 文件缺少约定表头：{path.name}")
    except SourceError:
        raise
    except Exception:
        raise SourceError(f"{kind} 文件无法解析：{path.name}") from None


def _locate_ub_sheet(workbook):
    # 平台原始导出表头在第 4 行，重排成品在第 1 行；在前 6 行内自动定位。
    required = ID_COLUMNS | {"账单周期", "账单状态"}
    candidates = []
    for candidate in workbook:
        if hasattr(candidate, "reset_dimensions"):
            candidate.reset_dimensions()
        for row_index, row in enumerate(candidate.iter_rows(min_row=1, max_row=6, values_only=True), 1):
            fields = [label(v) for v in row]
            if all(fields.count(name) == 1 for name in required):
                candidates.append((candidate, row_index))
                break
    if not candidates:
        raise SourceError("UB 骑手账单缺少完整关键表头（前 6 行内未识别）")
    if len(candidates) != 1:
        raise SourceError("UB 骑手账单存在多个匹配子表，需核对导出范围")
    return candidates[0]


def rider_bill_header_row(path):
    """返回 UB 账单表头所在行号（平台原始导出为 4，重排成品为 1）。"""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return _locate_ub_sheet(workbook)[1]
    finally:
        workbook.close()


def text_number(value):
    """Return int/float for a plain decimal string; keep IDs with leading zeros and other text."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not NUMBER_TEXT.fullmatch(text):
        return None
    unsigned = text.lstrip("+-")
    if unsigned.startswith("0") and unsigned != "0" and not unsigned.startswith("0."):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) >= 10 ** 15:
        return None
    return float(number) if "." in text else int(number)


def text_number_format(value):
    decimals = len(value.strip().split(".")[1]) if "." in value else 0
    return "0" if decimals == 0 else "0." + "0" * decimals


def convert_text_numbers(cell, header):
    if not header:
        return
    if header == "骑手ID":
        if isinstance(cell.value, str):
            number = text_number(cell.value)
            if number is None:
                return
            if isinstance(number, float):
                if not number.is_integer():
                    return
                number = int(number)
            cell.value, cell.number_format = number, "0"
        elif isinstance(cell.value, bool):
            return
        elif isinstance(cell.value, int):
            cell.number_format = "0"
        elif isinstance(cell.value, float) and cell.value.is_integer() and abs(cell.value) < 10 ** 15:
            cell.value, cell.number_format = int(cell.value), "0"
        return
    if header in TEXT_COLUMNS or not isinstance(cell.value, str):
        return
    number = text_number(cell.value)
    if number is None:
        return
    cell.value, cell.number_format = number, text_number_format(cell.value)


def format_rider_monthly_workbook(source, target):
    """按确认的成品规格重排平台原始导出：删前置说明行，统一表头/数据样式与列宽。"""
    workbook = load_workbook(source)
    try:
        sheet, header_row = _locate_ub_sheet(workbook)
        if header_row > 1:
            sheet.delete_rows(1, header_row - 1)
        for name in [candidate.title for candidate in workbook if candidate is not sheet]:
            del workbook[name]
        for cell in sheet[1]:
            if isinstance(cell.value, str):
                cell.value = cell.value.strip()
            if cell.value is not None:
                cell.font, cell.fill, cell.alignment = UB_FONT, UB_HEADER_FILL, UB_ALIGNMENT
        headers = {cell.column: label(cell.value) for cell in sheet[1]}
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if cell.value is not None:
                    cell.font, cell.alignment = UB_FONT, UB_ALIGNMENT
                    convert_text_numbers(cell, headers.get(cell.column, ""))
        for letter, width in UB_FORMATTED_WIDTHS.items():
            if column_index_from_string(letter) <= sheet.max_column:
                sheet.column_dimensions[letter].width = width
        sheet.sheet_format.defaultRowHeight = UB_ROW_HEIGHT
        sheet.freeze_panes = "A2"
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        workbook.save(target)
    finally:
        workbook.close()
    return Path(target)


def read_rider_bill(path, cleaned=False):
    if cleaned:
        with Path(path).open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.reader(source))
        header_index = 0
    else:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet, header_row = _locate_ub_sheet(workbook)
            rows = list(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
        header_index = header_row - 1
    if len(rows) <= header_index:
        raise SourceError("UB 骑手账单缺少表头行")
    headers = [label(v) for v in rows[header_index]]
    while headers and not headers[-1]:
        headers.pop()
    if any(headers.count(h) != 1 for h in ID_COLUMNS | {"账单周期", "账单状态"}):
        raise SourceError("UB 表头缺少关键字段或关键字段重名")
    if any(not h for h in headers) or len(set(headers)) != len(headers):
        raise SourceError("UB 表头存在空列或清洗后重名列，需核对原始导出")
    result = []
    bill_ids = set()
    for number, row in enumerate(rows[header_index + 1:], header_index + 2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        if any(v is not None and str(v).strip() for v in row[len(headers):]):
            raise SourceError(f"UB 第 {number} 行存在无表头的数据")
        cleaned_row = []
        for column, name in enumerate(headers):
            value = row[column] if column < len(row) else None
            if name in ID_COLUMNS:
                value = identifier(value)
                if not value:
                    raise SourceError(f"UB 第 {number} 行编号缺失")
            elif name in TEXT_COLUMNS or "原因" in name:
                value = str(value).strip() if value is not None else ""
            else:
                value = money(value)
            cleaned_row.append(value)
        bill_id = cleaned_row[headers.index("账单ID")]
        if bill_id in bill_ids:
            raise SourceError("UB 账单ID重复，已停止；不按骑手ID去重或合并")
        bill_ids.add(bill_id)
        result.append(cleaned_row)
    return headers, result


def clean_rider_bill(source, target, plan):
    headers, rows = read_rider_bill(source)
    agency_col, period_col = headers.index("代理商ID"), headers.index("账单周期")
    for row in rows:
        if row[agency_col] != plan.agency_id:
            raise SourceError("风神骑手月度 UB 账单包含其他城市代理商，已停止核算")
        period = row[period_col]
        if period != plan.month:
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", period)
            monthly = MonthlyBillRequest(plan.month)
            if dates != [monthly.start, monthly.end]:
                raise SourceError("风神骑手月度 UB 账单周期与 template 月份不一致")
    with Path(target).open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
    return {"rows": len(rows), "status": "empty" if not rows else "validated",
            "scope": "all_city_riders", "filtered_by_applicants": False}


def csv_encoding(path):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with Path(path).open(encoding=encoding, newline="") as source:
                headers = next(csv.reader(source), [])
            if "加盟商ID" in headers and "账单时间" in headers:
                return encoding
        except UnicodeDecodeError:
            pass
    raise SourceError("代理商 CSV 编码或表头无法识别")


def validate_daily(path, plan):
    encoding = csv_encoding(path)
    count = 0
    with Path(path).open(encoding=encoding, newline="") as source:
        reader = csv.DictReader(source)
        required = {"加盟商ID", "账单时间", "骑手ID", "金额"}
        if not required.issubset(reader.fieldnames or []) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise SourceError("代理商账单缺少关键表头或列重名")
        for row in reader:
            if not any(row.values()):
                continue
            if None in row or any(row.get(key) is None for key in required):
                raise SourceError("代理商账单行列结构损坏")
            if identifier(row["加盟商ID"]) != plan.agency_id:
                raise SourceError("代理商账单包含非目标城市数据")
            date = parse_date(row["账单时间"]).isoformat()
            if not plan.start <= date <= plan.end:
                raise SourceError("代理商账单日期超出申请名单范围")
            if not identifier(row["骑手ID"]) or money(row["金额"]) is None:
                raise SourceError("代理商账单的骑手ID或金额缺失")
            count += 1
    return {"rows": count, "status": "empty" if count == 0 else "validated", "encoding": encoding}


def unpack_daily(path, target, expected_kinds=None):
    expected_kinds = {"配送费", "违规扣款"} if expected_kinds is None else set(expected_kinds)
    if not expected_kinds or not expected_kinds.issubset({"配送费", "违规扣款"}):
        raise SourceError("代理商子账单选择无效")
    target = Path(target)
    target.mkdir()
    result = {}
    created = []
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(e.file_size for e in entries) > MAX_DAILY_ARCHIVE_BYTES:
                raise SourceError("代理商账单压缩包解压总量超过 10GiB 限制")
            selected = {}
            # 完整检查目录再开始写入，重复项或非法成员不会留下半份账单。
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                parts = name.split("/")
                if name.startswith("/") or ":" in name or ".." in parts or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise SourceError("账单压缩包包含不安全路径或加密文件")
                if entry.is_dir():
                    continue
                matches = [k for k in ("配送费", "违规扣款") if k in Path(name).name]
                if len(matches) != 1 or not name.lower().endswith(".csv"):
                    raise SourceError("代理商导出含未确认的文件，仅接受配送费和违规扣款 CSV")
                kind = matches[0]
                if kind not in expected_kinds:
                    raise SourceError("代理商导出包含本次未选择的子账单")
                if kind in selected:
                    raise SourceError(kind + "存在多份同类子账单，需核对导出范围")
                if entry.file_size > MAX_DAILY_FILE_BYTES:
                    raise SourceError(kind + "文件超过 4GiB 流式处理限制")
                selected[kind] = entry
            if set(selected) != expected_kinds:
                raise SourceError("代理商导出缺少所选配送费或违规扣款文件；未获取不等于无记录")
            total = 0
            for kind, entry in selected.items():
                destination = target / (kind + ".csv")
                size = 0
                with archive.open(entry) as source, destination.open("xb") as output:
                    created.append(destination)
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        total += len(block)
                        if size > MAX_DAILY_FILE_BYTES or total > MAX_DAILY_ARCHIVE_BYTES:
                            raise SourceError("代理商账单实际解压数据超过流式处理限制")
                        output.write(block)
                if size != entry.file_size:
                    raise SourceError(kind + "解压文件大小与回执不一致")
                result[kind] = destination
        return result
    except Exception:
        for destination in created:
            destination.unlink(missing_ok=True)
        raise


def load_profiles(plan):
    profiles = []
    for filename, dataset in (("fengshen_bill.profile.json", "agency_daily"), ("fengshen_rider_bill.profile.json", "rider_monthly"),
                              ("fengshen_orders.profile.json", "issue_orders")):
        path = Path(__file__).with_name(filename)
        if not path.is_file():
            raise SourceError(f"尚未完成真实页面配置：缺少 {filename}；自动下载未启动，核算已停止")
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SourceError(f"页面配置文件无法解析：{filename}") from None
        if not isinstance(profile, dict):
            raise SourceError(f"页面配置必须是 JSON 对象：{filename}")
        profile["expected_agency_id"] = plan.agency_id
        try:
            (validate_order_profile if dataset == "issue_orders" else validate_profile)(profile)
        except BillCollectionError as exc:
            raise SourceError(str(exc)) from None
        if profile.get("dataset") != dataset or profile.get("selection_mode") != "target_city":
            raise SourceError("页面配置必须按物流合作商目标城市切换，不能使用旧全选配置")
        profiles.append(profile)
    return profiles


def configuration_status():
    try:
        load_profiles(TemplatePlan("", "31029436", "2026-08-16", "2026-08-31", "2026-08", "", "", 0))
        return {"configured": True, "message": "页面配置已核对", "manual_types": list(MANUAL_TYPES),
                "required_uploads": ["template"], "optional_uploads": list(MANUAL_TYPES),
                "automatic_types": ["配送费", "违规扣款", "风神骑手月度 UB 账单", "欺诈单", "问题单"]}
    except (SourceError, TypeError, AttributeError):
        return {"configured": False, "message": "风神页面配置待联调"}


def validate_collection_window(plan):
    try:
        return date_batches(plan.start, plan.end)
    except BillCollectionError as exc:
        raise SourceError(str(exc)) from None


def collect_browser(plan, profiles, raw, log, cancelled, notify=lambda _: None):
    from fengshen_auth import BROKER, BrowserAuth, open_context, launch_background_edge, reveal_edge, conceal_edge
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SourceError("缺少 Playwright；请安装 backend/requirements-crawler.txt 中的采集依赖") from None
    phase, dataset = "browser_launch", ""
    try:
        with BROKER.operation(Path(raw).parent.parent.name, cancelled, notify), sync_playwright() as playwright:
            browser = None
            try:
                log("[采集] 正在启动专用 Edge 浏览器")
                browser = launch_background_edge(playwright)
                phase = "session_restore"
                log("[采集] 正在恢复本机登录会话")
                context = open_context(browser, BROKER)
                phase = "page_create"
                page = context.new_page()
                phase = "window_conceal"
                conceal_edge(page)
                auth = BrowserAuth(page, context, BROKER, cancelled, log, reveal=reveal_edge, conceal=conceal_edge)
                outputs = []
                for url, profile, request, collector in (
                    (BILL_URL, profiles[0], BillRequest(plan.start, plan.end, False, False, plan.agency_id), BillPageCollector),
                    (RIDER_BILL_URL, profiles[1], MonthlyBillRequest(plan.month), MonthlyBillPageCollector),
                ):
                    if cancelled.is_set():
                        raise SourceError("任务已取消，未启动核算")
                    dataset = profile["dataset"]
                    phase = "navigation"
                    log("[采集] 正在进入" + ("代理商账单" if dataset == "agency_daily" else "风神骑手月度 UB 账单") + "页面")
                    auth.navigate(url)
                    phase = "auth_check"
                    auth.ensure(url, profile)
                    phase = "collect"
                    outputs.append(collector(page, profile, raw / dataset, log=log,
                                             auth=lambda force=False, url=url, profile=profile: auth.ensure(url, profile, force)).collect(request))
                dataset = "issue_orders"
                profile = profiles[2]
                phase = "navigation"
                log("[采集] 正在进入运单页面")
                auth.navigate(WAYBILL_URL)
                phase = "auth_check"
                auth.ensure(WAYBILL_URL, profile)
                phase = "collect"
                orders = OrderPageCollector(page, profile, raw / "issue_orders", log=log,
                    auth=lambda force=False: auth.ensure(WAYBILL_URL, profile, force))
                outputs.extend(orders.collect_batches(plan.start, plan.end, cancelled))
                return outputs
            except Exception as exc:
                failure = collection_failure(exc, phase, dataset)
                # Update only while this operation owns the broker. A rejected
                # concurrent request must not change another user's login state.
                BROKER.update("signed_out" if cancelled.is_set() else "error", str(failure))
                raise failure from None
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        log("[采集] 浏览器关闭未完成，请检查专用 Edge 窗口")
    except Exception as exc:
        failure = collection_failure(exc, phase, dataset)
        raise failure from None


def prepare_inputs(folder, owner, log, cancelled, collector=None, notify=lambda _: None):
    if collector is None:
        collector = lambda *args: collect_browser(*args, notify=notify)
    try:
        plan, template, manual = inspect_source(folder)
        batches = validate_collection_window(plan)
        profiles = load_profiles(plan)
    except Exception as exc:
        failure = collection_failure(exc, "input_validation")
        error = SourceError(str(failure))
        error.diagnostics = failure.diagnostics
        raise error from None
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise SourceError("另一项风神采集正在运行，请等待完成后重试")
    run = Path(owner) / ("fengshen_" + uuid.uuid4().hex)
    raw, inputs = run / "raw", run / "input"
    manifest = {"plan": asdict(plan), "status": "running", "datasets": {}, "raw_retained": True,
                "optional_inputs": {kind: bool(paths) for kind, paths in manual.items()}}
    try:
        run.mkdir()
        raw.mkdir()
        inputs.mkdir()
        log(f"[计划] {plan.city} / {plan.agency_id} / {plan.start} 至 {plan.end} / 风神骑手月度 UB 账单 {plan.month}")
        if not manual["价格档案"]:
            log("[资料] 未上传价格档案，本次输出无单价，不沿用历史或模板中的旧单价")
        if not manual["骑手支付绑定"]:
            log("[资料] 未上传骑手支付绑定，本次跳过绑定校验")
        if any("欺诈单" in path.name or "问题单" in path.name for path in source_files(folder)):
            log("[资料] 自动模式忽略手动欺诈单和问题单，仅使用本次风神采集结果")
        for kind, paths in manual.items():
            for path in paths:
                validate_manual(path, kind)
        for path in [template] + [p for paths in manual.values() for p in paths]:
            if path.stat().st_size == 0 or path.stat().st_size > MAX_FILE_BYTES:
                raise SourceError("手动补充文件为空或超过大小限制")
            if path.suffix.lower() == ".xlsx":
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip() is not None:
                        raise SourceError("手动补充工作簿损坏")
            destination = inputs / path.name
            if destination.exists():
                raise SourceError("补充资料存在同名文件，不能覆盖")
            shutil.copy2(path, destination)
        downloads = collector(plan, profiles, raw, log, cancelled)
        if cancelled.is_set():
            raise SourceError("任务已取消，核算已停止")
        if len(downloads) != 2 + len(batches):
            raise SourceError("采集结果不完整")
        seen_datasets = set()
        for download in downloads:
            dataset = download.get("dataset")
            if dataset == "issue_orders":
                continue
            if dataset not in ("agency_daily", "rider_monthly") or download.get("status") != "success" or download.get("agency_id") != plan.agency_id:
                raise SourceError("下载清单的城市、类型或状态错误")
            if dataset in seen_datasets:
                raise SourceError("采集结果类型重复")
            seen_datasets.add(dataset)
            expected = (plan.start, plan.end) if dataset == "agency_daily" else (MonthlyBillRequest(plan.month).start, MonthlyBillRequest(plan.month).end)
            if (download.get("start"), download.get("end")) != expected:
                raise SourceError("下载清单周期错误")
            files = download.get("files", [])
            if len(files) != 1:
                raise SourceError("下载文件数量异常")
            base = (raw / dataset).resolve()
            path = (base / files[0]["path"]).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                raise SourceError("下载文件路径无效")
            if dataset == "agency_daily":
                for kind, data_path in unpack_daily(path, raw / "unpacked").items():
                    manifest["datasets"][kind] = validate_daily(data_path, plan)
                    shutil.copy2(data_path, inputs / (plan.agency_id + "-" + kind + ".csv"))
            else:
                manifest["datasets"]["骑手月账单"] = clean_rider_bill(path, inputs / ("UB骑手账单_cleaned_" + plan.month + ".csv"), plan)
        if set(manifest["datasets"]) != {"配送费", "违规扣款", "骑手月账单"}:
            raise SourceError("必要账单未准备齐全")
        orders = prepare_order_files([download for download in downloads if download.get("dataset") == "issue_orders"], raw, inputs, plan, batches)
        manifest["order_batches"] = orders.pop("order_batches")
        if any(batch["batch_total_inconsistent"] for batch in manifest["order_batches"]):
            log("[校验提示] 平台跨日汇总数存在差异；全部逐日数量已与文件核对一致，详见采集清单")
        manifest["datasets"].update(orders)
        problem = orders["问题单"]
        if problem.get("type_counts"):
            counts = "、".join(f"{kind} {count} 条" for kind, count in problem["type_counts"].items())
            log(f"[问题单] {counts}；服务奖惩原始 {problem['service_rows']} 条，剔除不成立或申诉成功 {problem['service_excluded_rows']} 条")
        manifest["status"] = "ready"
        atomic_json(run / "manifest.json", manifest)
        log("[校验] 五类自动资料及全部批次已完整校验；原文件留存，清洗未筛除非申请骑手")
        return inputs, plan
    except Exception as exc:
        failure = collection_failure(exc, "input_validation")
        manifest.update(status="error", failure=failure.diagnostics, error=str(failure))
        if run.is_dir():
            atomic_json(run / "manifest.json", manifest)
            log(f"[诊断] 失败记录和已下载原文件保留在：{run}")
        raise SourceError(manifest["error"]) from None
    finally:
        COLLECTION_LOCK.release()


async def run_fengshen_payroll(config, workspace):
    import tasks
    cancelled = threading.Event()
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    worker = None
    def log(message):
        if not cancelled.is_set():
            loop.call_soon_threadsafe(queue.put_nowait, tasks.create_log_event(message))
    def notify(status):
        if not cancelled.is_set():
            event = "data: " + json.dumps({"type": "fengshen_auth", "status": status}, ensure_ascii=False) + "\n\n"
            loop.call_soon_threadsafe(queue.put_nowait, event)
    try:
        folder, owner = owned_upload(config.sourcePath, workspace)
        worker = asyncio.create_task(asyncio.to_thread(prepare_inputs, folder, owner, log, cancelled, notify=notify))
        while not worker.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
        inputs, plan = await worker
        supplemental = {kind: any(kind in path.name and path.name != plan.template for path in inputs.iterdir())
                        for kind in MANUAL_TYPES}
        yield tasks.create_log_event("模板城市已确认：" + plan.city + "!!CITY!!" + plan.city)
        async for event in tasks.run_main_calculation_gen(
            plan.city, plan.cycle, str(inputs), config.basePath, config.theme,
            config.enableInterceptor, config.enableCrossStationMerge,
            deductionRules=config.deductionRules, taskQueue=[plan.template], strict_inputs=True,
            force_no_price=not supplemental["价格档案"], skip_binding_check=not supplemental["骑手支付绑定"],
        ):
            yield event
    except BillCollectionError as exc:
        yield tasks.create_log_event(str(exc), "ERROR")
        yield tasks.create_finish_event("error", str(exc))
    finally:
        cancelled.set()
        if worker is not None and not worker.done():
            try:
                await asyncio.shield(worker)
            except (Exception, asyncio.CancelledError):
                pass
