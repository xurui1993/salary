"""Verify human-downloaded inspection samples without enabling automatic payroll."""

import argparse
from collections import Counter
import csv
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import atomic_json, validate_bill_file
from parttime_source import (
    ROOT, SourceError, clean_rider_bill, csv_encoding, inspect_source, money,
    parse_date, read_rider_bill, unpack_daily, validate_daily,
)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def within(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise SourceError("检查记录引用了目录外的文件")
    return path


def captured_files(root):
    flow = json.loads((root / "inspection_flow.json").read_text(encoding="utf-8"))
    if flow.get("inspection_only") is not True or flow.get("complete") is not True:
        raise SourceError("两页检查尚未完成")
    if set(flow.get("captures", {})) != {"agency_daily", "rider_monthly"}:
        raise SourceError("缺少日账单或月账单检查记录")
    files = {}
    for dataset, relative in flow["captures"].items():
        controls = within(root, relative)
        data = json.loads(controls.read_text(encoding="utf-8"))
        samples = data.get("downloads", [])
        if data.get("observed_dataset") != dataset or len(samples) != 1:
            raise SourceError("每张账单需有唯一对应下载")
        sample = samples[0]
        if sample.get("status") != "saved" or sample.get("source_dataset") != dataset:
            raise SourceError("账单下载来源或保存状态未确认")
        files[dataset] = within(root, (controls.parent / sample["path"]).relative_to(root).as_posix())
        validate_bill_file(files[dataset])
    return files


def daily_records(path, plan):
    with path.open(encoding=csv_encoding(path), newline="") as source:
        reader = csv.DictReader(source)
        columns = tuple(reader.fieldnames)
        records = Counter()
        total = Decimal(0)
        dates = set()
        for row in reader:
            if not any(row.values()):
                continue
            day = parse_date(row["账单时间"]).isoformat()
            if not plan.start <= day <= plan.end:
                continue
            records[tuple(str(row.get(key) or "").strip() for key in columns)] += 1
            total += Decimal(money(row["金额"]))
            dates.add(day)
    return columns, records, total, dates


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--manual-source", type=Path, required=True)
    args = parser.parse_args(argv)
    files = captured_files(args.capture.resolve())
    plan, template, _ = inspect_source(args.manual_source)
    originals = [path for path in args.manual_source.iterdir() if path.is_file() and not path.name.startswith("~")]
    source_hashes = {path: digest(path) for path in originals + list(files.values())}
    run = ROOT / "outputs" / "capture_checks" / uuid.uuid4().hex
    run.mkdir(parents=True)
    report = {
        "inspection_only": True, "automatic_download_verified": False,
        "automatic_city_switch_verified": False, "payroll_executed": False,
        "plan": asdict(plan), "daily": {}, "monthly": {},
        "comparison_scope": "daily_template_period_and_all_monthly_city_riders",
    }
    try:
        unpacked = unpack_daily(files["agency_daily"], run / "daily")
        for kind, path in unpacked.items():
            info = validate_daily(path, plan)
            actual = daily_records(path, plan)
            manual = [item for item in originals if kind in item.name and item.suffix.lower() == ".csv"]
            if len(manual) > 1:
                raise SourceError("人工资料需有唯一对应子账单")
            expected = daily_records(manual[0], plan) if manual else None
            info.update(
                actual_min_date=min(actual[3]) if actual[3] else None,
                actual_max_date=max(actual[3]) if actual[3] else None,
                manual_rows=sum(expected[1].values()) if expected else None,
                headers_equal=actual[0] == expected[0] if expected else None,
                rows_equal=actual[0] == expected[0] and actual[1] == expected[1] if expected else None,
                total_equal=actual[2] == expected[2] if expected else None,
            )
            report["daily"][kind] = info
        monthly = clean_rider_bill(files["rider_monthly"], run / "monthly_cleaned.csv", plan)
        headers, rows = read_rider_bill(files["rider_monthly"])
        manual = [item for item in originals if "骑手账单" in item.name and item.suffix.lower() == ".xlsx"]
        if len(manual) > 1:
            raise SourceError("人工资料需有唯一 UB 骑手月账单")
        expected_headers, expected_rows = read_rider_bill(manual[0]) if manual else (None, None)
        riders = Counter(row[headers.index("骑手ID")] for row in rows)
        monthly.update(
            header_row=4, rider_count=len(riders),
            multi_bill_riders=sum(value > 1 for value in riders.values()),
            manual_rows=len(expected_rows) if expected_rows is not None else None,
            headers_equal=headers == expected_headers if expected_headers is not None else None,
            rows_equal=headers == expected_headers and Counter(map(tuple, rows)) == Counter(map(tuple, expected_rows))
                if expected_rows is not None else None,
        )
        report["monthly"] = monthly
        report["data_validation"] = "passed"
        if monthly["manual_rows"] is None or any(value["manual_rows"] is None for value in report["daily"].values()):
            report["manual_comparison"] = "unavailable"
        else:
            report["manual_comparison"] = "matched" if monthly["rows_equal"] and all(
                value["rows_equal"] and value["total_equal"] for value in report["daily"].values()) else "different"
    except SourceError as exc:
        report.update(data_validation="failed", error=str(exc))
    report["originals_unchanged"] = all(digest(path) == expected for path, expected in source_hashes.items())
    atomic_json(run / "verification.json", report)
    print(json.dumps({"report": str(run / "verification.json"), **{key: value for key, value in report.items()
        if key not in ("plan", "comparison_scope")}}, ensure_ascii=False))
    return 0 if report.get("data_validation") == "passed" and report["originals_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
