import math
import unittest
from scripts.phase2_compare import distribution, overdispersed, league_climatology, paired_day_bootstrap, truth

class ModelComparisonTests(unittest.TestCase):
    def test_goal_distributions_normalised_and_nested(self):
        for estimate in (distribution(1.4,1.1),distribution(1.4,1.1,rho=-.08),overdispersed(1.4,1.1)):
            self.assertAlmostEqual(sum(estimate[m] for m in ("home_win","draw","away_win")),1,places=8)
            self.assertLessEqual(estimate["over35"],estimate["over25"])
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
