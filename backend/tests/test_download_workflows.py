"""Cross-feature regressions using isolated accounts, jobs and synthetic files."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_accounts as accounts
import download_jobs as jobs
import download_routes as routes
from download_jobs import DownloadManager, DownloadNotFound, DownloadRequestConflict, DownloadResumeError, FINAL_STATUSES
from download_single_instance import DownloadInstanceBusy
from download_path_registry import refresh_protected_roots
from fastapi import HTTPException
from test_download_jobs import CONFIG, make_file, complete
from test_download_accounts import request, PASSWORD


class DownloadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow_", dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.managers, self.releases = [], []
        self.cities = patch.object(jobs, "_configured_cities", return_value={"泉州": "31029436", "三亚": "31030156"})
        self.cities.start()
        self.addCleanup(self.cities.stop)
        for name in ("gate_datasets", "ensure_ready"):
            preflight = patch(f"auth_preflight.{name}", lambda *args, **kwargs: None)
            preflight.start()
            self.addCleanup(preflight.stop)

    def tearDown(self):
        for release in self.releases:
            release.set()
        for manager in self.managers:
            manager.shutdown()
        self.temp.cleanup()

    def manager(self, executor):
        result = DownloadManager(self.root / "state" / "tasks.sqlite3", self.root / "archives", executor)
        self.managers.append(result)
        return result

    def wait(self, manager, identity, owner="tester"):
        limit = time.monotonic() + 8
        while time.monotonic() < limit:
            result = manager.get_run(owner, identity)
            if result["status"] in FINAL_STATUSES:
                if result['files']:manager.publish_delivery(owner,identity)
                return manager.get_run(owner,identity)
            threading.Event().wait(0.01)
        self.fail("synthetic job did not finish")

    @staticmethod
    def success(config, directory, log, cancelled, update):
        info = make_file(directory, config)
        update({**info, "status": "success", "phase": "completed", "files": [info]})
        return [info]

    def test_child_file_is_downloadable_while_later_child_waits_and_survives_error(self):
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        config = {**CONFIG, "datasets": ["delivery_fee", "penalty"]}
        def execute(config, directory, log, cancelled, update):
            info = make_file(directory, config)
            update({**info, "status": "success", "phase": "completed", "files": [info]})
            ready.set()
            release.wait(5)
            raise RuntimeError("synthetic later-child failure")
        manager = self.manager(execute)
        identity = manager.create("tester", config)["id"]
        self.assertTrue(ready.wait(4))
        running = manager.get_run("tester", identity)
        self.assertEqual(running["status"], "running")
        self.assertEqual(len(running["files"]), 1)
        file_id = running["files"][0]["id"]
        path, _ = manager.get_file("tester", identity, file_id)
        self.assertEqual(path.read_text(encoding="utf-8"), "synthetic,data\n")
        bundle, _ = manager.get_bundle("tester", identity)
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(set(archive.namelist()), {"result.csv"})
        bundle.unlink()
        release.set()
        finished = self.wait(manager, identity)
        self.assertEqual(finished["status"], "partial")
        self.assertEqual(finished["files"][0]["id"], file_id)

    def test_same_request_replays_after_completion_and_changed_payload_conflicts(self):
        execute = Mock(side_effect=self.success)
        manager = self.manager(execute)
        first = manager.create("tester", CONFIG, "same-request-001")
        self.wait(manager, first["id"])
        self.assertEqual(manager.create("tester", CONFIG, "same-request-001")["id"], first["id"])
        with self.assertRaises(DownloadRequestConflict):
            manager.create("tester", {**CONFIG, "end": "2026-10-06"}, "same-request-001")
        second = manager.create("tester", CONFIG, "explicit-new-001")
        self.wait(manager, second["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(execute.call_count, 2)

    def test_concurrent_repeated_clicks_share_one_active_job_but_not_other_owner(self):
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def execute(*args):
            ready.set()
            release.wait(5)
            return self.success(*args)
        runner = Mock(side_effect=execute)
        manager = self.manager(runner)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: manager.create("tester", CONFIG, f"click-request-{i:03}"), range(4)))
        self.assertEqual(len({result["id"] for result in results}), 1)
        self.assertTrue(ready.wait(4))
        other = manager.create("other", CONFIG, "click-request-000")
        self.assertNotEqual(other["id"], results[0]["id"])
        self.assertGreaterEqual(manager.get_run("other", other["id"])["queue_position"], 2)
        release.set()
        self.wait(manager, results[0]["id"])
        self.wait(manager, other["id"], "other")
        self.assertEqual(runner.call_count, 2)

    def test_selective_retry_keeps_success_and_blocks_uncertain_submission(self):
        config = {**CONFIG, "datasets": ["delivery_fee", "penalty"]}
        def execute(config, directory, log, cancelled, update):
            if "retry_items" in config:
                self.assertEqual([entry["dataset"] for entry in config["retry_items"]], ["penalty"])
                info = make_file(directory, config, dataset="penalty")
                update({**info, "status": "success", "files": [info]})
                return [info]
            info = make_file(directory, config)
            update({**info, "status": "success", "files": [info]})
            update({"city": "泉州", "dataset": "penalty", "start": config["start"], "end": config["end"],
                    "status": "error", "failure_phase": "preparing", "submission_state": "not_submitted", "error": "未提交"})
            return [info]
        manager = self.manager(execute)
        old = self.wait(manager, manager.create("tester", config)["id"])
        failed = old["items"][1]
        self.assertEqual(failed["recovery"]["mode"], "retry_unsubmitted")
        selected = [{key: failed[key] for key in ("city", "dataset", "start", "end")}]
        renewed = manager.retry("tester", old["id"], selected, "retry-select-001", actor_owner="admin-owner")
        renewed = self.wait(manager, renewed["id"], "admin-owner")
        self.assertEqual(renewed["status"], "success")
        self.assertEqual(len(renewed["items"]), 1)
        self.assertEqual(manager.get_run("tester", old["id"])["files"], old["files"])
        with self.assertRaises(DownloadResumeError):
            manager.retry("tester", old["id"], [{key: old["items"][0][key] for key in selected[0]}], "retry-success-no")
        manager._mutate("tester", old["id"], lambda run: run["items"][1].update(submission_state="unknown"))
        with self.assertRaises(DownloadResumeError):
            manager.retry("tester", old["id"], selected, "retry-unknown-no")

    def test_global_wait_phase_does_not_mark_queued_children_as_submitted(self):
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def execute(config, directory, log, cancelled, update):
            update({"_run_event": True, "status": "running", "phase": "waiting_collection"})
            ready.set()
            release.wait(5)
            return self.success(config, directory, log, cancelled, update)
        manager = self.manager(execute)
        identity = manager.create("tester", CONFIG)["id"]
        self.assertTrue(ready.wait(4))
        run = manager.get_run("tester", identity)
        self.assertEqual(run["phase"], "waiting_collection")
        self.assertEqual(run["items"][0]["submission_state"], "not_submitted")
        self.assertTrue(run["phase_since"])
        release.set()
        self.wait(manager, identity)

    def test_recovered_success_reused_across_new_request_ids_and_unknown_child_blocks_old_source(self):
        calls = []
        def execute(config, directory, log, cancelled, update):
            calls.append(config)
            if config.get("retry_of"):
                return self.success(config, directory, log, cancelled, update)
            update({"city": "泉州", "dataset": "delivery_fee", "start": config["start"], "end": config["end"],
                    "status": "error", "submission_state": "not_submitted", "error": "未提交"})
            return []
        manager = self.manager(execute)
        old = self.wait(manager, manager.create("tester", CONFIG)["id"])
        selected = [{key: old["items"][0][key] for key in ("city", "dataset", "start", "end")}]
        first = self.wait(manager, manager.retry("tester", old["id"], selected, "recovery-key-001")["id"])
        self.assertEqual(manager.retry("tester", old["id"], selected, "recovery-key-002")["id"], first["id"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(manager.get_run("tester", old["id"])["items"][0]["recovery"]["mode"], "blocked")
        manager._mutate("tester", first["id"], lambda run: (
            run.update(status="error", files=[]), run["items"][0].update(status="error", submission_state="unknown")))
        with self.assertRaises(DownloadResumeError):
            manager.retry("tester", old["id"], selected, "recovery-key-003")
        # An uncertain HTTP response still replays the already accepted request.
        self.assertEqual(manager.retry("tester", old["id"], selected, "recovery-key-001")["id"], first["id"])

    def test_different_admins_share_active_recovery_without_starting_another_export(self):
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []
        def execute(config, directory, log, cancelled, update):
            calls.append(config)
            if config.get("retry_of"):
                ready.set()
                release.wait(5)
                return self.success(config, directory, log, cancelled, update)
            update({"city": "泉州", "dataset": "delivery_fee", "start": config["start"], "end": config["end"],
                    "status": "error", "submission_state": "not_submitted", "error": "未提交"})
            return []
        manager = self.manager(execute)
        old = self.wait(manager, manager.create("tester", CONFIG)["id"])
        selected = [{key: old["items"][0][key] for key in ("city", "dataset", "start", "end")}]
        first = manager.retry("tester", old["id"], selected, "admin-one-key", actor_owner="admin-one", allow_shared_result=True)
        self.assertTrue(ready.wait(4))
        second = manager.retry("tester", old["id"], selected, "admin-two-key", actor_owner="admin-two", allow_shared_result=True)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(calls), 2)
        with self.assertRaises(DownloadResumeError):
            manager.retry("tester", old["id"], selected, "member-new-key")
        release.set()
        self.wait(manager, first["id"], "admin-one")

    def test_failed_detail_recovery_uses_ancestor_receipt_for_next_readonly_attempt(self):
        config = {**CONFIG, "datasets": ["rider_detail"]}
        calls = []
        def execute(config, directory, log, cancelled, update):
            calls.append(config)
            if not config.get("retry_of"):
                from test_download_jobs import write_detail_receipt
                write_detail_receipt(directory, config)
            update({"city": "泉州", "dataset": "rider_detail", "start": config["start"], "end": config["end"],
                    "status": "error", "submission_state": "submitted", "error": "等待原文件"})
            return []
        manager = self.manager(execute)
        old = self.wait(manager, manager.create("tester", config)["id"])
        selected = [{key: old["items"][0][key] for key in ("city", "dataset", "start", "end")}]
        child = self.wait(manager, manager.retry("tester", old["id"], selected, "detail-attempt-001")["id"])
        self.assertEqual(child["items"][0]["recovery"]["mode"], "resume_existing")
        again = self.wait(manager, manager.retry("tester", child["id"], selected, "detail-attempt-002")["id"])
        self.assertNotEqual(child["id"], again["id"])
        self.assertEqual(calls[1]["resume_detail_sources"], calls[2]["resume_detail_sources"])
        self.assertIn(old["archive_relative_dir"].replace("/", "\\"), calls[2]["resume_detail_sources"]["泉州"].replace("/", "\\"))

    def test_legacy_resume_http_replays_active_and_completed_child(self):
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def execute(config, directory, log, cancelled, update):
            if config.get("retry_of"):
                ready.set()
                release.wait(5)
                info = make_file(directory, config, dataset="rider_detail")
                update({**info, "status": "success", "files": [info]})
                return [info]
            from test_download_jobs import write_detail_receipt
            write_detail_receipt(directory, config)
            update({"city": "泉州", "dataset": "rider_detail", "start": config["start"], "end": config["end"],
                    "status": "error", "submission_state": "submitted", "error": "等待原文件"})
            return []
        manager = self.manager(execute)
        old = self.wait(manager, manager.create("tester", {**CONFIG, "datasets": ["rider_detail"]})["id"])
        with patch.object(routes, "get_manager", return_value=manager), patch.object(routes, "require_account", return_value={
            "id": "fixture", "username": "fixture", "role": "member", "owner": "tester"}), patch.object(routes, "audit_event"):
            first = complete(routes.resume_detail(old["id"], request("POST")))["run"]
            self.assertTrue(ready.wait(4))
            self.assertEqual(complete(routes.resume_detail(old["id"], request("POST")))["run"]["id"], first["id"])
            release.set()
            self.wait(manager, first["id"])
            self.assertEqual(complete(routes.resume_detail(old["id"], request("POST")))["run"]["id"], first["id"])

    def test_existing_only_legacy_entry_cannot_submit_an_unsubmitted_export(self):
        def execute(config, directory, log, cancelled, update):
            update({"city": "泉州", "dataset": "rider_detail", "start": config["start"], "end": config["end"],
                    "status": "error", "submission_state": "not_submitted", "error": "未提交"})
            return []
        manager = self.manager(execute)
        old = self.wait(manager, manager.create("tester", {**CONFIG, "datasets": ["rider_detail"]})["id"])
        with self.assertRaises(DownloadResumeError):
            manager.recover_detail("tester", old["id"])
        self.assertEqual(len(manager.list_runs("tester")), 1)

    def test_committed_manifest_is_reconciled_when_success_callback_temporarily_fails(self):
        def execute(config, directory, log, cancelled, update):
            info = make_file(directory, config)
            checkpoint = {"config": config, "payroll_executed": False, "files": [info],
                          "items": [{**info, "status": "success"}]}
            (directory / "manifest.json").write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
            update({**info, "status": "success", "files": [info]})
            return [info]
        manager = self.manager(execute)
        original = manager._update_item
        failed = False
        def temporarily_fail(owner, identity, change):
            nonlocal failed
            if change["status"] == "success" and not failed:
                failed = True
                raise sqlite3.OperationalError("synthetic transient storage failure")
            return original(owner, identity, change)
        with patch.object(manager, "_update_item", side_effect=temporarily_fail):
            completed = self.wait(manager, manager.create("tester", CONFIG)["id"])
        self.assertTrue(failed)
        self.assertEqual(len(completed["files"]), 1)
        self.assertEqual(completed["items"][0]["status"], "success")
        manager.get_file("tester", completed["id"], completed["files"][0]["id"])

    def test_second_manager_cannot_interrupt_active_instance(self):
        manager = self.manager(self.success)
        before = manager.create("tester", CONFIG)
        with self.assertRaises(DownloadInstanceBusy):
            DownloadManager(manager.db_path, self.root / "elsewhere", Mock())
        run = self.wait(manager, before["id"])
        self.assertEqual(run["status"], "success")
        manager.shutdown()
        reopened = self.manager(Mock())
        self.assertEqual(reopened.get_run("tester", run["id"])["status"], "success")

    def test_startup_recovers_manifest_committed_before_database_callback(self):
        manager = self.manager(self.success)
        old = self.wait(manager, manager.create("tester", CONFIG)["id"])
        directory = manager._run_directory("tester", old["id"])
        manager.shutdown()
        with closing(sqlite3.connect(manager.db_path)) as connection, connection:
            state = json.loads(connection.execute("SELECT state_json FROM download_runs WHERE id=?", (old["id"],)).fetchone()[0])
            checkpoint = {"config": CONFIG, "payroll_executed": False, "files": copy.deepcopy(state["files"]),
                          "items": [{**state["items"][0], "status": "success"}]}
            (directory / "manifest.json").write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
            state.update(status="running", files=[])
            state["items"][0].update(status="running", submission_state="unknown")
            connection.execute("UPDATE download_runs SET status='running',state_json=? WHERE id=?", (json.dumps(state), old["id"]))
        execute = Mock()
        reopened = self.manager(execute)
        recovered = reopened.get_run("tester", old["id"])
        self.assertEqual(len(recovered["files"]), 1)
        self.assertEqual(recovered["items"][0]["status"], "success")
        reopened.get_file("tester", old["id"], recovered["files"][0]["id"])
        execute.assert_not_called()

    def test_zip_refuses_tampered_file_and_removes_temporary_archive(self):
        manager = self.manager(self.success)
        run = self.wait(manager, manager.create("tester", CONFIG)["id"])
        path, _ = manager.get_file("tester", run["id"], run["files"][0]["id"])
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaises(DownloadNotFound):
            manager.get_bundle("tester", run["id"])
        self.assertEqual(list(manager.db_path.parent.glob('bundles/*.zip')), [])

    def test_root_protection_retains_historical_locations_and_rejects_corrupt_registry(self):
        manager = self.manager(self.success)
        self.wait(manager, manager.create("tester", CONFIG)["id"])
        roots = refresh_protected_roots(manager.db_path, self.root / "new_root")
        self.assertIn(str(manager.output_root), roots)
        self.assertIn(str(self.root / "new_root"), roots)
        target = manager.db_path.parent / "protected_roots.json"
        target.write_text('{"roots":["relative"]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            refresh_protected_roots(manager.db_path, manager.output_root)

    def test_shared_routes_can_read_legacy_files_and_audit_without_login(self):
        store = accounts.AccountStore(self.root / "identity" / "accounts.sqlite3")
        with patch.object(accounts, "get_account_store", return_value=store):
            manager = self.manager(self.success)
            old = self.wait(manager, manager.create("legacy_workspace", CONFIG)["id"], "legacy_workspace")
            with patch.object(routes, "get_manager", return_value=manager):
                self.assertEqual(len(routes.runs(request())["runs"]), 1)
                response = routes.file(old["id"], old["files"][0]["id"], request())
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(store.audit_events()[0]["action"], "download.file")
                self.assertEqual(store.audit_events()[0]["username"], "小组共享")


if __name__ == "__main__":
    unittest.main()
