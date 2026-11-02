#!/usr/bin/env python3
"""Two-source full-time score fallback for delayed primary CSV results.

This module ONLY produces candidate verified fixture scores for settlement.
It does not modify saved forecasts, bookmaker prices, or training records.
Require independent ESPN and Football Web Pages full-time scores to agree on
the exact date, competition, home club, away club, and score. Fail closed.
"""
import json
import re
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
ESPN_CODES = {"E0": "eng.1", "E1": "eng.2", "E2": "eng.3",
              "E3": "eng.4", "EC": "eng.5"}
MAX_LOOKBACK_DAYS = 7
MAX_RESULTS_PER_DAY = 120

# Provider-specific extra reviewed names; all other aliases use refresh.canon.
EXTRA_NAMES = {
    "peterborough united": "peterborough",
    "milton keynes dons": "milton keynes dons",
    "fc halifax": "fc halifax town",
    "halifax town": "fc halifax town",
    "forest green rovers": "forest green",
    "forest green": "forest green",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "bournemouth": "bournemouth",
    "accrington": "accrington stanley",
    "stockport county": "stockport county",
    "grimsby": "grimsby town",
    "bristol city": "bristol city",
    "bolton": "bolton",
    "cambridge united": "cambridge united",
    "leicester city": "leicester city",
    "harrogate town": "harrogate",
    "kidderminster harriers": "kidderminster",
    "aldershot town": "aldershot",
    "sutton united": "sutton",
    "solihull moors": "solihull",
    "boston united": "boston",
    "wigan athletic": "wigan",
    "wimbledon": "afc wimbledon",
    "afc hornchurch": "hornchurch",
}


def normalise_team(name, canonical):
    key = canonical(name)
    key = EXTRA_NAMES.get(key, key)
    return key


def verified_id(day, league, home, away, canonical):
    if league not in ESPN_CODES or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return None
    home = normalise_team(home, canonical)
    away = normalise_team(away, canonical)
    if not home or not away or home == away:
        return None
    return "|".join((day, league, home, away))


def valid_score(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 35 else None
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}", value.strip()):
        return None
    n = int(value.strip())
    return n if n <= 35 else None


def parse_espn(payload, league, day, canonical):
    """A completed league fixture needs two explicitly home/away teams."""
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("Missing ESPN events")
    games = {}
    for event in payload["events"]:
        if not isinstance(event, dict):
            continue
        kickoff = event.get("date")
        if not isinstance(kickoff, str):
            continue
        try:
            local_day = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(LONDON).date().isoformat()
        except ValueError:
            continue
        if local_day != day:
            continue
        comps = event.get("competitions")
        if not isinstance(comps, list) or len(comps) != 1:
            continue
        comp = comps[0]
        if not isinstance(comp, dict):
            continue
        status = comp.get("status") or event.get("status") or {}
        type_info = status.get("type", {}) if isinstance(status, dict) else {}
        if not isinstance(type_info, dict) or type_info.get("completed") is not True:
            continue
        competitors = comp.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            continue
        by_side = {c.get("homeAway"): c for c in competitors if isinstance(c, dict)}
        if len(by_side) != 2 or set(by_side) != {"home", "away"}:
            continue
        home, away = by_side["home"], by_side["away"]
        if not isinstance(home.get("team"), dict) or not isinstance(away.get("team"), dict):
            continue
        home_name = home["team"].get("displayName") or home["team"].get("name")
        away_name = away["team"].get("displayName") or away["team"].get("name")
        hg, ag = valid_score(home.get("score")), valid_score(away.get("score"))
        fid = verified_id(day, league, home_name, away_name, canonical)
        if fid is None or hg is None or ag is None:
            continue
        score = (hg, ag)
        if fid in games and games[fid] != score:
            raise ValueError("Conflicting scores in ESPN result source for " + fid)
        games[fid] = score
    if len(games) > MAX_RESULTS_PER_DAY:
        raise ValueError("Unreasonable ESPN full-time result count")
    return games


def league_from_heading(heading):
    heading = re.sub(r"\s+", " ", heading).strip().lower()
    if "national league" in heading and not any(x in heading for x in ("north", "south")):
        return "EC"
    if "premier league" in heading and "women" not in heading:
        return "E0"
    if "championship" in heading and not any(x in heading for x in ("scottish", "women")):
        return "E1"
    if "league one" in heading and "women" not in heading:
        return "E2"
    if "league two" in heading and "women" not in heading:
        return "E3"
    return None


class FootballWebPagesParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading_tag = None
        self.heading = []
        self.league = None
        self.current_row = None
        self.cell_tag = None
        self.cell_depth = 0
        self.cell_parts = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self.heading_tag is None:
            self.heading_tag = tag
            self.heading = []
        if tag == "tr" and self.current_row is None:
            self.current_row = []
        if tag in ("td", "th") and self.current_row is not None and self.cell_tag is None:
            self.cell_tag = tag
            self.cell_parts = []

    def handle_data(self, data):
        if self.heading_tag:
            self.heading.append(data)
        if self.cell_tag:
            self.cell_parts.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading_tag:
            heading = " ".join(" ".join(self.heading).split())
            identified = league_from_heading(heading)
            # A new league / competition heading ends the old section.
            if identified is not None:
                self.league = identified
            elif any(x in heading.lower() for x in ("league", "premiership", "championship", "fa cup", "scottish")):
                self.league = None
            self.heading_tag = None
            self.heading = []
        if tag == self.cell_tag:
            self.current_row.append(" ".join(" ".join(self.cell_parts).split()))
            self.cell_tag = None
            self.cell_parts = []
        if tag == "tr" and self.current_row is not None:
            self.rows.append((self.league, self.current_row))
            self.current_row = None


def parse_footballwebpages(page, day, canonical):
    """Only rows explicitly labelled FT with four outcome fields are accepted."""
    if not isinstance(page, str) or not page.strip():
        raise ValueError("Empty Football Web Pages response")
    parser = FootballWebPagesParser()
    parser.feed(page)
    games = {}
    for league, cells in parser.rows:
        if league is None:
            continue
        # Expected: FT | Home Club | 2 | 1 | Away Club
        starts = [i for i, cell in enumerate(cells) if cell.upper() in ("FT", "FULL TIME", "FULL-TIME")]
        for i in starts:
            if len(cells) < i + 5:
                continue
            home, hg_raw, ag_raw, away = cells[i+1:i+5]
            hg, ag = valid_score(hg_raw), valid_score(ag_raw)
            fid = verified_id(day, league, home, away, canonical)
            if fid is None or hg is None or ag is None:
                continue
            score = (hg, ag)
            if fid in games and games[fid] != score:
                raise ValueError("Conflicting scores in Football Web Pages for " + fid)
            games[fid] = score
    if len(games) > MAX_RESULTS_PER_DAY:
        raise ValueError("Unreasonable Football Web Pages full-time result count")
    return games


def public_get(url, timeout=12, size=3_500_000):
    # No credentials; strictly fixed hostnames and HTTPS.
    if not (url.startswith("https://site.api.espn.com/apis/site/v2/sports/soccer/")
            or url.startswith("https://www.footballwebpages.co.uk/")):
        raise ValueError("Results fallback URL is not on the approved domain")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FootballPredictionBoard/1.2)",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.7",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("Unexpected results HTTP status")
        return response.read(size + 1).decode("utf-8", errors="replace")


def reconcile(primary, candidates, existing):
    """Conflicting primary or previously settled scores are fatal, not overridden."""
    merged = dict(primary)
    accepted = {}
    for fid, item in sorted(candidates.items()):
        score = item["score"]
        if fid in primary:
            if tuple(primary[fid]) != tuple(score):
                raise ValueError("Fallback conflicts with primary CSV: " + fid)
            continue
        prior = existing.get(fid)
        if prior and prior.get("score") != "%d-%d" % tuple(score):
            raise ValueError("Fallback conflicts with previously settled result: " + fid)
        merged[fid] = tuple(score)
        accepted[fid] = item
    return merged, accepted


def get_confirmed_fallback(needed_fixtures, primary, existing, current_day,
                           canonical, fetcher=public_get, max_lookback=MAX_LOOKBACK_DAYS):
    """Return score candidates corroborated by BOTH independent public sources.

    Missing/ambiguous/conflicting matches remain pending. No future/current day
    matches are requested. All source errors are disclosed in diagnostics.
    """
    dates = defaultdict(set)
    for fixture in needed_fixtures:
        if not isinstance(fixture, dict):
            continue
        fid = fixture.get("id")
        league = fixture.get("division")
        day = fixture.get("date")
        if not isinstance(fid, str) or league not in ESPN_CODES or not isinstance(day, str):
            continue
        try:
            age = (current_day - datetime.strptime(day, "%Y-%m-%d").date()).days
        except ValueError:
            continue
        if 1 <= age <= max_lookback and fid not in primary and fid not in existing:
            dates[day].add((league, fid))
    diagnostics = {"attemptedDates": sorted(dates), "fullyConfirmed": 0,
                   "unconfirmed": 0, "conflicts": [], "sourceErrors": [],
                   "sourceUrls": [], "sources": ["ESPN full-time scoreboard", "Football Web Pages full-time results"]}
    if not dates:
        return {}, diagnostics
    queries = {}
    for day, fixtures in dates.items():
        stamp = day.replace("-", "")
        webpage = "https://www.footballwebpages.co.uk/" + stamp
        queries[("web", day, None)] = webpage
        for league in sorted({x[0] for x in fixtures}):
            code = ESPN_CODES[league]
            queries[("espn", day, league)] = (
                "https://site.api.espn.com/apis/site/v2/sports/soccer/"
                + code + "/scoreboard?dates=" + stamp + "&limit=100")
    responses = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetcher, url): (key, url) for key, url in queries.items()}
        for future in as_completed(futures):
            key, url = futures[future]
            try:
                responses[key] = future.result()
            except Exception as exc:
                diagnostics["sourceErrors"].append({
                    "date": key[1], "source": key[0], "league": key[2],
                    "errorType": type(exc).__name__,
                })
    diagnostics["sourceUrls"] = sorted(url for key, url in queries.items() if key in responses)
    matched = {}
    for day, expected in sorted(dates.items()):
        web_url = queries[("web", day, None)]
        try:
            web = (parse_footballwebpages(responses[("web", day, None)], day, canonical)
                   if ("web", day, None) in responses else {})
        except (ValueError, TypeError):
            web = {}
            diagnostics["sourceErrors"].append({"date": day, "source": "web", "errorType": "ParseError"})
        for league, fid in sorted(expected):
            key = ("espn", day, league)
            espn = {}
            if key in responses:
                try:
                    espn = parse_espn(json.loads(responses[key]), league, day, canonical)
                except (ValueError, TypeError, json.JSONDecodeError):
                    diagnostics["sourceErrors"].append({
                        "date": day, "source": "espn", "league": league, "errorType": "ParseError"
                    })
            if fid not in web or fid not in espn:
                diagnostics["unconfirmed"] += 1
                continue
            if web[fid] != espn[fid]:
                diagnostics["conflicts"].append({
                    "fixtureId": fid, "espnScore": "%d-%d" % espn[fid],
                    "webScore": "%d-%d" % web[fid],
                })
                diagnostics["unconfirmed"] += 1
                continue
            matched[fid] = {
                "score": espn[fid],
                "sources": [
                    queries[key], web_url,
                ],
                "verification": "Two independent full-time sources agreed",
                "verifiedAtUtc": datetime.now(LONDON).isoformat(),
            }
    diagnostics["fullyConfirmed"] = len(matched)
    return matched, diagnostics
