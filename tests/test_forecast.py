import math, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import refresh

class ForecastTests(unittest.TestCase):
    def test_team_aliases(self):
        self.assertEqual(refresh.canon("Bolton Wanderers"),"bolton")
        self.assertEqual(refresh.canon("Bolton"),"bolton")
        self.assertEqual(refresh.canon("Crewe Alexandra"),"crewe")
        self.assertEqual(refresh.canon("Sheffield Weds"),"sheffield wednesday")
    def test_market_partition(self):
        f={"division":"E0","homeKey":"home","awayKey":"away","date":"2026-10-19",
           "league":"Premier League","home":"Home","away":"Away","kickoff":"15:00","id":"x"}
        out=refresh.model(f,[])
        sc=out["scoreline"];m=sc["markets"];b=sc["goalBands"]
        self.assertAlmostEqual(m["over25"]+m["under25"],1,places=4)
        self.assertAlmostEqual(m["home_win"]+m["away_win"]+m["draw"],1,places=4)
        self.assertAlmostEqual(m["btts"]+m["no_btts"],1,places=4)
        self.assertAlmostEqual(sum(b.values()),1,places=4)
        self.assertGreaterEqual(m["over25"],m["over35"])
    def test_settlement_markets(self):
        self.assertEqual(refresh.settle(None,(3,0))["over25"],True)
        self.assertEqual(refresh.settle(None,(3,0))["btts"],False)
        self.assertEqual(refresh.settle(None,(0,0))["under25"],True)
        self.assertEqual(refresh.settle(None,(2,1))["home_win"],True)
    def test_conflicting_scores_rejected(self):
        row={"id":"same","hg":2,"ag":1,"status":"current"}
        with self.assertRaises(ValueError):
            refresh.unique_results([row,{**row,"hg":4}])
    def test_future_results_excluded(self):
        row={"id":"x","division":"E0","home":"home","away":"away","hg":9,"ag":0,
             "date":"2026-10-20","status":"current"}
        f={"division":"E0","homeKey":"home","awayKey":"away","date":"2026-10-19",
           "league":"Premier League","home":"Home","away":"Away","kickoff":"15:00","id":"y"}
        self.assertEqual(refresh.model(f,[])["scoreline"]["expectedHome"],
                         refresh.model(f,[row])["scoreline"]["expectedHome"])
if __name__=="__main__":unittest.main()
