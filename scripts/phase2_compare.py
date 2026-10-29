#!/usr/bin/env python3
"""Phase 2 chronological comparison. No edits to live forecasts or frozen odds."""
import json, math, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import refresh
from phase1_calibration import score

MARKETS=("home_win","draw","away_win","btts","over25","over35")
ROOT=Path(__file__).resolve().parents[1]
def distribution(lh,la,rho=0):
    h=refresh.dist(lh); a=refresh.dist(la)
    cells={}
    for i,x in enumerate(h):
        for j,y in enumerate(a):
            factor=1.
            if rho:
                if (i,j)==(0,0): factor=1-lh*la*rho
                elif (i,j)==(0,1): factor=1+lh*rho
                elif (i,j)==(1,0): factor=1+la*rho
                elif (i,j)==(1,1): factor=1-rho
            cells[i,j]=max(0,x*y*factor)
    z=sum(cells.values())
    if z<=0: raise ValueError("Invalid distribution")
    p={k:0. for k in MARKETS}
    for (i,j),v in cells.items():
        v/=z
        p["home_win"]+=v*(i>j);p["draw"]+=v*(i==j);p["away_win"]+=v*(i<j)
        p["btts"]+=v*(i>0 and j>0);p["over25"]+=v*(i+j>=3);p["over35"]+=v*(i+j>=4)
    return p

def variants(f,train):
    base=refresh.model(f,train)["scoreline"]
    lh,la=base["expectedHome"],base["expectedAway"]
    # V2: modest, predeclared home/away recent-strength correction; not fitted to test.
    relevant=[r for r in train if r["division"]==f["division"] and r["date"]<f["date"]]
    home=sorted([r for r in relevant if r["home"]==f["homeKey"]],key=lambda r:r["date"],reverse=True)[:12]
    away=sorted([r for r in relevant if r["away"]==f["awayKey"]],key=lambda r:r["date"],reverse=True)[:12]
    def shrink_mean(rows,field,prior):
        return (sum(r[field] for r in rows)+8*prior)/(len(rows)+8)
    hh=shrink_mean(home,"hg",lh); hc=shrink_mean(home,"ag",la)
    aa=shrink_mean(away,"ag",la); ac=shrink_mean(away,"hg",lh)
    l2h=max(.2,min(4.,lh*(max(.25,hh/lh)*max(.25,ac/lh))**.20))
    l2a=max(.2,min(4.,la*(max(.25,aa/la)*max(.25,hc/la))**.20))
    return {"V1 Poisson":distribution(lh,la),
            "V2 venue-strength":distribution(l2h,l2a),
            "V3 Dixon-Coles":distribution(lh,la,rho=-.08),
            "V3 overdispersion":overdispersed(lh,la)}

def overdispersed(lh,la):
    # Fixed 15% shared match-tempo mixture, increasing tails without test fitting.
    parts=[(.15,.70),(.70,1.),(.15,1.30)]
    out={m:0. for m in MARKETS}
    for weight,mult in parts:
        pred=distribution(lh*mult,la*mult)
        for m in MARKETS:out[m]+=weight*pred[m]
    return out

def clip(x):return max(.000001,min(.999999,x))
def temp(p,t):
    p=clip(p)
    return clip(1/(1+math.exp(-math.log(p/(1-p))/t)))
def fit_temperatures(rows):
    # Validation period only, prior to test season; fixed small grid.
    result={}
    for market in MARKETS:
        observations=[(p[market],y[market]) for p,y in rows]
        result[market]=min((.8,1.,1.2,1.5,2.),key=lambda t:sum((temp(p,t)-y)**2 for p,y in observations))
    return result

def truth(r):
    h,a=r["hg"],r["ag"]
    return {"home_win":int(h>a),"draw":int(h==a),"away_win":int(h<a),
            "btts":int(h>0 and a>0),"over25":int(h+a>=3),"over35":int(h+a>=4)}

def run(rows):
    # 2025/26 validation, 2026/27 untouched test. Pre-match histories only.
    rows=sorted(rows,key=lambda r:(r["date"],r["id"]))
    val=[];test=[]
    for r in rows:
        day=r["date"]
        if not ("2026-02-01"<=day<="2026-05-31" or "2026-08-01"<=day<="2026-10-29"):
            continue
        season="2526" if day<"2026-06-01" else "2627"
        if season=="2526":
            training=[dict(x,status=("current" if x["date"]>="2025-07-01" else "prior")) for x in rows if x["date"]<day and x["date"]>="2024-07-01"]
        else:
            training=[dict(x,status=("current" if x["date"]>="2026-07-01" else "prior")) for x in rows if x["date"]<day and x["date"]>="2025-07-01"]
        if len(training)<100:continue
        f={"division":r["division"],"homeKey":r["home"],"awayKey":r["away"],"date":day}
        predictions=variants(f,training)
        record={"date":day,"division":r["division"],"truth":truth(r),"predictions":predictions}
        (val if season=="2526" else test).append(record)
    if not val or not test:raise RuntimeError("Insufficient chronological validation/test fixtures")
    temps=fit_temperatures([(r["predictions"]["V1 Poisson"],r["truth"]) for r in val])
    for r in test:
        cal={m:temp(r["predictions"]["V1 Poisson"][m],temps[m]) for m in MARKETS}
        z=sum(cal[m] for m in ("home_win","draw","away_win"))
        for m in ("home_win","draw","away_win"):cal[m]/=z
        r["predictions"]["V4 calibrated V1"]=cal
    # Score 1X2 as one 3-way outcome and binary markets individually.
    report={"validationPeriod":"2026-02-01 to 2026-05-31","testPeriod":"2026-08-01 to 2026-10-29",
            "validationFixtures":len(val),"testFixtures":len(test),"temperatureFromValidation":temps,
            "caution":"Exploratory predeclared variants; not independent model optimisation. No historical bookmaker ROI inferred.",
            "models":{}}
    for name in test[0]["predictions"]:
        metrics={}
        for m in MARKETS:
            pairs=[(r["predictions"][name][m],r["truth"][m]) for r in test]
            metrics[m]=score(pairs)
        metrics["1x2MulticlassBrier"]=round(sum(sum((r["predictions"][name][m]-r["truth"][m])**2 for m in ("home_win","draw","away_win")) for r in test)/len(test),5)
        metrics["1x2LogLoss"]=round(-sum(math.log(clip(r["predictions"][name][next(m for m in ("home_win","draw","away_win") if r["truth"][m])])) for r in test)/len(test),5)
        report["models"][name]=metrics
    return report

def load():
    rows=[]
    for season in ("2425","2526","2627"):
        for div in refresh.DIVS:
            source,_=refresh.fetch_csv("https://www.football-data.co.uk/mmz4281/%s/%s.csv"%(season,div))
            for r in refresh.result_rows(source,div,"current"):
                rows.append(r)
    return refresh.unique_results(rows)

if __name__=="__main__":
    report=run(load())
    path=ROOT/"data"/"phase2_comparison.json"
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
