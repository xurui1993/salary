"""Reconcile isolated automatic downloads with captured manual exports; never calculate payroll."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import atomic_json, validate_bill_file
from parttime_source import ROOT, SourceError, clean_rider_bill, inspect_source, read_rider_bill, unpack_daily, validate_daily
from verify_fengshen_capture import captured_files, daily_records, digest, within


def accepted_file(root, dataset, plan):
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("status") != "success" or manifest.get("acceptance_only") is not True
            or manifest.get("payroll_executed") is not False or manifest.get("production_profile_enabled") is not False
            or manifest.get("dataset") != dataset or manifest.get("agency_id") != plan.agency_id
            or manifest.get("merchant_group") != "物流合作商" or len(manifest.get("files", [])) != 1):
        raise SourceError("自动验收任务未完成或范围不符")
    if dataset == "agency_daily":
        if ((manifest.get("start"), manifest.get("end")) != (plan.start, plan.end)
                or set(manifest.get("sub_bill_scope", [])) != {"配送费", "违规扣款"} or not manifest.get("task_id")):
            raise SourceError("日账单验收没有确认本次任务或两个子账单范围")
    elif manifest.get("month") != plan.month or manifest.get("bill_status") != "all":
        raise SourceError("月账单验收月份或状态范围不符")
    proof_root = root.with_name(root.name + "-diagnostics")
    before = json.loads((proof_root / f"city_{plan.agency_id}_selected_before_close.json").read_text(encoding="utf-8"))
    after = json.loads((proof_root / f"city_{plan.agency_id}_confirmed_after_close.json").read_text(encoding="utf-8"))
    groups = before.get("groups", [])
    partner = [group for group in groups if group["label"] == "物流合作商"]
    selected = lambda group: [item["agencyId"] for item in group["options"] if item["selected"]]
    if (before.get("header_ids") != [plan.agency_id] or after.get("header_ids") != [plan.agency_id]
            or len(partner) != 1 or selected(partner[0]) != [plan.agency_id]
            or any(selected(group) for group in groups if group["label"] != "物流合作商")):
        raise SourceError("自动城市切换缺少物流合作商唯一选中证据")
    item = manifest["files"][0]
    path = within(root, item["path"])
    actual = validate_bill_file(path)
    if any(item.get(key) != actual[key] for key in ("bytes", "sha256", "format")):
        raise SourceError("验收下载文件与原始清单不符")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-run", type=Path, required=True)
    parser.add_argument("--monthly-run", type=Path, required=True)
    parser.add_argument("--manual-capture", type=Path, required=True)
    parser.add_argument("--manual-source", type=Path, required=True)
    args = parser.parse_args(argv)
    plan, _, _ = inspect_source(args.manual_source)
    automatic = {dataset: accepted_file(root, dataset, plan) for dataset, root in
                 (("agency_daily", args.daily_run), ("rider_monthly", args.monthly_run))}
    manual = captured_files(args.manual_capture.resolve())
    originals = [path for path in args.manual_source.iterdir() if path.is_file() and not path.name.startswith("~")]
    source_hashes = {path: digest(path) for path in originals + list(automatic.values()) + list(manual.values())}
    run = ROOT / "outputs" / "acceptance_checks" / uuid.uuid4().hex
    run.mkdir(parents=True)
    report = {"plan": asdict(plan), "payroll_executed": False, "production_profile_enabled": False,
              "automatic_city_switch_verified": True, "automatic_download_verified": True,
              "daily": {}, "monthly": {}, "status": "running"}
    try:
        daily = unpack_daily(automatic["agency_daily"], run / "daily")
        baseline = unpack_daily(manual["agency_daily"], run / "manual_daily")
        for kind, path in daily.items():
            info = validate_daily(path, plan)
            validate_daily(baseline[kind], plan)
            actual, expected = daily_records(path, plan), daily_records(baseline[kind], plan)
            info.update(headers_equal=actual[0] == expected[0], records_equal=actual[1] == expected[1],
                        amount_total_equal=actual[2] == expected[2])
            report["daily"][kind] = info
        info = clean_rider_bill(automatic["rider_monthly"], run / "monthly_cleaned.csv", plan)
        clean_rider_bill(manual["rider_monthly"], run / "manual_monthly_cleaned.csv", plan)
        headers, rows = read_rider_bill(automatic["rider_monthly"])
        expected_headers, expected_rows = read_rider_bill(manual["rider_monthly"])
        riders = Counter(row[headers.index("骑手ID")] for row in rows)
        info.update(header_row=4, rider_count=len(riders), multi_bill_riders=sum(count > 1 for count in riders.values()),
                    headers_equal=headers == expected_headers,
                    records_equal=headers == expected_headers and Counter(map(tuple, rows)) == Counter(map(tuple, expected_rows)))
        report["monthly"] = info
        matched = info["records_equal"] and all(all(value[key] for key in
                    ("headers_equal", "records_equal", "amount_total_equal")) for value in report["daily"].values())
        report.update(data_validation="passed", manual_comparison="matched" if matched else "different",
                      status="passed" if matched else "failed")
    except SourceError as exc:
        report.update(status="failed", data_validation="failed", error=str(exc))
    report["originals_unchanged"] = all(digest(path) == expected for path, expected in source_hashes.items())
    if not report["originals_unchanged"]:
        report["status"] = "failed"
    atomic_json(run / "verification.json", report)
    print(json.dumps({"report": str(run / "verification.json"), **{key: value for key, value in report.items() if key != "plan"}}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
