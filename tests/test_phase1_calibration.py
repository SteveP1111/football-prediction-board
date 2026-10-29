import unittest
from scripts.phase1_calibration import audit

class CalibrationAuditTests(unittest.TestCase):
    def test_model_versions_are_separate_and_missing_markets_excluded(self):
        data={
            "a":{"model":"v1","division":"E0","probs":{"home_win":0.8},"outcomes":{"home_win":True}},
            "b":{"model":"v2","division":"E0","probs":{"home_win":0.2},"outcomes":{"home_win":False}},
            "c":{"model":"v1","division":"E0","probs":{},"outcomes":{"home_win":True}},
        }
        result=audit(data)
        self.assertEqual(result["models"]["v1"]["home_win"]["overall"]["n"],1)
        self.assertEqual(result["models"]["v2"]["home_win"]["overall"]["n"],1)
        self.assertEqual(result["excludedMissingOrInvalidByMarket"]["home_win"],1)
        self.assertEqual(result["models"]["v1"]["home_win"]["overall"]["brier"],0.04)

    def test_empty_and_invalid_probability(self):
        result=audit({"a":{"model":"v1","division":"E1","probs":{"draw":1.4},"outcomes":{"draw":True}}})
        self.assertNotIn("v1",result["models"])
        self.assertEqual(result["excludedMissingOrInvalidByMarket"]["draw"],1)

    def test_under35_is_derived_only_for_audit_and_never_overwrites_input(self):
        original={"a":{"model":"v1","division":"E0","probs":{"over35":0.3},"outcomes":{"over35":False,"under35":True}}}
        result=audit(original)
        self.assertEqual(result["models"]["v1"]["under35"]["overall"]["n"],1)
        self.assertEqual(result["models"]["v1"]["under35"]["overall"]["meanPredicted"],0.7)
        self.assertEqual(result["derivedUnder35ComplementsByModel"]["v1"],1)
        self.assertNotIn("under35", original["a"]["probs"])

if __name__=="__main__":
    unittest.main()
