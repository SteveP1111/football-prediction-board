"""Temporary diagnostic only; removed before merge. No credentials or paid APIs."""
import json
import re
import unittest
import urllib.request

class PublicResultsSourceProbe(unittest.TestCase):
    def test_inspect_public_sources(self):
        urls=[
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=20261031",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.2/scoreboard?dates=20261031",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.3/scoreboard?dates=20261031",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.4/scoreboard?dates=20261031",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.5/scoreboard?dates=20261031",
            "https://www.footballwebpages.co.uk/20261031",
            "https://www.theguardian.com/football/results/2026/oct/31",
        ]
        for url in urls:
            try:
                req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; VerifiedFootballResults/1.0)","Accept":"application/json,text/html;q=0.9,*/*;q=0.5"})
                with urllib.request.urlopen(req,timeout=7) as resp:
                    page=resp.read(900000).decode("utf-8",errors="replace")
                    status=resp.status
                print("PROBE",url,"STATUS",status,"LENGTH",len(page))
                if "espn" in url:
                    j=json.loads(page)
                    e=j.get("events",[])
                    print("ESPN_EVENTS",len(e),"LEAGUE",str(j.get("leagues",[]))[:250])
                    for row in e[:2]:
                        comp=(row.get("competitions") or [{}])[0]
                        print("ESPN_ROW",row.get("date"),row.get("name"),str(comp.get("status"))[:130],[(x.get("homeAway"),x.get("team",{}).get("displayName"),x.get("score")) for x in comp.get("competitors",[])])
                else:
                    for needle in ("Coventry City","Manchester City","FC Halifax Town","Boreham Wood","Premier League","Saturday, 31 October"):
                        m=re.search(re.escape(needle),page,re.I)
                        if m:
                            print("HTML_NEEDLE",needle,"RAW_CONTEXT",repr(page[max(0,m.start()-260):m.end()+350])[:660])
            except Exception as exc:
                print("PROBE_ERROR",url,type(exc).__name__,str(exc)[:150])
        self.assertTrue(True)
