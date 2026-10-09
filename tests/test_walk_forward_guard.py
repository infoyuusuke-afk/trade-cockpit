import unittest
from scripts.walk_forward_guard import evaluate_folds
class T(unittest.TestCase):
 def folds(self):return [{"train_end":"2026-01-31","test_start":"2026-02-01","test_end":"2026-02-28","test_expectancy":.2,"p_value":.004},{"train_end":"2026-02-28","test_start":"2026-03-01","test_end":"2026-03-31","test_expectancy":.1,"p_value":.003}]
 def test_pass(self):self.assertEqual(evaluate_folds("x",self.folds(),10)["status"],"PASS")
 def test_time_leakage(self):
  x=self.folds();x[0]["test_start"]="2026-01-01";self.assertIn("TIME_LEAKAGE",evaluate_folds("x",x,10)["reasons"])
 def test_negative_fold_fails(self):
  x=self.folds();x[1]["test_expectancy"]=-.1;self.assertIn("NON_POSITIVE_FOLD",evaluate_folds("x",x,10)["reasons"])
 def test_multiple_testing_adjustment(self):
  x=self.folds();x[0]["p_value"]=.02;self.assertIn("MULTIPLE_TESTING_NOT_CLEARED",evaluate_folds("x",x,10)["reasons"])
 def test_no_live(self):self.assertFalse(evaluate_folds("x",self.folds(),10)["real_submit_allowed"])
if __name__=="__main__":unittest.main()
