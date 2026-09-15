import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('ew', Path(__file__).parents[1] / 'scripts/earnings_watch.py')
ew = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ew)


class ClassifyMaterialProxyTests(unittest.TestCase):
    def test_good_material_label_is_positive(self):
        self.assertEqual(ew.classify_material_proxy('発表済み好材料あり'), 'POSITIVE')

    def test_bad_material_label_is_negative(self):
        self.assertEqual(ew.classify_material_proxy('警戒材料あり'), 'NEGATIVE')

    def test_related_disclosure_only_is_neutral(self):
        self.assertEqual(ew.classify_material_proxy('関連開示を確認'), 'NEUTRAL')

    def test_no_disclosure_is_neutral(self):
        self.assertEqual(ew.classify_material_proxy('未発表・期待判断の根拠不足'), 'NEUTRAL')

    def test_unknown_label_defaults_to_neutral_not_invented(self):
        self.assertEqual(ew.classify_material_proxy('見たことのないラベル'), 'NEUTRAL')

    def test_none_label_is_neutral(self):
        self.assertEqual(ew.classify_material_proxy(None), 'NEUTRAL')


class ClassifyStageTests(unittest.TestCase):
    def test_neutral_bias_stays_pre_event_watch(self):
        stage, direction, reasons = ew.classify_stage('NEUTRAL', None, 'UP')
        self.assertEqual(stage, 'pre_event_watch')
        self.assertEqual(direction, 'WAIT')
        self.assertIn('bias_not_directional', reasons)

    def test_missing_reaction_data_stays_post_event_bias(self):
        stage, direction, reasons = ew.classify_stage('POSITIVE', None, 'UP')
        self.assertEqual(stage, 'post_event_bias')
        self.assertEqual(direction, 'WAIT')
        self.assertIn('reaction_data_insufficient', reasons)

    def test_positive_bias_below_threshold_stays_bias_only(self):
        stage, direction, reasons = ew.classify_stage('POSITIVE', 1.0, 'UP')
        self.assertEqual(stage, 'post_event_bias')
        self.assertEqual(direction, 'WAIT')

    def test_positive_bias_with_reversed_reaction_waits(self):
        # 材料は好材料だが実際は下落している逆反応
        stage, direction, reasons = ew.classify_stage('POSITIVE', -3.0, 'UP')
        self.assertEqual(stage, 'post_event_bias')
        self.assertEqual(direction, 'WAIT')

    def test_positive_bias_confirmed_reaction_unknown_regime_waits(self):
        stage, direction, reasons = ew.classify_stage('POSITIVE', 3.0, None)
        self.assertEqual(stage, 'post_event_bias')
        self.assertIn('regime_unknown', reasons)

    def test_positive_bias_confirmed_reaction_wrong_regime_waits(self):
        stage, direction, reasons = ew.classify_stage('POSITIVE', 3.0, 'DOWN')
        self.assertEqual(stage, 'post_event_bias')
        self.assertIn('regime_not_up', reasons)

    def test_positive_bias_confirmed_reaction_up_regime_is_long_candidate(self):
        stage, direction, reasons = ew.classify_stage('POSITIVE', 3.0, 'UP')
        self.assertEqual(stage, 'trade_candidate')
        self.assertEqual(direction, 'LONG')
        self.assertEqual(reasons, [])

    def test_negative_bias_confirmed_reaction_down_regime_is_short_but_blocked(self):
        # 受入基準相当: NEGATIVE＋在庫不明→SHORT候補不可（block_reasonsで明示）
        stage, direction, reasons = ew.classify_stage('NEGATIVE', -3.0, 'DOWN')
        self.assertEqual(stage, 'trade_candidate')
        self.assertEqual(direction, 'SHORT')
        self.assertIn('short_eligibility_unconfirmed', reasons)

    def test_exact_threshold_boundary_counts_as_confirmed(self):
        stage, direction, _ = ew.classify_stage('POSITIVE', 2.0, 'UP')
        self.assertEqual(direction, 'LONG')

    def test_just_below_threshold_does_not_count(self):
        stage, direction, _ = ew.classify_stage('POSITIVE', 1.99, 'UP')
        self.assertEqual(direction, 'WAIT')


if __name__ == '__main__':
    unittest.main()
