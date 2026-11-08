"""Validate each downloaded slice before reusing the existing issue-order rules."""

import csv
import datetime as dt
import hashlib
import math
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from fengshen_bill import BillCollectionError
from issue_orders import DataCleaner, MergePenaltyRecords, issue_types
from order_metrics import measured

WAYBILL_COLUMNS = {
    "运单id", "骑手id", "骑手名称", "站点名称", "运单完成时间", "欺诈是否成立",
    "运单状态", "运单类型", "是否超平台期望时间", "平台期望时间", "配送标品",
    "订单来源", "超平台期望送达时长", "是否超骑手T", "骑手考核时间",
    "是否超用户T", "用户期望时间",
}
VIOLATION_COLUMNS = {
    "违规编号", "违规时间", "运单号", "团队名称", "骑手ID", "骑手名称",
    "违规分类", "违规类型", "违规原因", "违规状态", "申诉状态", "处罚",
}
ISSUE_COLUMNS = ["类型", "日期", "运单号", "骑手id", "配送员姓名", "团队名称", "事件原因", "处罚金额"]
VIOLATION_CLEAN_COLUMNS = ["违规编号", "日期", "运单号", "团队名称", "骑手id", "配送员姓名",
                           "违规分类", "违规类型", "违规原因", "违规状态", "申诉状态", "处罚金额"]
MAX_BYTES = 200 * 1024 * 1024
READ_CHUNK_ROWS = 10000


def file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _read_rows(rows, required, checkpoint=None):
    rows = iter(rows)
    headers = [str(value or "").strip() for value in next(rows, ())]
    if not required.issubset(set(headers)):
        return None
    while headers and not headers[-1]:
        headers.pop()
    if not all(headers) or len(set(headers)) != len(headers):
        raise BillCollectionError("运单或服务奖惩表头存在空列或重名列")
    chunks, chunk = [], []
    for number, row in enumerate(rows, 2):
        if checkpoint is not None and number % 1000 == 0:
            checkpoint()
        if not any(value is not None and str(value).strip() for value in row):
            continue
        if len(row) < len(headers) or any(value is not None and str(value).strip() for value in row[len(headers):]):
            raise BillCollectionError(f"导出第 {number} 行列结构损坏")
        chunk.append([value.strip() if isinstance(value, str) else value for value in row[:len(headers)]])
        if len(chunk) >= READ_CHUNK_ROWS:
            chunks.append(pd.DataFrame(chunk, columns=headers, dtype=object))
            chunk = []
    if chunk:
        chunks.append(pd.DataFrame(chunk, columns=headers, dtype=object))
    return (pd.concat(chunks, ignore_index=True).infer_objects() if chunks else pd.DataFrame(columns=headers))


@measured("source_read_seconds")
def read_table(path, required, *, checkpoint=None):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise BillCollectionError("运单或服务奖惩原始文件缺失、为空或超过大小限制")
    try:
        if path.suffix.lower() == ".csv":
            candidates = []
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    with path.open(encoding=encoding, newline="") as source:
                        candidates = [_read_rows(csv.reader(source), required, checkpoint)]
                    break
                except UnicodeDecodeError:
                    continue
        elif path.suffix.lower() == ".xlsx":
            from order_xlsx import read_xlsx_tables, FastXlsxUnsupported
            try:
                candidates = read_xlsx_tables(path, required, _read_rows, checkpoint)
            except FastXlsxUnsupported:
                book = load_workbook(path, read_only=True, data_only=True)
                try:
                    candidates = []
                    for sheet in book:
                        sheet.reset_dimensions()
                        frame = _read_rows(sheet.iter_rows(values_only=True), required, checkpoint)
                        if frame is not None:
                            candidates.append(frame)
                finally:
                    book.close()
        else:
            raise BillCollectionError("运单和服务奖惩仅接受已确认的 XLSX 或 CSV 导出")
        matched = [frame for frame in candidates if frame is not None]
        if len(matched) != 1:
            raise BillCollectionError("导出文件缺少约定表头或包含多个同类数据表")
        return matched[0]
    except BillCollectionError:
        raise
    except Exception:
        raise BillCollectionError("运单或服务奖惩文件无法解析，核算已停止") from None


@measured("source_validate_seconds")
def validate_slice(frame, request, time_column, id_columns, *, with_dates=False):
    from parttime_source import identifier, parse_date
    from order_dates import natural_dates
    frame = frame.copy()
    for column in id_columns:
        for value in frame[column]:
            if isinstance(value, (int, float)) and abs(value) >= 10 ** 15:
                raise BillCollectionError("导出长编号必须为文本，存在精度风险")
        frame[column] = frame[column].map(identifier)
        missing = frame[column] == ""
        if column == "骑手id" and {"运单状态", "欺诈是否成立"}.issubset(frame.columns):
            unassigned_failure = frame["运单状态"].eq("配送失败") & frame["欺诈是否成立"].eq("否")
            missing &= ~unassigned_failure
        if missing.any():
            raise BillCollectionError("运单或服务奖惩关键编号缺失")
    dates = natural_dates(frame[time_column])
    if not dates.between(request.start, request.end).all():
        raise BillCollectionError("运单或服务奖惩记录超出本批日期范围")
    for column in ("代理商ID", "加盟商ID", "物流合作商ID", "商id"):
        if column in frame and any(identifier(value) != request.agency_id for value in frame[column]):
            raise BillCollectionError("运单或服务奖惩包含非目标城市数据")
    result = frame.fillna("")
    return (result, dates) if with_dates else result


@measured("penalty_clean_seconds")
def clean_violations(frame):
    from parttime_source import money, parse_date
    from order_dates import natural_dates
    result = frame.copy()
    result["日期"] = natural_dates(result["违规时间"])
    result["骑手id"] = result["骑手ID"]
    result["配送员姓名"] = result["骑手名称"]
    result["处罚金额"] = result["处罚"].map(lambda value: money(str(value).strip().removesuffix("元")))
    if result["处罚金额"].isna().any():
        raise BillCollectionError("服务奖惩处罚金额缺失，不能按零处理")
    return result[VIOLATION_CLEAN_COLUMNS]


@measured("merge_seconds")
def merge_slices(frames, identity):
    if not frames:
        raise BillCollectionError("缺少采集分批，核算已停止")
    nonempty = [frame for frame in frames if not frame.empty]
    columns = list((nonempty or frames)[0].columns)
    if any(list(frame.columns) != columns for frame in nonempty):
        raise BillCollectionError("采集批次之间表头发生变化，核算已停止")
    combined = pd.concat([frame if list(frame.columns) == columns else frame.reindex(columns=columns)
                          for frame in frames], ignore_index=True)
    duplicate_ids = combined[identity].duplicated(keep=False)
    if not duplicate_ids.any():
        return combined
    for _, group in combined.loc[duplicate_ids].groupby(identity):
        if len(group.drop_duplicates()) != 1:
            raise BillCollectionError("同一运单或违规编号出现冲突记录，核算已停止")
    return combined.drop_duplicates(subset=[identity]).reset_index(drop=True)


def daily_count_basis(actual, daily, snapshot=None, task_id=None):
    """Historical days must match; today's export is a bounded live snapshot."""
    mismatch = {day for day, count in daily.items() if actual.get(day, 0) != count}
    if not mismatch:
        return "daily_verified"
    try:
        if not isinstance(snapshot, dict):
            raise ValueError()
        day, before, after = snapshot["date"], snapshot["before"], snapshot["after"]
        started, checked = snapshot["started_at"], snapshot["checked_at"]
        zone = dt.timezone(dt.timedelta(hours=8))
        if (not isinstance(task_id, str) or not task_id.isdigit() or snapshot["task_id"] != task_id
                or type(before) is not int or type(after) is not int or not 0 <= before <= after
                or day not in daily or daily[day] != before or mismatch != {day}
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in (started, checked))
                or not 0 < started <= checked
                or dt.datetime.fromtimestamp(started, zone).date().isoformat() != day
                or dt.datetime.fromtimestamp(checked, zone).date().isoformat() != day
                or not before <= actual.get(day, 0) <= after):
            raise ValueError()
        return "live_snapshot_verified"
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        raise BillCollectionError("本批运单文件逐日行数与平台查询不一致，缺少有效实时快照核对记录") from None


def prepare_order_slice(download, raw, plan, start, end, include_violations, *, checkpoint=None):
    from fengshen_orders import OrderRequest
    if (download.get("dataset") != "issue_orders" or download.get("status") != "success"
            or download.get("agency_id") != plan.agency_id or download.get("start") != start
            or download.get("end") != end or download.get("time_basis") != "tracking_finish"
            or download.get("merchant_group") != "物流合作商" or download.get("all_city_riders") is not True):
        raise BillCollectionError("运单采集批次的城市、完成时间口径或范围未经确认")
    request = OrderRequest(start, end, plan.agency_id)
    base = (Path(raw) / "issue_orders" / (start + "_" + end)).resolve()
    paths, checks = download.get("files", {}), download.get("file_checks", {})
    expected_files = {"waybills", "violations"} if include_violations else {"waybills"}
    if set(paths) != expected_files:
        raise BillCollectionError("本批缺少运单或服务奖惩原始文件")
    if not isinstance(checks, dict) or set(checks) != set(paths):
        raise BillCollectionError("本批原始文件缺少完整性校验记录")
    frames, dates = [], None
    for key, required, date_column, id_columns in (
        ("waybills", WAYBILL_COLUMNS, "运单完成时间", ("运单id", "骑手id")),
        ("violations", VIOLATION_COLUMNS, "违规时间", ("违规编号", "运单号", "骑手ID")),
    ):
        if key not in expected_files:
            continue
        if checkpoint is not None:
            checkpoint()
        path = (base / paths[key]).resolve()
        if not path.is_relative_to(base):
            raise BillCollectionError("运单采集文件路径越界")
        proof = checks[key]
        if (not isinstance(proof, dict) or proof.get("path") != paths[key] or not path.is_file()
                or proof.get("bytes") != path.stat().st_size or proof.get("sha256") != file_hash(path)):
            raise BillCollectionError("本批原始文件完整性校验失败")
        frame, frame_dates = validate_slice(read_table(path, required, checkpoint=checkpoint), request, date_column, id_columns, with_dates=True)
        frames.append(frame)
        if key == "waybills":
            dates = frame_dates
    expected, daily = download.get("expected_waybills"), download.get("expected_waybills_by_date")
    count_basis = "batch_total"
    if daily is not None:
        days = {(dt.date.fromisoformat(start) + dt.timedelta(days=n)).isoformat()
                for n in range((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1)}
        if (not isinstance(daily, dict) or set(daily) != days
                or any(type(value) is not int or value < 0 for value in daily.values())):
            raise BillCollectionError("本批运单逐日校验记录不完整")
        actual = dates.value_counts().to_dict()
        count_basis = daily_count_basis(actual, daily, download.get("live_day_snapshot"), download.get("task_id"))
    if expected is not None and (type(expected) is not int or expected < 0 or (daily is None and expected != len(frames[0]))):
        raise BillCollectionError("本批运单文件行数与平台查询总数不一致")
    proof = {"start": start, "end": end, "waybills": len(frames[0]), "count_basis": count_basis,
             "query_total": expected, "batch_total_inconsistent": expected is not None and expected != len(frames[0])}
    if count_basis == "live_snapshot_verified":
        proof["live_day_snapshot"] = {**download["live_day_snapshot"], "exported": actual[download["live_day_snapshot"]["date"]]}
    if include_violations:
        proof["violations"] = len(frames[1])
    return {"waybills": frames[0], "violations": frames[1] if include_violations else None, "proof": proof}


@measured("finalize_seconds")
def prepare_order_files(downloads, raw, inputs, plan, batches, selected_kinds=None, *, prepared_slices=None):
    from fengshen_orders import OrderRequest
    from order_dates import natural_dates
    if isinstance(selected_kinds, str):
        raise BillCollectionError("运单输出类型必须是欺诈单、问题单的非空集合")
    try:
        selected_kinds = {"欺诈单", "问题单"} if selected_kinds is None else set(selected_kinds)
    except TypeError:
        raise BillCollectionError("运单输出类型必须是欺诈单、问题单的非空集合") from None
    if not selected_kinds or not selected_kinds.issubset({"欺诈单", "问题单"}):
        raise BillCollectionError("运单输出类型必须是欺诈单、问题单的非空集合")
    include_violations = "问题单" in selected_kinds
    expected_files = {"waybills", "violations"} if include_violations else {"waybills"}
    if len(downloads) != len(batches):
        raise BillCollectionError("运单或服务奖惩采集分批不完整")
    waybills, violations = [], []
    proofs = []
    if prepared_slices is not None and len(prepared_slices) != len(batches):
        raise BillCollectionError("已处理的运单分批不完整")
    lazy = prepared_slices is not None and hasattr(prepared_slices, "merge") and hasattr(prepared_slices, "proof")
    for number, (download, (start, end)) in enumerate(zip(downloads, batches)):
        if lazy:
            proof = prepared_slices.proof(number)
        else:
            prepared = (prepare_order_slice(download, raw, plan, start, end, include_violations)
                        if prepared_slices is None else prepared_slices[number])
            proof = prepared["proof"]
            waybills.append(prepared["waybills"])
            if include_violations:
                violations.append(prepared["violations"])
        if proof["start"] != start or proof["end"] != end:
            raise BillCollectionError("已处理的运单分批日期不一致")
        proofs.append(proof)
    orders = prepared_slices.merge("waybills") if lazy else merge_slices(waybills, "运单id")
    waybills.clear()
    if include_violations:
        merged = prepared_slices.merge("violations") if lazy else merge_slices(violations, "违规编号")
        violations.clear()
        penalties = clean_violations(merged)
        del merged
    else:
        penalties = clean_violations(pd.DataFrame(columns=sorted(VIOLATION_COLUMNS)))
    if any(value not in ("是", "否") for value in orders["欺诈是否成立"]):
        raise BillCollectionError("欺诈是否成立出现未确认状态，核算已停止")
    cleaner = DataCleaner.from_frames(orders, penalties, copy=False)
    # 问题单汇总依然需要在内存识别欺诈运单，避免把同一运单重复列入问题单。
    kinds = cleaner.run(issue_types(plan.city) if include_violations else ["欺诈单"])
    fraud = kinds["欺诈单"]
    result = {"order_batches": proofs}
    if "欺诈单" in selected_kinds:
        result["欺诈单"] = {"rows": len(fraud), "status": "empty" if fraud.empty else "validated", "filtered_by_applicants": False}
    if include_violations:
        # Build the original summary in memory; do not merge with historical output directories.
        summary = MergePenaltyRecords.__new__(MergePenaltyRecords).build_sum_data(kinds)
        if any(pd.isna(value) or str(value).strip() == "" for value in summary["骑手id"]):
            raise BillCollectionError("问题单骑手编号缺失，核算已停止")
        # Payroll matches natural days; mixed date/timestamp CSV values lose dates downstream.
        summary["日期"] = natural_dates(summary["日期"])
        counts = summary["类型"].value_counts().to_dict()
        result["问题单"] = {"rows": len(summary), "status": "empty" if summary.empty else "validated", "filtered_by_applicants": False,
                            "type_counts": {kind: int(counts.get(kind, 0)) for kind in kinds if kind != "欺诈单"},
                            "service_rows": len(penalties),
                            "service_excluded_rows": len(penalties) - len(cleaner.bad_unit_data)}
    if "欺诈单" in selected_kinds:
        write_order_csv(fraud, Path(inputs) / (plan.city + "-欺诈单_auto.csv"))
    if include_violations:
        write_order_csv(summary, Path(inputs) / (plan.city + "-问题单_auto.csv"))
    return result


@measured("csv_write_seconds")
def write_order_csv(frame, path):
    frame.to_csv(path, encoding="utf-8-sig", index=False, chunksize=10000)
