/* Experiment tree opens collapsed, while visible rows remain sorted newest first. */
const fs=require("node:fs"),assert=require("node:assert/strict"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/experiments.js","utf8");
const html=fs.readFileSync("src/ui/html/experiments.html","utf8");
new vm.Script(js);
assert.match(js,/collapseInitialized:\s*false/);
assert.match(js,/if\(!state\.collapseInitialized && groups\.length\)/);
assert.match(js,/state\.collapsedGroups\.add\(user\.key\)/);
assert.match(js,/state\.collapsedGroups\.add\(campaign\.key\)/);
assert.match(js,/\.sort\(catalogRecentFirst\)/);
assert.match(js,/groups\.sort\(\(a,b\)=>groupRecent\(b\)-groupRecent\(a\)\)/);
assert.match(html,/js\/experiments\.js.*20261126tree1/);
const fn=js.match(/function catalogTimestamp\(value\)\s*\{[\s\S]*?\n\}/)?.[0];
assert.ok(fn);
const timestamp=vm.runInNewContext(fn+"\ncatalogTimestamp");
assert.ok(timestamp("2026-11-25T10:00:00Z")>timestamp("2026-11-24T10:00:00Z"));
console.log("Experiment tree collapsed-by-default and recency sorting checks passed.");
