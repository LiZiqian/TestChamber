const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..", "..");
const frontendRoot = path.join(root, "frontend");
const backendRoot = path.join(root, "backend");

function walk(dir) {
  const result = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...walk(full));
    else if (entry.isFile() && entry.name.endsWith(".js")) result.push(full);
  }
  return result;
}

function walkExt(dir, extension) {
  const result = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...walkExt(full, extension));
    else if (entry.isFile() && entry.name.endsWith(extension)) result.push(full);
  }
  return result;
}

function walkExts(dir, extensions) {
  const result = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...walkExts(full, extensions));
    else if (entry.isFile() && extensions.some(extension => entry.name.endsWith(extension))) result.push(full);
  }
  return result;
}

const jsFiles = walk(path.join(frontendRoot, "js"));
const cssFiles = walkExt(path.join(frontendRoot, "css"), ".css");
const rel = file => path.relative(frontendRoot, file).replace(/\\/g, "/");
const versionText = fs.readFileSync(path.join(root, "VERSION"), "utf8").trim();
assert.ok(/^[1-9]\d*\.\d+\.\d+$/.test(versionText), "VERSION must contain a semantic version like 7.2.0");

for (const file of jsFiles) {
  const text = fs.readFileSync(file, "utf8");
  assert.ok(!/Object\.assign\s*\(\s*app\s*,/.test(text), `${rel(file)} must use app.registerModule() instead of Object.assign(app, ...)`);
  assert.ok(!/\binsertAdjacentHTML\b/.test(text), `${rel(file)} must not use insertAdjacentHTML; use DOM helpers or bounded templates instead`);
  assert.ok(!/\.\s*on[a-z]+\s*=/.test(text), `${rel(file)} must use addEventListener() or delegated data-app-action handlers instead of .on* event properties`);
}

const directInnerHtmlFiles = jsFiles
  .filter(file => /\binnerHTML\b/.test(fs.readFileSync(file, "utf8")))
  .map(rel)
  .sort();
assert.deepEqual(
  directInnerHtmlFiles,
  ["js/app.core.js"],
  "direct innerHTML access must stay centralized in app.core.js replaceHtml()"
);

const appCore = fs.readFileSync(path.join(frontendRoot, "js/app.core.js"), "utf8");
assert.ok(/registerModule\s*\(\s*name\s*,\s*members\s*\)/.test(appCore), "app.core.js must expose registerModule(name, members)");
assert.ok(/handleDelegatedAction\s*\(/.test(appCore), "app.core.js must expose delegated data-app-action handling");
assert.ok(/replaceHtml\s*\(\s*target\s*,\s*html/.test(appCore), "app.core.js must expose replaceHtml(target, html)");
const indexHtml = fs.readFileSync(path.join(frontendRoot, "index.html"), "utf8");
assert.ok(!/\son[a-z]+\s*=/i.test(indexHtml), "index.html must use delegated data-app-action handlers instead of inline on* attributes");
assert.ok(indexHtml.includes('name="testchamber-version" content="__APP_VERSION__"'), "index.html must expose the server-injected app version meta tag");
assert.ok(!/\?v=[1-9]\d*\.\d+\.\d+/.test(indexHtml), "index.html must use __APP_VERSION__ cachebusters instead of hardcoded version values");

const styleCss = fs.readFileSync(path.join(frontendRoot, "css", "style.css"), "utf8");
assert.ok(styleCss.includes("__APP_VERSION__"), "style.css must use __APP_VERSION__ for versioned CSS imports");
assert.ok(!/\?v=[1-9]\d*\.\d+\.\d+/.test(styleCss), "style.css must not hardcode versioned CSS imports");

const productionVersionFiles = [
  ...walkExts(backendRoot, [".py"]),
  ...walkExts(frontendRoot, [".js", ".css", ".html"]),
];
const hardcodedVersionPattern = /["'`]v?[1-9]\d*\.\d+\.\d+["'`]|[?&]v=[1-9]\d*\.\d+\.\d+|version-v[1-9]\d*\.\d+\.\d+/;
for (const file of productionVersionFiles) {
  const text = fs.readFileSync(file, "utf8");
  assert.ok(!hardcodedVersionPattern.test(text), `${path.relative(root, file).replace(/\\/g, "/")} must read version from VERSION or __APP_VERSION__`);
}

const legacyStatusSelector = /\.s-(?:已借出|异常完成|Pass|Fail|OK|已分配|进入测试任务|Testing|已归还|待维修|报废|变更退出|未设置)\b/;
for (const file of cssFiles) {
  const text = fs.readFileSync(file, "utf8");
  assert.ok(!legacyStatusSelector.test(text), `${rel(file)} must not define legacy status CSS selectors`);
}

const legacyStatusWrite = /\b(?:status|flowStatus|progressStatus|latestResult|result|completionType|fault|problemState)\s*[:=]\s*["'](?:待启动|待执行|Testing|Pass|Fail|OK|异常完成|完成|已完成|已分配|进入测试任务|已借出|借出|已归还|待维修|报废|变更退出|未设置)["']/;
for (const file of jsFiles) {
  const text = fs.readFileSync(file, "utf8");
  assert.ok(!legacyStatusWrite.test(text), `${rel(file)} must write canonical status values instead of legacy aliases`);
  assert.ok(!/已退出测试/.test(text), `${rel(file)} must display 退出测试 instead of 已退出测试`);
}

const delegatedShellFiles = [
  "js/app.logs.js",
  "js/app.render.js",
  "js/projects.js",
  "js/samples/01-pool.js",
  "js/samples/03-detail-fields.js",
  "js/samples/04-photos.js",
  "js/samples/05-problems.js",
  "js/samples/06-history.js",
  "js/samples/07-detail.js",
  "js/workspace/02-home.js",
  "js/workspace/03-strategy.js",
  "js/workspace/04-stage.js",
  "js/workspace/05-task-table.js",
  "js/workspace/06-sample-picker.js",
  "js/workspace/07-task-config.js",
  "js/workspace/08-task-actions.js",
  "js/workspace/09-task-result.js",
  "js/workspace/10-dropdown-issue.js",
];
for (const relativePath of delegatedShellFiles) {
  const text = fs.readFileSync(path.join(frontendRoot, relativePath), "utf8");
  assert.ok(!/\son[a-z]+\s*=/i.test(text), `${relativePath} shell UI must use delegated data-app-action handlers`);
}

const stateRefFiles = jsFiles
  .filter(file => fs.readFileSync(file, "utf8").includes("/api/state"))
  .map(rel)
  .sort();
assert.deepEqual(stateRefFiles, ["js/app.server.js"], "/api/state references must stay centralized in app.server.js");

const fullStateLoadCallFiles = jsFiles
  .filter(file => /\bensureFullStateLoaded\s*\(/.test(fs.readFileSync(file, "utf8")))
  .map(rel)
  .sort();
assert.deepEqual(
  fullStateLoadCallFiles,
  [],
  "frontend modules must use targeted detail APIs instead of ensureFullStateLoaded()"
);

const fullStateSaveCallFiles = jsFiles
  .filter(file => /\b(?:this|app)\.(?:save|scheduleSave)\s*\(/.test(fs.readFileSync(file, "utf8")))
  .map(rel)
  .sort();
assert.deepEqual(
  fullStateSaveCallFiles,
  ["js/app.server.js"],
  "business modules must use granular mutation APIs instead of app.save()/scheduleSave() full-state writes"
);

const appServer = fs.readFileSync(path.join(frontendRoot, "js/app.server.js"), "utf8");
assert.ok(/fullStateUrl\s*\(\s*reason/.test(appServer), "app.server.js must require a reason when constructing /api/state URLs");
assert.ok(/fetch\s*\(\s*this\.fullStateUrl\s*\(\s*reason\s*\)/.test(appServer), "reloadFromServer() must fetch /api/state through fullStateUrl(reason)");

const projectModule = fs.readFileSync(path.join(frontendRoot, "js/projects.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(projectModule), "projects.js must use project state accessors instead of direct app.data/app.view access");
assert.ok(!/\b(?:innerHTML|insertAdjacentHTML)\b/.test(projectModule), "projects.js list shell must be rendered with DOM APIs instead of HTML string injection");
const appRenderModule = fs.readFileSync(path.join(frontendRoot, "js/app.render.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(appRenderModule), "app.render.js must use state accessors instead of direct app.data/app.view access");
assert.ok(!/\b(?:innerHTML|insertAdjacentHTML)\b/.test(appRenderModule), "app.render.js shell UI must be rendered with DOM APIs instead of HTML string injection");
const appFiltersModule = fs.readFileSync(path.join(frontendRoot, "js/app.filters.js"), "utf8");
assert.ok(!/\b(?:this|app)\.view\b/.test(appFiltersModule), "app.filters.js must use view map accessors instead of direct app.view access");
const auditConsistencyModule = fs.readFileSync(path.join(frontendRoot, "js/debug/auditConsistency.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(auditConsistencyModule), "debug audit must read a dataSnapshot() instead of direct app.data access");
assert.ok(/\bdataSnapshot\s*\(\s*\)/.test(auditConsistencyModule), "debug audit must read through dataSnapshot()");
const appLogsModule = fs.readFileSync(path.join(frontendRoot, "js/app.logs.js"), "utf8");
assert.ok(/\btaskLogListNode\s*\(/.test(appLogsModule), "task log modal list shell must be rendered through DOM nodes");
assert.ok(!/\btaskLogHtml\b/.test(appLogsModule), "task log modal list items must not regress to HTML string builders");
const sampleDetailFieldsModule = fs.readFileSync(path.join(frontendRoot, "js/samples/03-detail-fields.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(sampleDetailFieldsModule), "sample detail field helpers must use state accessors instead of direct app.data access");
assert.ok(/\bprojectRecords\s*\(\s*\)/.test(sampleDetailFieldsModule), "sample detail field helpers must read project locations through projectRecords()");
assert.ok(/\bsampleCategoryRecords\s*\(\s*\)/.test(sampleDetailFieldsModule), "sample detail field helpers must read reassembly sources through sampleCategoryRecords()");
const sampleProblemsModule = fs.readFileSync(path.join(frontendRoot, "js/samples/05-problems.js"), "utf8");
assert.ok(!/\binnerHTML\b/.test(sampleProblemsModule), "sample problem row append must use DOM nodes instead of template.innerHTML");
const sampleHistoryModule = fs.readFileSync(path.join(frontendRoot, "js/samples/06-history.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(sampleHistoryModule), "sample history must use state accessors instead of direct app.data access");
assert.ok(/\bsampleEventRecords\s*\(\s*\)/.test(sampleHistoryModule), "sample history must read event logs through sampleEventRecords()");
assert.ok(/\bprojectRecords\s*\(\s*\)/.test(sampleHistoryModule), "sample history snapshot fallback must read projects through projectRecords()");
const sampleImportExportModule = fs.readFileSync(path.join(frontendRoot, "js/samples/02-import-export.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(sampleImportExportModule), "sample import/export must use sample category and snapshot accessors instead of direct app.data");
assert.ok(/\bsampleCategoryRecords\s*\(\s*\)/.test(sampleImportExportModule), "sample import/export must enumerate pools through sampleCategoryRecords()");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(sampleImportExportModule), "sample import/export must restore failed imports through restoreDataSnapshot()");
const samplePoolModule = fs.readFileSync(path.join(frontendRoot, "js/samples/01-pool.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(samplePoolModule), "sample pool must use state accessors instead of direct app.data/app.view access");
assert.ok(/\bsamplePoolPageState\s*\(/.test(samplePoolModule), "sample pool must read pagination and filters through samplePoolPageState()");
assert.ok(/\bsetSamplePoolFilterState\s*\(/.test(samplePoolModule), "sample pool must update filters through setSamplePoolFilterState()");
assert.ok(/\bsampleCategoryRecords\s*\(\s*\)/.test(samplePoolModule), "sample pool must enumerate pools through sampleCategoryRecords()");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(samplePoolModule), "sample pool must restore failed mutations through restoreDataSnapshot()");
assert.ok(/\bsampleCategoryOverviewNode\s*\(/.test(samplePoolModule), "sample pool category overview must be rendered through DOM nodes");
assert.ok(/\bsamplePageShellNode\s*\(/.test(samplePoolModule), "sample pool page shell must be rendered through DOM nodes");
assert.ok(!/\breplaceHtml\s*\(\s*content\b/.test(samplePoolModule), "sample pool must not inject whole-page shells through replaceHtml(content, ...)");
assert.ok(!/\bsampleCategoryStatsHtml\b/.test(samplePoolModule), "sample pool category stats must not regress to HTML string builders");
const sampleDetailModule = fs.readFileSync(path.join(frontendRoot, "js/samples/07-detail.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(sampleDetailModule), "sample detail modal must use dataSnapshot()/restoreDataSnapshot() instead of direct app.data rollback");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(sampleDetailModule), "sample detail modal must restore failed edits through restoreDataSnapshot()");
const workspaceStageModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/04-stage.js"), "utf8");
assert.ok(!/\binnerHTML\b/.test(workspaceStageModule), "stage SKU append helpers must use DOM nodes instead of innerHTML");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(workspaceStageModule), "stage module must use data/view accessors instead of direct app.data/app.view access");
assert.ok(/\bpatchViewState\s*\(/.test(workspaceStageModule), "stage module must update selected stage through patchViewState()");
assert.ok(/\bsampleEventRecords\s*\(\s*\)/.test(workspaceStageModule), "stage module must read sample events through sampleEventRecords()");
const workspaceStrategyModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/03-strategy.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(workspaceStrategyModule), "stage strategy module must use view accessors instead of direct app.data/app.view access");
assert.ok(/\bpatchViewState\s*\(/.test(workspaceStrategyModule), "stage strategy module must update navigation through patchViewState()");
assert.ok(/\bstageStrategyId\s*\(\s*\)/.test(workspaceStrategyModule), "stage strategy module must read strategy page state through stageStrategyId()");
assert.ok(/\bclearStageStrategyState\s*\(\s*\)/.test(workspaceStrategyModule), "stage strategy module must clear strategy page state through clearStageStrategyState()");
assert.ok(/\bensureViewMap\s*\(/.test(workspaceStrategyModule), "stage strategy module must read filters through ensureViewMap()");
assert.ok(/\bstageStrategyPageNodes\s*\(/.test(workspaceStrategyModule), "stage strategy page shell must be rendered through DOM nodes");
assert.ok(!/\breplaceHtml\s*\(\s*document\.getElementById\(\s*["']content["']\s*\)/.test(workspaceStrategyModule), "stage strategy page must not inject whole-page shells through replaceHtml(content, ...)");
const workspaceHomeModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/02-home.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(workspaceHomeModule), "workspace home must use state accessors instead of direct app.data/app.view access");
assert.ok(/\bensureWorkspaceStageSelection\s*\(/.test(workspaceHomeModule), "workspace home must normalize selected stage through ensureWorkspaceStageSelection()");
assert.ok(/\bstageSortMode\s*\(\s*\)/.test(workspaceHomeModule), "workspace home must read sort state through stageSortMode()");
assert.ok(/\bsetStageSortModeState\s*\(/.test(workspaceHomeModule), "workspace home must update sort state through setStageSortModeState()");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(workspaceHomeModule), "workspace home must restore failed project mutations through restoreDataSnapshot()");
assert.ok(/\bprojectWorkspacePageNodes\s*\(/.test(workspaceHomeModule), "workspace home page shell must be rendered through DOM nodes");
assert.ok(!/\breplaceHtml\s*\(\s*document\.getElementById\(\s*["']content["']\s*\)/.test(workspaceHomeModule), "workspace home must not inject whole-page shells through replaceHtml(content, ...)");
const taskConfigModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/07-task-config.js"), "utf8");
assert.ok(!/\binnerHTML\b/.test(taskConfigModule), "task config titlebar must use DOM nodes instead of innerHTML");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(taskConfigModule), "task config must use project/view accessors instead of direct app.data/app.view access");
assert.ok(/\bfindProjectRecord\s*\(/.test(taskConfigModule), "task config must locate projects through findProjectRecord()");
const taskActionsModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/08-task-actions.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(taskActionsModule), "task actions must use dataSnapshot()/restoreDataSnapshot() instead of direct app.data rollback");
assert.ok(/\bdataSnapshot\s*\(\s*\)/.test(taskActionsModule), "task actions must capture rollback state through dataSnapshot()");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(taskActionsModule), "task actions must restore rollback state through restoreDataSnapshot()");
const taskTableModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/05-task-table.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(taskTableModule), "task table must use task flow and project accessors instead of direct app.data/app.view access");
assert.ok(/\btaskFlowPageState\s*\(/.test(taskTableModule), "task table must read pagination/filter state through taskFlowPageState()");
assert.ok(/\bisCurrentProjectWorkspaceStage\s*\(/.test(taskTableModule), "task table must check current stage through isCurrentProjectWorkspaceStage()");
const samplePickerModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/06-sample-picker.js"), "utf8");
assert.ok(!/\b(?:this|app)\.(?:data|view)\b/.test(samplePickerModule), "sample picker must use sample category accessors instead of direct app.data/app.view access");
assert.ok(/\bsampleCategoryRecords\s*\(\s*\)/.test(samplePickerModule), "sample picker must merge candidates through sampleCategoryRecords()");
const taskResultModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/09-task-result.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(taskResultModule), "task result module must use dataSnapshot()/restoreDataSnapshot() instead of direct app.data rollback");
assert.ok(/\bdataSnapshot\s*\(\s*\)/.test(taskResultModule), "task result module must capture save snapshots through dataSnapshot()");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(taskResultModule), "task result module must restore failed saves through restoreDataSnapshot()");
const dropdownIssueModule = fs.readFileSync(path.join(frontendRoot, "js/workspace/10-dropdown-issue.js"), "utf8");
assert.ok(!/\b(?:this|app)\.data\b/.test(dropdownIssueModule), "dropdown issue module must use project and snapshot accessors instead of direct app.data");
assert.ok(/\bfindProjectRecord\s*\(/.test(dropdownIssueModule), "dropdown issue module must locate projects through findProjectRecord()");
assert.ok(/\brestoreDataSnapshot\s*\(/.test(dropdownIssueModule), "dropdown issue module must restore failed edits through restoreDataSnapshot()");
const appData = fs.readFileSync(path.join(frontendRoot, "js/app.data.js"), "utf8");
[
  "projectRecords",
  "findProjectRecord",
  "appendProjectRecord",
  "removeProjectRecord",
  "selectProjectWorkspaceState",
  "homeMetrics",
  "navFingerprintData",
  "patchViewState",
  "navigateModuleState",
  "stageStrategyId",
  "clearStageStrategyState",
  "ensureViewMap",
  "setViewMapValue",
  "resetViewMap",
  "resetTaskFlowPage",
  "taskFlowPageState",
  "setTaskFlowPageState",
  "setTaskFlowPageSizeState",
  "isCurrentProjectWorkspaceStage",
  "ensureWorkspaceStageSelection",
  "stageSortMode",
  "setStageSortModeState",
  "samplePoolPageState",
  "setSamplePoolPageState",
  "setSamplePoolPageSizeState",
  "setSamplePoolFilterState",
  "resetSamplePoolFiltersState",
  "isCurrentSampleCategoryPage",
].forEach(name => {
  assert.ok(new RegExp(`${name}\\s*\\(`).test(appData), `app.data.js must expose ${name}() for the project state boundary`);
});

console.log("frontend architecture guard passed");
