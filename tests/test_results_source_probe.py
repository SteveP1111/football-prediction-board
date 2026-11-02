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
                    from results_fallback import parse_espn
                    from refresh import canon
                    j=json.loads(page)
                    league={"eng.1":"E0","eng.2":"E1","eng.3":"E2","eng.4":"E3","eng.5":"EC"}[next(k for k in ("eng.1","eng.2","eng.3","eng.4","eng.5") if "/"+k+"/" in url)]
                    parsed=parse_espn(j,league,"2026-10-31",canon)
                    print("ESPN_PARSED",league,len(parsed),sorted(parsed.items())[:4])
                    e=j.get("events",[])
                    print("ESPN_EVENTS",len(e),"LEAGUE",str(j.get("leagues",[]))[:250])
                    for row in e[:2]:
                        comp=(row.get("competitions") or [{}])[0]
                        print("ESPN_ROW",row.get("date"),row.get("name"),str(comp.get("status"))[:130],[(x.get("homeAway"),x.get("team",{}).get("displayName"),x.get("score")) for x in comp.get("competitors",[])])
                else:
                    if "footballwebpages" in url:
                        from results_fallback import parse_footballwebpages
                        from refresh import canon
                        parsed=parse_footballwebpages(page,"2026-10-31",canon)
                        print("FWP_PARSED",len(parsed),sorted(parsed.items())[:12])
                        for needle in ("Manchester City 0-1", "FC Halifax Town 2-0"):
                            match=re.search(r"<tr[^>]+title=[\\\"']" + re.escape(needle) + r".*?</tr>",page,re.I|re.S)
                            if match:
                                print("FWP_FULL_MATCH_ROW",needle,repr(match.group(0)[:2100]))
                        for needle in ("comp-1","comp-2","comp-3","comp-4","comp-5"):
                            match=re.search(r"<tr class=[\\\"']" + re.escape(needle) + r".*?</tr>",page,re.I|re.S)
                            if match:
                                print("FWP_FIRST_ROW",needle,repr(match.group(0)[:900]))
                    for needle in ("Coventry City","Manchester City","FC Halifax Town","Boreham Wood","Premier League","Saturday, 31 October"):
                        m=re.search(re.escape(needle),page,re.I)
                        if m:
                            print("HTML_NEEDLE",needle,"RAW_CONTEXT",repr(page[max(0,m.start()-260):m.end()+350])[:660])
            except Exception as exc:
                print("PROBE_ERROR",url,type(exc).__name__,str(exc)[:150])
        self.assertTrue(True)
