#!/usr/bin/env python3
"""Read-only Phase 1 calibration audit of original settled pre-match probabilities."""
import json, math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETS = ("home_win","draw","away_win","btts","no_btts","over25","under25","over35","under35")
BANDS = ((0,.1),(.1,.2),(.2,.3),(.3,.4),(.4,.5),(.5,.6),(.6,.7),(.7,.8),(.8,.9),(.9,1.000001))
MIN_BAND = 20

def score(rows):
    n=len(rows)
    if not n: return {"n":0}
    mean_p=sum(p for p,y in rows)/n
    actual=sum(y for p,y in rows)/n
    eps=1e-12
    return {"n":n,"meanPredicted":round(mean_p,4),"actualRate":round(actual,4),
        "gapPp":round(100*(actual-mean_p),2),
        "brier":round(sum((p-y)**2 for p,y in rows)/n,5),
        "logLoss":round(-sum(y*math.log(max(eps,p))+(1-y)*math.log(max(eps,1-p)) for p,y in rows)/n,5),
        "hindsightConstantRateBrier_NotForecastBenchmark":round(actual*(1-actual),5)}

def audit(settlements):
    groups=defaultdict(list)
    excluded=defaultdict(int)
    complements=defaultdict(int)
    for fid, record in settlements.items():
        if not isinstance(record,dict): continue
        model=record.get("model","unknown")
        probs=record.get("probs") or {}
        outcomes=record.get("outcomes") or {}
        div=record.get("division","unknown")
        for market in MARKETS:
            p=probs.get(market); y=outcomes.get(market)
            if market=="under35" and p is None:
                opposite=probs.get("over35")
                if isinstance(opposite,(int,float)) and not isinstance(opposite,bool) and math.isfinite(opposite) and 0<=opposite<=1:
                    p=1.0-opposite
                    if not isinstance(y,bool) and isinstance(outcomes.get("over35"),bool):
                        y=not outcomes["over35"]
                    complements[model]+=1
            if isinstance(p,bool) or not isinstance(p,(float,int)) or not math.isfinite(p) or not 0<=p<=1 or not isinstance(y,bool):
                excluded[market]+=1; continue
            for group in (("overall",model,market),("division",model,div,market)):
                groups[group].append((float(p),int(y)))
    result={"note":"Descriptive in-sample audit of immutable settled forecasts; mathematically derived Under 3.5 complements are counted separately and never written back to originals. Not out-of-sample validation or evidence of betting profitability.",
        "excludedMissingOrInvalidByMarket":dict(excluded),
        "derivedUnder35ComplementsByModel":dict(complements),
        "hindsightBaselineWarning":"The constant observed-rate Brier in each group uses that same group's outcomes: an optimistic retrospective reference, not a deployable baseline.",
        "models":{}}
    for key,rows in groups.items():
        if key[0]!="overall":continue
        _,model,market=key
        bands=[]
        for lo,hi in BANDS:
            subset=[(p,y) for p,y in rows if lo<=p<hi]
            entry={"band":f"{round(lo*100)}-{round(min(hi,1)*100)}%","sufficientForDisplay":len(subset)>=MIN_BAND}
            entry.update(score(subset))
            bands.append(entry)
        result["models"].setdefault(model,{})[market]={"overall":score(rows),"bands":bands}
    result["byDivision"]={}
    for key,rows in groups.items():
        if key[0]=="division":
            _,model,div,market=key
            result["byDivision"].setdefault(model,{}).setdefault(div,{})[market]=score(rows)
    return result

def main():
    src=ROOT/"data"/"settlements.json"
    out=ROOT/"data"/"phase1_calibration.json"
    result=audit(json.loads(src.read_text(encoding="utf-8")))
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("Wrote",out,"models:",", ".join(result["models"]))

if __name__=="__main__": main()
