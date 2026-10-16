#!/usr/bin/env python3
"""Standalone English football scoreline forecaster.
Data: Football-Data.co.uk fixtures/results, never bookmaker odds.
B3.1 is NOT approximated here: use its preserved external frozen snapshots.
"""
import csv, io, json, math, hashlib, os, re, sys, time, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SNAP = DATA / "snapshots"
TZ = ZoneInfo("Europe/London")
DIVS = {"E0":"Premier League","E1":"Championship","E2":"League One","E3":"League Two","EC":"National League"}
ALIASES = {
    "bolton wanderers":"bolton","burton albion":"burton","crewe alexandra":"crewe",
    "oldham athletic":"oldham","mk dons":"milton keynes dons","peterboro":"peterborough",
    "bristol rvs":"bristol rovers","sheffield weds":"sheffield wednesday",
    "sheffield utd":"sheffield united","stockport":"stockport county",
    "cambridge":"cambridge united","wimbledon":"afc wimbledon",
    "luton":"luton town","ipswich":"ipswich town","newport":"newport county",
    "northampton":"northampton town","grimsby":"grimsby town",
    "huddersfield":"huddersfield town","plymouth":"plymouth argyle",
    "salford":"salford city","millwall":"millwall",
    "blackburn":"blackburn rovers","west brom":"west bromwich albion",
    "man city":"manchester city","man united":"manchester united",
    "qpr":"queens park rangers","notts co":"notts county",
    "tranmere":"tranmere rovers","colchester":"colchester united",
    "southend":"southend united","hartlepool":"hartlepool united",
    "boreham wood":"boreham wood","halifax":"fc halifax town",
    "chesterfield":"chesterfield","gillingham":"gillingham",
    "cheltenham":"cheltenham town","shrewsbury":"shrewsbury town",
    "accrington":"accrington stanley","crawley":"crawley town",
    "fleetwood":"fleetwood town","rotherham":"rotherham united",
    "brighton":"brighton and hove albion","wolves":"wolverhampton wanderers","newport county afc":"newport county"
}
def canon(value):
    s = re.sub(r"\s+"," ", re.sub(r"[^\w\s]", " ",str(value or "").lower())).strip()
    return ALIASES.get(s,s)
def dt(value):
    v=str(value or "").strip().split()[0]
    for fmt in ("%d/%m/%Y","%d/%m/%y","%Y-%m-%d","%d-%m-%Y"):
        try:return datetime.strptime(v,fmt).date()
        except ValueError:continue
    return None
def fetch_csv(url, timeout=22):
    error=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"FootballPredictor/1.0 (public-data research; contact via GitHub)","Accept":"text/csv,*/*"})
            with urllib.request.urlopen(req,timeout=timeout) as f:
                raw=f.read(8_000_000)
                typ=f.headers.get("Content-Type","")
            decoded=raw.decode("utf-8-sig",errors="replace")
            if "<html" in decoded[:500].lower() or "Date" not in decoded[:600]:
                raise ValueError("CSV source returned unexpected content")
            return list(csv.DictReader(io.StringIO(decoded))),url
        except Exception as exc:
            error=exc
            if attempt<2:time.sleep(2*(attempt+1))
    raise RuntimeError("%s: %s"%(url,error))
def fetch_one(urls):
    errors=[]
    for url in urls:
        try:return fetch_csv(url)
        except Exception as exc:errors.append(str(exc))
    raise RuntimeError("; ".join(errors))
def result_rows(rows, division, status):
    clean=[]
    for row in rows:
        day=dt(row.get("Date"))
        home=canon(row.get("HomeTeam")); away=canon(row.get("AwayTeam"))
        if not day or not home or not away:continue
        try:h=int(row["FTHG"]);a=int(row["FTAG"])
        except (ValueError,KeyError,TypeError):continue
        if h<0 or a<0:continue
        clean.append({"id":"%s|%s|%s|%s"%(day,division,home,away),
            "date":str(day),"division":division,"home":home,"away":away,
            "hg":h,"ag":a,"status":status})
    return clean
def unique_results(rows):
    d={}
    for r in rows:
        key=r["id"]
        if key in d and (r["hg"],r["ag"])!=(d[key]["hg"],d[key]["ag"]):
            raise ValueError("Conflicting scores for "+key)
        if key not in d or (d[key]["status"]=="prior" and r["status"]=="current"):
            d[key]=r
    return list(d.values())
def fixture_rows(rows):
    out={}
    for row in rows:
        div=row.get("Div") or row.get("div")
        if div not in DIVS:continue
        day=dt(row.get("Date"))
        home=canon(row.get("HomeTeam"));away=canon(row.get("AwayTeam"))
        if not day or not home or not away:continue
        label=lambda s:re.sub(r"\s+"," ",str(s or "").strip())
        match={"id":"%s|%s|%s|%s"%(day,div,home,away),"date":str(day),
            "league":DIVS[div],"division":div,
            "home":label(row.get("HomeTeam")),"away":label(row.get("AwayTeam")),
            "homeKey":home,"awayKey":away,"kickoff":row.get("Time") or "TBC"}
        out[match["id"]]=match
    return list(out.values())
def smooth_average(matches, side, scored, league_average):
    # Exponential recent-form weighting, prior-season matches down-weighted.
    matches=sorted(matches,key=lambda x:x["date"],reverse=True)[:20]
    num=0.0;den=0.0
    for i,m in enumerate(matches):
        w=(0.88**i)*(0.35 if m["status"]=="prior" else 1.0)
        if side=="home": val=m["hg"] if scored else m["ag"]
        else: val=m["ag"] if scored else m["hg"]
        num+=w*val;den+=w
    strength=(num+6.0*league_average)/(den+6.0)
    return strength,den
def dist(lamb):
    p=[math.exp(-lamb)]
    for i in range(1,12):p.append(p[-1]*lamb/i)
    return p
def model(f,train):
    div=f["division"];home=f["homeKey"];away=f["awayKey"];now=f["date"]
    relevant=[x for x in train if x["division"]==div and x["date"]<now]
    current=[x for x in relevant if x["status"]=="current"]
    # True league means from results available before fixture; never match result itself.
    source=current if len(current)>=24 else relevant
    hmean=sum(x["hg"] for x in source)/len(source) if source else 1.48
    amean=sum(x["ag"] for x in source)/len(source) if source else 1.22
    hmean=max(0.6,min(2.5,hmean));amean=max(0.5,min(2.3,amean))
    hm=[x for x in relevant if x["home"]==home]
    aw=[x for x in relevant if x["away"]==away]
    hfor,hn=smooth_average(hm,"home",True,hmean)
    hcon,_=smooth_average(hm,"home",False,amean)
    afor,an=smooth_average(aw,"away",True,amean)
    acon,_=smooth_average(aw,"away",False,hmean)
    lh=hmean*(max(.25,hfor/hmean)*max(.25,acon/hmean))**0.55
    la=amean*(max(.25,afor/amean)*max(.25,hcon/amean))**0.55
    lh=max(.25,min(3.7,lh));la=max(.25,min(3.7,la))
    ph=dist(lh);pa=dist(la)
    mass=sum(ph)*sum(pa)
    b={"0-1":0.,"2":0.,"3":0.,"4+":0.}
    m={k:0. for k in ["home_win","draw","away_win","btts","no_btts","over25","under25","over35"]}
    top=[]
    for i,p in enumerate(ph):
        for j,q in enumerate(pa):
            v=p*q/mass
            t=i+j
            b["0-1" if t<=1 else ("2" if t==2 else ("3" if t==3 else "4+"))]+=v
            m["home_win" if i>j else ("away_win" if j>i else "draw")]+=v
            m["btts" if i and j else "no_btts"]+=v
            m["over25" if t>=3 else "under25"]+=v
            if t>=4:m["over35"]+=v
            top.append((v,i,j))
    top.sort(reverse=True)
    assert abs(sum(b.values())-1)<1e-8
    assert abs(m["over25"]+m["under25"]-1)<1e-8
    assert abs(m["home_win"]+m["draw"]+m["away_win"]-1)<1e-8
    markets={k:round(v,5) for k,v in m.items()}
    result=dict(f)
    result["scoreline"]={"expectedHome":round(lh,3),"expectedAway":round(la,3),
        "expectedTotal":round(lh+la,3),
        "modalScore":"%s-%s"%(top[0][1],top[0][2]),"modalProbability":round(top[0][0],5),
        "topScores":[{"score":"%s-%s"%(i,j),"p":round(v,5)} for v,i,j in top[:5]],
        "goalBands":{k:round(v,5) for k,v in b.items()},
        "markets":markets,
        "cleanSheetRisk":round(max(math.exp(-lh),math.exp(-la)),5),
        "sampleHome":sum(x["status"]=="current" for x in hm),
        "sampleAway":sum(x["status"]=="current" for x in aw),
        "model":"INDEPENDENT_SCORELINE_V1_GITHUB",
        "calibrated":False}
    result["b31"]={"status":"not-calculated","qualifiers":[]}
    return result
def settle(f,score):
    h,a=score
    return {"home_win":h>a,"away_win":a>h,"draw":h==a,"btts":h>0 and a>0,
        "no_btts":h==0 or a==0,"over25":h+a>=3,
        "under25":h+a<3,"over35":h+a>=4}
def atomic_write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    t=path.with_suffix(path.suffix+".tmp")
    t.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    t.replace(path)
def run():
    DATA.mkdir(parents=True,exist_ok=True);SNAP.mkdir(exist_ok=True)
    now=datetime.now(TZ);today=now.date();state={"refreshed":now.isoformat(),"sources":[],"warnings":[]}
    history=[]
    failures=[]
    for season,status in [("2526","prior"),("2627","current")]:
        for div in DIVS:
            try:
                rows,url=fetch_one(["https://www.football-data.co.uk/mmz4281/%s/%s.csv"%(season,div)])
                history.extend(result_rows(rows,div,status));state["sources"].append(url)
            except Exception as exc:failures.append("%s/%s: %s"%(season,div,exc))
    history=unique_results(history)
    if failures:raise RuntimeError("Fail closed: missing required league CSV: "+"; ".join(failures))
    curr=[x for x in history if x["status"]=="current"]
    if len(curr)<150:raise RuntimeError("Fail closed: incomplete current-season training results (%s): %s"%(len(curr),failures))
    fixture_data,fixture_url=fetch_one(["https://www.football-data.co.uk/fixtures.csv","https://www.football-data.co.uk/matches/fixtures.csv"])
    fixtures=fixture_rows(fixture_data);state["sources"].append(fixture_url)
    state["warnings"]=failures
    state["resultsCount"]=len(curr)
    state["resultsByLeague"]={d:sum(x["division"]==d for x in curr) for d in DIVS}
    state["fixtureDateRange"]=[min((x["date"] for x in fixtures),default=None),max((x["date"] for x in fixtures),default=None)]
    completed={x["id"]:(x["hg"],x["ag"]) for x in curr}
    # Freeze before kickoff; an old snapshot is immutable even after a model revision.
    today_str=today.isoformat();today_file=SNAP/(today_str+".json")
    if not today_file.exists():
        todays=[f for f in fixtures if f["date"]==today_str]
        ready=[]
        for f in todays:
            try:
                kickoff=datetime.strptime(f["kickoff"][:5],"%H:%M").time()
                kickoff_at=datetime.combine(today,kickoff,tzinfo=TZ)
                if kickoff_at<=now:continue # Never issue hindsight predictions.
            except ValueError:pass
            if f["id"] not in completed:ready.append(model(f,history))
        snapshot={"date":today_str,"capturedAt":now.isoformat(),"model":"INDEPENDENT_SCORELINE_V1_GITHUB",
                  "games":ready,"status":"frozen-prekickoff" if ready else "no-prekickoff-fixtures",
                  "fixtureSource":fixture_url,"trainingCurrentCount":len(curr),
                  "b31Available":False}
        if ready:atomic_write(today_file,snapshot)
    # Snapshot results may be added later to a separate mutable settlement file.
    settlements_path=DATA/"settlements.json"
    settled=json.loads(settlements_path.read_text(encoding="utf-8")) if settlements_path.exists() else {}
    summary=[]
    by_market=defaultdict(lambda:{"total":0,"wins":0,"brier":0.})
    b31_market=defaultdict(lambda:{"total":0,"wins":0})
    by_div=defaultdict(lambda:{"total":0,"wins":0})
    for p in sorted(SNAP.glob("????-??-??.json")):
        try:shot=json.loads(p.read_text(encoding="utf-8"))
        except (ValueError,OSError):continue
        bridge_file=DATA/"b31-snapshots"/(str(shot.get("date"))+".json")
        b31_overlay={}
        if bridge_file.exists():
            overlay=json.loads(bridge_file.read_text(encoding="utf-8"))
            if overlay.get("date")!=shot.get("date") or overlay.get("status")!="frozen-prekickoff":
                raise ValueError("Invalid B3.1 overlay date/status: "+str(bridge_file))
            for item in overlay.get("fixtures",[]):
                if item.get("id") and isinstance(item.get("qualifiers"),list):
                    b31_overlay[item["id"]]=item["qualifiers"]
        daily={"date":shot.get("date"),"games":len(shot.get("games",[])),"settled":0,"wins":0,"markets":0}
        for f in shot.get("games",[]):
            r=completed.get(f["id"])
            prior_settlement=settled.get(f["id"])
            if prior_settlement:
                original=tuple(int(x) for x in prior_settlement["score"].split("-"))
                if r and r!=original:raise ValueError("Conflicting revised final score for "+f["id"])
                r=r or original
            if not r:continue
            truth=settle(f,r)
            preds=f.get("scoreline",{}).get("markets",{})
            daily["settled"]+=1
            b31_results=[]
            names={"BTTS":"btts","No BTTS":"no_btts","Over 2.5":"over25","Under 2.5":"under25","Over 3.5":"over35","Home Win":"home_win","Away Win":"away_win","Draw":"draw"}
            for q in b31_overlay.get(f["id"],f.get("b31",{}).get("qualifiers",[])):
                market=names.get(q.get("key") or q.get("name"))
                if not market:continue
                win=bool(truth[market]);b31_results.append({"market":market,"score":q.get("score"),"likelihood":q.get("likelihood"),"confidence":q.get("confidence"),"outcome":"Win" if win else "Loss"})
                b31_market[market]["total"]+=1;b31_market[market]["wins"]+=int(win)
            settled[f["id"]]={"date":f["date"],"division":f["division"],"home":f["home"],"away":f["away"],"score":"%d-%d"%r,
                "outcomes":truth,"probs":preds,"model":shot.get("model"),"b31Outcomes":b31_results}
            for k,prob in preds.items():
                by_market[k]["total"]+=1;by_market[k]["wins"]+=int(truth[k])
                by_market[k]["brier"]+=(prob-int(truth[k]))**2
                daily["markets"]+=1;daily["wins"]+=int(truth[k])
            # A match result is counted once for each market in its own market report.
            by_div[f["division"]]["total"]+=1
        summary.append(daily)
    market_perf={k:{"predictions":v["total"],"hits":v["wins"],
        "hitRate":round(v["wins"]/v["total"],4) if v["total"] else None,
        "brier":round(v["brier"]/v["total"],4) if v["total"] else None}
        for k,v in by_market.items()}
    latest=json.loads(today_file.read_text(encoding="utf-8")) if today_file.exists() else {
        "date":today_str,"capturedAt":now.isoformat(),"games":[],"status":"no-frozen-matches",
        "model":"INDEPENDENT_SCORELINE_V1_GITHUB","b31Available":False}
    # Do not silently show yesterday's games as today's games.
    atomic_write(DATA/"latest.json",latest)
    atomic_write(DATA/"settlements.json",settled)
    atomic_write(DATA/"history.json",summary)
    b31_perf={k:{"selections":v["total"],"wins":v["wins"],"hitRate":round(v["wins"]/v["total"],4) if v["total"] else None} for k,v in b31_market.items()}
    atomic_write(DATA/"performance.json",{"updated":now.isoformat(),"markets":market_perf,"b31FrozenMarkets":b31_perf,
        "byDivision":dict(by_div),"totalSnapshots":len(summary),"totalSettledGames":len(settled),
        "model":"INDEPENDENT_SCORELINE_V1_GITHUB","b31Note":"B3.1 records include only dated imported/frozen qualifiers; do not mix with independent model totals."})
    atomic_write(DATA/"status.json",state)
    print("Frozen daily games:",len(latest["games"]),"historical settlements:",len(settled),"results:",len(curr))
if __name__=="__main__":
    run()
