# TestChamber V7 — 数字治理平台 · AI 代码定位器
（本文件不允许 claude code 修改/编辑/删除，本文件只允许 codex 进行编辑修改，该规则只适用于本文件）

> **用途**：让 AI agent 快速定位需要修改的代码。每个函数、CSS 规则组、API 端点都标注 `文件:行号`。

## 项目概要

| 项目 | 值 |
|------|-----|
| 应用 | 数字治理平台 V7 |
| 用途 | 终端硬件测试样机全生命周期：项目→阶段→任务→样机→结果 |
| 部署 | Python stdlib `ThreadingHTTPServer`，端口 9398，SQLite WAL |
| 前端 | Vanilla JS SPA，`app.registerModule(name, members)` 命名模块注册；项目/工作台主页/策略/阶段/任务表/样机池主干已收敛到状态访问器，核心兼容层集中持有 `app.data/app.view` |
| 规模 | ~18,000+ 行源码；`server.py` 约 7,544 行，已扩展到 SQLite 外置表、数据包导入导出、照片/事件/履历按需加载、任务/项目/阶段/样机增量写入、分页查询索引、样机身份查重索引、关键 P0 幂等兜底与空白平台整包导入兜底 |

### Codex 启动/验证方式

> 2026-06-02 验证：不要优先用隐藏窗口跑 `.bat`。在 Codex/PowerShell 环境中，`Start-Process -RedirectStandardOutput/-RedirectStandardError` 可能触发 `Path/PATH` 环境变量冲突。

```powershell
cd C:\Users\ROG\Desktop\TestChamberV7
python .\server.py --host 127.0.0.1 --port 9398
```

后台启动时使用：

```powershell
Start-Process -FilePath "python" -ArgumentList ".\server.py --host 127.0.0.1 --port 9398" -WorkingDirectory "C:\Users\ROG\Desktop\TestChamberV7"
Start-Sleep -Seconds 2
netstat -ano | Select-String ":9398"
Invoke-WebRequest -Uri http://127.0.0.1:9398/ -UseBasicParsing | Select-Object StatusCode,ContentLength
```

内置浏览器访问：`http://127.0.0.1:9398/`，标题应为 `数字治理平台 V7`。

---

### 版本发布规则

- `v7.0.0` 固定指向 2026-06-03 时 GitHub `origin/main` 的既有提交 `66ae30e`。
- `v7.1.0` 是 7.1 系列性能和导航响应优化的统一 GitHub Release/tag 入口；当前发布显示版本为 `v7.1.2`。
- 7.1 系列每次 GitHub push 只递增最后一位 patch：`7.1.X` → `7.1.(X+1)`，`7.1` 主线保持不变。
- 以后更新版本时，同步修改 `server.py` 的 `APP_VERSION` / `SERVER_VERSION`、`js/app.core.js` 的 `app.version`，并把 `index.html` 与 `css/style.css` 的静态资源 cachebuster 改为同一个语义版本号。
- 发布前运行：`python -m py_compile server.py`、`python tests\test_server_core.py`、`python tests\test_import_conflicts.py`、`node tests\frontend_pagination_perf.test.cjs`、`node tests\frontend_status_transitions.test.cjs`。
- 7.1 系列发布流程：提交到 `main`，推送 `origin main`，移动并强推既有 `v7.1.0` tag 到最新提交，再用 `gh release edit v7.1.0 --title "v7.1.X"` 更新同一个 Release 标题；不要为每次 7.1 patch 新建 Release。
- 7.2 及以后新主线再按新主线策略创建对应 tag / Release。
- Release 只发布源码；不要提交或上传 `data/`、`backups/`、`__pycache__/`、真实数据库或备份文件。

---

## 大数据量性能改造路线（20项目 / 10万任务 / 月级7万样机 / 百万照片）

### 目标原则

1. **日常运行不能依赖完整 state** — `/api/state` 只保留初始化兼容、导出/调试兜底；大列表和详情必须走分页/按需 API。
2. **任务、样机、照片、日志分层加载** — 首页/导航只取摘要；列表只取当前页；详情打开后再加载照片、事件、履历。
3. **SQLite 作为查询型数据库使用** — 高频字段建索引，筛选/搜索尽量 SQL 侧完成；批量导入使用事务。
4. **前端渲染有硬上限** — 任务表、样机卡片列表不得一次渲染数千节点，默认分页 50/100 条。
5. **增量写入逐步替代 PUT /api/state** — 任务状态、结果录入、样机状态、照片上传/删除后续都应收敛为细粒度 API。

### 当前性能相关入口

| 要改什么 | 文件:函数 |
|----------|-----------|
| 全量 state 拼装 | `server.py:3403` `compose_state()` |
| 全量 state 读取 | `server.py:3457` `get_state()` / `server.py:3467` `get_state_metadata()` / `server.py:6787` `Handler.do_GET()` `/api/state` |
| 全量 state 保存 | `server.py:5494` `save_state()` / `server.py:7282` `Handler.do_PUT()` `/api/state`；写入使用 SQLite `BEGIN IMMEDIATE`，不持有全局 `DB_LOCK` |
| SQLite schema / 索引 | `server.py:401` `ensure_schema()`；`server.py:341` `ensure_table_column()`；`server.py:347` `backfill_query_state_columns()`；`server.py:382` `backfill_sample_identity_columns()` |
| 查询状态列 | `project_tasks.flow_status`、`sample_records.effective_status/has_problem/board_sn/is_reassembled`，用于状态筛选、统计与身份查重避免整表 JSON 解析 |
| 项目/阶段/任务外置同步 | `server.py:1400` `sync_project_library()` |
| 项目/阶段/任务加载 | `server.py:1585` `load_project_library()` |
| 样机库加载 | `server.py:1167` `load_sample_library(include_photos/include_logs)` |
| 照片按需加载 | `server.py:1096` `load_sample_photos()` + `GET /api/samples/<id>/photos` |
| 事件按需加载 | `server.py:1151` `load_sample_events()` + `GET /api/samples/<id>/events` |
| 样机测试履历分页 API | `server.py:3166` `list_sample_history_page()` + `GET /api/samples/<id>/history` |
| 启动骨架 API | `server.py:3370` `compose_bootstrap_state()` + `GET /api/bootstrap` |
| 项目/样机池按需详情 API | `server.py:1675` `load_project_detail()` / `server.py:3269` `load_sample_category_detail()` |
| 分页参数解析 | `server.py:1806` `parse_page_params()` |
| 阶段任务分页 API | `server.py:2041` `list_stage_tasks_page()` + `GET /api/stages/<stageId>/tasks` |
| 样机池分页 API | `server.py:2446` `list_samples_page()` + `GET /api/sample-categories/<catId>/samples` |
| 任务样机候选分页 API | `server.py:2971` `list_task_sample_candidates_page()` + `GET /api/task-sample-candidates` |
| 样机/样机池销毁影响范围 API | `server.py:2741` `list_sample_destroy_impact_scope()` + `GET /api/sample-destroy-impact`，返回受影响项目/样机池 ID，前端按需加载详情，不拉完整 `/api/state` |
| 样机身份查重 API | `server.py:2868` `check_sample_identity_conflicts()` + `POST /api/sample-identity-check` |
| 项目摘要 API | `server.py:3328` `list_project_summary()` + `GET /api/projects/summary` |
| 样机池摘要 API | `server.py:2396` `list_sample_categories_summary()` + `GET /api/sample-categories` |
| 项目记录增量 upsert/delete | `server.py:5789` `update_project_record()` / `server.py:5848` `delete_project_record()` |
| 阶段记录增量 upsert/delete | `server.py:5866` `update_stage_record()` / `server.py:5924` `delete_stage_record()` |
| 样机池记录增量 upsert/delete | `server.py:5941` `update_sample_category_record()` / `server.py:6707` `delete_sample_category_record()` |
| 任务增量写入 API | `server.py:6253` `commit_task_mutation()` + `server.py:7180` `Handler.do_PATCH()`；写入使用 SQLite `BEGIN IMMEDIATE`，不持有全局 `DB_LOCK` |
| 批量任务增量写入 API | `server.py:6360` `commit_task_batch_mutation()` + `PATCH /api/stages/<stageId>/tasks/batch` |
| 任务记录增量 upsert | `server.py:5715` `upsert_task_record()` |
| 任务记录增量删除 | `server.py:5783` `delete_task_record()` |
| 样机记录增量更新/创建 | `server.py:5805` `update_sample_record(create_if_missing)` |
| 样机事件增量 upsert | `server.py:6073` `upsert_sample_events()` |
| 任务结束幂等兜底 | `server.py:6184` `existing_finished_task()`；重复 `finish_task_result` 返回 `409 TASK_ALREADY_FINISHED` |
| 样机新增选择状态兜底 | `server.py:6203` `detect_task_mutation_sample_status_blockers()`；新增样机只有“闲置”可写入任务 |
| 项目/阶段增量写入 API | `server.py:6561` `commit_project_mutation()` / `server.py:6622` `commit_stage_mutation()`；写入使用 SQLite `BEGIN IMMEDIATE`，不持有全局 `DB_LOCK` |
| 样机增量写入 API | `server.py:6463` `commit_sample_mutation()` + `server.py:7180` `Handler.do_PATCH()`；写入使用 SQLite `BEGIN IMMEDIATE`，不持有全局 `DB_LOCK` |
| 样机池增量写入 API | `server.py:6729` `commit_sample_category_mutation()` + `server.py:7180` `Handler.do_PATCH()`；写入使用 SQLite `BEGIN IMMEDIATE`，不持有全局 `DB_LOCK` |
| 完整数据包导出 | `server.py:3703` `prepare_export_bundle_parts()` / `server.py:3784` `build_export_bundle_file()` + `server.py:6787` `GET /api/export-bundle` |
| 数据包导入预览 | `server.py:3799` `analyze_import_bundle()` / `server.py:3879` `_diff_import_bundle()` + `server.py:7008` `POST /api/import-bundle/preview` |
| 数据包导入提交 | `server.py:4488` `commit_import_bundle()` + `server.py:7008` `POST /api/import-bundle/commit`；提交链路写入使用 SQLite `BEGIN IMMEDIATE`，不持有全局 `DB_LOCK` |
| 导入整树映射/一致性校验 | `server.py:5152` `_register_imported_stage_tree()` / `server.py:5169` `_register_imported_project_tree()` / `server.py:5224` `_validate_import_commit_state()` |
| 临时库压测脚本 | `tools/perf_benchmark.py` 默认造 20 项目 / 10万任务 / 30 池 / 7万样机 / 70万照片元数据 |
| 临时库并发压测脚本 | `tools/concurrency_benchmark.py` 默认造 4 项目 / 1 万任务 / 6 池 / 5,000 样机，并发跑分页/摘要/销毁影响范围读与 SQLite 写事务；运行期将 `DB_LOCK` 替换为报错锁，验证业务路径不回退全局锁 |
| 真实 HTTP 并发压测脚本 | `tools/http_concurrency_benchmark.py` 使用临时 SQLite 库启动 `ThreadingHTTPServer`，并发请求 bootstrap、摘要、任务分页、样机分页、销毁影响范围、照片上传/删除、`/api/export-bundle`、导入预览和导入提交；运行期将 `DB_LOCK` 替换为报错锁，导入提交遇到并发 revision 冲突会重试 |
| 前端启动/按需加载 | `js/app.server.js:8` `fetchBootstrapState()` / `:474` `fetchProjectDetail()` / `:763` `ensureProjectLoaded()` / `:834` `ensureSampleDestroyImpactScope()`；完整 `/api/state` 前端入口仅保留 `reloadFromServer()` 手动/调试兼容 |
| 前端分页 API 调用 | `js/app.server.js:396` `fetchProjectSummary()` / `:427` `fetchStageTasksPage()` / `:439` `fetchSampleCategoriesSummary()` / `:446` `fetchSamplePage()` / `:398` `fetchSampleHistory()` / `:408` `checkSampleIdentityConflicts()` / `:458` `fetchTaskSampleCandidates()` |
| 前端分页缓存失效 | `js/app.server.js:868` `invalidatePagedCaches()`；`:238` `invalidateSampleHistoryCache()` |
| 前端项目/阶段增量提交 | `js/app.server.js:1035` `commitProjectMutation()` / `:1072` `commitStageMutation()` |
| 前端任务增量提交 | `js/app.server.js:909` `commitTaskMutation()` / `:895` `taskSampleStatusBlockerMessage()` |
| 前端样机/样机池增量提交 | `js/app.server.js:1120` `commitSampleMutation()` / `:1157` `commitSampleCategoryMutation()` |
| 启动/阻塞/临时变更增量入口 | `js/workspace/08-task-actions.js:55` `startTask()` / `:405` `blockTask()` / `:259` `tempChangeTask()` |
| 结果录入增量入口 | `js/workspace/09-task-result.js:676` `saveTaskResult()`；`:617` `restoreTaskResultSaveSnapshot()`；`:624` `refreshTaskAfterAlreadyFinished()` |
| 任务新增/配置/分配增量入口 | `js/workspace/07-task-config.js:68` `openAddTasksFromPoolModal()` / `:191` `assignPlanTaskSamples()` / `:244` `setPlanTaskSchedule()` / `:443` `saveTaskConfigAll()` |
| 任务删除增量入口 | `js/workspace/08-task-actions.js:8` `deleteTask()` |
| 项目 CRUD 增量入口 | `js/projects.js:122` `addProject()` / `:174` `editProject()` / `:295` `deleteProject()` |
| 项目人员/位置增量入口 | `js/workspace/02-home.js:282` `addProjectLocation()` / `:277` `addProjectMember()` / `:347` `importProjectMembersCsv()` |
| 阶段 CRUD/排序增量入口 | `js/workspace/04-stage.js:191` `addStage()` / `:229` `editStage()` / `:260` `deleteStage()` / `:309` `copyStage()` / `js/workspace/02-home.js:541` `onStageDrop()` |
| 样机池/样机新增导入增量入口 | `js/samples/01-pool.js:739` `addSampleCategory()` / `:316` `editSampleCategory()` / `:781` `addSample()` / `js/samples/02-import-export.js:8` `importSampleBatch()` |
| 样机详情/销毁增量入口 | `js/samples/07-detail.js:8` `openSampleDetail()` / `js/samples/01-pool.js:791` `deleteSampleCategory()` / `:666` `destroySample()` |
| 异步弹窗确认 | `js/app.modal.js:26` `showModal()` |
| 任务表服务端分页入口 | `js/workspace/05-task-table.js:53` `taskFlowPagerHtml()` / `:84` `taskFlowQueryParams()` / `:102` `loadTaskFlowPage()` / `:135` `workspaceTaskFlowHtml()` |
| 样机池服务端摘要/分页入口 | `js/samples/01-pool.js:8` `samplePagerHtml()` / `:28` `setSamplePage()` / `:112` `loadSampleCategorySummary()` / `:133` `loadSamplePage()` / `:174` `prefetchAdjacentSamplePages()` / `:238` `refreshSamplePageRegion()` / `:257` `renderSamples()` |
| 策略/BOM/用例集增量入口 | `js/workspace/03-strategy.js:36` `persistStageStrategyMutation()` / `:39` `scheduleStageStrategySave()` / `:292` `importTestCaseXlsx()` |
| 问题单/照片重命名增量入口 | `js/workspace/10-dropdown-issue.js:221` `openTaskIssueRecordModal()` / `js/samples/04-photos.js:259` `startPhotoRename()` |
| 前端数据包导入导出 | `js/import-export-bundle.js:10` `exportBundle()` / `:67` `importBundle()` / `:581` `_onImportCommit()`；`js/app.server.js:1262` `importBundlePreview()` / `:789` `importBundleCommit()` |

### 第一阶段执行顺序

1. 后端新增分页/摘要 API：任务列表、样机列表、项目摘要、样机池摘要。
2. 前端任务表和样机池先加本地分页护栏，避免现有全量 state 下直接渲染数千 DOM。
3. 前端新增分页 API 调用函数，后续逐页替换本地数据源。
4. 补测试覆盖分页参数、筛选结果、边界 page/pageSize。
5. 再进入第二阶段：任务状态/样机状态/结果录入改增量写入。

### 第二阶段已完成

1. 新增 `PATCH /api/tasks/<taskId>/mutation`：只写当前任务、任务日志、当前阶段概要、受影响样机、样机事件，不再走整份 `/api/state`。
2. 前端 `startTask()`、`blockTask()`、`tempChangeTask()`、`saveTaskResult()` 已切到 `commitTaskMutation()`。
3. `showModal()` 支持异步 `onOk`，结果录入可等待服务器成功后再关闭。
4. 导入测试改为临时数据目录，避免误删真实 `data/`。

### 第三阶段已完成

1. 任务新增、计划配置、样机分配、任务双 Tab 配置已切到 `commitTaskMutation(createIfMissing)`。
2. 未执行任务删除使用 `deleteMode="delete"` 物理删除任务记录；已执行任务继续归档隐藏但走任务增量保存。
3. 样机详情编辑/状态修改已切到 `commitSampleMutation()`，只写单台样机和本样机事件。
4. 单台样机档案销毁已切到 `commitSampleMutation(deleteSample)`，同步受影响任务与其它样机释放状态。
5. 样机池档案销毁已切到 `commitSampleCategoryMutation(deleteCategory)`，物理删除池内样机/资产/事件，同时同步受影响任务。
6. 已补 `tests/test_server_core.py` 覆盖任务新增/删除、样机更新/删除、样机池销毁。
7. 已补 `tests/test_server_core.py` 覆盖任务新增/删除、样机更新/删除、样机池销毁。

### 第四阶段已完成

1. 项目新建/编辑/删除已切到 `commitProjectMutation()`，项目删除会同步释放受影响样机占用。
2. 项目人员、项目位置、人员 CSV 导入已切到项目增量 API。
3. 阶段新增/编辑/删除/复制/排序、策略页内联阶段名与 SKU 编辑已切到 `commitStageMutation()`。
4. 样机池新建/编辑、样机新增、样机批量导入已切到 `commitSampleCategoryMutation(createSamples)`。
5. 任务表正式使用 `/api/stages/<stageId>/tasks` 服务端分页；样机池卡片使用 `/api/sample-categories` 摘要，池内样机使用 `/api/sample-categories/<catId>/samples` 分页。
6. `index.html` 静态资源加 cachebuster，当前发布版本统一为 `v=7.1.2`，避免浏览器缓存旧 JS 影响验证。
7. 已补 `tests/test_server_core.py` 覆盖项目增量、阶段增量、样机池创建与批量样机插入。
8. 已推进到第五阶段：初始化不再直接拉全量 `/api/state`。

### 第五阶段已完成

1. 启动入口已改为 `GET /api/bootstrap`，只返回项目摘要、样机池摘要、revision 和当前选择 ID；当前验证数据下 bootstrap 约 1.3KB，旧 `/api/state` 约 2.68MB。
2. 新增 `GET /api/projects/<projectId>` 按需加载项目详情；普通进入项目不加载全量任务，任务表继续走 `/api/stages/<stageId>/tasks` 分页。
3. 新增 `GET /api/sample-categories/<catId>` 按需加载样机池完整样机基础数据；普通池内浏览继续走样机分页。
4. 前端新增 `ensureProjectLoaded()`、`ensureSampleCategoryLoaded()` 等按需详情加载；`ensureFullStateLoaded()` 已移除，低频危险操作改走目标详情/影响范围 API。
5. 阶段策略、BOM、用例集导入已切到阶段/项目增量 API，不再触发全量保存。
6. 任务问题单录入已切到任务增量 API；样机照片重命名新增独立 PATCH 接口并更新 `sample_assets.original_name`。
7. 已补 `tests/test_server_core.py` 覆盖 bootstrap、项目详情按需任务加载、样机池详情加载。

### 第六阶段已完成

1. SQLite 查询列补强：`project_tasks.flow_status` 用于任务状态筛选/统计；`sample_records.has_problem/effective_status` 用于样机故障和状态筛选/统计。
2. `ensure_schema()` 会自动补列和回填旧库数据；`sync_project_library()`、`upsert_task_record()`、`sync_sample_library()`、`update_sample_record()` 会持续写入这些查询列。
3. 新增分页顺序索引：任务按 `stage_id/deleted_at/created_at/id`，任务状态按 `stage_id/deleted_at/flow_status/created_at/id`，样机按 `category_id/deleted_at/created_at/id`，样机状态按 `category_id/deleted_at/effective_status/created_at/id`。
4. `list_stage_tasks_page()` 的无深度关键词路径改为 SQL `COUNT + LIMIT/OFFSET`；SKU、执行人、任务状态筛选走数据库分页。`categoryKeyword/caseKeyword/dtsKeyword/resultKeyword` 保留精确 Python 兜底。
5. `list_samples_page()` 的无关键词路径改为 SQL `COUNT + LIMIT/OFFSET`；状态、保管人、借用人筛选走数据库分页。全文关键词保留精确 Python 兜底。
6. 新增 `tools/perf_benchmark.py`，默认使用临时 SQLite 造 20 项目 / 5 阶段 / 10万任务 / 30 样机池 / 7万样机 / 每台 10 张照片元数据，跑完自动清理，不污染真实 `data/`。
7. 2026-06-02 目标规模压测结果（median）：`/api/bootstrap` 约 46ms；任务默认分页约 1.2ms；任务状态分页约 1.2ms；样机默认分页约 1.1ms；样机状态分页约 1.1ms；项目详情不含任务约 0.6ms；项目详情含任务约 59ms。
8. 仍需注意：任务结果深度关键词和样机全文关键词会扫 JSON 兜底，本轮目标规模下约 15–18ms；如果未来复杂全文搜索继续增长，应考虑 FTS5 或专用搜索表。

### 第七阶段已完成

1. 样机池分页前端流畅度优化：`js/samples/01-pool.js` 增加分页缓存、加载态、局部刷新和相邻页预取；同一池内翻页不再整页重建 toolbar/header。
2. 任务表分页同步收敛：`js/workspace/05-task-table.js` 在服务端分页 cache miss 时显示加载反馈，避免先跑本地深度结果搜索。
3. 样机选择器 P0 修复：新增选择样机统一要求状态为“闲置”；`测试中 / 在位等待 / 已退库 / 取走分析 / 已借出` 不可新增勾选，当前任务已拥有的样机仍可取消。
4. 样机选择器体验优化：可选样机卡片整卡点击即可切换勾选，`IMEI/SN/主板SN` 文本链接只保留文字级点击范围。
5. 删除按钮统一改为项目内常用垃圾桶图标，并补充二次确认，降低误删风险。
6. 结束任务 P0 修复：额外“结束任务”按钮改为 async 等待、点击后禁用并显示“结束中...”；前端增加任务级 in-flight guard 和失败回滚。
7. 结束任务后端幂等兜底：`finish_task_result` 如果命中已完成任务，返回 `409 TASK_ALREADY_FINISHED`，不写任务、不写样机事件、不写 audit_log、不增加 revision。
8. 侧栏折叠体验修复：折叠态图标居中，展开/折叠按钮固定在导航栏内部并贴右边线。
9. 已补前后端回归：`tests/frontend_status_transitions.test.cjs` 覆盖结束任务防重与样机选择器规则，`tests/test_server_core.py` 覆盖重复结束拒绝与样机状态不可选兜底。

### 第八阶段已完成（数据包导入正确性专项）

1. 系统检查完整链路：`GET /api/export-bundle` → `POST /api/import-bundle/preview` → `POST /api/import-bundle/commit`；2026-06-03 起成功提交后前端走局部同步，完整 `/api/state` 只保留为异常兜底。
2. 修复空白平台整包导入 P0：`commit_import_bundle()` 导入 `new_project` / `new_stage` 时不再把已随整树复制的阶段和任务二次追加，避免重复任务触发样机占用冲突。
3. 新增导入提交前一致性校验：同一项目内阶段 ID 不重复、同一阶段内任务 ID 不重复、任务 `sampleIds` 必须能映射到存在样机。
4. 已补导入专项回归：`tests/test_import_conflicts.py` 覆盖源库导出完整包、目标库清空、空白平台导入、项目/阶段/任务/样机占用关系只保留一份。
5. 验证通过：`python tests\test_import_conflicts.py`、`python tests\test_server_core.py`、`python -m py_compile server.py`。

### 性能改造暂停点 / 剩余任务

> 记录时间：2026-06-03。当前已完成启动瘦身、增量写入主干、任务/样机池服务端分页、SQLite 索引补强、目标规模压测、数据包导入正确性专项。剩余任务如下。

1. **大列表前端渲染优化（本轮已推进）**
   - 2026-06-03 已修复：任务/批量任务增量提交、样机/样机池增量提交成功后，不再默认整页 `render()` 重建大列表；当前项目任务表改为刷新 `/api/stages/<stageId>/tasks` 当前页并局部替换 `taskFlowShell`，当前样机池改为刷新 `/api/sample-categories/<catId>/samples` 当前页并局部替换 `samplePageShell`。
   - 2026-06-03 已修复：任务样机选择器不再打开前加载全部样机池详情，也不再基于 `allSamples()` 一次渲染全部候选；改为 `GET /api/task-sample-candidates` 服务端分页/搜索/按状态筛选，并返回 `selectable/disabledReason` 与已选样机详情。
   - 2026-06-03 已新增：`project_task_samples` 轻量关联表维护任务-样机关联，候选页和样机占用冲突检测可按 `sample_id` 查询，不再扫描全部任务 JSON。
   - 已补 `tests/frontend_pagination_perf.test.cjs` 覆盖任务表/样机池 mutation 后不触发 `/api/state` / `reloadFromServer()` / 全量 render；2026-06-04 起，当前无筛选页且 affected payload 覆盖可见行/卡片时直接 patch 当前页缓存和 DOM，不再额外拉分页 API。
   - 剩余关注：样机详情、任务详情、履历、照片区继续压测，避免一次性渲染大量历史记录或图片节点；浏览器端仍需补完整交互回归。

2. **数据包导入后的局部同步策略（本轮已完成，导入专项）**
   - 2026-06-03 已修复：`commit_import_bundle()` 成功返回 `mutationSummary`，包含受影响 `projectIds/stageIds/taskIds/sampleCategoryIds/sampleIds`。
   - 前端 `_onImportCommit()` 不再成功后直接 `reloadFromServer()`；改由 `applyImportBundleMutationResult()` 刷新项目摘要、样机池摘要、受影响项目详情、当前任务分页和当前样机分页。
   - 完整 `/api/state` 刷新仅作为缺失 summary 或局部同步失败时的异常兜底，日常导入成功路径不再依赖完整 state。

3. **测试覆盖补强（下一优先级最高）**
   - 后端已有核心单元测试、导入冲突测试、空白平台整包导入测试、导入后 mutation summary、照片上传/删除/重命名路由测试、照片资产级提交不拼完整 state、样机身份查重 API、样机履历分页 API，以及任务样机候选分页/可选性测试；前端已覆盖任务/样机分页性能、状态流转、照片局部合并、任务/样机 mutation 后当前分页局部刷新、导入后当前任务/样机分页局部同步、任务样机选择器不枚举全量样机、样机导入走服务端查重、履历渲染不扫本地 projects。
   - 仍缺结果录入表单、任务临时变更、SQLite 持久化迁移和浏览器端交互回归专项覆盖。
   - 浏览器端需要补最小回归：启动 bootstrap、进入项目、任务分页筛选、进入样机池、样机分页筛选、打开样机详情、照片区域操作。

4. **长期技术债（不阻塞当前大数据流畅度）**
   - 2026-06-04 已修复第一层模块边界：26 个业务文件已从 `Object.assign(app, {...})` 迁移为命名 `app.registerModule(name, members)`，并新增 `tests/frontend_architecture_guard.test.cjs` 防止回退；项目域新增 `projectRecords()` / `findProjectRecord()` / `selectProjectWorkspaceState()` 等状态访问器，`js/projects.js` 不再直接访问 `this.data` / `this.view`；全局渲染外壳新增 `homeMetrics()` / `navFingerprintData()` / `navigateModuleState()` 等访问器，`js/app.render.js` 不再直接访问 `this.data` / `this.view`；筛选模块新增 `ensureViewMap()` / `setViewMapValue()` / `resetViewMap()` / `resetTaskFlowPage()`，`js/app.filters.js` 不再直接访问 `this.view`；调试审计改读 `dataSnapshot()`，样机详情字段/样机导入导出/样机履历改用 `projectRecords()` / `sampleCategoryRecords()` / `sampleEventRecords()`；工作台主页、阶段策略、阶段 CRUD、任务表、样机选择器、结果录入、任务配置/任务动作、问题单入口和样机池主干均已通过 `app.data.js` 状态访问器或快照隔离。当前扫描只剩 `js/app.data.js`、`js/app.core.js`、`js/app.server.js` 核心兼容/状态边界文件直接持有 `this.data` / `this.view`。
   - 2026-06-04 已收窄 `/api/state` 调用入口：前端只通过 `fullStateUrl(reason)` / `reloadFromServer()` 保留手动调试完整 state GET，后端回传 compat reason 并对无 reason 调用打印警告；业务模块禁止调用 `app.save()` / `scheduleSave()`，`ensureFullStateLoaded()` 已移除；`save_state()` 的当前态快照已改为不加载样机照片、保留事件日志参与三向合并，写入改用 SQLite `BEGIN IMMEDIATE`，不再持有全局 `DB_LOCK`。样机/样机池销毁影响分析已改为 `GET /api/sample-destroy-impact` 返回受影响项目/样机池范围并按需加载详情；导入提交已改为专用写入函数，不再二次进入 `save_state()` / `compose_state()`；完整 state 入口仍保留为导入异常兜底和调试兼容路径。
   - 2026-06-04 已完成 `index.html` 与 `js/**` 内联事件迁移：`js/app.core.js` 统一绑定 `click/change/input/keydown/focusout/focusin/dblclick/drag*` 并按 `data-app-action` 分发，当前扫描无 `on*=` 模板属性；`tests/frontend_architecture_guard.test.cjs` 使用架构护栏防止 `Object.assign(app, {...})`、内联事件、全局渲染外壳字符串注入回退。
   - 2026-06-04 已降低导入导出内存风险：HTTP 导出改为临时 zip 文件流式发送，`build_export_bundle()` 兼容 wrapper 也复用临时文件构建；导入预览新增 TTL、条数、缓存总字节和 `state.json` 大小上限，并改用 `get_state(compact=True)` 对比，避免把主库照片/事件数组拉入预览内存；上传 zip 进入预览后立即落到临时目录 `bundle.zip` 并清空 multipart 内存引用；`_IMPORT_PREVIEWS` 只保留轻量元数据和临时目录 payload 路径，完整 incoming state 与 preview result 写入 `preview_payload.json`，提交时按需读取；导入提交主库快照保持 compact，只有合并导入照片的既有样机通过 `hydrate_import_target_photos()` 按需补读当前照片；导入提交改用 `commit_merged_import_state()` 直接写外置表和 revision，不再调用 `save_state()` 二次拼当前库；导入提交的 stale-preview revision check 改为 `get_state_metadata()`，过期预览拒绝路径不再 `compose_state()`。

5. **照片/结果图片后端直接变更链路（本轮已完成）**
   - 2026-06-03 已修复：样机照片上传/删除、任务结果图片上传成功后不再 `syncAfterDirectMutation()` / `reloadFromServer()` 拉取 `/api/state`，改由 `js/app.server.js` `applySamplePhotosMutationResult()` 合并接口返回的 `photos/revision` 并局部刷新照片面板/分页缓存。
   - 2026-06-03 已修复：照片重命名 PATCH 已统一写入 `audit_log`，并补 `tests/test_server_core.py` 覆盖照片上传、重命名、删除三段后端路由。
   - 2026-06-03 已修复：照片/结果图上传和照片删除后端改为 `server.py:5630` `commit_sample_asset_mutation()`，只更新 `sample_assets`、当前样机 `updatedAt`、`app_state.revision` 和 `audit_log`；成功路径不再 `compose_state()` / `commit_data_mutation()` / `sync_project_library()` / `sync_sample_library()`。2026-06-04 起，照片上传/删除/重命名数据库变更改用 SQLite `BEGIN IMMEDIATE` 写事务，不再持有全局 `DB_LOCK`；照片上传文件写入和照片删除文件 unlink 也已移到 DB 提交临界区外。

6. **样机全局查重（本轮已完成）**
   - 2026-06-03 已新增 `sample_records.board_sn/is_reassembled` 查询列、回填和索引；`server.py:2868` `check_sample_identity_conflicts()` + `POST /api/sample-identity-check` 支持批量 SN/IMEI/主板SN 查重、重组样机豁免和编辑排除自身。
   - 2026-06-03 已修复：样机批量导入、新增样机、编辑样机身份不再为了查重调用 `ensureFullStateLoaded()` 或遍历完整样机库；批量导入一次调用服务端查重并保留本批次内重复过滤。

7. **样机测试履历服务端分页（本轮已完成）**
   - 2026-06-03 已新增 `server.py:3166` `list_sample_history_page()` + `GET /api/samples/<sampleId>/history`，由 SQLite 侧按 `sample_events` 与 `project_task_samples` 聚合任务、日志和结果图片，并支持分页。
   - 2026-06-03 已修复：`js/samples/06-history.js:102` `sampleTestHistoryHtml()` 只渲染 `fetchSampleHistory()` 返回的缓存页，不再遍历本地 `projects/stages/tasks`；照片/任务/样机 mutation 会失效相关样机履历缓存。

8. **增量 mutation 返回值与缓存失效粒度继续收窄**
   - 2026-06-04 已完成第一步：任务、批量任务、项目、阶段、样机、样机池增量 PATCH 成功后返回 `affected`，包含受影响 `projectIds/stageIds/taskIds/sampleCategoryIds/sampleIds`、项目摘要、样机池摘要、compact 任务行和样机卡片，单次最多 100 行。
   - 前端已新增 `applyMutationAffected()` 合并 affected compact 数据；2026-06-04 进一步新增 `tryPatchCurrentTaskFlowPage()` / `tryPatchCurrentSamplePage()`，当前无筛选页且 affected 覆盖可见行/卡片时直接 patch 当前页缓存和 DOM，跳过分页 API 复查。筛选页、新增/删除、truncated affected 仍走分页 API 兜底，避免行跨页/跨筛选条件时显示错误。

9. **并发与锁粒度未按多用户场景压测**
   - 2026-06-04 已把纯 GET 热点查询从全局 `DB_LOCK` 中拆出：bootstrap、项目摘要/详情、样机池摘要/详情、任务分页、样机分页、候选样机、照片/事件/履历读取、样机身份查重不再共享 Python 锁；完整 state 兼容读取 `get_state()` / `get_state_metadata()` 也改为 SQLite read snapshot；任务/批量任务/样机/项目/阶段/样机池增量提交、照片上传/删除/重命名数据库变更、`save_state()` 兼容保存和导入提交链路都改用 `write_db_connection()` + SQLite `BEGIN IMMEDIATE` 写事务，不再持有全局 Python 锁；任务/批量任务增量提交后的 backup 改为 `write_compact_backup_snapshot()` 无锁只读快照；照片上传文件写入、照片删除文件 unlink、样机销毁资产 unlink、样机池销毁资产 unlink 均已移到 DB 提交临界区之外。
   - 当前运行期业务读写路径已不依赖全局 `DB_LOCK`，仅 `init_db()` 启动建库/迁移仍使用全局锁；2026-06-04 已新增 `tools/concurrency_benchmark.py`，可用临时 SQLite 库并发跑 bootstrap/任务分页/样机分页读取与 SQLite 写事务，并把 `DB_LOCK` 替换为报错锁确认业务路径不回退全局锁；2026-06-04 已新增 `tools/http_concurrency_benchmark.py`，用临时库启动真实 `ThreadingHTTPServer` 并发请求 bootstrap、摘要、任务分页、样机分页、照片上传/删除、`/api/export-bundle`、导入预览和导入提交，导入提交遇到并发 revision 冲突会重新预览再提交。后续仍需要在目标数据量下继续压测 SQLite 写事务排队、导入提交耗时和进度反馈。

10. **AGENTS 文件地图刷新机制**
   - 2026-06-04 已新增 `tools/update_agents_map.py`，可扫描 Python/JS 函数和方法并刷新 `AGENTS.md` 中的文件地图行号。
   - 后续较大改动后运行 `python tools\update_agents_map.py`，再检查 `AGENTS.md` 的行号 diff；本文件当前已刷新到 `server.py` 7362 行版本。

---

## 文件地图 — 精确到函数

### server.py (7544 行，含 SQLite 外置表、数据包导入导出、启动骨架 API、分页摘要 API、查询状态列、样机身份查重/履历分页 API、任务/项目/阶段/样机增量写入 API、P0 幂等兜底、空白平台整包导入兜底)

| 行号 | 符号 | 职责 |
|------|------|------|
| 67 / 79 | `empty_data()`, `ensure_dirs()` | 空状态模板, 目录创建 |
| 107 / 116 | `connect_db()` / `write_db_connection()` | SQLite 连接(WAL, 30s timeout) 与无全局 Python 锁写事务 |
| 244 / 258 / 272 / 290 | `_should_backup()`, `write_backup()`, `write_compact_backup_snapshot()`, `prune_backups()` | backup 节流判断、写入、无锁 compact 快照与清理 |
| 341 / 347 / 382 / 401 | `ensure_table_column()` / `backfill_query_state_columns()` / `backfill_sample_identity_columns()` / `ensure_schema()` | SQLite 表结构 DDL/迁移、查询状态列/样机身份列回填、索引创建 |
| 932 | `sync_sample_library()` | 样机库 → SQLite 同步(upsert+清理，写入 effective_status/has_problem/board_sn/is_reassembled) |
| 1169 | `load_sample_library()` | SQLite → 内存样机库 |
| 1246 / 1264 / 1289 | `list_item_key()`, `merge_record()`, `merge_list_by_id()` | 三向合并引擎 |
| 1182–1191 | `PROJECT_CHILDREN`, `SAMPLE_CATEGORY_CHILDREN` | 项目/样机嵌套合并层级声明 |
| 1373 | `merge_state()` | 顶层三向合并入口 |
| 1400 | `sync_project_library()` | 项目/阶段/任务 → SQLite，写入 flow_status |
| 1585 | `load_project_library()` | SQLite → 项目列表 |
| 1975 / 1979 / 1998 | `task_query_requires_python_scan()` / `task_sql_filter_parts()` / `task_from_db_row()` | 任务分页 SQL 快路径辅助 |
| 2041 | `list_stage_tasks_page()` | `/api/stages/<stageId>/tasks` 服务端分页，默认/状态/SKU/执行人走 SQL 分页 |
| 2333 / 2346 / 2371 | `sample_query_requires_python_scan()` / `sample_sql_filter_parts()` / `sample_from_db_row()` | 样机分页 SQL 快路径辅助 |
| 2396 | `list_sample_categories_summary()` | `/api/sample-categories` 样机池摘要，按 effective_status 统计 |
| 2446 | `list_samples_page()` | `/api/sample-categories/<catId>/samples` 服务端分页，默认/状态/保管人/借用人走 SQL 分页 |
| 2868 | `check_sample_identity_conflicts()` | `/api/sample-identity-check` 服务端样机身份查重，支持批量、重组豁免、编辑排除自身 |
| 2971 | `list_task_sample_candidates_page()` | `/api/task-sample-candidates` 服务端分页候选 |
| 3166 | `list_sample_history_page()` | `/api/samples/<sampleId>/history` 服务端履历分页聚合 |
| 3269 | `load_sample_category_detail()` | 样机池详情按需加载 |
| 3328 | `list_project_summary()` | `/api/projects/summary` 项目摘要 |
| 3370 | `compose_bootstrap_state()` | `/api/bootstrap` 启动骨架 |
| 3403 | `compose_state()` | 从 SQLite 拼装完整 state |
| 3416 | `begin_read_snapshot()` | 完整 state / metadata 兼容读取的 SQLite 只读快照事务 |
| 3424 | `init_db()` | 首次启动建库 + V6→V7 自动迁移 |
| 3703 / 3740 / 3775 / 3784 / 3799 / 3879 / 4488 / 5344 / 5224 | `prepare_export_bundle_parts()` / `write_export_bundle_zip()` / `build_export_bundle()` / `build_export_bundle_file()` / `analyze_import_bundle()` / `_diff_import_bundle()` / `commit_import_bundle()` / `hydrate_import_target_photos()` / `_validate_import_commit_state()` | 完整数据包导出、HTTP 临时 zip 流式发送、预览、冲突分析、compact 提交、导入照片目标样机按需补读、空白平台整包导入一致性兜底 |
| 5449 | `detect_sample_occupancy_conflicts()` | C1 占用冲突检测 |
| 5494 | `save_state()` | PUT /api/state 处理 |
| 5568 | `parse_multipart()` | multipart/form-data 解析 |
| 5598 | `commit_data_mutation()` | 旧直接变更兼容入口；照片上传/删除已不再使用 |
| 917 / 928 | `sample_asset_relative_paths()` / `cleanup_sample_asset_files()` | 样机资产文件路径收集与低频清理，销毁路径提交后再 unlink |
| 692 / 722 | `write_sample_asset_file()` / `upsert_sample_asset_meta()` | 照片/结果图文件写入与 SQLite 资产记录 upsert 拆分 |
| 5630 | `commit_sample_asset_mutation()` | 照片/结果图上传删除后的资产级 revision/audit/sample 更新时间提交 |
| 5715 / 5789 / 5866 / 5941 / 5998 / 6073 | `upsert_task_record()` / `update_project_record()` / `update_stage_record()` / `update_sample_category_record()` / `update_sample_record()` / `upsert_sample_events()` | 任务/项目/阶段/样机池/样机/事件增量 upsert |
| 6184 | `existing_finished_task()` | 结束任务幂等兜底，重复 finish 返回 `TASK_ALREADY_FINISHED` |
| 6203 | `detect_task_mutation_sample_status_blockers()` | 新增任务样机状态兜底，只有“闲置”可新增选择 |
| 6253 / 6360 / 6463 / 6561 / 6622 / 6729 | `commit_task_mutation()` / `commit_task_batch_mutation()` / `commit_sample_mutation()` / `commit_project_mutation()` / `commit_stage_mutation()` / `commit_sample_category_mutation()` | 任务、批量任务、样机、项目、阶段、样机池增量写入 API |
| 6831 | `Handler` | HTTP 路由类 |
| 6964 | `_is_public_static_path()` | 静态文件白名单 |
| 6787 | `Handler.do_GET()` | GET 路由(全量 state、摘要、分页、样机履历、静态资源) |
| 7008 | `Handler.do_POST()` | POST 路由(导入、样机身份查重、照片上传) |
| 7137 | `Handler.do_DELETE()` | DELETE 路由(照片软删除) |
| 7180 | `Handler.do_PATCH()` | PATCH 增量写入路由 |
| 7282 | `Handler.do_PUT()` | PUT /api/state 路由 |
| 7517 | `main()` | 启动入口 |

### js/utils.js (615 行) — 纯工具函数

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `esc(v)` | HTML转义—**所有用户输入必须经此** |
| 13 | `id(prefix)` | 唯一ID(timestamp36+random6) |
| 19 / 22 | `now()`, `today()` | 时间工具 |
| 24 | `toast(msg)` | 轻提示3.2s |
| 34 | `normalizeDigits(v)` | 全角数字→半角 |
| 40 / 46 | `normalizeEmployeeNoKey()`, `memberIdentityKey()` | 人员去重key |
| 52 | `personIdentityFromText()` | `姓名/工号`→`{name,employeeNo}` |
| 65 | `personText()` | `{name,employeeNo}`→格式化 |
| 71 | `personMatchesMember()` | 人员文本与成员匹配 |
| 81 | `parsePositiveInt()` | 正整数解析,失败返null |
| 92 | `parseCsvLine()` | CSV行解析(含引号转义) |
| 122 | `parseProjectMembersCsv()` | 项目人员CSV导入 |
| 150 | `sampleImportAliases()` | 样机导入列名别名表 |
| 171 | `parseSampleDateField()` | 多格式日期→yyyy-MM-dd |
| 202 | `parsePersonField()` | 人员字段严格校验(姓名/工号) |
| 230 | `isNoSampleIssueText()` | 判定"无问题"占位文本 |
| 251 | `parseSampleIssueText()` | 问题文本按行/分号拆分 |
| 247–316 | `parseSampleImportMatrix/Csv()` | 样机导入解析核心 |
| 331 | `parseSampleImportXlsx()` 及相关 | 纯JS XLSX解析(含ZIP + raw deflate兜底) |
| 376–534 | `inflateRawBytes()/inflateRawBytesFallback()` | XLSX deflate解压:优先浏览器API, 旧浏览器走JS兜底 |
| 585–613 | `csvEscape/downloadCsv/downloadText` | 导出工具 |

### js/app.core.js (548 行)

| 行号 | 符号 | 职责 |
|------|------|------|
| 5–35 | `app = {...}` | 全局对象(version, data, view, constants, _baseData, _saveInFlight等) |
| 27–34 | `app.view` | UI状态: module, selectedProjectId, filters, collapsed, sidebarCollapsed |
| 37–38 | `app.constants` | 样机5状态, 任务5状态, 模块名称枚举 |
| 99 / 106 | `htmlFragment()` / `replaceHtml()` | 受控 HTML 字符串替换入口；直接 `innerHTML` 只允许集中在这里 |
| 117 / 123 | `cloneChildNodes()` / `replaceWithClonedNodes()` | 弹窗堆栈 DOM clone 保存/恢复 |
| 139 / 168 | `bindDelegatedEvents()` / `dispatchAppAction()` | 全局 `data-app-action` 事件委托绑定与分发 |
| 509 | `init()` | 入口: GET /api/bootstrap → normalize → render → 全局事件绑定 |

### js/app.server.js (1065 行) — 服务器通信

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `fetchBootstrapState()` | 启动骨架读取 API |
| 15 | `updateServerStatus()` | 侧栏保存状态指示器 |
| 35 | `reloadFromServer()` | GET /api/state 完整基础数据刷新 |
| 56 | `scheduleSave()` | 旧全量保存 debounce 入口(保留兼容，摘要态禁止业务误用) |
| 68 | `save()` | PUT /api/state 持久化(含C1冲突处理，摘要态拒绝) |
| 152 | `hasLocalUnsavedChanges()` | JSON比较 data vs _baseData |
| 156 | `prepareBeforeDirectMutation()` | 照片上传/删除前:清debounce→等inFlight→存草稿 |
| 183 | `syncAfterDirectMutation()` | 照片上传/删除后:从服务器刷新 |
| 188 / 214 | `applySamplePhotosMutationResult()` / `invalidateSampleHistoryCache()` | 照片局部合并、履历缓存失效 |
| 273–295 | `fetchSamplePhotos()/fetchSampleEvents()/fetchSampleHistory()` | 样机照片/事件/履历按需加载 |
| 384 | `checkSampleIdentityConflicts()` | 调用 `/api/sample-identity-check` 服务端身份查重 |
| 309–335 | `fetchProjectSummary()/fetchStageTasksPage()/fetchSampleCategoriesSummary()/fetchSamplePage()` | 摘要/分页读取 API |
| 348–580 | `fetchProjectDetail()/fetchSampleCategoryDetail()/merge*/ensure*Loaded()` | 项目/样机池按需详情加载与本地合并 |
| 868 | `invalidatePagedCaches()` | 任务表/样机池分页缓存失效 |
| 899 | `taskSampleStatusBlockerMessage()` | 样机状态不可选错误提示 |
| 909 | `commitTaskMutation()` | 任务增量写入：任务/阶段/样机/样机事件；识别 `TASK_ALREADY_FINISHED`，并失效样机履历缓存 |
| 1035 | `commitProjectMutation()` | 项目增量写入/删除 |
| 1076 | `commitStageMutation()` | 阶段增量写入/删除/排序 |
| 1120 | `commitSampleMutation()` | 单台样机增量写入/删除，失效样机履历缓存 |
| 1161 | `commitSampleCategoryMutation()` | 样机池增量写入/销毁/批量新增样机 |
| 1238 | `ensureSampleHistoryLoaded()` | 样机履历分页加载与面板刷新 |

### js/app.data.js (811 行) — 数据工具与状态访问器

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `emptyData()` | 空状态模板 |
| 19 | `cloneData()` | JSON深拷贝 |
| 23 / 30 | `normalizePersonText()`, `projectActiveMembers()` | 人员工具 |
| 34 | `normalize()` | **数据修复入口**: 旧格式升级/成员去重/状态映射/problemRecords迁移 |
| 214 / 218 / 223 | `dataSnapshot()` / `restoreDataSnapshot()` / `patchViewState()` | 数据快照恢复与 view 状态补丁入口 |
| 317 / 357 / 444 | `homeMetrics()` / `navFingerprintData()` / `navigateModuleState()` | 全局渲染外壳的状态读写边界 |
| 370 / 376 / 398 / 404 | `projectRecords()` / `findProjectRecord()` / `appendProjectRecord()` / `removeProjectRecord()` | 项目域状态访问器 |
| 427 | `selectProjectWorkspaceState()` | 项目工作台选择状态入口 |
| 260 / 285 | `samplePoolPageState()` / `setSamplePoolFilterState()` | 样机池分页/筛选 view 状态访问器 |
| 482 / 488 / 498 / 504 | `ensureViewMap()` / `setViewMapValue()` / `resetViewMap()` / `resetTaskFlowPage()` | 筛选/分页 view map 状态访问器 |
| 514 | `taskFlowPageState()` | 任务表分页/筛选状态访问器 |
| 562 | `currentProject()` | 当前选中项目 |
| 565 | `currentStage()` | 当前选中阶段 |
| 569 | `allSamples()` | 所有样机(含categoryName) |
| 578 | `findSample(id)` | 返回`{category, sample}`或null |
| 585 / 586 | `projectName()`, `stageName()` | ID→名称 |
| 595 | `sampleProblemRecords()` | 样机问题表(规范化) |
| 612 | `sampleHasProblem()` | 是否有故障 |
| 622 | `sampleEffectiveStatus()` | 有效状态(含故障判定) |
| 626 / 642 / 652 | `normalizeSampleStatusValue()/repairSampleStatus()/clearSampleOccupancy()` | 样机状态/占用数据修复入口(不写业务日志) |
| 670 | `addSampleProblem()` | 追加样机问题(去重) |
| 716 | `changeSampleStatus()` | **样机状态业务变更统一入口**: 事件日志/borrower/owner/destLocation管理 |
| 757 | `activeTaskUsagesForSample()` | 样机活跃任务占用查询 |
| 770 | `reconcileSampleTaskOccupancy()` | 无活跃任务时清除占用标记 |
| 785 | `getProjectStageTask()` | 项目/阶段/任务三元组 |
| 792 | `isTaskCompleted()` | 任务是否完成(正常完成/异常终止/归档) |
| 799 | `isTaskExecuted()` | 任务是否已执行过(含进行中/阻塞中) |
| 806 | `isSampleUsedByAnotherOpenTask()` | 样机是否被其他未完成任务占用 |

### js/app.render.js (322 行) — 渲染引擎

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `render()` | 按 `viewModule()` 分发渲染 |
| 51 | `renderHome()` | 首页入口卡片，DOM API 渲染 |
| 94 | `renderNav()` | 左侧导航(项目子目录+样机池子目录)，DOM API 渲染 |
| 182 / 188 | `_navToggle()`, `_navGoSub()` | 导航展开/收起/跳转 |
| 201 / 210 / 228 | `renderHeader()` / `breadcrumbParts()` / `breadcrumbNodes()` | 顶部面包屑 DOM 渲染 |
| 247 | `go(module)` | 模块导航,离开策略页自动autoSyncProgress |
| 257 | `toggleSidebar()` | 侧栏折叠(localStorage持久化) |
| 277 / 288 | `isCollapsed()`, `toggleSection()` | 折叠面板 |
| 302 | `renderEmpty()` | 空状态 DOM 渲染 |
| 309 | `closeTaskOpMenus()` | 任务操作菜单统一关闭 |

### js/app.modal.js (241 行) — 弹窗系统

| 行号 | 函数 | 职责 |
|------|------|------|
| 26 | `showModal()` | **主弹窗**: onOk返回true=保持打开, 返回false/undefined=关闭 |
| 91 | `showConfirm()` | 独立确认框(支持异步确认回调) |
| 138 | `showAlert()` | 纯提示框(隐藏取消) |
| 155 | `closeModal()` | 关闭弹窗(modal stack弹出恢复) |
| 182 | `clearFieldValidationMarks()` | 清除所有.is-invalid+.field-error |
| 189 / 196 / 203 | `fieldErrorNode()` / `appendFieldError()` / `insertFieldErrorAfter()` | 表单错误 DOM 节点创建与安全插入 |
| 202 | `markFieldInvalid(el,msg)` | 标红+追加.field-error+自动滚动 |
| 223 | `showDangerConfirm()` | 危险操作确认(需输入DELETE关键词，支持异步确认回调) |

### js/app.filters.js (56 行)

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 / 12 | `setProgressFilter()`, `clearProgressFilters()` | 进度筛选，经 view map 访问器写入 |
| 16 / 23 | `setStageStrategyFilter()`, `clearStageStrategyFilters()` | 阶段策略筛选，经 view map 访问器写入 |
| 27 / 32 / 35 / 48 | `setTaskFlowFilter()`, `setTaskFlowTextFilter()`, `commitTaskFlowTextFilter()`, `clearTaskFlowFilters()` | 任务流筛选，经 view map 访问器写入并重置分页 |

### js/app.logs.js (181 行) — 日志系统

| 行号 | 函数 | 职责 |
|------|------|------|
| 30 | `addTaskLog()` | 任务日志写入 |
| 95 | `taskLogContentHtml()` | 日志内容HTML(含detailLines) |
| 187 | `linkSampleRefsInLogText()` | SN/IMEI→可点击链接 |
| 258 | `showTaskLogs()` | 任务日志弹窗 |

### js/projects.js (391 行) — 项目管理

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 / 107 | `renderProjectLoading()` / `renderProjects()` | 项目列表 DOM API 渲染，不直接写 `innerHTML` |
| 118 | `projectNameExists()` | 项目名唯一性(大小写不敏感) |
| 122 | `addProject()` | 新建项目弹窗(增量 API) |
| 174 | `editProject()` | 编辑项目弹窗(增量 API) |
| 222 | `collectProjectDeleteImpact()` | 删除影响分析 |
| 295 | `deleteProject()` | 删除项目(释放样机+showDangerConfirm+增量 API) |
| 371 | `selectProject()` | 进入项目工作台 |

### js/workspace/01-shared.js (253 行) — 跨模块共享

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 / 16 | `taskOwnerName()`, `taskOwnerId()` | 执行人姓名/工号提取 |
| 42 | `taskFlowStatus()` | **任务状态标准化**(5种标准值) |
| 52–108 | `taskStoredStatus()/repairTaskStatus()/setProgressStatus()/createProgressRecord()` | 任务/progress 状态与默认记录修复入口 |
| 113 | `transitionTaskStatus()` | **任务状态业务变更统一入口** |
| 129 | `syncProgressStatus()` | 任务状态→progress 状态同步入口 |
| 158 | `getProgressRequiredSampleCount()` | 读取所需样机数 |
| 172 | `projectMemberSelectHtml()` | `<select>`下拉生成(项目人员) |
| 192 | `statusForOpenTaskUsage()` | 活跃任务→样机状态映射 |
| 199 | `releaseTaskSamples()` | **释放任务占用样机**(检查其他任务占用) |
| 227–251 | `taskSampleDisplayName/ArchiveName/IdentityInfo` | 样机名称/标识 |

### js/workspace/02-home.js (484 行) — 工作台主页

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `renderProjectWorkspace()` | 主页渲染:阶段卡片+人员+位置+任务管理 |
| 215 | `workspaceMembersHtml()` | 人员配置区域 |
| 254 | `workspaceLocationsHtml()` | 位置配置区域 |
| 195–238 | `add/edit/removeProjectLocation()` | 位置 CRUD(增量 API) |
| 277–394 | `add/edit/removeProjectMember()` | 人员 CRUD(增量 API) |
| 434 | `importProjectMembersCsv()` | 人员CSV批量导入(增量 API) |
| 494 | `memberWorkStats()` | 人员工作统计 |
| 431–478 | 拖拽排序回调 | 阶段排序(增量 API) |

### js/workspace/10-dropdown-issue.js (260 行) — 用例下拉+问题单

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `openCaseDropdown()` | 打开用例搜索下拉，DOM API 构建 shell |
| 23 | `positionCaseDropdown()` | 下拉定位(自动上/下) |
| 60 / 76 / 82 | `caseDropdownShellNodes()` / `caseDropdownEmptyNode()` / `caseDropdownOptionNode()` | 用例下拉 DOM 节点 helper |
| 108 | `renderCaseDropdownOptions()` | 下拉选项渲染(含 mousedown 选择)，不直接写 `innerHTML` |
| 163 | `selectCaseSuggestion()` | 选择用例填充到策略输入框 |
| 198 | `taskIssueRecordHtml()` | 任务问题单展示(DTS/是否重复/备注) |
| 221 | `openTaskIssueRecordModal()` | 问题单录入弹窗 |

### js/workspace/03-strategy.js (331 行) — 阶段策略配置

| 行号 | 函数 | 职责 |
|------|------|------|
| 9 | `openStageStrategy()` | 进入策略页 |
| 36 | `persistStageStrategyMutation()` | 阶段策略/BOM 增量保存 |
| 43 | `scheduleStageStrategySave()` | 阶段策略/BOM 增量保存 debounce |
| 52 | `renderStageStrategyPage()` | 策略页渲染(阶段编辑+BOM+策略表) |
| 72–119 | `workspaceBomHtml/addBomRow/updateBom/deleteBomRow` | BOM上料清单(增量 API) |
| 122–198 | `workspaceStrategyHtml/addStrategyRow/onStrategyInput` | 测试策略表(增量 API) |
| 285 | `scheduleStrategySync()` | 800ms节流策略同步 |
| 326 | `autoSyncProgress()` | **策略→进度自动同步**(离开策略页时触发，增量 API) |
| 369 | `importTestCaseXlsx()` | 用例集导入(项目增量 API) |

### js/workspace/04-stage.js (364 行) — 阶段与SKU编辑

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `inlineStageEditorHtml()` | 策略页内联编辑器(SKU管理) |
| 30 / 150 | `inlineSkuRowNode()` / `skuRowNode()` | 新增 SKU 行 DOM helper，不直接写 `innerHTML` |
| 54 | `persistCurrentStageMutation()` | 阶段名/SKU 内联编辑增量保存 |
| 138 | `skuEditorHtml()` | 弹窗版SKU编辑器 |
| 191 | `addStage()` | 新建阶段弹窗(增量 API) |
| 229 | `editStage()` | 编辑阶段弹窗(增量 API) |
| 260 | `deleteStage()` | 删除阶段(安全机制:占用样机时拒绝，增量 API) |
| 309 | `copyStage()` | 复制阶段(含strategy/progress深层克隆，增量 API) |

### js/workspace/05-task-table.js (528 行) — 任务表格

| 行号 | 函数 | 职责 |
|------|------|------|
| 53 | `taskFlowPagerHtml()` | 任务分页条，含 loading/disabled 状态 |
| 83 | `taskFlowQueryParams()` | 从筛选器生成服务端分页查询参数 |
| 98 | `taskFlowCacheKey()` | 任务分页缓存 key |
| 166 | `loadTaskFlowPage()` | 拉取 `/api/stages/<stageId>/tasks` 并合并本地任务 |
| 187 | `workspaceTaskFlowHtml()` | **任务管理工作台**:服务端分页统计+筛选栏+表格+新增按钮 |
| 356 | `taskDeleteImpactHtml()` | 任务删除影响分析 |
| 420 | `taskFlowActionsHtml()` | **操作按钮**:按状态显示不同按钮组合 |
| 494 | `showTaskSamples()` | 任务样机清单弹窗 |
| 575 | `sampleTestedItemNames()` | 样机已测项目列表 |

### js/workspace/06-sample-picker.js (485 行) — 样机选择器

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `getSelectedTaskSampleIds()` | 读取勾选样机ID |
| 58 | `buildTaskSamplePickerHtml()` | **样机选择器HTML骨架**：不枚举 `allSamples()`，只创建分页候选容器和已选状态 |
| 65 | `initTaskSamplePicker()` | 弹窗打开后加载第一页候选样机 |
| 85 | `loadTaskSamplePickerPage()` | 调用 `/api/task-sample-candidates`，服务端分页/搜索/状态筛选并合并已返回样机 |
| 246 | `taskSamplePickerSampleRowHtml()` | 候选/已选样机行渲染，使用后端 `selectable/disabledReason` |
| 309 | `validateTaskSampleSelection()` | 样机数量校验 |
| 317 | `setTaskSampleLimitHintContent()` | 样机数量提示 DOM 更新 helper |
| 327 | `updateTaskSampleLimitUI()` | 计数胶囊(warn/bad/full状态) |
| 376 | `onTaskSampleCheckboxChange()` | 勾选状态写入分页选择器 state，跨页保留已选样机 |
| 409 | `onTaskSampleRowClick()` | 整卡点击切换勾选，链接/表单控件不触发 |
| 454 | `filterDispatchGroup()` | 旧分组搜索兼容函数 |
| 472 | `isTaskChangePayloadChanged()` | 变更检测(计划+样机) |

### js/workspace/07-task-config.js (577 行) — 任务配置弹窗

| 行号 | 函数 | 职责 |
|------|------|------|
| 15 | `resolveTaskProgress()` | 解析progress(live vs snapshot) |
| 31 | `createTaskFromProgress()` | 从progress创建任务 |
| 68 | `openAddTasksFromPoolModal()` | 从测试池批量新增任务(增量 API) |
| 191 | `assignPlanTaskSamples()` | 待下发任务样机分配/重分配(增量 API) |
| 244 | `setPlanTaskSchedule()` | 待下发任务计划时间/执行人配置(增量 API) |
| 320 | `taskConfigTitlebarNode()` | 任务配置弹窗标题 DOM helper |
| 335 | `openTaskConfigPanel()` | **新版双Tab配置弹窗入口** |
| 378 | `taskConfigPanelHtml()` | 弹窗外壳(导航+面板) |
| 401 | `taskPlanConfigPanelHtml()` | 计划配置Tab |
| 426 | `taskSampleConfigPanelHtml()` | 样机配置Tab |
| 443 | `saveTaskConfigAll()` | **统一保存**:plan+sample校验+增量写入 |
| 544 | `hasUnsavedTaskConfigChanges()` | 未保存检测(取消按钮用) |
| 564 | `switchTaskConfigTab()` | Tab切换 |

### js/workspace/08-task-actions.js (434 行) — 任务操作

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `deleteTask()` | 删除任务(已执行→归档,未执行→物理删除) |
| 55 | `startTask()` | **启动任务**:校验→确认→改状态→日志 |
| 106 | `taskFailureProblemsBySample()` | 任务范围内样机问题收集 |
| 151 | `taskFailureStats()` | 失效统计(active/removed×fail/pass) |
| 211 | `taskIssueSummaryHtml()` | **测试结果列HTML**:失效比例+问题清单 |
| 259 | `tempChangeTask()` | **临时变更**:执行人/计划/样机变更+差异日志 |
| 406 | `blockTask()` | 阻塞任务:校验→确认→改状态→日志 |

### js/workspace/09-task-result.js (840 行) — 结果录入

| 行号 | 函数 | 职责 |
|------|------|------|
| 31 | `onTaskResultDestinationChange()` | 去向切换(取走分析→取走人必填) |
| 85 | `recordTaskRemovedSamples()` | 记录退出样机 |
| 108 | `taskResultSampleEntries()` | 合并active+removed样机 |
| 161 / 252 | `taskResultProblemEmptyNode()` / `taskResultPhotoChipNode()` | 问题空态与结果图片 chip DOM helper |
| 179 | `taskResultSampleRowsHtml()` | 每台样机结果行(去向/位置/取走人/挂账人/问题) |
| 285 | `uploadTaskResultPhotos()` | 结果图片上传(multipart→服务器→刷新) |
| 348 | `collectTaskResultForm()` | **表单收集**:遍历所有.task-result-sample-row |
| 385 | `validateTaskResultPayload()` | 结果验证 |
| 436 | `taskResultAutoReason()` | 自动生成结果摘要(≤500字符) |
| 522 | `applyTaskResult()` | **应用结果**:改状态/写日志/追加resultUploads |
| 650 | `restoreTaskResultSaveSnapshot()` | 结束任务保存失败时回滚本地乐观更新 |
| 657 | `refreshTaskAfterAlreadyFinished()` | 服务端提示任务已结束时按需刷新当前项目详情 |
| 676 | `saveTaskResult()` | **保存/结束入口**:draft vs finish分支；结束任务含 in-flight 防重 |
| 746 | `uploadResult()` | **结果录入弹窗**:任务级结果+每台样机去向；结束按钮 async 等待并禁用 |

### js/samples/ — 样机档案池（已拆分）

| 文件 | 行数 | 主要职责 |
|------|------|------|
| `js/samples.js` | 4 | 兼容占位，实际实现由 `index.html` 加载子模块 |
| `js/samples/01-pool.js` | 1103 | 样机池服务端摘要/分页、分页缓存/加载态/相邻页预取、样机卡片、池/样机 CRUD、销毁影响分析；分页/筛选/回滚走状态访问器；新增样机走服务端身份查重；单台/整池销毁走增量 API |
| `js/samples/02-import-export.js` | 283 | 样机批量导入(增量 API)/导出、本批次重复过滤、服务端 SN/IMEI/主板SN 身份查重；样机池枚举走状态访问器 |
| `js/samples/03-detail-fields.js` | 153 | 样机详情字段、人名输入、位置输入、初检问题解析、重组来源展示；位置/重组来源走状态访问器 |
| `js/samples/04-photos.js` | 344 | 照片上传、缩略图生成、预览、重命名、删除；照片预览/重命名行使用 DOM helper |
| `js/samples/05-problems.js` | 137 | 样机问题表多行编辑 UI；新增行使用 DOM helper |
| `js/samples/06-history.js` | 212 | 样机测试履历分页渲染、结果图片、只读快照；本地兜底走状态访问器 |
| `js/samples/07-detail.js` | 192 | 样机详情 5 Tab 弹窗；编辑样机身份走服务端查重 |

### js/debug/auditConsistency.js (191 行)

| 行号 | 函数 | 职责 |
|------|------|------|
| 33 | `auditConsistency()` | 浏览器控制台只读审计(占用冲突/孤立progress/缺失样机/状态不一致/重复ID) |

---

## 功能 → 代码速查

想修改某行为？直接跳到对应位置:

| 要改什么 | 文件:函数(行号) |
|----------|-----------------|
| 后端端口/地址 | `server.py:5778-5779` |
| 最大上传体积 | `server.py:48` `MAX_UPLOAD_BYTES` |
| backup频率/数量 | `server.py:197-210` |
| 数据库表结构 | `server.py:401` `ensure_schema()` |
| 样机/任务状态枚举 | `js/app.core.js:37-38` |
| 状态变更统一入口 | `js/app.data.js:716` `changeSampleStatus()` |
| 任务状态标准化 | `js/workspace/01-shared.js:42` `taskFlowStatus()` |
| 数据规范化(旧格式修复) | `js/app.data.js:34` `normalize()` |
| 三向合并(服务端) | `server.py:1373` `merge_state()` |
| 保存流程(前端) | `js/app.server.js:68` `save()` |
| 保存流程(后端) | `server.py:5494` `save_state()` |
| 样机占用冲突C1(后端) | `server.py:5449` `detect_sample_occupancy_conflicts()` |
| 样机占用冲突C1(前端) | `js/app.server.js:85-98` |
| 弹窗onOk行为 | `js/app.modal.js:26` `showModal()` (返回true=保持打开) |
| 内联校验标红 | `js/app.modal.js:213` `markFieldInvalid()` / `:185` `appendFieldError()` / `:192` `insertFieldErrorAfter()` |
| DELETE确认弹窗 | `js/app.modal.js:223` `showDangerConfirm()` |
| Toast提示 | `js/utils.js:24` |
| HTML转义 | `js/utils.js:7` `esc()` |
| 人员格式校验 | `js/utils.js:202` `parsePersonField()` |
| 人员下拉生成 | `js/workspace/01-shared.js:172` `projectMemberSelectHtml()` |
| 样机释放 | `js/workspace/01-shared.js:199` `releaseTaskSamples()` |
| 样机新增校验 | `js/samples/01-pool.js:1233` `addSample()` + `POST /api/sample-identity-check` |
| 样机去重系统 | `js/samples/02-import-export.js:8` `importSampleBatch()` / `:252` `_checkServerIdentityDuplicate()` / 后端 `server.py:2868` `check_sample_identity_conflicts()` |
| 样机详情弹窗 | `js/samples/07-detail.js:8` `openSampleDetail()` |
| 样机照片上传(前端) | `js/samples/04-photos.js:228` / 后端 `server.py:5630` `commit_sample_asset_mutation()` |
| 样机批量导入 | `js/samples/02-import-export.js:8` `importSampleBatch()` |
| 样机测试履历 | `js/samples/06-history.js:102` `sampleTestHistoryHtml()` / 后端 `server.py:3021` `GET /api/samples/<id>/history` |
| 阶段卡片渲染 | `js/workspace/02-home.js:52-99` |
| 项目人员CRUD | `js/workspace/02-home.js:277-394` |
| 项目位置CRUD | `js/workspace/02-home.js:195-238` |
| 阶段CRUD | `js/workspace/04-stage.js:149-266` |
| 阶段复制 | `js/workspace/04-stage.js:309` `copyStage()` |
| BOM上料清单 | `js/workspace/03-strategy.js:54-104` |
| 测试策略表 | `js/workspace/03-strategy.js:107-166` |
| 策略→进度同步 | `js/workspace/03-strategy.js:326` `autoSyncProgress()` |
| 用例下拉搜索 | `js/workspace/10-dropdown-issue.js:8-163` |
| 任务表格渲染 | `js/workspace/05-task-table.js:187` `workspaceTaskFlowHtml()` |
| 任务筛选器 | `js/app.filters.js:8-56` |
| 任务操作按钮 | `js/workspace/05-task-table.js:420` `taskFlowActionsHtml()` |
| 任务配置弹窗(新版) | `js/workspace/07-task-config.js:320-564` |
| 任务配置CSS | `css/33-task-config-modal.css` |
| 样机选择器UI | `js/workspace/06-sample-picker.js:58` `buildTaskSamplePickerHtml()` / `:85` `loadTaskSamplePickerPage()` |
| 样机选择整卡点击 | `js/workspace/06-sample-picker.js:409` `onTaskSampleRowClick()` |
| 样机新增状态兜底 | 前端 `js/workspace/06-sample-picker.js:247` 使用后端可选性字段；后端 `server.py:6203` `detect_task_mutation_sample_status_blockers()` |
| 样机选择器CSS | `css/34-sample-picker.css` |
| 任务启动 | `js/workspace/08-task-actions.js:55` `startTask()` |
| 任务阻塞 | `js/workspace/08-task-actions.js:406` `blockTask()` |
| 任务临时变更 | `js/workspace/08-task-actions.js:259` `tempChangeTask()` |
| 任务删除 | `js/workspace/08-task-actions.js:8` `deleteTask()` |
| 测试结果列 | `js/workspace/08-task-actions.js:211` `taskIssueSummaryHtml()` |
| 结果录入弹窗 | `js/workspace/09-task-result.js:746` `uploadResult()` |
| 结果表单收集 | `js/workspace/09-task-result.js:348` `collectTaskResultForm()` |
| 结果应用 | `js/workspace/09-task-result.js:522` `applyTaskResult()` |
| 结束任务防重复 | 前端 `js/workspace/09-task-result.js:676` `saveTaskResult()`；后端 `server.py:6184` `existing_finished_task()` |
| 结果图片上传 | `js/workspace/09-task-result.js:285` |
| 问题单录入 | `js/workspace/10-dropdown-issue.js:221` |
| 任务日志展示 | `js/app.logs.js:258` `showTaskLogs()` |
| 导航栏渲染 | `js/app.render.js:94` `renderNav()` |
| 侧栏折叠 | `js/app.render.js:257` `toggleSidebar()` |
| 首页 | `js/app.render.js:51` `renderHome()` |
| 项目删除影响分析 | `js/projects.js:222` `collectProjectDeleteImpact()` |
| 一致性审计(浏览器) | `js/debug/auditConsistency.js:33` |
| 静态文件白名单 | `server.py:5306` |
| 照片文件存储 | `data/samples/<sampleId>/photos/` |

---

## CSS 架构

```
css/style.css              → @import 总入口
├── 00-vars.css            → CSS变量(颜色/字体/圆角/阴影) — 26行
├── 01-layout.css          → body/sidebar/topbar/content — 248行
├── 02-components.css      → button/input/table/badge/card/modal/toast — 438行
├── 20-samples.css         → 样机卡片/问题行 — 454行
├── 21-sample-photos.css   → 样机照片/履历图片/预览 — 276行
├── 22-sample-archive.css  → 样机详情/履历布局 — 209行
├── 30-workspace-home.css  → 阶段卡片 — 213行
├── 30-workspace-members.css → 项目人员/位置 — 213行
├── 30-workspace-sections.css → 工作台区块/内联编辑 — 168行
├── 31-stage-strategy.css  → BOM/策略表 — 106行
├── 32-task-flow.css       → 任务汇总/主表 — 298行
├── 32-task-issue-record.css → 问题单/更多菜单 — 215行
├── 32-task-flow-actions.css → 任务操作按钮 — 88行
├── 33-task-config-modal.css → 任务配置双Tab弹窗 — 363行
├── 34-sample-picker.css   → 样机选择器(dispatch-sample-*) — 213行
├── 35-task-result.css     → 结果样机行/问题/图片 — 240行
├── 35-task-result-modal.css → 结果弹窗布局/校验 — 287行
├── 35-task-sample-list.css → 任务样机清单 — 268行
├── 36-task-log.css        → 任务日志 — 116行
└── 90-responsive.css      → 响应式 — 18行
```

### 关键CSS类→功能映射

| CSS选择器 | 用途 | 位置 |
|-----------|------|------|
| `.sidebar`, `.sidebar.collapsed` | 侧栏+折叠 | `01-layout.css` |
| `.modal`, `.modal-mask` | 弹窗 | `02-components.css` |
| `.sample-archive-shell/.nav/.content` | 样机详情扁平布局 | `22-sample-archive.css` |
| `.sample-photo-preview-mask` | 照片全屏预览 | `21-sample-photos.css` |
| `.stage-summary-card` | 阶段卡片 | `30-workspace-home.css` |
| `.task-flow-table` | 任务表格 | `32-task-flow.css` |
| `.task-config-shell/.nav/.main` | 任务配置弹窗布局 | `33-task-config-modal.css:51-107` |
| `#tcPanelSample .dispatch-sample-group` | 任务配置中样机池组 | `33-task-config-modal.css:239` |
| `.sample-limit-global` | 样机计数胶囊 | `33-task-config-modal.css:173` |
| `.dispatch-sample-row` | 样机选择行 | `34-sample-picker.css:20` |
| `.task-result-sample-row` | 结果录入样机行 | `35-task-result.css` |
| `.task-result-route-grid` | 结果去向网格 | `35-task-result.css` |

---

## 数据模型

```js
// app.data 顶层结构
{
  version: "V7",
  currentProjectId, currentStageId,
  projects: [{
    id, name, code, owner,
    stages: [{
      id, name,
      skuNames: ["SKU1", ...],
      bom: [{ materialName, sku1, sku2, ... }],
      strategy: [{ id, category, item, sampleSize, skuMap }],
      progress: [{ id, strategyId, category, testItem, skuIndex, sampleSize, status, ... }],
      tasks: [{
        id, progressId, category, testItem, skuIndex,
        owner, planStartDate, planEndDate,
        status, completed, archived,
        sampleIds: [...],
        removedSampleRecords: [...],    // 临时变更/销毁退出的样机
        sampleFaultRecords: [...],      // 本任务记录的故障
        resultUploads: [...],           // 结果上传历史
        resultDraft: {...},             // 当前草稿
        logs: [...],                    // 任务操作日志
        issueRecord: { dtsNo, isIssue, issueNote }
      }]
    }],
    members: [{ id, name, employeeNo, active }],
    locations: ["位置A", ...]
  }],
  sampleLibrary: {
    categories: [{
      id, name, description,
      samples: [{
        id, sampleNo, sn, imei, boardSn, status, location, owner, borrower,
        sourceStageName, sourceSkuName,
        problemRecords: [{ id, description, source, taskLabel }],
        photos: [{ id, name, url, type, size, uploadedAt }],
        logs: [...],
        currentProjectId, currentStageId, currentTaskId, currentTestItem  // 占用追踪
      }]
    }],
    logs: []  // 全局样机事件日志(与sample.logs双写)
  }
}
```

### 状态机

```
样机: 闲置 ←→ 在位等待 ←→ 测试中
       ↓         ↓          ↓
     已退库   取走分析   故障(problemRecords判定)

任务: 待下发 → 进行中 ⇄ 阻塞中 → 正常完成 / 异常终止
```

---

## 编码约定速查

- **HTML转义**: 所有用户输入必须经 `Utils.esc()` (`utils.js:7`)
- **弹窗校验**: 失败 `return true`(保持打开), 成功 `return;`或不返回
- **内联校验**: `clearFieldValidationMarks()` → `markFieldInvalid(el, msg)` / `appendFieldError()` / `insertFieldErrorAfter()` (`app.modal.js:171-206`)
- **持久化**: `app.save()` 立即, `app.scheduleSave()` 450ms debounce
- **样机状态**: 业务变更必须 `app.changeSampleStatus()` (`app.data.js:716`)，数据修复仅用 `app.repairSampleStatus()`
- **任务状态读取**: `app.taskFlowStatus(t)` 标准化 (`01-shared.js:42`)
- **任务状态变更**: 业务变更必须 `app.transitionTaskStatus()` (`01-shared.js:113`)，默认/修复仅用 `app.repairTaskStatus()`
- **唯一ID**: `Utils.id(prefix)` (`utils.js:13`)
- **人员格式**: 统一 `姓名/工号`, 如 `张三/00609513`
- **加载顺序**: `index.html:69-89` 中 script 标签顺序；业务文件通过 `app.registerModule(name, members)` 注册到全局 `app`

---

## 技术债务（已知问题）

> 复核时间：2026-06-04。基于 `server.py`、`index.html`、`js/**`、`css/**`、`tests/**`、`tools/**` 的全量扫描与关键路径抽查。

### 已复核完成

1. ~~**workspace.js 过大** (3594行)~~ ✅ 已解决 — 已拆分为 `js/workspace/01-shared.js` 至 `10-dropdown-issue.js` 共 10 个模块。
2. ~~**samples.js 中 openSampleReadonly 与 app.render.js 重复定义**~~ ✅ 已解决 — 代码扫描确认仅 `js/samples/06-history.js:180` 保留 `openSampleReadonly()`。
3. ~~**`saveTaskPlanConfig()` / `saveTaskSampleConfig()` 死代码**~~ ✅ 已解决 — 旧版单独保存函数已删除，当前由 `js/workspace/07-task-config.js:443` `saveTaskConfigAll()` 统一保存。
4. ~~**完全没有自动化测试入口**~~ ✅ 已缓解 — 已新增 `tests/test_server_core.py` 覆盖后端三向合并/样机占用冲突，新增 `tests/frontend_status_transitions.test.cjs` 覆盖前端状态流转工具和样机状态入口。
5. ~~**照片无缩略图链路**~~ ✅ 已解决 — 前端上传时生成 JPEG 缩略图，服务端保存 `photo` + `photo_thumb` 资产，列表/履历优先显示 `thumbUrl`，预览仍打开原图。
6. ~~**samples.js 最大模块**~~ ✅ 已解决 — `js/samples.js` 仅保留兼容占位，实际拆分到 `js/samples/01-*.js` 至 `07-detail.js`。
7. ~~**样机日志双写 sample.logs/sampleLibrary.logs**~~ ✅ 已解决 — `eventSchema=sample_events_v2` 后样机对象不再保存 `logs`，样机事件只写 `sampleLibrary.logs` 并由后端落 `sample_events`。
8. ~~**CSS 超大文件集中堆叠 / 补丁化**~~ ✅ 已解决 — 样机、工作台、任务流、结果录入 CSS 已按功能拆分，最大相关 CSS 文件降到 454 行；全 `css/**` 的 `!important` 已从 37 处清理到 0 处。
9. ~~**XLSX 解析依赖浏览器能力**~~ ✅ 已解决 — `Utils.unzipXlsxFiles()` 仍优先使用 `DecompressionStream("deflate-raw")`，旧浏览器无该能力时走 `inflateRawBytesFallback()` 纯 JS raw deflate 解压。
10. ~~**样机状态统一入口仍需继续收敛**~~ ✅ 已解决 — 业务入口为 `changeSampleStatus()`；`normalize()` / `reconcileSampleTaskOccupancy()` 的数据修复入口拆为 `repairSampleStatus()` 与 `clearSampleOccupancy()`，不写业务事件日志。
11. ~~**任务状态与 progress 状态已部分收口但未完成**~~ ✅ 已解决 — `transitionTaskStatus()` 复用 `repairTaskStatus()`，progress 状态统一经 `setProgressStatus()`；策略新增 progress 使用 `createProgressRecord()`，任务配置默认状态不再直接写入。
12. ~~**照片重命名审计表名不一致**~~ ✅ 已解决 — `server.py` 照片重命名 PATCH 已统一写入 `audit_log`，不再写不存在的 `change_log`。
13. ~~**照片上传/删除后前端全量刷新**~~ ✅ 已缓解 — 样机照片上传/删除、任务结果图片上传成功路径已改为 `applySamplePhotosMutationResult()` 局部合并返回的 `photos/revision`，不再触发 `/api/state`。
14. ~~**任务/样机增量变更后大列表整页刷新**~~ ✅ 已缓解 — `commitTaskMutation()` / `commitTaskBatchMutation()` 成功后只刷新当前任务分页并局部替换 `taskFlowShell`；`commitSampleMutation()` / `commitSampleCategoryMutation()` 成功后只刷新当前样机分页并局部替换 `samplePageShell`，已补前端回归确认不触发 `/api/state` / 全量 render。
15. ~~**数据包导入成功后前端全量 state 刷新**~~ ✅ 已缓解 — `commit_import_bundle()` 返回 `mutationSummary`，`_onImportCommit()` 成功路径改为 `applyImportBundleMutationResult()` 局部刷新摘要、受影响项目详情、当前任务页和当前样机页；完整 `/api/state` 仅保留为异常兜底。
16. ~~**任务样机选择器一次加载和渲染全部候选样机**~~ ✅ 已缓解 — 新增 `GET /api/task-sample-candidates` 和 `project_task_samples` 关联表；前端选择器改为服务端分页/搜索/状态筛选，已选样机跨页保留，候选行使用后端 `selectable/disabledReason`，不再枚举 `allSamples()`。
17. ~~**照片/结果图片后端仍依赖旧式直接变更同步**~~ ✅ 已解决 — 照片/结果图上传和照片删除改为 `commit_sample_asset_mutation()` 资产级提交，只更新 `sample_assets`、样机 `updatedAt`、revision 和 `audit_log`，测试禁止该路径 `compose_state()`；照片上传/删除/重命名数据库变更已改用 SQLite `BEGIN IMMEDIATE` 写事务，照片上传文件写入和照片删除文件 unlink 已移到 DB 提交临界区外。
18. ~~**样机全局查重仍在前端全量扫描**~~ ✅ 已解决 — 新增 `sample_records.board_sn/is_reassembled` 查询列和 `POST /api/sample-identity-check`；新增样机、编辑身份和批量导入查重不再触发完整样机库加载。
19. ~~**样机测试履历仍依赖前端全局任务扫描**~~ ✅ 已解决 — 新增 `GET /api/samples/<id>/history` 服务端分页聚合；`sampleTestHistoryHtml()` 只渲染服务端缓存页，不再遍历本地 `projects/stages/tasks`。

### 本轮修复后仍需关注

1. **全局 app 混入已修复，状态所有权继续拆分中** — 业务 JS 已从 `Object.assign(app, {...})` 迁移到 `app.registerModule(name, members)`，并有架构测试防回退；项目域、全局渲染外壳、筛选模块、调试审计、样机详情字段、样机导入导出、样机履历、工作台主页、阶段策略、阶段 CRUD、任务表、样机选择器、结果录入、任务配置、任务动作、问题单模块和样机池主干已通过 `app.data.js` 状态访问器或快照隔离。当前扫描只剩 `js/app.data.js` / `js/app.core.js` / `js/app.server.js` 这些核心状态/兼容层直接访问 `this.data` / `this.view`；后续重点是把核心层继续拆成更明确的 store/service，而不是业务模块继续裸读写。
2. **自动化测试覆盖仍需继续补强** — 当前已有核心后端、导入冲突、照片路由、照片资产级提交、样机身份查重、样机履历分页、前端状态流转、分页性能、样机导入服务端查重、履历不扫本地 projects、增量变更后局部刷新、导入成功后局部同步和架构护栏；尚未覆盖结果录入表单、任务临时变更、SQLite 持久化迁移和浏览器端完整交互回归。
3. **全量 state 兼容入口已收窄但仍保留低频路径** — 前端只允许通过 `fullStateUrl(reason)` / `reloadFromServer()` 手动调试调用 `/api/state`，业务模块禁止调用 `app.save()` / `scheduleSave()`，`ensureFullStateLoaded()` 已移除；后端记录 compat reason 并警告无 reason 请求；`save_state()` 当前态快照已不再加载全量样机照片，写入改用 SQLite 写事务，compact 保存回归覆盖旧照片和事件保留；样机/样机池销毁影响分析已改成 `/api/sample-destroy-impact` + 按需项目/样机池详情加载；导入提交已改为专用写入函数，不再二次进入 `save_state()` / `compose_state()`；导入异常兜底和调试仍可能触发完整 `compose_state()`。
4. **内联事件模板属性与 `insertAdjacentHTML` 已清零，业务模块直接 `innerHTML` 已集中治理** — 当前 `index.html` 与 `js/**` 扫描无 `on*=` 模板属性和 `insertAdjacentHTML`，已迁移为 `data-app-action` 事件委托并由架构测试防回退；直接 `innerHTML` 只允许出现在 `js/app.core.js` 的 `replaceHtml()` 受控入口，业务模块通过该入口替换局部/整页模板，弹窗堆栈改用 DOM clone 保存/恢复；`js/projects.js` 主列表和 `js/app.render.js` 首页/导航/面包屑外壳已改为 DOM API 渲染，分别由 `tests/frontend_project_boundary.test.cjs` 与 `tests/frontend_render_shell.test.cjs` 覆盖。仍需长期治理的是大块 UI 模板字符串本身，后续应继续拆成节点构造或小组件以降低转义和局部更新成本。
5. **增量 mutation 返回已补 affected summary，当前页可直接 patch** — 任务、批量任务、项目、阶段、样机、样机池 PATCH 已返回受影响摘要、compact 任务行和样机卡片；无筛选当前页且 affected 覆盖可见行/卡片时前端直接 patch 当前页缓存和 DOM，筛选页、新增/删除、truncated affected 继续分页复查以保证正确性。
6. **导入导出内存风险已缓解，提交链路仍有完整 incoming state merge** — HTTP 导出已改为临时 zip 文件流式发送，导入预览缓存有 TTL、条数、总字节和 `state.json` 上限；导入预览对比主库时已改用 compact snapshot，不再拉取主库照片/事件数组；`_IMPORT_PREVIEWS` 当前只保存轻量元数据和 `_payload_path`，完整 incoming state 与 preview result 已落到临时目录 `preview_payload.json`，提交时按需读取；导入提交主库快照已改用 compact，并只为合并导入照片的既有样机按需补读当前照片；导入提交 stale-preview revision check 已改为 metadata-only，不再为过期预览拼完整 state。导入提交仍围绕导入包 `state.json` merge，大包场景后续应继续评估分块预览、进度反馈和临时目录清理。
7. **数据库全局锁已从运行期业务读写拆出，SQLite 写事务仍需压测** — bootstrap、摘要、详情、分页、候选、照片/事件/履历读取、身份查重以及 `get_state()` / `get_state_metadata()` 不再持有全局 `DB_LOCK`，完整 state 读取改用 SQLite read snapshot；任务/批量任务/样机/项目/阶段/样机池增量提交、照片上传/删除/重命名数据库变更、`save_state()` 兼容保存和导入提交链路都改用 SQLite `BEGIN IMMEDIATE` 写事务，不再持有全局 Python 锁；任务提交后的 backup 也改为无锁 compact 只读快照；照片上传文件写入、照片删除文件 unlink、样机销毁资产 unlink、样机池销毁资产 unlink 已移到 DB 提交临界区外；已新增 `tools/concurrency_benchmark.py` 做临时库并发读写 smoke，并用报错 `DB_LOCK` 验证运行期路径无全局锁依赖；已新增 `tools/http_concurrency_benchmark.py` 启动真实 `ThreadingHTTPServer` 并发覆盖分页/摘要、照片上传/删除、`/api/export-bundle`、导入预览和导入提交。后续仍需要目标数据量压测 SQLite 写事务排队、导入提交耗时和进度反馈。
8. **AGENTS 文件地图漂移已有刷新工具** — 已新增并运行 `tools/update_agents_map.py`；较大改动后运行该脚本并复核 diff，避免定位表再次按旧行号指导 agent。
