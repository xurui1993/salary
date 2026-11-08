import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from fengshen_bill import BillCollectionError
from order_sources import daily_count_basis


class LiveSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.day = '2026-10-18'
        self.daily = {'2026-10-17': 21978, self.day: 3434}
        self.actual = {'2026-10-17': 21978, self.day: 3439}
        start = dt.datetime(2026, 10, 18, 10, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()
        self.snapshot = {'date': self.day, 'before': 3434, 'after': 3450, 'task_id': '152962964',
                         'started_at': start, 'checked_at': start + 30}

    def test_live_growth_uses_both_bounds_and_keeps_exact_history(self):
        self.assertEqual(daily_count_basis(self.actual, self.daily, self.snapshot, '152962964'),
                         'live_snapshot_verified')
        self.assertEqual(daily_count_basis(self.daily, self.daily), 'daily_verified')

    def test_missing_proof_historical_changes_and_outside_bounds_stop(self):
        variants = [({}, None), ({'2026-10-17': 21977}, self.snapshot),
                    ({self.day: 3433}, self.snapshot), ({self.day: 3451}, self.snapshot)]
        for changed, snapshot in variants:
            with self.subTest(changed=changed), self.assertRaises(BillCollectionError):
                daily_count_basis({**self.actual, **changed}, self.daily, snapshot, '152962964')

    def test_wrong_task_date_count_clock_and_types_stop(self):
        for changed in ({'task_id': 'other'}, {'date': '2026-10-17'}, {'before': 3433},
                        {'after': 3433}, {'after': True}, {'started_at': float('nan')},
                        {'checked_at': self.snapshot['started_at'] - 1},
                        {'checked_at': self.snapshot['started_at'] + 86400}):
            with self.subTest(changed=changed), self.assertRaises(BillCollectionError):
                daily_count_basis(self.actual, self.daily, {**self.snapshot, **changed}, '152962964')


if __name__ == '__main__':
    unittest.main()
