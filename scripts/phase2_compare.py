#!/usr/bin/env python3
"""Phase 2 chronological comparison. No edits to live forecasts or frozen odds."""
import hashlib, json, math, random, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import refresh
from phase1_calibration import score

PRIMARY_MARKETS=("home_win","draw","away_win","btts","over25","over35")
MARKETS=("home_win","draw","away_win","btts","no_btts","over25","under25","over35","under35")
UNDER35_THRESHOLDS=(.55,.60,.65,.70,.75,.80)
MIN_CALIBRATION_BAND=20

def add_complements(probabilities):
    """Derive logically equivalent outcomes, without modifying the supplied dict."""
    result=dict(probabilities)
    for negative,positive in (("no_btts","btts"),("under25","over25"),("under35","over35")):
        result[negative]=1.0-result[positive]
    return result

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
    return add_complements(p)

def variants(f,train):
    base=refresh.model(f,train)["scoreline"]
    lh,la=base["expectedHome"],base["expectedAway"]
    exact_v1={m:base["markets"][m] for m in MARKETS}
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
    return {"V1 Poisson":exact_v1,
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
    for market in PRIMARY_MARKETS:
        observations=[(p[market],y[market]) for p,y in rows]
        result[market]=min((.8,1.,1.2,1.5,2.),key=lambda t:sum((temp(p,t)-y)**2 for p,y in observations))
    return result

def truth(r):
    h,a=r["hg"],r["ag"]
    return {"home_win":int(h>a),"draw":int(h==a),"away_win":int(h<a),
            "btts":int(h>0 and a>0),"no_btts":int(h==0 or a==0),
            "over25":int(h+a>=3),"under25":int(h+a<3),
            "over35":int(h+a>=4),"under35":int(h+a<4)}


def league_climatology(train, division):
    """Only results preceding kickoff; naive benchmark, not modelled odds."""
    past=sorted((r for r in train if r["division"]==division),key=lambda r:r["date"],reverse=True)[:250]
    if not past:
        return add_complements({"home_win":1/3,"draw":1/3,"away_win":1/3,"btts":.5,"over25":.5,"over35":.5})
    obs=[truth(r) for r in past]
    n=len(obs)
    result={m:(sum(y[m] for y in obs)+1)/(n+2) for m in ("btts","over25","over35")}
    result.update({m:(sum(y[m] for y in obs)+1)/(n+3) for m in ("home_win","draw","away_win")})
    return add_complements(result)

def loss_value(row, name, measure):
    predicted=row["predictions"][name]; observed=row["truth"]
    if measure=="1x2MulticlassBrier":
        return sum((predicted[m]-observed[m])**2 for m in ("home_win","draw","away_win"))
    if measure=="1x2LogLoss":
        winner=next(m for m in ("home_win","draw","away_win") if observed[m])
        return -math.log(clip(predicted[winner]))
    return (predicted[measure]-observed[measure])**2

def paired_day_bootstrap(rows, candidate, baseline="V1 Poisson", iterations=1200):
    """Compare the same matches; resample whole fixture dates."""
    measures=("1x2MulticlassBrier","1x2LogLoss")+MARKETS
    output={}
    rng=random.Random(20261029)
    for metric in measures:
        days=defaultdict(lambda:[0.,0])
        for row in rows:
            difference=loss_value(row,candidate,metric)-loss_value(row,baseline,metric)
            days[row["date"]][0]+=difference
            days[row["date"]][1]+=1
        samples=[days[key] for key in sorted(days)]
        n=sum(count for total,count in samples)
        point=sum(total for total,count in samples)/n
        draws=[]
        for _ in range(iterations):
            selected=[samples[rng.randrange(len(samples))] for _ in samples]
            draws.append(sum(x[0] for x in selected)/sum(x[1] for x in selected))
        draws.sort()
        lower=draws[int(.025*iterations)]
        upper=draws[int(.975*iterations)]
        output[metric]={"differenceVsV1":round(point,6),
            "dayClusterBootstrap95":[round(lower,6),round(upper,6)],
            "clearImprovementInThisExploratoryInterval":upper<0,
            "interpretation":"Negative means lower forecast loss than V1."}
    return output


def under35_analysis(rows, model):
    """Outcome calibration and probability-first candidate cohorts; never infer bookmaker value."""
    observations=[(r["predictions"][model]["under35"],r["truth"]["under35"]) for r in rows]
    thresholds={}
    for threshold in UNDER35_THRESHOLDS:
        candidates=[(p,y) for p,y in observations if p>=threshold]
        results=score(candidates)
        thresholds[f"{threshold:.0%}"]={
            **results,
            "wins":sum(y for _,y in candidates),
            "losses":sum(1-y for _,y in candidates),
            "interpretation":"Model-qualified fixtures only, no verified odds or hypothetical P/L."
        }
    bands={}
    for low in range(0,100,10):
        high=(low+10)/100
        members=[(p,y) for p,y in observations if low/100<=p<high or (low==90 and p==1)]
        bands[f"{low}-{low+10}%"]={
            **score(members),
            "sufficientForInterpretation":len(members)>=MIN_CALIBRATION_BAND
        }
    return {
        "market":"under35",
        "outcomeDefinition":"Total full-time goals <= 3 (0, 1, 2 or 3 goals)",
        "overall":score(observations),
        "thresholds":thresholds,
        "calibrationBands":bands,
        "noBookmakerValueClaim":True
    }

def run(rows):
    # 2025/26 validation, 2026/27 untouched test. Pre-match histories only.
    rows=sorted(rows,key=lambda r:(r["date"],r["id"]))
    val=[];test=[]
    for r in rows:
        day=r["date"]
        if not ("2026-02-01"<=day<="2026-05-31" or "2026-08-01"<=day<="2026-10-28"):
            continue
        season="2526" if day<"2026-06-01" else "2627"
        if season=="2526":
            training=[dict(x,status=("current" if x["date"]>="2025-07-01" else "prior")) for x in rows if x["date"]<day and x["date"]>="2024-07-01"]
        else:
            training=[dict(x,status=("current" if x["date"]>="2026-07-01" else "prior")) for x in rows if x["date"]<day and x["date"]>="2025-07-01"]
        if len(training)<100:continue
        f={"division":r["division"],"homeKey":r["home"],"awayKey":r["away"],"date":day}
        predictions=variants(f,training)
        predictions["V0 league prior"]=league_climatology(training,r["division"])
        for label, pred in predictions.items():
            if set(pred)!=set(MARKETS):
                raise AssertionError("Missing or extra markets: "+label)
            if any(not math.isfinite(p) or not 0<=p<=1 for p in pred.values()):
                raise AssertionError("Invalid probability: "+label)
            if abs(sum(pred[m] for m in ("home_win","draw","away_win"))-1)>0.00005:
                raise AssertionError("1X2 outcomes not normalised: "+label)
            if pred["over35"] > pred["over25"]+0.000001:
                raise AssertionError("Inconsistent goals probabilities: "+label)
            for a,b in (("btts","no_btts"),("over25","under25"),("over35","under35")):
                if abs(pred[a]+pred[b]-1)>0.00005:
                    raise AssertionError("Complementary market probabilities not normalised: "+label)
        record={"date":day,"division":r["division"],"truth":truth(r),"predictions":predictions}
        (val if season=="2526" else test).append(record)
    if not val or not test:raise RuntimeError("Insufficient chronological validation/test fixtures")
    temps=fit_temperatures([(r["predictions"]["V1 Poisson"],r["truth"]) for r in val])
    for r in test:
        cal={m:temp(r["predictions"]["V1 Poisson"][m],temps[m]) for m in PRIMARY_MARKETS}
        z=sum(cal[m] for m in ("home_win","draw","away_win"))
        for m in ("home_win","draw","away_win"):cal[m]/=z
        r["predictions"]["V4 calibrated V1"]=add_complements(cal)
    # Score 1X2 as one 3-way outcome and binary markets individually.
    report={"validationPeriod":"2026-02-01 to 2026-05-31","testPeriod":"2026-08-01 to 2026-10-28",
            "validationFixtures":len(val),"testFixtures":len(test),"temperatureFromValidation":temps,
            "datasetSha256":hashlib.sha256(json.dumps(rows,sort_keys=True).encode("utf-8")).hexdigest(),
            "caution":"Exploratory predeclared variants; not independent model optimisation. No historical bookmaker ROI inferred.",
            "models":{},"byDivision":{},"pairedBootstrapVsV1":{},
            "under35Research":{},
            "methodNotes":["No odds used in fitting; no priced-bet ROI estimated.",
                "Multiple candidates compared on the same single holdout. Confidence intervals are exploratory, not proof of superiority.",
                "The 2026/27 test period was inspected on 29 October 2026; it must not be reused as a new untouched holdout for future tuning.",
                "The venue-strength variant reuses form features already in V1, so improvements do not establish a unique causal effect.",
                "Overdispersion uses a fixed shared-tempo mixture, not a fitted negative binomial.",
                "Calibration parameters are fitted on earlier 2025/26 validation fixtures only.",
                "Under 3.5 is exactly the complement of Over 3.5. Binary complement calibration and Brier scores are not independent evidence.",
                "Under 3.5 threshold cohorts are retrospective diagnostic slices, not selections with verified pre-match bookmaker odds."]}
    for name in test[0]["predictions"]:
        metrics={}
        for m in MARKETS:
            pairs=[(r["predictions"][name][m],r["truth"][m]) for r in test]
            metrics[m]=score(pairs)
        metrics["1x2MulticlassBrier"]=round(sum(sum((r["predictions"][name][m]-r["truth"][m])**2 for m in ("home_win","draw","away_win")) for r in test)/len(test),5)
        metrics["1x2LogLoss"]=round(-sum(math.log(clip(r["predictions"][name][next(m for m in ("home_win","draw","away_win") if r["truth"][m])])) for r in test)/len(test),5)
        metrics["1x2TopChoiceAccuracy"]=round(sum(
            r["truth"][max(("home_win","draw","away_win"),key=lambda m:r["predictions"][name][m])]
            for r in test)/len(test),5)
        report["models"][name]=metrics
        report["under35Research"][name]=under35_analysis(test,name)
        report["byDivision"][name]={}
        for div in refresh.DIVS:
            part=[r for r in test if r["division"]==div]
            if not part:continue
            report["byDivision"][name][div]={m:score([(r["predictions"][name][m],r["truth"][m]) for r in part])
                for m in MARKETS}
        if name!="V1 Poisson":
            report["pairedBootstrapVsV1"][name]=paired_day_bootstrap(test,name)
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
