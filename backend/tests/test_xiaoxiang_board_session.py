"""看板 SSO 缓存：只保留 zl.meituan.com 与 sankuai.com，DPAPI 加密落盘。"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xiaoxiang_board as board


def state():
    return {
        'cookies': [
            {'name': 'mall.fe.pc_ssoid', 'value': 'synthetic', 'domain': 'zl.meituan.com', 'path': '/', 'expires': -1},
            {'name': 'ssosv_session', 'value': 'synthetic', 'domain': '.sankuai.com', 'path': '/', 'expires': -1},
            {'name': 'token2', 'value': 'synthetic', 'domain': '.meituan.com', 'path': '/', 'expires': -1},
            {'name': 'mall-passport-token', 'value': 'synthetic', 'domain': 'maicaipeisong.meituan.com', 'path': '/', 'expires': -1},
        ],
        'origins': [
            {'origin': 'https://zl.meituan.com', 'localStorage': [{'name': 'k', 'value': 'v'}]},
            {'origin': 'https://ssosv.sankuai.com', 'localStorage': []},
            {'origin': 'https://maicaipeisong.meituan.com', 'localStorage': []},
        ],
    }


class BoardSessionTests(unittest.TestCase):
    def test_scope_keeps_only_board_and_elephant_sso(self):
        scoped = board.scoped_board_state(state())
        self.assertEqual([cookie['name'] for cookie in scoped['cookies']], ['mall.fe.pc_ssoid', 'ssosv_session'])
        self.assertEqual({origin['origin'] for origin in scoped['origins']},
                         {'https://zl.meituan.com', 'https://ssosv.sankuai.com'})

    def test_scope_drops_duplicates_and_invalid_cookies(self):
        duplicate = dict(state())
        duplicate['cookies'] = state()['cookies'] + [
            {'name': 'ssosv_session', 'value': 'synthetic', 'domain': '.sankuai.com', 'path': '/', 'expires': -1},
            {'name': 'bad', 'value': 1, 'domain': 'zl.meituan.com', 'path': '/'},
            {'name': 'bad', 'value': 'x', 'domain': 'evil.example', 'path': '/'},
        ]
        self.assertEqual(len(board.scoped_board_state(duplicate)['cookies']), 2)

    def test_roundtrip_saves_encrypted_and_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.dpapi'
            board.save_board_state(state(), path)
            self.assertNotIn(b'mall.fe.pc_ssoid', path.read_bytes())
            restored = board.load_board_state(path)
        self.assertEqual([cookie['name'] for cookie in restored['cookies']], ['mall.fe.pc_ssoid', 'ssosv_session'])

    def test_missing_or_corrupt_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.dpapi'
            self.assertIsNone(board.load_board_state(path))
            path.write_bytes(b'not-encrypted')
            self.assertIsNone(board.load_board_state(path))

    def test_state_without_board_cookies_is_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.dpapi'
            with self.assertRaises(board.LighthouseError):
                board.save_board_state({'cookies': state()['cookies'][2:], 'origins': []}, path)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
