"use strict";
/* Runtime tests of the functions actually embedded in the public board. */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length, 1, "Exactly one inline board script expected");
const source = scripts[0][1];

function functionFromSource(name) {
  const marker = "function " + name + "(";
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, "Missing function " + name);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}") {
      depth--;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error("Unclosed function " + name);
}

function constLine(name) {
  const line = source.split("\n").find(s => s.startsWith("const " + name + "="));
  assert.ok(line, "Missing const " + name);
  return line;
}
const functions = ["modelMarkets", "prob", "marketFromQuery"].map(functionFromSource).join("\n");
const code = functions + "\n" + ["isGoalsOrBtts", "marketThreshold"].map(constLine).join("\n");
const { modelMarkets, prob, marketFromQuery, marketThreshold, isGoalsOrBtts } =
  new Function(code + "\nreturn {modelMarkets,prob,marketFromQuery,marketThreshold,isGoalsOrBtts};")();

const intents = [
  ["Top 5 under 3.5", "under35"],
  ["best UNDER 3.5 goals selections", "under35"],
  ["top 3 unders 3.5 in league one", "under35"],
  ["best 3.5 unders", "under35"],
  ["five under 3,5", "under35"],
  ["top 5 under 2.5", "under25"],
  ["best unders 2.5", "under25"],
  ["best over 3.5 goals", "over35"],
  ["top 10 over 2.5", "over25"],
  ["top BTTS yes", "btts"],
  ["top BTTS no", "no_btts"],
  ["both teams do not score", "no_btts"],
  ["top 3 home wins", "home_win"],
  ["top 5 away wins", "away_win"],
];
for (const [question, expected] of intents) {
  assert.equal(marketFromQuery(question), expected, question);
}
assert.equal(marketFromQuery("top 3 over and under 3.5"), "under35");
assert.equal(marketFromQuery("top 5 scores"), null);

assert.ok(html.includes('<option value="under35">Under 3.5</option>'),
  "Under 3.5 must be available as a manually selectable model market");
assert.ok(html.includes('data-query="Top 5 under 3.5"'),
  "Under 3.5 should have a quick-search shortcut");
assert.ok(html.includes('id="qualified-only" checked'),
  "Confidence filter must be user-switchable");
assert.ok(html.includes('id="edge-confident" checked'),
  "Bookmaker odds filter must be user-switchable");
assert.ok(html.includes('state.qualifiedOnly'), "Question view needs qualifying filter");

const historical = JSON.parse(fs.readFileSync(
  path.join(root, "data", "snapshots", "2026-10-24.json"), "utf8"));
assert.ok(historical.games.length > 0);
const game = historical.games.find(g => Number.isFinite(g.scoreline?.markets?.over35));
assert.ok(game, "Need archived 3.5 goal forecast to test fallback");
assert.ok(!Object.hasOwn(game.scoreline.markets, "under35"),
  "Historical snapshot should remain unchanged for this test");
assert.ok(Math.abs(prob(game, "under35") - (1 - prob(game, "over35"))) < 1e-8);
assert.ok(modelMarkets(game).under35 > 0);
assert.ok(!Object.hasOwn(game.scoreline.markets, "under35"),
  "Renderer should not mutate immutable archived probabilities");

const future = {scoreline: {markets: {over35: 0.45, under35: 0.55,
  over25: 0.57, under25: 0.43, btts: 0.55, no_btts: 0.45}}};
assert.equal(prob(future, "under35"), 0.55);
for (const key of ["btts", "no_btts", "over25", "under25", "over35", "under35"]) {
  assert.ok(isGoalsOrBtts(key), key);
  assert.equal(marketThreshold(key), 0.55, key);
}
for (const key of ["home_win", "away_win", "draw"]) {
  assert.equal(marketThreshold(key), 0.60, key);
}
assert.ok(prob(future, "under35") >= marketThreshold("under35"));
assert.ok(prob(future, "btts") >= marketThreshold("btts"));
assert.ok(prob(future, "over25") >= marketThreshold("over25"));
assert.ok(prob(future, "over35") < marketThreshold("over35"));

console.log("PASS: " + intents.length + " query variants, archived Under 3.5 derivation, 55% market thresholds and UI controls.");
