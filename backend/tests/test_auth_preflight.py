"""认证预检闸门：数据集→平台映射、探测状态、409 载荷与路由硬闸门。"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_routes as routes
import auth_preflight
import platform_auth_control
from auth_preflight import LABELS, platforms_for_datasets, probe, ensure_ready, gate_datasets
from download_jobs import DownloadManager, FINAL_STATUSES
from test_download_jobs import CONFIG, make_file, request, complete


class PlatformMappingTests(unittest.TestCase):
    def test_datasets_map_to_expected_platforms(self):
        cases = {
            ('delivery_fee',): {'fengshen'},
            ('lanorange_part_price',): {'lanorange'},
            ('rider_daily',): {'xiaoxiang'},
            ('baize_employees',): {'baize'},
            ('payment_binding',): {'fengshen', 'lanorange', 'baize'},
            ('abnormal_followup',): {'fengshen', 'lanorange', 'baize'},
            ('abnormal_riders',): {'lanorange'},
            (): set(),
        }
        for datasets, expected in cases.items():
            with self.subTest(datasets=datasets):
                self.assertEqual(platforms_for_datasets(datasets), expected)
        self.assertEqual(platforms_for_datasets(None), set())

    def test_mixed_selection_covers_all_platforms(self):
        self.assertEqual(
            platforms_for_datasets(('delivery_fee', 'lanorange_part_price', 'rider_daily', 'baize_employees')),
            {'fengshen', 'lanorange', 'baize', 'xiaoxiang'})


class ProbeTests(unittest.TestCase):
    def test_ready_states_pass_and_busy_or_unknown_fail(self):
        def check(source, deep=False):
            return {'fengshen': {'state': 'ready', 'message': 'ok'},
                    'lanorange': {'state': 'ready', 'message': 'ok'},
                    'baize': {'state': 'ready', 'message': 'ok'},
                    'xiaoxiang': {'state': 'partial', 'message': '看板未就绪'}}[source]
        with patch.object(platform_auth_control, 'check', side_effect=check):
            entries = {entry['source']: entry for entry in probe({'fengshen', 'lanorange', 'baize', 'xiaoxiang'})}
        self.assertTrue(all(entry['ready'] for entry in entries.values()))
        self.assertEqual(entries['xiaoxiang']['state'], 'partial')
        self.assertEqual(set(entries), set(LABELS))

    def test_login_required_blocks_creation(self):
        with patch.object(platform_auth_control, 'check',
                   side_effect=lambda source, deep=False: {'state': 'login_required', 'message': '需要登录'}):
            entries = probe({'fengshen'})
        self.assertEqual(entries, [{'source': 'fengshen', 'label': '风神', 'state': 'login_required',
                                    'ready': False, 'message': '需要登录'}])

    def test_busy_and_unknown_entries_are_reported(self):
        def check(source, deep=False):
            if source == 'fengshen':
                raise HTTPException(409, '正在采集，请稍后再试')
            raise RuntimeError('connection reset')
        with patch.object(platform_auth_control, 'check', side_effect=check):
            entries = {entry['source']: entry for entry in probe({'fengshen', 'lanorange'})}
        self.assertEqual(entries['fengshen']['state'], 'busy')
        self.assertEqual(entries['fengshen']['message'], '正在采集，请稍后再试')
        self.assertEqual(entries['lanorange']['state'], 'unknown')

    def test_deep_xiaoxiang_only_deepens_xiaoxiang_probe(self):
        seen = {}
        def check(source, deep=False):
            seen[source] = deep
            return {'state': 'ready', 'message': 'ok'}
        with patch.object(platform_auth_control, 'check', side_effect=check):
            probe({'fengshen', 'xiaoxiang'}, deep_xiaoxiang=True)
        self.assertEqual(seen, {'fengshen': False, 'xiaoxiang': True})


class EnsureReadyTests(unittest.TestCase):
    def test_all_ready_returns_entries(self):
        with patch.object(platform_auth_control, 'check',
                   side_effect=lambda source, deep=False: {'state': 'ready', 'message': 'ok'}):
            entries = ensure_ready({'fengshen'})
        self.assertEqual([entry['source'] for entry in entries], ['fengshen'])

    def test_not_ready_raises_409_with_platform_list(self):
        with patch.object(platform_auth_control, 'check', side_effect=lambda source, deep=False:
                   {'state': 'login_required', 'message': '需要登录'} if source == 'fengshen'
                   else {'state': 'ready', 'message': 'ok'}):
            with self.assertRaises(HTTPException) as blocked:
                ensure_ready({'fengshen', 'lanorange'})
        self.assertEqual(blocked.exception.status_code, 409)
        detail = blocked.exception.detail
        self.assertEqual(detail['code'], 'AUTH_PREFLIGHT_REQUIRED')
        self.assertEqual({entry['source'] for entry in detail['platforms']}, {'fengshen', 'lanorange'})
        self.assertFalse(detail['platforms'][0]['ready'])


class GateDatasetTests(unittest.TestCase):
    def test_gate_passes_platforms_and_xiaoxiang_depth(self):
        with patch('auth_preflight.ensure_ready') as ready:
            gate_datasets(('rider_daily', 'delivery_fee'))
        ready.assert_called_once_with({'fengshen', 'xiaoxiang'}, deep_xiaoxiang=True)

    def test_gate_without_xiaoxiang_is_shallow_and_empty_selection_passes(self):
        with patch('auth_preflight.ensure_ready') as ready:
            gate_datasets(('lanorange_part_price',))
            gate_datasets(None)
        self.assertEqual(ready.call_args_list,
                         [call({'lanorange'}, deep_xiaoxiang=False),
                          call(set(), deep_xiaoxiang=False)])


class RoutePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="preflight_route_", dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        account = patch.object(routes, "require_account", side_effect=lambda req: {
            "id": "fixture", "username": "fixture", "role": "member", "owner": routes.workspace_owner(req)})
        account.start()
        self.addCleanup(account.stop)
        audit = patch.object(routes, "audit_event")
        audit.start()
        self.addCleanup(audit.stop)

    def manager(self):
        def executor(config, run_dir, log, cancelled, update_item):
            file = make_file(run_dir, config)
            update_item({**file, "status": "success"})
            return [file]
        manager = DownloadManager(self.root / "db" / "tasks.sqlite3", self.root / "outputs", executor, flat_delivery=False)
        self.addCleanup(manager.shutdown)
        return manager

    def wait_run(self, manager, run_id, owner="测试-1"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = manager.get_run(owner, run_id)
            if run["status"] in FINAL_STATUSES:
                return run
            threading.Event().wait(0.01)
        self.fail("下载任务未在限定时间内达到目标状态")

    def test_create_is_blocked_with_409_when_platform_not_ready(self):
        manager = self.manager()
        with patch.object(routes.importlib, "import_module", return_value=SimpleNamespace(
                get_options=lambda: {"cities": [], "datasets": []},
                ValidationError=ValueError, validate_request=Mock(return_value=CONFIG))), \
                patch.object(routes, "get_manager", return_value=manager), \
                patch.object(routes, "configured_output_root", return_value=manager.output_root), \
                patch.object(platform_auth_control, 'check',
                      side_effect=lambda source, deep=False: {'state': 'login_required', 'message': '需要登录'}):
            with self.assertRaises(HTTPException) as blocked:
                complete(routes.create(request("POST", "测试-1", CONFIG)))
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertEqual(blocked.exception.detail['code'], 'AUTH_PREFLIGHT_REQUIRED')
        self.assertEqual([entry['source'] for entry in blocked.exception.detail['platforms']], ['fengshen'])
        self.assertEqual(manager.list_runs("测试-1"), [])

    def test_create_proceeds_when_all_required_platforms_ready(self):
        manager = self.manager()
        with patch.object(routes.importlib, "import_module", return_value=SimpleNamespace(
                get_options=lambda: {"cities": [], "datasets": []},
                ValidationError=ValueError, validate_request=Mock(return_value=CONFIG))), \
                patch.object(routes, "get_manager", return_value=manager), \
                patch.object(routes, "configured_output_root", return_value=manager.output_root), \
                patch.object(platform_auth_control, 'check',
                      side_effect=lambda source, deep=False: {'state': 'ready', 'message': 'ok'}):
            result = complete(routes.create(request("POST", "测试-1", CONFIG)))
        run = self.wait_run(manager, result["run"]["id"])
        self.assertEqual(run["status"], "success")

    def test_retry_is_blocked_for_stale_platform_session(self):
        manager = self.manager()
        with patch.object(routes.importlib, "import_module", return_value=SimpleNamespace(
                get_options=lambda: {"cities": [], "datasets": []},
                ValidationError=ValueError, validate_request=Mock(return_value=CONFIG))), \
                patch.object(routes, "get_manager", return_value=manager), \
                patch.object(routes, "configured_output_root", return_value=manager.output_root), \
                patch.object(platform_auth_control, 'check',
                      side_effect=lambda source, deep=False: {'state': 'ready', 'message': 'ok'}):
            result = complete(routes.create(request("POST", "测试-1", CONFIG)))
        self.wait_run(manager, result["run"]["id"])
        with patch.object(platform_auth_control, 'check',
                   side_effect=lambda source, deep=False: {'state': 'signed_out', 'message': '登录已失效'}), \
                patch.object(routes, "get_manager", return_value=manager), \
                self.assertRaises(HTTPException) as blocked:
            complete(routes.retry(result["run"]["id"], request("POST", "测试-1",
                                                              {"items": [{"city": "泉州", "dataset": "delivery_fee",
                                                                          "start": CONFIG["start"], "end": CONFIG["end"]}],
                                                               "request_id": "retry-preflight-01"})))
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertEqual(blocked.exception.detail['code'], 'AUTH_PREFLIGHT_REQUIRED')


if __name__ == "__main__":
    unittest.main()
