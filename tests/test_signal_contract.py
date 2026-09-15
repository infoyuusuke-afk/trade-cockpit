import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('sc', Path(__file__).parents[1] / 'scripts/signal_contract.py')
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

JST = timezone(timedelta(hours=9))


def at(y, m, d, h=9, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=JST)


class FreshnessTests(unittest.TestCase):
    def test_missing_when_point_is_none(self):
        self.assertEqual(sc.check_freshness(None, 60, at(2026, 9, 15)), 'missing')

    def test_missing_when_value_is_none(self):
        p = sc.DataPoint(value=None, fetched_at=at(2026, 9, 15))
        self.assertEqual(sc.check_freshness(p, 60, at(2026, 9, 15)), 'missing')

    def test_ok_within_ttl(self):
        p = sc.DataPoint(value=100, fetched_at=at(2026, 9, 15, 9, 0, 0))
        asof = at(2026, 9, 15, 9, 0, 30)
        self.assertEqual(sc.check_freshness(p, 60, asof), 'ok')

    def test_stale_beyond_ttl(self):
        p = sc.DataPoint(value=100, fetched_at=at(2026, 9, 15, 9, 0, 0))
        asof = at(2026, 9, 15, 9, 5, 0)
        self.assertEqual(sc.check_freshness(p, 60, asof), 'stale')

    def test_future_data_is_detected_not_used_as_ok(self):
        # 受入基準#2: 発表後データを発表前asofへ渡していないかの検知
        p = sc.DataPoint(value=100, published_at=at(2026, 9, 15, 15, 30, 0), fetched_at=at(2026, 9, 15, 15, 30, 0))
        asof = at(2026, 9, 15, 9, 0, 0)  # 発表前の意思決定時点
        self.assertEqual(sc.check_freshness(p, 3600, asof), 'future')


class GateTests(unittest.TestCase):
    def test_all_ok_allows_trade(self):
        allowed, reasons = sc.gate_no_trade('ok', 'ok', 'ok')
        self.assertTrue(allowed)
        self.assertEqual(reasons, [])

    def test_any_stale_blocks_trade(self):
        # 受入基準#1: 古い価格・欠落データはWAIT
        allowed, reasons = sc.gate_no_trade('ok', 'stale', 'ok')
        self.assertFalse(allowed)
        self.assertIn('input_1_stale', reasons)

    def test_missing_blocks_trade(self):
        allowed, reasons = sc.gate_no_trade('missing')
        self.assertFalse(allowed)


class BuildSignalTests(unittest.TestCase):
    def test_trading_enabled_is_always_false(self):
        # build_signalはtrading_enabledという引数自体を受け付けない（TypeErrorで守られる）
        with self.assertRaises(TypeError):
            sc.build_signal(horizon='DAY', code='285A', side='WAIT', strategy_id='s1',
                             decision_asof=at(2026, 9, 15), source_quality='ok', trading_enabled=True)

    def test_wait_signal_does_not_require_entry_stop(self):
        sig = sc.build_signal(horizon='DAY', code='285A', side='WAIT', strategy_id='s1',
                               decision_asof=at(2026, 9, 15), source_quality='ok')
        self.assertFalse(sig['trading_enabled'])
        self.assertIsNone(sig['entry'])

    def test_long_signal_requires_entry_and_stop(self):
        with self.assertRaises(ValueError):
            sc.build_signal(horizon='DAY', code='285A', side='LONG', strategy_id='s1',
                             decision_asof=at(2026, 9, 15), source_quality='ok')

    def test_invalid_side_rejected(self):
        with self.assertRaises(ValueError):
            sc.build_signal(horizon='DAY', code='285A', side='BUY', strategy_id='s1',
                             decision_asof=at(2026, 9, 15), source_quality='ok')

    def test_schema_version_present(self):
        sig = sc.build_signal(horizon='DAY', code='285A', side='WAIT', strategy_id='s1',
                               decision_asof=at(2026, 9, 15), source_quality='ok')
        self.assertEqual(sig['schema_version'], sc.SCHEMA_VERSION)


class SnapshotTests(unittest.TestCase):
    def test_record_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            asof = at(2026, 9, 15, 9, 30, 0)
            sig = sc.build_signal(horizon='DAY', code='285A', side='WAIT', strategy_id='s1',
                                   decision_asof=asof, source_quality='ok')
            sc.record_snapshot(out_dir, asof, {'price': 51750}, sig)
            records = sc.read_snapshots(out_dir, '2026-09-15')
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['inputs']['price'], 51750)
            self.assertEqual(records[0]['signal']['code'], '285A')

    def test_multiple_records_append_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            asof = at(2026, 9, 15, 9, 30, 0)
            for i in range(3):
                sig = sc.build_signal(horizon='DAY', code=f'CODE{i}', side='WAIT', strategy_id='s1',
                                       decision_asof=asof, source_quality='ok')
                sc.record_snapshot(out_dir, asof, {}, sig)
            records = sc.read_snapshots(out_dir, '2026-09-15')
            self.assertEqual(len(records), 3)

    def test_missing_day_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(sc.read_snapshots(Path(d), '2026-01-01'), [])


if __name__ == '__main__':
    unittest.main()
