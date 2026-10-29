import math
import unittest
from scripts.phase2_compare import distribution, overdispersed, league_climatology, paired_day_bootstrap, truth, add_complements, under35_analysis, MARKETS

class ModelComparisonTests(unittest.TestCase):
    def test_goal_distributions_normalised_and_nested(self):
        for estimate in (distribution(1.4,1.1),distribution(1.4,1.1,rho=-.08),overdispersed(1.4,1.1)):
            self.assertAlmostEqual(sum(estimate[m] for m in ("home_win","draw","away_win")),1,places=8)
            self.assertLessEqual(estimate["over35"],estimate["over25"])
            self.assertEqual(set(estimate),set(MARKETS))
            self.assertAlmostEqual(estimate["over35"]+estimate["under35"],1,places=8)
            self.assertAlmostEqual(estimate["over25"]+estimate["under25"],1,places=8)
            self.assertAlmostEqual(estimate["btts"]+estimate["no_btts"],1,places=8)
            self.assertTrue(all(0 <= p <= 1 for p in estimate.values()))

    def test_dixon_coles_changes_draw_probability(self):
        raw=distribution(1.4,1.1)
        adjusted=distribution(1.4,1.1,rho=-.08)
        self.assertNotAlmostEqual(raw["draw"],adjusted["draw"])

    def test_rolling_league_benchmark(self):
        history=[
          {"division":"E0","date":"2026-02-01","hg":2,"ag":1},
          {"division":"E0","date":"2026-02-02","hg":1,"ag":1},
          {"division":"E1","date":"2026-02-02","hg":5,"ag":0}
        ]
        benchmark=league_climatology(history,"E0")
        self.assertAlmostEqual(sum(benchmark[m] for m in ("home_win","draw","away_win")),1)
        self.assertAlmostEqual(benchmark["home_win"],2/5)
        self.assertAlmostEqual(benchmark["over35"]+benchmark["under35"],1)
        self.assertAlmostEqual(benchmark["over25"]+benchmark["under25"],1)
        self.assertAlmostEqual(benchmark["btts"]+benchmark["no_btts"],1)

    def test_under35_boundary_exactly_three_goals(self):
        for h,a,expected in ((0,0,1),(2,1,1),(3,0,1),(2,2,0),(4,0,0),(1,3,0)):
            row=truth({"hg":h,"ag":a})
            self.assertEqual(row["under35"],expected)
            self.assertEqual(row["over35"],1-expected)

    def test_complements_are_derived_without_mutating(self):
        base={"home_win":0.45,"draw":0.30,"away_win":0.25,"btts":0.4,"over25":0.5,"over35":0.2}
        output=add_complements(base)
        self.assertAlmostEqual(output["under35"],0.8)
        self.assertAlmostEqual(output["under25"],0.5)
        self.assertAlmostEqual(output["no_btts"],0.6)
        self.assertNotIn("under35",base)

    def test_under35_probability_cohorts(self):
        data=[]
        for idx, (prob,final) in enumerate(((.71,1),(.65,0),(.56,1),(.52,1))):
            data.append({"date":"2026-10-01","truth":{"under35":final},
                         "predictions":{"V1 Poisson":{"under35":prob}}})
        result=under35_analysis(data,"V1 Poisson")
        self.assertEqual(result["overall"]["n"],4)
        self.assertEqual(result["thresholds"]["70%"]["n"],1)
        self.assertEqual(result["thresholds"]["70%"]["wins"],1)
        self.assertEqual(result["thresholds"]["65%"]["n"],2)
        self.assertEqual(result["thresholds"]["65%"]["wins"],1)
        self.assertEqual(result["thresholds"]["55%"]["n"],3)
        self.assertEqual(result["thresholds"]["55%"]["wins"],2)
        self.assertTrue(result["noBookmakerValueClaim"])
        self.assertEqual(result["calibrationBands"]["70-80%"]["n"],1)
        self.assertFalse(result["calibrationBands"]["70-80%"]["sufficientForInterpretation"])

    def test_under35_bootstrap_compares_same_fixtures(self):
        baseline=add_complements({"home_win":.5,"draw":.25,"away_win":.25,"btts":.5,"over25":.5,"over35":.45})
        challenger=add_complements({"home_win":.5,"draw":.25,"away_win":.25,"btts":.5,"over25":.5,"over35":.3})
        row={"date":"2026-08-01","truth":{"under35":1},
             "predictions":{"V1 Poisson":baseline,"V2":challenger}}
        delta=paired_day_bootstrap([row],"V2",iterations=100)
        self.assertLess(delta["under35"]["differenceVsV1"],0)
        self.assertEqual(delta["over35"]["differenceVsV1"],delta["under35"]["differenceVsV1"])

    def test_paired_bootstrap_constant_impact(self):
        original={"home_win":.5,"draw":.25,"away_win":.25,"btts":.5,"over25":.5,"over35":.3}
        alternative=dict(original,home_win=.6,draw=.2,away_win=.2)
        row={"date":"2026-08-01","truth":{"home_win":1,"draw":0,"away_win":0,"btts":1,"over25":1,"over35":0},
             "predictions":{"V1 Poisson":original,"V2":alternative}}
        delta=paired_day_bootstrap([row], "V2",iterations=100)
        self.assertLess(delta["1x2MulticlassBrier"]["differenceVsV1"],0)
        self.assertEqual(delta["btts"]["differenceVsV1"],0)

if __name__=="__main__":
    unittest.main()
