"use strict";
// Check local links in the current documentation. Ignore external URLs and anchors.
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const files=["README.md","src/docs/README.md","src/docs/SYSTEM_ARCHITECTURE.md","src/docs/EXPERIMENTS_STAGES_MEASUREMENTS.md","src/docs/CELLS_SENSORS_HIFIE.md","src/docs/SERVER_INTEGRATION.md","src/docs/HTTP_API_REFERENCE.md","src/docs/TROUBLESHOOTING.md"];
let count=0;
for(const file of files){
  const source=fs.readFileSync(file,"utf8");
  for(const match of source.matchAll(/\]\(([^)]+)\)/g)){
    let url=match[1].trim().split(/\s+["']/)[0];
    if(/^(https?:|mailto:|#|data:)/.test(url))continue;
    url=decodeURIComponent(url.split("#")[0]);
    if(!url)continue;
    const resolved=path.resolve(path.dirname(file),url);
    assert(fs.existsSync(resolved),`Broken documentation link: ${file} -> ${url}`);
    count++;
  }
}
console.log(`Verified ${count} internal documentation links across ${files.length} documents.`);
