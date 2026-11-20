import test from 'node:test';
import assert from 'node:assert/strict';
import { selectionKey } from '../src/lib/downloadCenterLogic';

test('xiaoxiang all-dates selection is distinct from a manual full range', () => {
  const base = {
    cities: ['全部城市'],
    datasets: ['rider_daily', 'rider_order_detail'],
    start: '2025-11-20',
    end: '2026-11-19',
  };
  assert.notEqual(
    selectionKey({ ...base, xiaoxiang_all_dates: true }),
    selectionKey(base),
  );
  assert.equal(
    selectionKey({ ...base, xiaoxiang_all_dates: true }),
    selectionKey({ ...base, xiaoxiang_all_dates: true, cities: ['泉州'] }),
  );
});