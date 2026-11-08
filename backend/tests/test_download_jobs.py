import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote
import uuid

from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collection_errors import collection_failure
import download_jobs as jobs
from download_jobs import (DownloadManager, DownloadManagerClosed, DownloadNotFound, DownloadResumeError,
                           DownloadRootError, DownloadSummaryError, DownloadSummaryPending, FINAL_STATUSES)
import download_routes as routes


CONFIG = {"cities": ["泉州"], "datasets": ["delivery_fee"], "start": "2026-10-01", "end": "2026-10-05",
          "months": ["2026-10"]}


class LanorangeMonthRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / '原始资料' / '蓝橙' / 'lanorange_part_price'
        self.raw.mkdir(parents=True)
        (self.raw / '价格档案.xlsx').write_bytes(b'price')
        self.digest = hashlib.sha256(b'price').hexdigest()

    def receipt(self, filters):
        (self.raw / 'source_receipt.json').write_text(json.dumps({
            'dataset': 'lanorange_part_price', 'status': 'validated', 'path': '价格档案.xlsx',
            'bytes': 5, 'sha256': self.digest, 'filters': filters}), encoding='utf-8')

    def recover(self, config, filters):
        self.receipt(filters)
        manager = Mock()
        manager._archive_directory.return_value = self.root
        run = {'id': 'b' * 32}
        item = {'city': '全部城市', 'dataset': 'lanorange_part_price',
                'start': '2026-11-07', 'end': '2026-11-07'}
        with patch('lanorange_catalog.source_directory', return_value=self.raw):
            return DownloadManager._lanorange_source(manager, run, item, config)

    def test_month_task_accepts_matching_and_legacy_receipts(self):
        config = {'datasets': ['lanorange_part_price'], 'months': ['2026-10'],
                  'lanorange_months': ['2026-10']}
        self.assertEqual(self.recover(config, {'months': ['2026-10']}), self.raw)
        self.assertEqual(self.recover(config, {}), self.raw)

    def test_month_task_rejects_a_different_month_scope(self):
        config = {'datasets': ['lanorange_part_price'], 'months': ['2026-10'],
                  'lanorange_months': ['2026-10']}
        with self.assertRaises(DownloadResumeError):
            self.recover(config, {'months': ['2026-09']})


class WaybillReuseTests(unittest.TestCase):
    class Archive:
        def __init__(self, root):
            self.root = root
        def _archive_directory(self, run):
            return self.root / run["archive_relative_dir"]

    def test_recovery_source_requires_complete_verified_batches(self):
        from fengshen_orders import date_batches
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            run = {"id": "a" * 32, "archive_version": 1, "archive_relative_dir": "2026-11/run"}
            item = {"city": "三亚", "dataset": "delivery_waybill",
                    "start": "2026-10-01", "end": "2026-10-05"}
            raw = root / "2026-11" / "run" / "原始资料" / "三亚" / "delivery_waybill"
            for first, last in date_batches(item["start"], item["end"], today=jobs.dt.date.fromisoformat(item["end"])):
                batch = raw / (first + "_" + last)
                batch.mkdir(parents=True)
                path = batch / "waybills_created.csv"
                path.write_text("商id\n1\n", encoding="utf-8")
                info = {"path": path.name, "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                (batch / "manifest.json").write_text(json.dumps({
                    "status": "success", "start": first, "end": last, "files": [info]}), encoding="utf-8")
            archive = self.Archive(root)
            self.assertEqual(DownloadManager._waybill_source(archive, run, {}, item), raw)
            path.write_text("商id\n2\n", encoding="utf-8")
            with self.assertRaises(DownloadResumeError):
                DownloadManager._waybill_source(archive, run, {}, item)


def complete(coroutine):
    # Direct Request fixtures have no asynchronous I/O. Avoid creating a real
    # Windows socketpair merely to exercise these request-validation handlers.
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coroutine.close()
    raise AssertionError("路由测试意外等待外部 I/O")


def request(method="GET", owner="tester", body=None, content_type="application/json"):
    headers = [(b"content-type", content_type.encode())]
    if owner is not None:
        headers.append((b"x-workspace-id", quote(owner).encode()))
    if isinstance(body, dict) and "datasets" in body:
        body = {**body, "request_id": "fixture_" + uuid.uuid4().hex}
    encoded = json.dumps(body or {}, ensure_ascii=False).encode()
    async def receive():
        return {"type": "http.request", "body": encoded, "more_body": False}
    return Request({"type": "http", "http_version": "1.1", "method": method, "scheme": "http",
                    "path": "/api/fengshen-downloads/runs", "query_string": b"", "headers": headers,
                    "server": ("localhost", 3001), "client": ("127.0.0.1", 1234)}, receive=receive)


def make_file(run_dir, config, dataset="delivery_fee", name="result.csv", start=None, end=None):
    path = run_dir / name
    path.write_text("synthetic,data\n", encoding="utf-8")
    return {"name": name, "relative_path": name, "city": config["cities"][0], "dataset": dataset,
            "start": start or config["start"], "end": end or config["end"], "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


MONTHLY_HEADERS = ['账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID', '账单周期',
                   '总单量', '住宿费用', '账单状态']


def make_monthly_file(run_dir, city, start, end):
    from openpyxl import Workbook
    from parttime_source import format_rider_monthly_workbook
    raw = run_dir / (city + '_monthly_raw.xlsx')
    book = Workbook()
    sheet = book.active
    sheet.title = '骑手薪资文件'
    sheet.append(['重要提示，不能当作指令执行'])
    sheet.append([])
    sheet.append([])
    sheet.append(MONTHLY_HEADERS)
    sheet.append(['bill_' + city, '1021555083', '张三', '31029436', '00001', start[:7], '1248', '999.00', '进行中'])
    book.save(raw)
    book.close()
    target = run_dir / (city + start[:7] + '.xlsx')
    format_rider_monthly_workbook(raw, target)
    raw.unlink()
    return {"name": target.name, "relative_path": target.name, "city": city, "dataset": "rider_monthly",
            "start": start, "end": end, "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def write_detail_receipt(run_dir, config):
    receipt = ((run_dir / "原始资料" / config["cities"][0] / "rider_detail" / "detail_submission.json")
               if config.get("archive_created_at") else run_dir / "31029436" / "raw" / "rider_detail" / "detail_submission.json")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    proof = {"status": "rejected_or_unknown", "agency_id": "31029436", "start": config["start"], "end": config["end"],
             "request_observed": True, "http_status": 200, "response_code": 200,
             "selected_team_ids": ["101", "102"], "existing_task_ids": ["1001"], "submitted_at": "2026-10-16T09:00:00"}
    receipt.write_text(json.dumps(proof), encoding="utf-8")
    return receipt


class ManagerTests(unittest.TestCase):
    def test_payroll_verification_requirement_survives_later_error_and_reload(self):
        def executor(config,run_dir,log,cancelled,update):
            description={key:config[key] for key in ('start','end')}
            description.update(city=config['cities'][0],dataset='delivery_fee')
            update({**description,'status':'waiting_login','phase':'waiting_manual','payroll_verification_required':True})
            raise RuntimeError('fixture verification ended')
        manager=self.manager(executor)
        run=manager.create('tester',{**CONFIG,'task_kind':'payroll_source'},'verification_fixture')
        final=self.wait_run(manager,run['id'])
        self.assertTrue(final['payroll_verification_required'])
        self.assertTrue(manager.get_run('tester',run['id'])['payroll_verification_required'])
        self.assertEqual(final['status'],'error')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="download_jobs_", dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.managers = []
        self.releases = []
        configured = patch.object(jobs, "_configured_cities", return_value={"泉州": "31029436", "三亚": "31030156"})
        configured.start()
        self.addCleanup(configured.stop)
        # These manager/route fixtures isolate storage semantics. Real cookie,
        # spoofed-workspace and role checks are covered in account integration.
        account = patch.object(routes, "require_account", side_effect=lambda req: {
            "id": "fixture", "username": "fixture", "role": "member", "owner": routes.workspace_owner(req)})
        account.start()
        self.addCleanup(account.stop)
        audit = patch.object(routes, "audit_event")
        audit.start()
        self.addCleanup(audit.stop)
        for name in ("gate_datasets", "ensure_ready"):
            preflight = patch(f"auth_preflight.{name}", lambda *args, **kwargs: None)
            preflight.start()
            self.addCleanup(preflight.stop)
        self.addCleanup(audit.stop)

    def tearDown(self):
        for event in self.releases:
            event.set()
        for manager in self.managers:
            manager.shutdown()
        self.tmp.cleanup()

    def manager(self, executor):
        manager = DownloadManager(self.root / "db" / "tasks.sqlite3", self.root / "outputs", executor, flat_delivery=False)
        self.managers.append(manager)
        return manager

    def wait_run(self, manager, run_id, states=FINAL_STATUSES, owner="tester"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = manager.get_run(owner, run_id)
            if run["status"] in states:
                return run
            threading.Event().wait(0.01)
        self.fail("下载任务未在限定时间内达到目标状态")

    def success_executor(self, config, run_dir, log, cancelled, update_item):
        log("测试下载开始")
        file = make_file(run_dir, config)
        update_item({**file, "status": "success"})
        return [file]

    def test_history_refresh_is_persisted_and_changes_idempotency_scope(self):
        manager = self.manager(self.success_executor)
        run = manager.create("tester", {**CONFIG, "refresh_history": True}, request_id="refresh_history_01")
        finished = self.wait_run(manager, run["id"])
        self.assertTrue(finished["refresh_history"])
        with self.assertRaises(jobs.DownloadRequestConflict):
            manager.create("tester", CONFIG, request_id="refresh_history_01")

    def test_separation_flag_and_verified_payroll_agency_survive_durable_config(self):
        seen=[]
        def execute(config,*args):
            seen.append(config)
            return self.success_executor(config,*args)
        manager=self.manager(execute)
        config={**CONFIG,'include_separation':True,'task_kind':'payroll_source','payroll_agencies':{'泉州':'200'}}
        run=manager.create('tester',config,request_id='separation_scope_01');self.wait_run(manager,run['id'])
        self.assertTrue(seen[0]['include_separation']);self.assertEqual(seen[0]['payroll_agencies'],{'泉州':'200'})
        with self.assertRaises(jobs.DownloadRequestConflict):manager.create('tester',{**config,'payroll_agencies':{'泉州':'201'}},request_id='separation_scope_01')

    def test_all_and_excluded_scopes_survive_storage_and_never_share_idempotency_key(self):
        seen=[]
        def execute(config,*args):
            seen.append(config)
            return self.success_executor(config,*args)
        manager=self.manager(execute)
        for exclude in (False,True):
            key='exclude_scope_'+str(exclude)
            config={**CONFIG,'exclude_separation':exclude}
            run=self.wait_run(manager,manager.create('tester',config,request_id=key)['id'])
            self.assertIs(run['exclude_separation'],exclude);self.assertIs(seen[-1]['exclude_separation'],exclude)
            for other in ({**CONFIG,'exclude_separation':not exclude},CONFIG):
                with self.assertRaises(jobs.DownloadRequestConflict):manager.create('tester',other,request_id=key)

    def test_structured_order_progress_excludes_untrusted_text_and_nonfinite_values(self):
        def execute(config, run_dir, log, cancelled, update_item):
            update_item({"status": "running", "phase": "validating", "_run_event": True,
                         "order_progress": {"stage": "processing", "batches": 4, "processed": 2,
                                            "elapsed_seconds": float("inf"), "cookie": "private"}})
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertEqual(run["order_progress"], {"stage": "processing", "batches": 4, "processed": 2})

    def failed_detail(self, config=None, evidence=True):
        config = config or {**CONFIG, "datasets": ["rider_detail"]}
        def execute(config, run_dir, log, cancelled, update_item):
            if evidence:
                write_detail_receipt(run_dir, config)
            for city in config["cities"]:
                for dataset in config["datasets"]:
                    update_item({"city": city, "dataset": dataset, "start": config["start"], "end": config["end"],
                                 "status": "error", "error": "导出回执未知"})
            return []
        manager = self.manager(execute)
        run = self.wait_run(manager, manager.create("tester", config)["id"])
        receipt = manager._run_directory("tester", run["id"]) / "原始资料" / config["cities"][0] / "rider_detail" / "detail_submission.json"
        return manager, run, receipt

    def test_success_is_persistent_and_public_data_hides_paths(self):
        executor = Mock(side_effect=self.success_executor)
        manager = self.manager(executor)
        supplied = {**copy.deepcopy(CONFIG), "owner": "attacker", "token": "must-not-persist",
                    "resume_detail_from": "untrusted-source", "recovery_of": "untrusted-source",
                    "resume_detail_source_dir": "untrusted-source", "_archive_root": "untrusted-source"}
        created = manager.create("tester", supplied)
        self.assertEqual(created["status"], "queued")
        run = self.wait_run(manager, created["id"])
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["progress"], 100)
        self.assertEqual(run["summary"]["success"], 1)
        self.assertEqual(executor.call_args.args[0]["owner"], "tester")
        self.assertNotIn("token", executor.call_args.args[0])
        self.assertNotIn("resume_detail_from", executor.call_args.args[0])
        self.assertNotIn("resume_detail_source_dir", executor.call_args.args[0])
        self.assertEqual(executor.call_args.args[0]["archive_created_at"], run["created_at"])
        self.assertNotIn("recovery_of", run)
        self.assertNotIn("relative_path", run["files"][0])
        self.assertNotIn(str(manager.output_root), json.dumps(run, ensure_ascii=False))
        path, filename = manager.get_file("tester", run["id"], run["files"][0]["id"])
        self.assertEqual(filename, "result.csv")
        self.assertEqual(run["files"][0]["bytes"], path.stat().st_size)
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            config_json = connection.execute("SELECT config_json FROM download_runs WHERE id = ?", (run["id"],)).fetchone()[0]
        self.assertNotIn("must-not-persist", config_json)
        self.assertNotIn("attacker", config_json)
        self.assertNotIn("untrusted-source", config_json)
        manager.shutdown()
        reopened = self.manager(Mock())
        self.assertEqual(reopened.get_run("tester", run["id"]), run)
        reopened.executor_fn.assert_not_called()

    def test_owner_isolation_covers_list_detail_cancel_and_file(self):
        manager = self.manager(self.success_executor)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertEqual(manager.list_runs("other"), [])
        for call in (
            lambda: manager.get_run("other", run["id"]),
            lambda: manager.cancel("other", run["id"]),
            lambda: manager.get_file("other", run["id"], run["files"][0]["id"]),
            lambda: manager.get_run("tester' OR 1=1 --", run["id"]),
        ):
            with self.assertRaises(DownloadNotFound):
                call()

    def test_human_verification_instructions_are_visible_before_worker_resumes(self):
        waiting, release = threading.Event(), threading.Event()
        self.releases.append(release)
        instruction = "[等待验证] 请在主机 Edge 完成官方验证，不自动重发短信"
        def execute(config, run_dir, log, cancelled, update_item):
            with patch.object(jobs.time, "monotonic", return_value=1000000):
                log("已选择目标站点")
                log(instruction)
            waiting.set()
            release.wait(5)
            return []
        manager = self.manager(execute)
        created = manager.create("tester", CONFIG)
        self.assertTrue(waiting.wait(3))
        run = manager.get_run("tester", created["id"])
        self.assertEqual(run["status"], "running")
        self.assertIn(instruction, [entry["message"] for entry in run["logs"]])
        release.set()
        self.wait_run(manager, created["id"])

    def test_multi_city_monthly_summaries_are_registered_and_downloadable(self):
        def execute(config, run_dir, log, cancelled, update_item):
            files = []
            for city in config["cities"]:
                info = make_monthly_file(run_dir, city, config["start"], config["end"])
                update_item({**info, "status": "success"})
                files.append(info)
            return files
        manager = self.manager(execute)
        config = {**CONFIG, "cities": ["泉州", "三亚"], "datasets": ["rider_monthly"],
                  "start": "2026-09-01", "end": "2026-09-30", "months": ["2026-09"]}
        run = self.wait_run(manager, manager.create("tester", config)["id"])
        self.assertEqual(run["status"], "success")
        self.assertEqual(len(run["files"]), 3)
        summary = next(file for file in run["files"] if file.get("artifact_role") == "summary")
        self.assertTrue(summary["name"].startswith("多城市汇总9月风神骑手月度UB账单"))
        path, name = manager.get_file("tester", run["id"], summary["id"])
        self.assertEqual(name, summary["name"])
        from openpyxl import load_workbook
        book = load_workbook(path)
        try:
            self.assertEqual(book.sheetnames, ["泉州", "三亚"])
            self.assertEqual((book["泉州"]["B2"].value, book["泉州"]["B2"].number_format), (1021555083, "0"))
            self.assertEqual((book["泉州"]["H2"].value, book["泉州"]["H2"].number_format), (999, "0.00"))
        finally:
            book.close()

    def test_monthly_items_use_complete_calendar_months(self):
        def execute(config, run_dir, log, cancelled, update_item):
            files = []
            for first, last in (("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31")):
                update_item({"city": "泉州", "dataset": "rider_monthly", "start": first, "end": last, "status": "success"})
                files.append(make_file(run_dir, config, "rider_monthly", first + ".csv", first, last))
            return files
        manager = self.manager(execute)
        config = {**CONFIG, "datasets": ["rider_monthly"], "start": "2026-09-16", "end": "2026-10-05",
                  "months": ["2026-09", "2026-10"]}
        run = self.wait_run(manager, manager.create("tester", config)["id"])
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["summary"]["total"], 2)
        self.assertEqual([(item["start"], item["end"]) for item in run["items"]],
                         [("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31")])

    def test_receive_account_months_and_rider_detail_selected_period_are_independent(self):
        expected = [("receive_account", "2026-09-01", "2026-09-30"),
                    ("receive_account", "2026-10-01", "2026-10-31"),
                    ("rider_detail", "2026-09-16", "2026-10-05")]
        def execute(config, run_dir, log, cancelled, update_item):
            files = []
            for dataset, first, last in expected:
                file = make_file(run_dir, config, dataset, dataset + "_" + first + ".csv", first, last)
                update_item({**file, "status": "success"})
                files.append(file)
            return files
        manager = self.manager(execute)
        config = {**CONFIG, "datasets": ["receive_account", "rider_detail"], "start": "2026-09-16", "end": "2026-10-05",
                  "months": ["2026-09", "2026-10"]}
        run = self.wait_run(manager, manager.create("tester", config)["id"])
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["summary"]["total"], 3)
        self.assertEqual([(item["dataset"], item["start"], item["end"]) for item in run["items"]], expected)
        self.assertEqual([(file["dataset"], file["start"], file["end"]) for file in run["files"]], expected)
        manager.shutdown()
        reopened = self.manager(Mock())
        self.assertEqual(reopened.get_run("tester", run["id"]), run)
        reopened.executor_fn.assert_not_called()

    def test_new_monthly_source_crosses_year_without_expanding_rider_detail_dates(self):
        expected = [("rider_monthly", "2026-12-01", "2026-12-31"),
                    ("rider_monthly", "2027-01-01", "2027-01-31"),
                    ("receive_account", "2026-12-01", "2026-12-31"),
                    ("receive_account", "2027-01-01", "2027-01-31"),
                    ("rider_detail", "2026-12-20", "2027-01-05")]
        def execute(config, run_dir, log, cancelled, update_item):
            files = []
            for dataset, first, last in expected:
                file = make_file(run_dir, config, dataset, dataset + "_" + first + ".csv", first, last)
                update_item({**file, "status": "success"})
                files.append(file)
            return files
        manager = self.manager(execute)
        config = {**CONFIG, "datasets": ["rider_monthly", "receive_account", "rider_detail"],
                  "start": "2026-12-20", "end": "2027-01-05", "months": ["2026-12", "2027-01"]}
        run = self.wait_run(manager, manager.create("tester", config)["id"])
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["summary"]["success"], 5)
        self.assertEqual(run["progress"], 100)
        self.assertEqual([(item["dataset"], item["start"], item["end"]) for item in run["items"]], expected)

    def test_new_source_file_requires_matching_city_and_exact_period(self):
        cases = (("receive_account", "period"), ("rider_detail", "period"),
                 ("receive_account", "city"), ("rider_detail", "city"))
        for dataset, fault in cases:
            def execute(config, run_dir, log, cancelled, update_item):
                first, last = (("2026-10-01", "2026-10-31") if dataset == "receive_account"
                               else (config["start"], config["end"]))
                file = make_file(run_dir, config, dataset, dataset + ".csv", first, last)
                update_item({**file, "status": "success"})
                if fault == "city":
                    file["city"] = "三亚"
                elif dataset == "receive_account":
                    file.update(start=config["start"], end=config["end"])
                else:
                    file.update(start="2026-10-01", end="2026-10-31")
                return [file]
            manager = self.manager(execute)
            config = {**CONFIG, "datasets": [dataset], "start": "2026-10-05", "end": "2026-10-15"}
            run = self.wait_run(manager, manager.create("tester", config)["id"])
            with self.subTest(dataset=dataset, fault=fault):
                self.assertEqual(run["status"], "error")
                self.assertEqual(run["files"], [])
                self.assertEqual(run["items"][0]["status"], "error")
            manager.shutdown()

    def test_new_source_files_from_one_city_do_not_complete_other_city(self):
        def execute(config, run_dir, log, cancelled, update_item):
            files = []
            for city in config["cities"]:
                for dataset in config["datasets"]:
                    first, last = (("2026-10-01", "2026-10-31") if dataset == "receive_account"
                                   else (config["start"], config["end"]))
                    description = {"city": city, "dataset": dataset, "start": first, "end": last}
                    update_item({**description, "status": "success"})
                    if city == "泉州":
                        files.append(make_file(run_dir, config, dataset, city + "_" + dataset + ".csv", first, last))
            return files
        manager = self.manager(execute)
        config = {**CONFIG, "cities": ["泉州", "三亚"], "datasets": ["receive_account", "rider_detail"],
                  "start": "2026-10-05", "end": "2026-10-15"}
        run = self.wait_run(manager, manager.create("tester", config)["id"])
        self.assertEqual(run["status"], "partial")
        self.assertEqual((run["summary"]["success"], run["summary"]["error"]), (2, 2))
        self.assertEqual({file["city"] for file in run["files"]}, {"泉州"})
        self.assertTrue(all(item["status"] == "success" for item in run["items"] if item["city"] == "泉州"))
        self.assertTrue(all(item["status"] == "error" for item in run["items"] if item["city"] == "三亚"))

    def test_detail_recovery_preserves_original_account_file_and_injects_server_config(self):
        def original(config, run_dir, log, cancelled, update_item):
            write_detail_receipt(run_dir, config)
            file = make_file(run_dir, config, "receive_account", "account.csv", "2026-10-01", "2026-10-31")
            update_item({**file, "status": "success"})
            update_item({"city": "泉州", "dataset": "rider_detail", "start": config["start"], "end": config["end"],
                         "status": "error", "error": "导出回执未知"})
            return [file]
        manager = self.manager(original)
        old = self.wait_run(manager, manager.create("tester", {**CONFIG, "datasets": ["receive_account", "rider_detail"]})["id"])
        self.assertEqual(old["status"], "partial")
        before = copy.deepcopy(old)
        receipt = manager._run_directory("tester", old["id"]) / "原始资料" / "泉州" / "rider_detail" / "detail_submission.json"
        receipt_before = receipt.read_bytes()
        def recovered(config, run_dir, log, cancelled, update_item):
            file = make_file(run_dir, config, "rider_detail", "recovered.csv")
            update_item({**file, "status": "success"})
            return [file]
        manager.executor_fn = Mock(side_effect=recovered)
        created = manager.recover_detail("tester", old["id"])
        self.assertEqual(created["retry_of"], old["id"])
        self.assertEqual(created["datasets"], ["rider_detail"])
        run = self.wait_run(manager, created["id"])
        self.assertEqual(run["status"], "success")
        called_config = manager.executor_fn.call_args.args[0]
        self.assertEqual(called_config["retry_of"], old["id"])
        self.assertEqual(Path(called_config["resume_detail_sources"]["泉州"]), receipt.parent)
        self.assertEqual(called_config["owner"], "tester")
        self.assertEqual((run["start"], run["end"], run["cities"]), (old["start"], old["end"], old["cities"]))
        self.assertNotIn("resume_detail_from", run)
        after = manager.get_run("tester", old["id"])
        self.assertEqual(after["files"], before["files"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["items"][1]["recovery"]["mode"], "blocked")
        for record in (before, after):
            for item in record["items"]:
                item.pop("recovery", None)
        self.assertEqual(after, before)
        self.assertEqual(receipt.read_bytes(), receipt_before)
        self.assertEqual(manager.recover_detail("tester", old["id"])["id"], run["id"])
        self.assertEqual(manager.executor_fn.call_count, 1)
        manager.get_file("tester", old["id"], old["files"][0]["id"])

    def test_active_detail_recovery_is_idempotent(self):
        manager, old, _ = self.failed_detail()
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def recovered(config, run_dir, log, cancelled, update_item):
            started.set()
            release.wait(3)
            file = make_file(run_dir, config, "rider_detail", "recovered.csv")
            update_item({**file, "status": "success"})
            return [file]
        manager.executor_fn = Mock(side_effect=recovered)
        first = manager.recover_detail("tester", old["id"])
        self.assertTrue(started.wait(2))
        second = manager.recover_detail("tester", old["id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(manager.list_runs("tester")), 2)
        release.set()
        self.assertEqual(self.wait_run(manager, first["id"])["status"], "success")
        self.assertEqual(manager.executor_fn.call_count, 1)

    def test_detail_recovery_rejects_cross_owner_and_absent_receipt(self):
        manager, old, _ = self.failed_detail(evidence=False)
        manager.executor_fn = Mock()
        with self.assertRaises(DownloadNotFound):
            manager.recover_detail("other", old["id"])
        with self.assertRaises(DownloadResumeError):
            manager.recover_detail("tester", old["id"])
        self.assertEqual(len(manager.list_runs("tester")), 1)
        manager.executor_fn.assert_not_called()

    def test_detail_recovery_requires_exact_success_receipt_and_basic_proof(self):
        manager, old, receipt = self.failed_detail()
        proof = json.loads(receipt.read_text(encoding="utf-8"))
        changes = ({"agency_id": "31030156"}, {"start": "2026-10-02"}, {"end": "2026-10-06"},
                   {"request_observed": False}, {"http_status": 403}, {"http_status": "200"},
                   {"response_code": 201}, {"response_code": "200"}, {"selected_team_ids": []},
                   {"selected_team_ids": ["101", "101"]}, {"selected_team_ids": [101]},
                   {"existing_task_ids": None}, {"existing_task_ids": ["bad-id"]},
                   {"submitted_at": "2026-10-16"}, {"submitted_at": "not-a-date"}, {"task_id": "bad-id"})
        manager.executor_fn = Mock()
        for change in changes:
            with self.subTest(change=change):
                receipt.write_text(json.dumps({**proof, **change}), encoding="utf-8")
                with self.assertRaises(DownloadResumeError):
                    manager.recover_detail("tester", old["id"])
        self.assertEqual(len(manager.list_runs("tester")), 1)
        manager.executor_fn.assert_not_called()

    def test_detail_recovery_rejects_wrong_source_folder_and_ineligible_jobs(self):
        manager, old, receipt = self.failed_detail()
        wrong = receipt.with_name("other_receipt.json")
        receipt.rename(wrong)
        with self.assertRaises(DownloadResumeError):
            manager.recover_detail("tester", old["id"])
        wrong.rename(receipt)
        manager._mutate("tester", old["id"], lambda run: run["items"][0].update(status="success"))
        with self.assertRaises(DownloadResumeError):
            manager.recover_detail("tester", old["id"])
        manager.shutdown()
        for config in ({**CONFIG, "datasets": ["delivery_fee"]},
                       {**CONFIG, "datasets": ["rider_detail"], "cities": ["泉州", "三亚"]}):
            manager, old, _ = self.failed_detail(config)
            with self.subTest(config=config), self.assertRaises(DownloadResumeError):
                manager.recover_detail("tester", old["id"])
            manager.shutdown()

    def test_detail_recovery_route_maps_conflict_and_rejects_payload_parameters(self):
        manager, old, _ = self.failed_detail(evidence=False)
        with patch.object(routes, "get_manager", return_value=manager):
            with self.assertRaises(HTTPException) as missing:
                complete(routes.resume_detail(old["id"], request("POST")))
            self.assertEqual(missing.exception.status_code, 409)
            with self.assertRaises(HTTPException) as owner:
                complete(routes.resume_detail(old["id"], request("POST", owner="other")))
            self.assertEqual(owner.exception.status_code, 404)
            with self.assertRaises(HTTPException) as payload:
                complete(routes.resume_detail(old["id"], request("POST", body={"resume_detail_from": "untrusted-source"})))
            self.assertEqual(payload.exception.status_code, 400)
        fake = Mock()
        fake.get_run.return_value = {"items": [{"city": "泉州", "dataset": "rider_detail", "start": CONFIG["start"],
                                               "end": CONFIG["end"], "status": "error", "recovery": {"mode": "resume_existing"}}]}
        fake.retry.return_value = {"id": "recovery", "retry_of": old["id"]}
        with patch.object(routes, "get_manager", return_value=fake):
            result = complete(routes.resume_detail(old["id"], request("POST")))
        self.assertEqual(result["run"]["id"], "recovery")
        fake.retry.assert_called_once()
        self.assertEqual(fake.retry.call_args.args[:2], ("tester", old["id"]))

    def test_new_archive_uses_beijing_time_and_hides_private_fields(self):
        manager = self.manager(self.success_executor)
        with patch.object(jobs, "_now", return_value="2026-09-30T16:01:02+00:00"):
            created = manager.create("tester", CONFIG)
        run = self.wait_run(manager, created["id"])
        self.assertEqual(run["created_at"], "2026-09-30T16:01:02+00:00")
        self.assertEqual(run["archive_relative_dir"], "2026-10/20261001_000102_风神_配送费_泉州_" + run["id"][:6].upper())
        self.assertEqual(run["archive_code"], run["id"][:6].upper())
        self.assertEqual(run["archive_version"], 1)
        directory = manager._run_directory("tester", run["id"])
        self.assertEqual(directory, manager.output_root / run["archive_relative_dir"])
        self.assertEqual(json.loads((directory / ".archive_task.json").read_text(encoding="utf-8")), {"id": run["id"], "version": 1})
        manager._mutate("tester", run["id"], lambda current: current.update(debug={"_secret": "synthetic-private", "visible": True}))
        public = manager.get_run("tester", run["id"])
        self.assertNotIn("_archive_root", public)
        self.assertEqual(public["debug"], {"visible": True})
        self.assertNotIn("synthetic-private", json.dumps(public))

    def test_saved_archive_root_survives_output_root_change(self):
        manager = self.manager(self.success_executor)
        old = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        manager._queue.join()
        original_path, _ = manager.get_file("tester", old["id"], old["files"][0]["id"])
        manager.shutdown()
        changed = DownloadManager(manager.db_path, self.root / "changed_root", self.success_executor, flat_delivery=False)
        self.managers.append(changed)
        restored_path, _ = changed.get_file("tester", old["id"], old["files"][0]["id"])
        self.assertEqual(restored_path, original_path)
        summary, _ = changed.get_summary("tester", old["id"])
        self.assertEqual(summary.parent, original_path.parents[2])
        self.assertTrue((summary.parent / '任务清单.csv').is_file())
        new = self.wait_run(changed, changed.create("tester", CONFIG)["id"])
        new_path, _ = changed.get_file("tester", new["id"], new["files"][0]["id"])
        self.assertTrue(new_path.is_relative_to(changed.output_root))
        self.assertFalse(new_path.is_relative_to(manager.output_root))

    def test_legacy_file_and_summary_fall_back_to_original_default_root(self):
        manager = self.manager(self.success_executor)
        old = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        manager._queue.join()
        original, _ = manager.get_file("tester", old["id"], old["files"][0]["id"])
        legacy_project = self.root / "legacy_project"
        legacy_dir = legacy_project / "outputs" / "fengshen_downloads" / old["id"]
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "result.csv"
        legacy_file.write_bytes(original.read_bytes())
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            state = json.loads(connection.execute("SELECT state_json FROM download_runs WHERE id=?", (old["id"],)).fetchone()[0])
            for key in ("archive_version", "archive_relative_dir", "archive_code", "_archive_root"):
                state.pop(key)
            state.pop('archive_label', None)
            state.pop('result_layout', None)
            state['files'][0]['relative_path'] = 'result.csv'
            connection.execute("UPDATE download_runs SET state_json=? WHERE id=?", (json.dumps(state), old["id"]))
        manager.shutdown()
        with patch.object(jobs, "ROOT", legacy_project):
            changed = DownloadManager(manager.db_path, self.root / "new_location", Mock(), flat_delivery=False)
            self.managers.append(changed)
            path, name = changed.get_file("tester", old["id"], old["files"][0]["id"])
            self.assertEqual((path, name), (legacy_file, "result.csv"))
            summary, _ = changed.get_summary("tester", old["id"])
            self.assertEqual(summary.parent, legacy_dir)
            self.assertIn("历史任务原目录", summary.read_text(encoding="utf-8-sig"))
            self.assertEqual(legacy_file.read_bytes(), original.read_bytes())
            changed.executor_fn.assert_not_called()

    def test_legacy_recovery_supplies_fixed_source_directory_after_root_change(self):
        manager, old, receipt = self.failed_detail()
        manager._queue.join()
        legacy_project = self.root / "legacy_project"
        legacy_raw = legacy_project / "outputs" / "fengshen_downloads" / old["id"] / "31029436" / "raw" / "rider_detail"
        legacy_raw.mkdir(parents=True)
        (legacy_raw / "detail_submission.json").write_bytes(receipt.read_bytes())
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            state = json.loads(connection.execute("SELECT state_json FROM download_runs WHERE id=?", (old["id"],)).fetchone()[0])
            for key in ("archive_version", "archive_relative_dir", "archive_code", "_archive_root"):
                state.pop(key)
            connection.execute("UPDATE download_runs SET state_json=? WHERE id=?", (json.dumps(state), old["id"]))
        manager.shutdown()
        def recovered(config, run_dir, log, cancelled, update_item):
            file = make_file(run_dir, config, "rider_detail")
            update_item({**file, "status": "success"})
            return [file]
        executor = Mock(side_effect=recovered)
        with patch.object(jobs, "ROOT", legacy_project):
            changed = DownloadManager(manager.db_path, self.root / "recovered_root", executor, flat_delivery=False)
            self.managers.append(changed)
            recovered_job = changed.recover_detail("tester", old["id"])
            result = self.wait_run(changed, recovered_job["id"])
            self.assertEqual(result["status"], "success")
            self.assertEqual(Path(executor.call_args.args[0]["resume_detail_sources"]["泉州"]), legacy_raw)
            self.assertEqual(changed.recover_detail("tester", old["id"])["id"], result["id"])
            self.assertEqual(executor.call_count, 1)

    def test_summary_owner_final_state_and_business_count(self):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def execute(config, run_dir, log, cancelled, update_item):
            started.set()
            release.wait(3)
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        created = manager.create("tester", CONFIG)
        self.assertTrue(started.wait(2))
        with self.assertRaises(DownloadSummaryPending):
            manager.get_summary("tester", created["id"])
        with self.assertRaises(DownloadNotFound):
            manager.get_summary("other", created["id"])
        with patch.object(routes, "get_manager", return_value=manager), self.assertRaises(HTTPException) as pending:
            routes.summary(created["id"], request())
        self.assertEqual(pending.exception.status_code, 409)
        release.set()
        run = self.wait_run(manager, created["id"])
        manager._queue.join()
        path, filename = manager.get_summary("tester", run["id"])
        self.assertEqual(filename, "下载说明.txt")
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("已验证成品文件：1 个", text)
        self.assertIn("SHA-256", text)
        self.assertNotIn(str(manager.output_root), text)
        self.assertEqual(manager.get_run("tester", run["id"])["summary"]["files"], 1)
        with patch.object(routes, "get_manager", return_value=manager):
            self.assertIsInstance(routes.summary(run["id"], request()), FileResponse)

    def test_queued_cancel_and_restart_interrupted_can_download_summary(self):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def execute(config, run_dir, log, cancelled, update_item):
            started.set()
            release.wait(3)
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        first = manager.create("tester", CONFIG)
        self.assertTrue(started.wait(2))
        queued = manager.create("tester", CONFIG)
        manager.cancel("tester", queued["id"])
        summary, _ = manager.get_summary("tester", queued["id"])
        self.assertIn("已取消", summary.read_text(encoding="utf-8-sig"))
        self.assertEqual(manager.get_run("tester", queued["id"])["files"], [])
        release.set()
        self.wait_run(manager, first["id"])
        manager._queue.join()
        manager.shutdown()
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            state = json.loads(connection.execute("SELECT state_json FROM download_runs WHERE id=?", (first["id"],)).fetchone()[0])
            state["status"] = "running"
            state["items"][0]["status"] = "running"
            connection.execute("UPDATE download_runs SET status=?, state_json=? WHERE id=?", ("running", json.dumps(state), first["id"]))
        restarted = self.manager(Mock())
        existing_summary = restarted._run_directory("tester", first["id"]) / "下载说明.txt"
        self.assertIn("服务重启中断", existing_summary.read_text(encoding="utf-8-sig"))
        summary, _ = restarted.get_summary("tester", first["id"])
        self.assertIn("服务重启中断", summary.read_text(encoding="utf-8-sig"))
        restarted.executor_fn.assert_not_called()

    def test_summary_failure_logs_warning_without_changing_business_success(self):
        manager = self.manager(self.success_executor)
        with patch.object(jobs, "write_download_summary", side_effect=PermissionError("private-directory")):
            run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
            manager._queue.join()
            run = manager.get_run("tester", run["id"])
            self.assertEqual(run["status"], "success")
            self.assertEqual(run["summary"]["files"], 1)
            self.assertTrue(any("下载说明写入失败" in entry["message"] for entry in run["logs"]))
            self.assertNotIn("private-directory", json.dumps(run))
            with self.assertRaises(DownloadSummaryError):
                manager.get_summary("tester", run["id"])
        self.assertEqual(manager.get_run("tester", run["id"])["status"], "success")

    def test_archive_path_tampering_cannot_read_or_write_outside_registered_directory(self):
        manager = self.manager(self.success_executor)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        manager._queue.join()
        outside = self.root / "outside"
        outside.mkdir()
        protected = outside / "下载说明.txt"
        protected.write_text("keep-existing", encoding="utf-8")
        manager._mutate("tester", run["id"], lambda current: current.update(archive_relative_dir="../../outside"))
        with self.assertRaises(DownloadNotFound):
            manager.get_file("tester", run["id"], run["files"][0]["id"])
        with self.assertRaises(DownloadSummaryError):
            manager.get_summary("tester", run["id"])
        self.assertEqual(protected.read_text(encoding="utf-8"), "keep-existing")

    def test_archive_collision_retries_without_touching_existing_receipt(self):
        from download_archive import archive_relative_dir
        stamp = "2026-09-30T16:01:02+00:00"
        old_id, collision_id, fresh_id = "abcdef" + "0" * 26, "abcdef" + "1" * 26, "123456" + "2" * 26
        release = threading.Event()
        self.releases.append(release)
        def execute(config, run_dir, log, cancelled, update_item):
            release.wait(3)
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        old_dir = manager.output_root / archive_relative_dir(old_id, stamp, CONFIG["cities"], jobs.task_archive_label(CONFIG['datasets']))
        old_dir.mkdir(parents=True)
        (old_dir / ".archive_task.json").write_text(json.dumps({"id": old_id, "version": 1}), encoding="utf-8")
        protected = old_dir / "下载说明.txt"
        protected.write_text("old-summary", encoding="utf-8")
        with patch.object(jobs, "_now", return_value=stamp), patch.object(jobs.uuid, "uuid4", side_effect=[SimpleNamespace(hex=collision_id), SimpleNamespace(hex=fresh_id)]) as allocate:
            run = manager.create("tester", CONFIG)
        self.assertEqual(allocate.call_count, 2)
        self.assertEqual(run["id"], fresh_id)
        release.set()
        self.wait_run(manager, run["id"])
        manager._queue.join()
        self.assertEqual(protected.read_text(encoding="utf-8"), "old-summary")

    def test_unowned_directory_appearing_after_enqueue_never_gets_summary_overwritten(self):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []
        def execute(config, run_dir, log, cancelled, update_item):
            calls.append(run_dir)
            started.set()
            release.wait(3)
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        first = manager.create("tester", CONFIG)
        self.assertTrue(started.wait(2))
        queued = [manager.create("tester", CONFIG), manager.create("tester", CONFIG)]
        protected = []
        for index, run in enumerate(queued):
            directory = manager._run_directory("tester", run["id"])
            directory.mkdir(parents=True)
            marker = directory / ".archive_task.json"
            if index:
                marker.write_text(json.dumps({"id": "f" * 32, "version": 1}), encoding="utf-8")
            summary = directory / "下载说明.txt"
            summary.write_text("unowned-summary-" + str(index), encoding="utf-8")
            protected.append(summary)
        release.set()
        self.wait_run(manager, first["id"])
        for run in queued:
            self.assertEqual(self.wait_run(manager, run["id"])["status"], "error")
            with self.assertRaises(DownloadSummaryError):
                manager.get_summary("tester", run["id"])
        manager._queue.join()
        self.assertEqual(len(calls), 1)
        for index, path in enumerate(protected):
            self.assertEqual(path.read_text(encoding="utf-8"), "unowned-summary-" + str(index))

    def test_environment_root_validation_and_options_are_explicit(self):
        with patch.dict(os.environ, {"FENGSHEN_DOWNLOAD_ROOT": ""}):
            self.assertEqual(jobs.configured_output_root(), (jobs.ROOT / "outputs" / "fengshen_downloads").resolve())
        custom = self.root / "configured-root"
        with patch.dict(os.environ, {"FENGSHEN_DOWNLOAD_ROOT": str(custom)}):
            self.assertEqual(jobs.configured_output_root(), custom)
            fake = Mock()
            with patch.object(jobs, "_manager", None), patch.object(jobs, "DownloadManager", return_value=fake) as factory, patch.object(jobs.atexit, "register"):
                self.assertIs(jobs.get_manager(), fake)
                self.assertEqual(factory.call_args.args[1], custom)
        service = SimpleNamespace(get_options=lambda: {"cities": [], "datasets": []})
        with patch.dict(os.environ, {"FENGSHEN_DOWNLOAD_ROOT": "relative-folder"}):
            with self.assertRaises(DownloadRootError):
                jobs.configured_output_root()
            with patch.object(routes.importlib, "import_module", return_value=service), self.assertRaises(HTTPException) as invalid:
                routes.options(request())
            self.assertEqual(invalid.exception.status_code, 503)
            self.assertIn("绝对目录", invalid.exception.detail)

    def test_partial_and_error_follow_item_outcomes(self):
        def execute(config, run_dir, log, cancelled, update_item):
            files = []
            for dataset in config["datasets"]:
                update_item({"city": "泉州", "dataset": dataset, "start": config["start"], "end": config["end"],
                             "status": "success" if dataset == "delivery_fee" else "error", "error": "平台导出失败"})
                if dataset == "delivery_fee":
                    files.append(make_file(run_dir, config))
            return files
        manager = self.manager(execute)
        partial = self.wait_run(manager, manager.create("tester", {**CONFIG, "datasets": ["delivery_fee", "penalty"]})["id"])
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["summary"]["success"], 1)
        self.assertEqual(partial["summary"]["error"], 1)
        self.assertEqual(partial["progress"], 100)
        failed = self.wait_run(manager, manager.create("tester", {**CONFIG, "datasets": ["penalty"]})["id"])
        self.assertEqual(failed["status"], "error")

    def test_single_worker_and_queued_cancellation(self):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []
        def execute(config, run_dir, log, cancelled, update_item):
            calls.append(config["owner"])
            started.set()
            release.wait(3)
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        first = manager.create("tester", CONFIG)
        self.assertTrue(started.wait(2))
        second = manager.create("second", CONFIG)
        self.assertEqual(manager.get_run("second", second["id"])["status"], "queued")
        self.assertEqual(manager.cancel("second", second["id"])["status"], "cancelled")
        release.set()
        self.wait_run(manager, first["id"])
        manager._queue.join()
        self.assertEqual(calls, ["tester"])
        self.assertEqual(manager.get_run("second", second["id"])["status"], "cancelled")

    def test_waiting_login_cancel_retains_completed_files(self):
        waiting = threading.Event()
        def execute(config, run_dir, log, cancelled, update_item):
            file = make_file(run_dir, config)
            update_item({**file, "status": "success"})
            update_item({"city": "泉州", "dataset": "penalty", "start": config["start"], "end": config["end"],
                         "status": "waiting_login"})
            waiting.set()
            cancelled.wait(3)
            return [file]
        manager = self.manager(execute)
        created = manager.create("tester", {**CONFIG, "datasets": ["delivery_fee", "penalty"]})
        self.assertTrue(waiting.wait(2))
        self.assertEqual(manager.get_run("tester", created["id"])["status"], "waiting_login")
        self.assertEqual(manager.cancel("tester", created["id"])["status"], "cancelling")
        run = self.wait_run(manager, created["id"])
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(len(run["files"]), 1)
        self.assertEqual(run["summary"]["cancelled"], 1)
        self.assertEqual(manager.cancel("tester", run["id"])["status"], "cancelled")

    def test_followup_expansion_is_normalized_in_manifest_fingerprint(self):
        from download_service import expand_followup_datasets
        selected = {**CONFIG, "datasets": ["abnormal_followup"]}
        expanded = {**selected, "datasets": expand_followup_datasets(selected["datasets"])}
        self.assertEqual(jobs._fingerprint(selected), jobs._fingerprint(expanded))
        self.assertNotEqual(jobs._fingerprint(selected),
                            jobs._fingerprint({**selected, "datasets": ["delivery_fee"]}))

    def test_abnormal_riders_expansion_is_normalized_in_manifest_fingerprint(self):
        from download_service import expand_followup_datasets
        selected = {**CONFIG, "datasets": ["abnormal_riders"]}
        expanded = {**selected, "datasets": expand_followup_datasets(selected["datasets"])}
        self.assertEqual(jobs._fingerprint(selected), jobs._fingerprint(expanded))

    def test_abnormal_riders_creates_single_global_item_and_readds_sources_on_retry(self):
        from lanorange_catalog import ALL_CITIES
        config = {**CONFIG, "cities": [ALL_CITIES], "datasets": ["abnormal_riders"],
                  "start": "2026-10-16", "end": "2026-10-16", "months": ["2026-10"]}
        items = jobs._initial_items(config)
        self.assertEqual({item["dataset"] for item in items},
                         {"abnormal_riders", "lanorange_batch_quit", "lanorange_rider_quit",
                          "lanorange_rider_report", "lanorange_rider_leave", "lanorange_rider_archive"})
        self.assertTrue(all(item["city"] == ALL_CITIES for item in items))
        retry = [{key: item[key] for key in ("city", "dataset", "start", "end")}
                 for item in items if item["dataset"] == "abnormal_riders"]
        kept = jobs._initial_items({**config, "retry_items": retry})
        self.assertEqual({item["dataset"] for item in kept}, {item["dataset"] for item in items})
        # 仅重试生成项时，5 类蓝橙来源自动补回且不产生按城市子项
        self.assertEqual(len(kept), len(items))

    def test_abnormal_followup_summary_is_accepted_for_multi_city_runs(self):
        config = {**CONFIG, "cities": ["三亚", "泉州"], "datasets": ["abnormal_followup"],
                  "start": "2026-10-01", "end": "2026-10-31", "months": ["2026-10"]}
        manager = self.manager(Mock())
        run = {"id": "a" * 32, "owner": "tester", "status": "running"}
        directory = manager._archive_directory(run, create=True)
        name = "多城市汇总10月异常骑手跟进明细表1023.xlsx"
        (directory / name).write_bytes(b"synthetic summary")
        info = {"city": "多城市汇总", "dataset": "abnormal_followup", "artifact_role": "summary",
                "start": "2026-10-01", "end": "2026-10-31", "name": name, "relative_path": name}
        entry = manager._file_entry(run, info, config)
        self.assertEqual((entry["artifact_role"], entry["name"]), ("summary", name))

    def test_multi_city_merged_rider_detail_is_accepted_for_multi_city_runs(self):
        config = {**CONFIG, "cities": ["三亚", "泉州"], "datasets": ["rider_detail"],
                  "start": "2026-10-01", "end": "2026-10-31"}
        manager = self.manager(Mock())
        run = {"id": "a" * 32, "owner": "tester", "status": "running"}
        directory = manager._archive_directory(run, create=True)
        name = "骑手数据明细_多城市_2026-10-01_2026-10-31.csv"
        (directory / name).write_bytes(b"synthetic merged")
        info = {"city": "多城市", "dataset": "rider_detail", "start": "2026-10-01", "end": "2026-10-31",
                "name": name, "relative_path": name}
        entry = manager._file_entry(run, info, config)
        self.assertEqual((entry["city"], entry["dataset"]), ("多城市", "rider_detail"))

    def test_merged_rider_detail_rejected_for_changed_period_or_single_city(self):
        manager = self.manager(Mock())
        run = {"id": "a" * 32, "owner": "tester", "status": "running"}
        for changes in ({"end": "2026-10-15"}, {"cities": ["泉州"]}):
            with self.subTest(changes=changes):
                config = {**CONFIG, "cities": ["三亚", "泉州"], "datasets": ["rider_detail"],
                          "start": "2026-10-01", "end": "2026-10-31", **changes}
                directory = manager._archive_directory(run, create=True)
                name = "骑手数据明细_多城市.csv"
                (directory / name).write_bytes(b"synthetic merged")
                info = {"city": "多城市", "dataset": "rider_detail", "start": "2026-10-01",
                        "end": "2026-10-31", "name": name, "relative_path": name}
                with self.assertRaises(ValueError):
                    manager._file_entry(run, info, config)

    def test_summary_progress_never_reaches_hundred_before_completion(self):
        run = {"items": [{"status": "success"}, {"status": "error"}], "files": [], "phase": "summarizing",
               "summary_progress": {"stage": "merging", "current": 0, "total": 4}}
        jobs._refresh(run)
        self.assertEqual(run["progress"], 90)
        run["summary_progress"].update(current=1, city="三亚")
        jobs._refresh(run)
        self.assertEqual(run["progress"], 92)
        run["summary_progress"]["current"] = 4
        jobs._refresh(run)
        self.assertEqual(run["progress"], 99)
        run["summary_progress"].update(stage="failed")
        jobs._refresh(run)
        self.assertEqual(run["progress"], 99)
        run["summary_progress"].update(stage="completed")
        jobs._refresh(run)
        self.assertEqual(run["progress"], 100)

    def test_payment_binding_summary_exposes_summarizing_phase_and_logs(self):
        config = {**CONFIG, "cities": ["三亚", "泉州"], "datasets": ["payment_binding"],
                  "start": "2026-10-01", "end": "2026-10-31", "months": ["2026-10"]}
        observed = {}
        manager = self.manager(Mock(return_value=[]))
        created = manager.create("tester", config)
        def summary(root, summary_config, files, items, cancelled, report=None, progress=None):
            observed["phase"] = manager.get_run("tester", created["id"])["phase"]
            if report:
                report("[汇总] 正在合并 三亚（1/2）")
            if progress:
                progress(1, 2, "三亚", "2026-10")
            current = manager.get_run("tester", created["id"])
            observed.update(progress=current["progress"], summary_progress=current["summary_progress"])
            return []
        with patch("binding_summary.build_binding_summaries", side_effect=summary):
            run = self.wait_run(manager, created["id"])
        messages = [entry["message"] for entry in run["logs"]]
        self.assertEqual(observed["phase"], "summarizing")
        self.assertGreaterEqual(observed["progress"], 90)
        self.assertLess(observed["progress"], 100)
        self.assertEqual(observed["summary_progress"]["total"], 2)
        self.assertEqual(observed["summary_progress"]["city"], "三亚")
        self.assertTrue(any("正在合并多城市资料" in message for message in messages))
        self.assertTrue(any("正在合并 三亚" in message for message in messages))
        self.assertEqual(run["phase"], "failed")

    def test_unknown_exception_is_hidden_and_safe_collection_error_is_retained(self):
        private = "https://example.invalid/?token=private-token cookie=private-cookie 13800138000"
        manager = self.manager(Mock(side_effect=RuntimeError(private)))
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertEqual(run["status"], "error")
        self.assertIn("RuntimeError", run["error"])
        self.assertNotIn("private", json.dumps(run, ensure_ascii=False))
        safe = collection_failure(RuntimeError("net::ERR_CERT_AUTHORITY_INVALID " + private), "navigation")
        manager.executor_fn = Mock(side_effect=safe)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertIn("证书", run["error"])
        self.assertNotIn("private", json.dumps(run, ensure_ascii=False))

    def test_logs_are_limited_and_sensitive_messages_hidden(self):
        def execute(config, run_dir, log, cancelled, update_item):
            for number in range(510):
                log("测试日志 " + str(number))
            log("token=private-token https://example.invalid")
            return self.success_executor(config, run_dir, log, cancelled, update_item)
        manager = self.manager(execute)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertEqual(len(run["logs"]), 500)
        self.assertNotIn("测试日志 0", [entry["message"] for entry in run["logs"]])
        self.assertNotIn("private-token", json.dumps(run, ensure_ascii=False))

    def test_executor_cannot_offer_files_outside_run_directory(self):
        outside = self.root / "outside.csv"
        outside.write_text("not-owned", encoding="utf-8")
        def execute(config, run_dir, log, cancelled, update_item):
            return [{"name": outside.name, "relative_path": "../../outside.csv", "city": "泉州", "dataset": "delivery_fee",
                     "start": config["start"], "end": config["end"]}]
        manager = self.manager(execute)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertEqual(run["status"], "error")
        self.assertEqual(run["files"], [])
        self.assertIn("归属", run["error"])
        self.assertEqual(outside.read_text(encoding="utf-8"), "not-owned")

    def test_get_file_rechecks_containment_even_if_record_is_tampered(self):
        manager = self.manager(self.success_executor)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            state = json.loads(connection.execute("SELECT state_json FROM download_runs WHERE id = ?", (run["id"],)).fetchone()[0])
            state["files"][0]["relative_path"] = "../../outside.csv"
            connection.execute("UPDATE download_runs SET state_json = ? WHERE id = ?", (json.dumps(state), run["id"]))
        (self.root / "outside.csv").write_text("private", encoding="utf-8")
        with self.assertRaises(DownloadNotFound):
            manager.get_file("tester", run["id"], run["files"][0]["id"])

    def test_reported_success_without_a_valid_file_is_error(self):
        def execute(config, run_dir, log, cancelled, update_item):
            update_item({"city": "泉州", "dataset": "delivery_fee", "start": config["start"], "end": config["end"],
                         "status": "success"})
            return []
        manager = self.manager(execute)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        self.assertEqual(run["status"], "error")
        self.assertEqual(run["items"][0]["status"], "error")
        self.assertIn("文件", run["error"])

    def test_hash_or_period_mismatch_rejects_file_and_success_claim(self):
        for fault in ("sha256", "start"):
            def execute(config, run_dir, log, cancelled, update_item):
                file = make_file(run_dir, config)
                update_item({**file, "status": "success"})
                file[fault] = "0" * 64 if fault == "sha256" else "2026-09-01"
                return [file]
            manager = self.manager(execute)
            run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
            with self.subTest(fault=fault):
                self.assertEqual(run["status"], "error")
                self.assertEqual(run["files"], [])
                self.assertEqual(run["items"][0]["status"], "error")
            manager.shutdown()

    def test_file_download_rechecks_bytes_and_hash(self):
        manager = self.manager(self.success_executor)
        run = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        file_id = run["files"][0]["id"]
        path, _ = manager.get_file("tester", run["id"], file_id)
        original_size = path.stat().st_size
        for content in (b"x", b"x" * original_size):
            with self.subTest(size=len(content)):
                path.write_bytes(content)
                with self.assertRaises(DownloadNotFound):
                    manager.get_file("tester", run["id"], file_id)

    def test_run_listing_is_limited_to_latest_one_hundred(self):
        manager = self.manager(self.success_executor)
        first = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        inserted = []
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            for _ in range(105):
                state = copy.deepcopy(first)
                state["id"] = uuid.uuid4().hex
                inserted.append(state["id"])
                connection.execute("INSERT INTO download_runs(id, owner, created_at, status, config_json, state_json) VALUES (?, ?, ?, ?, ?, ?)",
                                   (state["id"], "tester", state["created_at"], state["status"], json.dumps(CONFIG), json.dumps(state)))
        runs = manager.list_runs("tester")
        self.assertEqual(len(runs), 100)
        self.assertEqual(runs[0]["id"], inserted[-1])
        self.assertNotIn(first["id"], [item["id"] for item in runs])
        self.assertEqual(manager.get_run("tester", first["id"])["id"], first["id"])

    def test_restart_interrupts_active_states_without_replaying(self):
        manager = self.manager(self.success_executor)
        completed = self.wait_run(manager, manager.create("tester", CONFIG)["id"])
        manager.shutdown()
        inserted = []
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            for status in ("queued", "running", "waiting_login", "cancelling"):
                state = copy.deepcopy(completed)
                state.update(id=uuid.uuid4().hex, status=status)
                state["items"][0]["status"] = "running"
                inserted.append(state["id"])
                connection.execute("INSERT INTO download_runs(id, owner, created_at, status, config_json, state_json) VALUES (?, ?, ?, ?, ?, ?)",
                                   (state["id"], "tester", state["created_at"], status, json.dumps(CONFIG), json.dumps(state)))
        executor = Mock()
        restarted = self.manager(executor)
        for run_id in inserted:
            run = restarted.get_run("tester", run_id)
            self.assertEqual(run["status"], "interrupted")
            self.assertEqual(run["items"][0]["status"], "interrupted")
            self.assertIn("重启", run["error"])
        executor.assert_not_called()

    def test_shutdown_rejects_new_jobs(self):
        manager = self.manager(self.success_executor)
        manager.shutdown()
        with self.assertRaises(DownloadManagerClosed):
            manager.create("tester", CONFIG)

    def test_routes_validate_json_owner_and_do_not_expose_unknown_errors(self):
        class ValidationError(ValueError):
            pass
        service = SimpleNamespace(get_options=lambda: {"cities": [], "datasets": []}, ValidationError=ValidationError,
                                  validate_request=Mock(return_value=CONFIG))
        manager = self.manager(self.success_executor)
        with patch.object(routes.importlib, "import_module", return_value=service), patch.object(routes, "get_manager", return_value=manager), \
                patch.object(routes, "configured_output_root", return_value=manager.output_root):
            self.assertEqual(routes.options(request()), {"cities": [], "datasets": [], "archive_root": str(manager.output_root),
                                                        "archive_naming_version": 1})
            result = complete(routes.create(request("POST", "测试-1", CONFIG)))
            run = self.wait_run(manager, result["run"]["id"], owner="测试-1")
            self.assertEqual(routes.run(run["id"], request(owner="测试-1"))["run"]["status"], "success")
            self.assertEqual(len(routes.runs(request(owner="测试-1"))["runs"]), 1)
            response = routes.file(run["id"], run["files"][0]["id"], request(owner="测试-1"))
            self.assertIsInstance(response, FileResponse)
            with self.assertRaises(HTTPException) as hidden:
                routes.run(run["id"], request(owner="other"))
            self.assertEqual(hidden.exception.status_code, 404)
            service.validate_request.side_effect = ValidationError("日期不能倒置")
            with self.assertRaises(HTTPException) as invalid:
                complete(routes.create(request("POST", body=CONFIG)))
            self.assertEqual((invalid.exception.status_code, invalid.exception.detail), (400, "日期不能倒置"))
            service.validate_request.side_effect = RuntimeError("token=private-token")
            with self.assertRaises(HTTPException) as unknown:
                complete(routes.create(request("POST", body=CONFIG)))
            self.assertEqual(unknown.exception.status_code, 500)
            self.assertNotIn("private-token", unknown.exception.detail)
        for owner in (None, "bad/path", "bad\\path", "a" * 129):
            with self.subTest(owner=owner), self.assertRaises(HTTPException) as invalid:
                routes.workspace_owner(request(owner=owner))
            self.assertEqual(invalid.exception.status_code, 400)
        with self.assertRaises(HTTPException) as content:
            complete(routes.create(request("POST", content_type="text/plain")))
        self.assertEqual(content.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()
