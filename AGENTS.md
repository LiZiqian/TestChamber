# TestChamber V7 — 数字治理平台 · AI 代码定位器
（本文件不允许 claude code 修改/编辑/删除，本文件只允许 codex 进行编辑修改，该规则只适用于本文件）

> **用途**：让 AI agent 快速定位需要修改的代码。每个函数、CSS 规则组、API 端点都标注 `文件:行号`。

## 项目概要

| 项目 | 值 |
|------|-----|
| 应用 | 数字治理平台 V7 |
| 用途 | 终端硬件测试样机全生命周期：项目→阶段→任务→样机→结果 |
| 部署 | Python stdlib `ThreadingHTTPServer`，端口 9398，SQLite WAL |
| 前端 | Vanilla JS SPA，`Object.assign(app, {...})` 模块模式 |
| 规模 | ~18,000+ 行源码；`server.py` 约 6,023 行，已扩展到 SQLite 外置表、数据包导入导出、照片/事件按需加载、任务/项目/阶段/样机增量写入、分页查询索引、关键 P0 幂等兜底与空白平台整包导入兜底 |

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
- `v7.1.0` 是本轮性能和导航响应优化版本。
- 以后更新版本时，同步修改 `server.py` 的 `APP_VERSION` / `SERVER_VERSION`、`js/app.core.js` 的 `app.version`，并把 `index.html` 与 `css/style.css` 的静态资源 cachebuster 改为同一个语义版本号。
- 发布前运行：`python -m py_compile server.py`、`python tests\test_server_core.py`、`python tests\test_import_conflicts.py`、`node tests\frontend_pagination_perf.test.cjs`、`node tests\frontend_status_transitions.test.cjs`。
- 发布流程：提交到 `main`，推送 `origin main`，创建并推送 `vX.Y.Z` tag，再用 `gh release create vX.Y.Z --verify-tag --title "TestChamber V7 X.Y.Z" --notes "..."` 创建 GitHub Release。
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
| 全量 state 拼装 | `server.py:2446` `compose_state()` |
| 全量 state 读取 | `server.py:2492` `get_state()` / `server.py:5323` `Handler.do_GET()` `/api/state` |
| 全量 state 保存 | `server.py:4000` `save_state()` / `server.py:5748` `Handler.do_PUT()` `/api/state` |
| SQLite schema / 索引 | `server.py:349` `ensure_schema()`；`server.py:311` `ensure_table_column()`；`server.py:317` `backfill_query_state_columns()` |
| 查询状态列 | `project_tasks.flow_status`、`sample_records.effective_status/has_problem`，用于状态筛选与统计避免整表 JSON 解析 |
| 项目/阶段/任务外置同步 | `server.py:1304` `sync_project_library()` |
| 项目/阶段/任务加载 | `server.py:1486` `load_project_library()` |
| 样机库加载 | `server.py:1075` `load_sample_library(include_photos/include_logs)` |
| 照片按需加载 | `server.py:1002` `load_sample_photos()` + `GET /api/samples/<id>/photos` |
| 事件按需加载 | `server.py:1057` `load_sample_events()` + `GET /api/samples/<id>/events` |
| 启动骨架 API | `server.py:2413` `compose_bootstrap_state()` + `GET /api/bootstrap` |
| 项目/样机池按需详情 API | `server.py:1577` `load_project_detail()` / `server.py:2312` `load_sample_category_detail()` |
| 分页参数解析 | `server.py:1668` `parse_page_params()` |
| 阶段任务分页 API | `server.py:1839` `list_stage_tasks_page()` + `GET /api/stages/<stageId>/tasks` |
| 样机池分页 API | `server.py:2168` `list_samples_page()` + `GET /api/sample-categories/<catId>/samples` |
| 项目摘要 API | `server.py:2371` `list_project_summary()` + `GET /api/projects/summary` |
| 样机池摘要 API | `server.py:2132` `list_sample_categories_summary()` + `GET /api/sample-categories` |
| 项目记录增量 upsert/delete | `server.py:4239` `update_project_record()` / `server.py:4298` `delete_project_record()` |
| 阶段记录增量 upsert/delete | `server.py:4315` `update_stage_record()` / `server.py:4373` `delete_stage_record()` |
| 样机池记录增量 upsert/delete | `server.py:4389` `update_sample_category_record()` / `server.py:5081` `delete_sample_category_record()` |
| 任务增量写入 API | `server.py:4698` `commit_task_mutation()` + `server.py:5646` `Handler.do_PATCH()` |
| 批量任务增量写入 API | `server.py:4794` `commit_task_batch_mutation()` + `PATCH /api/stages/<stageId>/tasks/batch` |
| 任务记录增量 upsert | `server.py:4167` `upsert_task_record()` |
| 任务记录增量删除 | `server.py:4234` `delete_task_record()` |
| 样机记录增量更新/创建 | `server.py:4446` `update_sample_record(create_if_missing)` |
| 样机事件增量 upsert | `server.py:4517` `upsert_sample_events()` |
| 任务结束幂等兜底 | `server.py:4631` `existing_finished_task()`；重复 `finish_task_result` 返回 `409 TASK_ALREADY_FINISHED` |
| 样机新增选择状态兜底 | `server.py:4650` `detect_task_mutation_sample_status_blockers()`；新增样机只有“闲置”可写入任务 |
| 项目/阶段增量写入 API | `server.py:4958` `commit_project_mutation()` / `server.py:5010` `commit_stage_mutation()` |
| 样机增量写入 API | `server.py:4889` `commit_sample_mutation()` + `server.py:5646` `Handler.do_PATCH()` |
| 样机池增量写入 API | `server.py:5102` `commit_sample_category_mutation()` + `server.py:5646` `Handler.do_PATCH()` |
| 完整数据包导出 | `server.py:2765` `build_export_bundle()` + `server.py:5552` `GET /api/export-bundle` |
| 数据包导入预览 | `server.py:2837` `analyze_import_bundle()` / `server.py:2898` `_diff_import_bundle()` + `server.py:5738` `POST /api/import-bundle/preview` |
| 数据包导入提交 | `server.py:3282` `commit_import_bundle()` + `server.py:5748` `POST /api/import-bundle/commit` |
| 导入整树映射/一致性校验 | `server.py:3911` `_register_imported_stage_tree()` / `server.py:3928` `_register_imported_project_tree()` / `server.py:3983` `_validate_import_commit_state()` |
| 临时库压测脚本 | `tools/perf_benchmark.py` 默认造 20 项目 / 10万任务 / 30 池 / 7万样机 / 70万照片元数据 |
| 前端启动/按需加载 | `js/app.server.js:8` `fetchBootstrapState()` / `:258` `fetchProjectDetail()` / `:320` `ensureProjectLoaded()` / `:50` `ensureFullStateLoaded()` |
| 前端分页 API 调用 | `js/app.server.js:220` `fetchProjectSummary()` / `:227` `fetchStageTasksPage()` / `:239` `fetchSampleCategoriesSummary()` / `:246` `fetchSamplePage()` |
| 前端分页缓存失效 | `js/app.server.js:421` `invalidatePagedCaches()` |
| 前端项目/阶段增量提交 | `js/app.server.js:586` `commitProjectMutation()` / `:625` `commitStageMutation()` |
| 前端任务增量提交 | `js/app.server.js:462` `commitTaskMutation()` / `:452` `taskSampleStatusBlockerMessage()` |
| 前端样机/样机池增量提交 | `js/app.server.js:667` `commitSampleMutation()` / `:707` `commitSampleCategoryMutation()` |
| 启动/阻塞/临时变更增量入口 | `js/workspace/08-task-actions.js:55` `startTask()` / `:405` `blockTask()` / `:259` `tempChangeTask()` |
| 结果录入增量入口 | `js/workspace/09-task-result.js:643` `saveTaskResult()`；`:617` `restoreTaskResultSaveSnapshot()`；`:624` `refreshTaskAfterAlreadyFinished()` |
| 任务新增/配置/分配增量入口 | `js/workspace/07-task-config.js:68` `openAddTasksFromPoolModal()` / `:194` `assignPlanTaskSamples()` / `:244` `setPlanTaskSchedule()` / `:429` `saveTaskConfigAll()` |
| 任务删除增量入口 | `js/workspace/08-task-actions.js:8` `deleteTask()` |
| 项目 CRUD 增量入口 | `js/projects.js:39` `addProject()` / `:93` `editProject()` / `:214` `deleteProject()` |
| 项目人员/位置增量入口 | `js/workspace/02-home.js:195` `addProjectLocation()` / `:277` `addProjectMember()` / `:347` `importProjectMembersCsv()` |
| 阶段 CRUD/排序增量入口 | `js/workspace/04-stage.js:149` `addStage()` / `:187` `editStage()` / `:218` `deleteStage()` / `:266` `copyStage()` / `js/workspace/02-home.js:468` `onStageDrop()` |
| 样机池/样机新增导入增量入口 | `js/samples/01-pool.js:290` `addSampleCategory()` / `:316` `editSampleCategory()` / `:781` `addSample()` / `js/samples/02-import-export.js:8` `importSampleBatch()` |
| 样机详情/销毁增量入口 | `js/samples/07-detail.js:8` `openSampleDetail()` / `js/samples/01-pool.js:349` `deleteSampleCategory()` / `:666` `destroySample()` |
| 异步弹窗确认 | `js/app.modal.js:26` `showModal()` |
| 任务表服务端分页入口 | `js/workspace/05-task-table.js:53` `taskFlowPagerHtml()` / `:84` `taskFlowQueryParams()` / `:102` `loadTaskFlowPage()` / `:135` `workspaceTaskFlowHtml()` |
| 样机池服务端摘要/分页入口 | `js/samples/01-pool.js:8` `samplePagerHtml()` / `:28` `setSamplePage()` / `:112` `loadSampleCategorySummary()` / `:133` `loadSamplePage()` / `:174` `prefetchAdjacentSamplePages()` / `:238` `refreshSamplePageRegion()` / `:257` `renderSamples()` |
| 策略/BOM/用例集增量入口 | `js/workspace/03-strategy.js:32` `persistStageStrategyMutation()` / `:39` `scheduleStageStrategySave()` / `:292` `importTestCaseXlsx()` |
| 问题单/照片重命名增量入口 | `js/workspace/10-dropdown-issue.js:174` `openTaskIssueRecordModal()` / `js/samples/04-photos.js:216` `startPhotoRename()` |
| 前端数据包导入导出 | `js/import-export-bundle.js:10` `exportBundle()` / `:67` `importBundle()` / `:581` `_onImportCommit()`；`js/app.server.js:780` `importBundlePreview()` / `:789` `importBundleCommit()` |

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
6. `index.html` 静态资源加 cachebuster，当前发布版本统一为 `v=7.1.0`，避免浏览器缓存旧 JS 影响验证。
7. 已补 `tests/test_server_core.py` 覆盖项目增量、阶段增量、样机池创建与批量样机插入。
8. 已推进到第五阶段：初始化不再直接拉全量 `/api/state`。

### 第五阶段已完成

1. 启动入口已改为 `GET /api/bootstrap`，只返回项目摘要、样机池摘要、revision 和当前选择 ID；当前验证数据下 bootstrap 约 1.3KB，旧 `/api/state` 约 2.68MB。
2. 新增 `GET /api/projects/<projectId>` 按需加载项目详情；普通进入项目不加载全量任务，任务表继续走 `/api/stages/<stageId>/tasks` 分页。
3. 新增 `GET /api/sample-categories/<catId>` 按需加载样机池完整样机基础数据；普通池内浏览继续走样机分页。
4. 前端新增 `ensureProjectLoaded()`、`ensureSampleCategoryLoaded()`、`ensureFullStateLoaded()`，低频危险操作/全局查重操作前再兜底加载完整基础数据。
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

1. 系统检查完整链路：`GET /api/export-bundle` → `POST /api/import-bundle/preview` → `POST /api/import-bundle/commit` → 前端 `reloadFromServer()`。
2. 修复空白平台整包导入 P0：`commit_import_bundle()` 导入 `new_project` / `new_stage` 时不再把已随整树复制的阶段和任务二次追加，避免重复任务触发样机占用冲突。
3. 新增导入提交前一致性校验：同一项目内阶段 ID 不重复、同一阶段内任务 ID 不重复、任务 `sampleIds` 必须能映射到存在样机。
4. 已补导入专项回归：`tests/test_import_conflicts.py` 覆盖源库导出完整包、目标库清空、空白平台导入、项目/阶段/任务/样机占用关系只保留一份。
5. 验证通过：`python tests\test_import_conflicts.py`、`python tests\test_server_core.py`、`python -m py_compile server.py`。

### 性能改造暂停点 / 剩余任务

> 记录时间：2026-06-03。当前已完成启动瘦身、增量写入主干、任务/样机池服务端分页、SQLite 索引补强、目标规模压测、数据包导入正确性专项。剩余任务如下。

1. **大列表前端渲染优化（下一优先级最高）**
   - 任务表/样机池列表已经走服务端分页，样机池翻页已做局部刷新、缓存和预取；后续重点是任务/样机增量变更后的当前行/当前卡片局部刷新。
   - 样机详情、任务详情、履历、照片区继续压测，避免一次性渲染大量历史记录或图片节点。
   - 验证方式：浏览器打开项目页和样机池页，切筛选、翻页、改状态、上传/删除照片后确认无明显闪烁、无控制台错误、当前页数据正确。

2. **数据包导入后的局部同步策略（导入专项）**
   - 整包导入到空白平台的正确性已修复并覆盖回归；当前剩余问题是导入成功后仍有 `reloadFromServer()` / 全局刷新痕迹，后续大包导入时可能造成不必要的全量拉取。
   - 目标是导入提交后只刷新受影响项目、阶段、任务页、样机池和样机摘要；必要时返回 mutation summary 给前端做局部合并。
   - 保留全量刷新作为异常兜底，但日常导入成功路径不应依赖完整 `/api/state`。

3. **测试覆盖补强**
   - 后端已有核心单元测试、导入冲突测试和空白平台整包导入测试，但还缺照片上传/删除、结果录入、任务临时变更、SQLite 持久化迁移的专项覆盖。
   - 浏览器端需要补最小回归：启动 bootstrap、进入项目、任务分页筛选、进入样机池、样机分页筛选、打开样机详情、照片区域操作。

4. **长期技术债（不阻塞当前大数据流畅度）**
   - 全局 `Object.assign(app, {...})` 混入仍存在，模块边界弱。
   - 仍有兼容用 `/api/state` 和全量 `compose_state()`；后续应继续把它压缩到导出/调试/异常兜底范围。
   - 大量 DOM 字符串拼接和内联事件仍存在，后续重构时注意事件绑定、转义漏点和局部更新成本。

---

## 文件地图 — 精确到函数

### server.py (6023 行，含 SQLite 外置表、数据包导入导出、启动骨架 API、分页摘要 API、查询状态列、任务/项目/阶段/样机增量写入 API、P0 幂等兜底、空白平台整包导入兜底)

| 行号 | 符号 | 职责 |
|------|------|------|
| 61–73 | `empty_data()`, `ensure_dirs()` | 空状态模板, 目录创建 |
| 101 | `connect_db()` | SQLite 连接(WAL, 30s timeout) |
| 220–260 | `_should_backup()`, `write_backup()`, `prune_backups()` | backup 节流判断、写入与清理 |
| 311 / 317 / 349 | `ensure_table_column()` / `backfill_query_state_columns()` / `ensure_schema()` | SQLite 表结构 DDL/迁移、查询状态列回填、索引创建 |
| 844 | `sync_sample_library()` | 样机库 → SQLite 同步(upsert+清理，写入 effective_status/has_problem) |
| 1075 | `load_sample_library()` | SQLite → 内存样机库 |
| 1146–1189 | `list_item_key()`, `merge_record()`, `merge_list_by_id()` | 三向合并引擎 |
| 1182–1191 | `PROJECT_CHILDREN`, `SAMPLE_CATEGORY_CHILDREN` | 项目/样机嵌套合并层级声明 |
| 1277 | `merge_state()` | 顶层三向合并入口 |
| 1304 | `sync_project_library()` | 项目/阶段/任务 → SQLite，写入 flow_status |
| 1486 | `load_project_library()` | SQLite → 项目列表 |
| 1772–1808 | `task_query_requires_python_scan()` / `task_sql_filter_parts()` / `task_from_db_row()` | 任务分页 SQL 快路径辅助 |
| 1839 | `list_stage_tasks_page()` | `/api/stages/<stageId>/tasks` 服务端分页，默认/状态/SKU/执行人走 SQL 分页 |
| 2069–2107 | `sample_query_requires_python_scan()` / `sample_sql_filter_parts()` / `sample_from_db_row()` | 样机分页 SQL 快路径辅助 |
| 2132 | `list_sample_categories_summary()` | `/api/sample-categories` 样机池摘要，按 effective_status 统计 |
| 2168 | `list_samples_page()` | `/api/sample-categories/<catId>/samples` 服务端分页，默认/状态/保管人/借用人走 SQL 分页 |
| 2312 | `load_sample_category_detail()` | 样机池详情按需加载 |
| 2371 | `list_project_summary()` | `/api/projects/summary` 项目摘要 |
| 2413 | `compose_bootstrap_state()` | `/api/bootstrap` 启动骨架 |
| 2446 | `compose_state()` | 从 SQLite 拼装完整 state |
| 2434 | `init_db()` | 首次启动建库 + V6→V7 自动迁移 |
| 2765–4103 | `build_export_bundle()` / `analyze_import_bundle()` / `_diff_import_bundle()` / `commit_import_bundle()` / `_validate_import_commit_state()` | 完整数据包导出、预览、冲突分析、提交、空白平台整包导入一致性兜底 |
| 3930 | `detect_sample_occupancy_conflicts()` | C1 占用冲突检测 |
| 4000 | `save_state()` | PUT /api/state 处理 |
| 4046 | `parse_multipart()` | multipart/form-data 解析 |
| 4076 | `commit_data_mutation()` | 照片上传/删除等直接变更 |
| 4167–4517 | `upsert_task_record()` / `update_project_record()` / `update_stage_record()` / `update_sample_category_record()` / `update_sample_record()` / `upsert_sample_events()` | 任务/项目/阶段/样机池/样机/事件增量 upsert |
| 4631 | `existing_finished_task()` | 结束任务幂等兜底，重复 finish 返回 `TASK_ALREADY_FINISHED` |
| 4650 | `detect_task_mutation_sample_status_blockers()` | 新增任务样机状态兜底，只有“闲置”可新增选择 |
| 4698–5102 | `commit_task_mutation()` / `commit_task_batch_mutation()` / `commit_sample_mutation()` / `commit_project_mutation()` / `commit_stage_mutation()` / `commit_sample_category_mutation()` | 任务、批量任务、样机、项目、阶段、样机池增量写入 API |
| 4955 | `Handler` | HTTP 路由类 |
| 5306 | `_is_public_static_path()` | 静态文件白名单 |
| 5323 | `Handler.do_GET()` | GET 路由(全量 state、摘要、分页、静态资源) |
| 5514 | `Handler.do_POST()` | POST 路由(照片上传) |
| 5602 | `Handler.do_DELETE()` | DELETE 路由(照片软删除) |
| 5646 | `Handler.do_PATCH()` | PATCH 增量写入路由 |
| 5748 | `Handler.do_PUT()` | PUT /api/state 路由 |
| 5776 | `main()` | 启动入口 |

### js/utils.js (615 行) — 纯工具函数

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `esc(v)` | HTML转义—**所有用户输入必须经此** |
| 13 | `id(prefix)` | 唯一ID(timestamp36+random6) |
| 17–21 | `now()`, `today()` | 时间工具 |
| 24 | `toast(msg)` | 轻提示3.2s |
| 34 | `normalizeDigits(v)` | 全角数字→半角 |
| 40–49 | `normalizeEmployeeNoKey()`, `memberIdentityKey()` | 人员去重key |
| 52 | `personIdentityFromText()` | `姓名/工号`→`{name,employeeNo}` |
| 65 | `personText()` | `{name,employeeNo}`→格式化 |
| 71 | `personMatchesMember()` | 人员文本与成员匹配 |
| 81 | `parsePositiveInt()` | 正整数解析,失败返null |
| 92 | `parseCsvLine()` | CSV行解析(含引号转义) |
| 121 | `parseProjectMembersCsv()` | 项目人员CSV导入 |
| 150 | `sampleImportAliases()` | 样机导入列名别名表 |
| 169 | `parseSampleDateField()` | 多格式日期→yyyy-MM-dd |
| 188 | `parsePersonField()` | 人员字段严格校验(姓名/工号) |
| 218 | `isNoSampleIssueText()` | 判定"无问题"占位文本 |
| 240 | `parseSampleIssueText()` | 问题文本按行/分号拆分 |
| 247–316 | `parseSampleImportMatrix/Csv()` | 样机导入解析核心 |
| 319–615 | `parseSampleImportXlsx()` 及相关 | 纯JS XLSX解析(含ZIP + raw deflate兜底) |
| 376–534 | `inflateRawBytes()/inflateRawBytesFallback()` | XLSX deflate解压:优先浏览器API, 旧浏览器走JS兜底 |
| 585–613 | `csvEscape/downloadCsv/downloadText` | 导出工具 |

### js/app.core.js (114 行)

| 行号 | 符号 | 职责 |
|------|------|------|
| 5–35 | `app = {...}` | 全局对象(version, data, view, constants, _baseData, _saveInFlight等) |
| 27–34 | `app.view` | UI状态: module, selectedProjectId, filters, collapsed, sidebarCollapsed |
| 37–38 | `app.constants` | 样机5状态, 任务5状态, 模块名称枚举 |
| 53–113 | `init()` | 入口: GET /api/bootstrap → normalize → render → 全局事件绑定 |

### js/app.server.js (800 行) — 服务器通信

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `fetchBootstrapState()` | 启动骨架读取 API |
| 16 | `updateServerStatus()` | 侧栏保存状态指示器 |
| 30 | `reloadFromServer()` | GET /api/state 完整基础数据刷新 |
| 50 | `ensureFullStateLoaded()` | 摘要态下低频危险操作前完整兜底加载 |
| 66 | `scheduleSave()` | 旧全量保存 debounce 入口(保留兼容，摘要态禁止业务误用) |
| 78 | `save()` | PUT /api/state 持久化(含C1冲突处理，摘要态拒绝) |
| 168 | `hasLocalUnsavedChanges()` | JSON比较 data vs _baseData |
| 172 | `prepareBeforeDirectMutation()` | 照片上传/删除前:清debounce→等inFlight→存草稿 |
| 198 | `syncAfterDirectMutation()` | 照片上传/删除后:从服务器刷新 |
| 207–217 | `fetchSamplePhotos()/fetchSampleEvents()` | 样机照片/事件按需加载 |
| 220–254 | `fetchProjectSummary()/fetchStageTasksPage()/fetchSampleCategoriesSummary()/fetchSamplePage()` | 摘要/分页读取 API |
| 258–390 | `fetchProjectDetail()/fetchSampleCategoryDetail()/merge*/ensure*Loaded()` | 项目/样机池按需详情加载与本地合并 |
| 421 | `invalidatePagedCaches()` | 任务表/样机池分页缓存失效 |
| 452 | `taskSampleStatusBlockerMessage()` | 样机状态不可选错误提示 |
| 462 | `commitTaskMutation()` | 任务增量写入：任务/阶段/样机/样机事件；识别 `TASK_ALREADY_FINISHED` |
| 586 | `commitProjectMutation()` | 项目增量写入/删除 |
| 625 | `commitStageMutation()` | 阶段增量写入/删除/排序 |
| 667 | `commitSampleMutation()` | 单台样机增量写入/删除 |
| 707 | `commitSampleCategoryMutation()` | 样机池增量写入/销毁/批量新增样机 |

### js/app.data.js (455 行) — 数据工具

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `emptyData()` | 空状态模板 |
| 18 | `cloneData()` | JSON深拷贝 |
| 22–32 | `normalizePersonText()`, `projectActiveMembers()` | 人员工具 |
| 33 | `normalize()` | **数据修复入口**: 旧格式升级/成员去重/状态映射/problemRecords迁移 |
| 209 | `currentProject()` | 当前选中项目 |
| 212 | `currentStage()` | 当前选中阶段 |
| 216 | `allSamples()` | 所有样机(含categoryName) |
| 225 | `findSample(id)` | 返回`{category, sample}`或null |
| 232–233 | `projectName()`, `stageName()` | ID→名称 |
| 242 | `sampleProblemRecords()` | 样机问题表(规范化) |
| 259 | `sampleHasProblem()` | 是否有故障 |
| 263 | `sampleEffectiveStatus()` | 有效状态(含故障判定) |
| 270–303 | `normalizeSampleStatusValue()/repairSampleStatus()/clearSampleOccupancy()` | 样机状态/占用数据修复入口(不写业务日志) |
| 314 | `addSampleProblem()` | 追加样机问题(去重) |
| 360 | `changeSampleStatus()` | **样机状态业务变更统一入口**: 事件日志/borrower/owner/destLocation管理 |
| 401 | `activeTaskUsagesForSample()` | 样机活跃任务占用查询 |
| 414 | `reconcileSampleTaskOccupancy()` | 无活跃任务时清除占用标记 |
| 429 | `getProjectStageTask()` | 项目/阶段/任务三元组 |
| 436 | `isTaskCompleted()` | 任务是否完成(正常完成/异常终止/归档) |
| 443 | `isTaskExecuted()` | 任务是否已执行过(含进行中/阻塞中) |
| 450 | `isSampleUsedByAnotherOpenTask()` | 样机是否被其他未完成任务占用 |

### js/app.render.js (268 行) — 渲染引擎

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `render()` | 按view.module分发渲染 |
| 25 | `renderHome()` | 首页入口卡片 |
| 70 | `renderNav()` | 左侧导航(项目子目录+样机池子目录) |
| 112–134 | `_navToggle()`, `_navGoSub()` | 导航展开/收起/跳转 |
| 136 | `renderHeader()` | 顶部面包屑 |
| 166 | `go(module)` | 模块导航,离开策略页自动autoSyncProgress |
| 180 | `toggleSidebar()` | 侧栏折叠(localStorage持久化) |
| 199 | `isCollapsed()`, `toggleSection()` | 折叠面板 |
| 230 | `closeTaskOpMenus()` | 任务操作菜单统一关闭 |

### js/app.modal.js (220 行) — 弹窗系统

| 行号 | 函数 | 职责 |
|------|------|------|
| 26 | `showModal()` | **主弹窗**: onOk返回true=保持打开, 返回false/undefined=关闭 |
| 88 | `showConfirm()` | 独立确认框(支持异步确认回调) |
| 128 | `showAlert()` | 纯提示框(隐藏取消) |
| 145 | `closeModal()` | 关闭弹窗(modal stack弹出恢复) |
| 171 | `clearFieldValidationMarks()` | 清除所有.is-invalid+.field-error |
| 179 | `markFieldInvalid(el,msg)` | 标红+插入.field-error+自动滚动 |
| 191 | `showDangerConfirm()` | 危险操作确认(需输入DELETE关键词，支持异步确认回调) |

### js/app.filters.js (55 行)

| 行号 | 函数 | 职责 |
|------|------|------|
| 8–17 | `setProgressFilter()`, `clearProgressFilters()` | 进度筛选 |
| 18–53 | `setTaskFlowFilter()`, `commitTaskFlowTextFilter()`, `clearTaskFlowFilters()` | 任务流筛选 |

### js/app.logs.js (181 行) — 日志系统

| 行号 | 函数 | 职责 |
|------|------|------|
| 30 | `addTaskLog()` | 任务日志写入 |
| 95 | `taskLogContentHtml()` | 日志内容HTML(含detailLines) |
| 136 | `linkSampleRefsInLogText()` | SN/IMEI→可点击链接 |
| 172 | `showTaskLogs()` | 任务日志弹窗 |

### js/projects.js (298 行) — 项目管理

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `renderProjects()` | 项目列表渲染 |
| 31 | `projectNameExists()` | 项目名唯一性(大小写不敏感) |
| 39 | `addProject()` | 新建项目弹窗(增量 API) |
| 93 | `editProject()` | 编辑项目弹窗(增量 API) |
| 141 | `collectProjectDeleteImpact()` | 删除影响分析 |
| 214 | `deleteProject()` | 删除项目(释放样机+showDangerConfirm+增量 API) |
| 290 | `selectProject()` | 进入项目工作台 |

### js/workspace/01-shared.js (253 行) — 跨模块共享

| 行号 | 函数 | 职责 |
|------|------|------|
| 8–26 | `taskOwnerName()`, `taskOwnerId()` | 执行人姓名/工号提取 |
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
| 128 | `workspaceMembersHtml()` | 人员配置区域 |
| 167 | `workspaceLocationsHtml()` | 位置配置区域 |
| 195–238 | `add/edit/removeProjectLocation()` | 位置 CRUD(增量 API) |
| 277–394 | `add/edit/removeProjectMember()` | 人员 CRUD(增量 API) |
| 347 | `importProjectMembersCsv()` | 人员CSV批量导入(增量 API) |
| 407 | `memberWorkStats()` | 人员工作统计 |
| 431–478 | 拖拽排序回调 | 阶段排序(增量 API) |

### js/workspace/10-dropdown-issue.js (215 行) — 用例下拉+问题单

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `openCaseDropdown()` | 打开用例搜索下拉 |
| 22 | `positionCaseDropdown()` | 下拉定位(自动上/下) |
| 59 | `renderCaseDropdownOptions()` | 下拉选项渲染(含mousedown选择) |
| 116 | `selectCaseSuggestion()` | 选择用例填充到策略输入框 |
| 145 | `taskIssueRecordHtml()` | 任务问题单展示(DTS/是否重复/备注) |
| 168 | `openTaskIssueRecordModal()` | 问题单录入弹窗 |

### js/workspace/03-strategy.js (331 行) — 阶段策略配置

| 行号 | 函数 | 职责 |
|------|------|------|
| 9 | `openStageStrategy()` | 进入策略页 |
| 32 | `persistStageStrategyMutation()` | 阶段策略/BOM 增量保存 |
| 39 | `scheduleStageStrategySave()` | 阶段策略/BOM 增量保存 debounce |
| 51 | `renderStageStrategyPage()` | 策略页渲染(阶段编辑+BOM+策略表) |
| 72–119 | `workspaceBomHtml/addBomRow/updateBom/deleteBomRow` | BOM上料清单(增量 API) |
| 122–198 | `workspaceStrategyHtml/addStrategyRow/onStrategyInput` | 测试策略表(增量 API) |
| 218 | `scheduleStrategySync()` | 800ms节流策略同步 |
| 250 | `autoSyncProgress()` | **策略→进度自动同步**(离开策略页时触发，增量 API) |
| 292 | `importTestCaseXlsx()` | 用例集导入(项目增量 API) |

### js/workspace/04-stage.js (321 行) — 阶段与SKU编辑

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `inlineStageEditorHtml()` | 策略页内联编辑器(SKU管理) |
| 30 | `persistCurrentStageMutation()` | 阶段名/SKU 内联编辑增量保存 |
| 116 | `skuEditorHtml()` | 弹窗版SKU编辑器 |
| 149 | `addStage()` | 新建阶段弹窗(增量 API) |
| 187 | `editStage()` | 编辑阶段弹窗(增量 API) |
| 218 | `deleteStage()` | 删除阶段(安全机制:占用样机时拒绝，增量 API) |
| 266 | `copyStage()` | 复制阶段(含strategy/progress深层克隆，增量 API) |

### js/workspace/05-task-table.js (528 行) — 任务表格

| 行号 | 函数 | 职责 |
|------|------|------|
| 53 | `taskFlowPagerHtml()` | 任务分页条，含 loading/disabled 状态 |
| 84 | `taskFlowQueryParams()` | 从筛选器生成服务端分页查询参数 |
| 98 | `taskFlowCacheKey()` | 任务分页缓存 key |
| 102 | `loadTaskFlowPage()` | 拉取 `/api/stages/<stageId>/tasks` 并合并本地任务 |
| 135 | `workspaceTaskFlowHtml()` | **任务管理工作台**:服务端分页统计+筛选栏+表格+新增按钮 |
| 294 | `taskDeleteImpactHtml()` | 任务删除影响分析 |
| 358 | `taskFlowActionsHtml()` | **操作按钮**:按状态显示不同按钮组合 |
| 432 | `showTaskSamples()` | 任务样机清单弹窗 |
| 513 | `sampleTestedItemNames()` | 样机已测项目列表 |

### js/workspace/06-sample-picker.js (271 行) — 样机选择器

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `getSelectedTaskSampleIds()` | 读取勾选样机ID |
| 46 | `validateTaskSampleSelection()` | 样机数量校验 |
| 54 | `updateTaskSampleLimitUI()` | 计数胶囊(warn/bad/full状态) |
| 103 | `onTaskSampleCheckboxChange()` | 勾选:超量静默取消+选满禁用 |
| 128 | `onTaskSampleRowClick()` | 整卡点击切换勾选，链接/表单控件不触发 |
| 157 | `buildTaskSamplePickerHtml()` | **样机选择器HTML**(池分组/搜索/勾选/禁用；非闲置不可新增选择) |
| 223 | `updateDispatchSamplePoolCounts()` | 各池已选计数更新 |
| 241 | `filterDispatchGroup()` | 池内搜索/排除过滤 |
| 259 | `isTaskChangePayloadChanged()` | 变更检测(计划+样机) |

### js/workspace/07-task-config.js (554 行) — 任务配置弹窗

| 行号 | 函数 | 职责 |
|------|------|------|
| 15 | `resolveTaskProgress()` | 解析progress(live vs snapshot) |
| 31 | `createTaskFromProgress()` | 从progress创建任务 |
| 68 | `openAddTasksFromPoolModal()` | 从测试池批量新增任务(增量 API) |
| 194 | `assignPlanTaskSamples()` | 待下发任务样机分配/重分配(增量 API) |
| 244 | `setPlanTaskSchedule()` | 待下发任务计划时间/执行人配置(增量 API) |
| 320 | `openTaskConfigPanel()` | **新版双Tab配置弹窗入口** |
| 364 | `taskConfigPanelHtml()` | 弹窗外壳(导航+面板) |
| 387 | `taskPlanConfigPanelHtml()` | 计划配置Tab |
| 412 | `taskSampleConfigPanelHtml()` | 样机配置Tab |
| 429 | `saveTaskConfigAll()` | **统一保存**:plan+sample校验+增量写入 |
| 521 | `hasUnsavedTaskConfigChanges()` | 未保存检测(取消按钮用) |
| 541 | `switchTaskConfigTab()` | Tab切换 |

### js/workspace/08-task-actions.js (412 行) — 任务操作

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `deleteTask()` | 删除任务(已执行→归档,未执行→物理删除) |
| 44 | `startTask()` | **启动任务**:校验→确认→改状态→日志 |
| 92 | `taskFailureProblemsBySample()` | 任务范围内样机问题收集 |
| 137 | `taskFailureStats()` | 失效统计(active/removed×fail/pass) |
| 197 | `taskIssueSummaryHtml()` | **测试结果列HTML**:失效比例+问题清单 |
| 245 | `tempChangeTask()` | **临时变更**:执行人/计划/样机变更+差异日志 |
| 386 | `blockTask()` | 阻塞任务:校验→确认→改状态→日志 |

### js/workspace/09-task-result.js (807 行) — 结果录入

| 行号 | 函数 | 职责 |
|------|------|------|
| 31 | `onTaskResultDestinationChange()` | 去向切换(取走分析→取走人必填) |
| 80 | `recordTaskRemovedSamples()` | 记录退出样机 |
| 103 | `taskResultSampleEntries()` | 合并active+removed样机 |
| 166 | `taskResultSampleRowsHtml()` | 每台样机结果行(去向/位置/取走人/挂账人/问题) |
| 252 | `uploadTaskResultPhotos()` | 结果图片上传(multipart→服务器→刷新) |
| 313 | `collectTaskResultForm()` | **表单收集**:遍历所有.task-result-sample-row |
| 347 | `validateTaskResultPayload()` | 结果验证 |
| 399 | `taskResultAutoReason()` | 自动生成结果摘要(≤500字符) |
| 485 | `applyTaskResult()` | **应用结果**:改状态/写日志/追加resultUploads |
| 617 | `restoreTaskResultSaveSnapshot()` | 结束任务保存失败时回滚本地乐观更新 |
| 624 | `refreshTaskAfterAlreadyFinished()` | 服务端提示任务已结束时按需刷新当前项目详情 |
| 643 | `saveTaskResult()` | **保存/结束入口**:draft vs finish分支；结束任务含 in-flight 防重 |
| 713 | `uploadResult()` | **结果录入弹窗**:任务级结果+每台样机去向；结束按钮 async 等待并禁用 |

### js/samples/ — 样机档案池（已拆分）

| 文件 | 行数 | 主要职责 |
|------|------|------|
| `js/samples.js` | 4 | 兼容占位，实际实现由 `index.html` 加载子模块 |
| `js/samples/01-pool.js` | 1010 | 样机池服务端摘要/分页、分页缓存/加载态/相邻页预取、样机卡片、池/样机 CRUD、销毁影响分析；单台/整池销毁走增量 API |
| `js/samples/02-import-export.js` | 216 | 样机批量导入(增量 API)/导出、SN/IMEI/主板SN 去重链 |
| `js/samples/03-detail-fields.js` | 98 | 样机详情字段、人名输入、位置输入、初检问题解析 |
| `js/samples/04-photos.js` | 298 | 照片上传、缩略图生成、预览、重命名、删除 |
| `js/samples/05-problems.js` | 92 | 样机问题表多行编辑 UI |
| `js/samples/06-history.js` | 219 | 样机测试履历、结果图片、只读快照 |
| `js/samples/07-detail.js` | 186 | 样机详情 5 Tab 弹窗 |

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
| 数据库表结构 | `server.py:349` `ensure_schema()` |
| 样机/任务状态枚举 | `js/app.core.js:37-38` |
| 状态变更统一入口 | `js/app.data.js:360` `changeSampleStatus()` |
| 任务状态标准化 | `js/workspace/01-shared.js:42` `taskFlowStatus()` |
| 数据规范化(旧格式修复) | `js/app.data.js:33` `normalize()` |
| 三向合并(服务端) | `server.py:1277` `merge_state()` |
| 保存流程(前端) | `js/app.server.js:78` `save()` |
| 保存流程(后端) | `server.py:4000` `save_state()` |
| 样机占用冲突C1(后端) | `server.py:3930` `detect_sample_occupancy_conflicts()` |
| 样机占用冲突C1(前端) | `js/app.server.js:85-98` |
| 弹窗onOk行为 | `js/app.modal.js:26` `showModal()` (返回true=保持打开) |
| 内联校验标红 | `js/app.modal.js:179` `markFieldInvalid()` |
| DELETE确认弹窗 | `js/app.modal.js:191` `showDangerConfirm()` |
| Toast提示 | `js/utils.js:24` |
| HTML转义 | `js/utils.js:7` `esc()` |
| 人员格式校验 | `js/utils.js:188` `parsePersonField()` |
| 人员下拉生成 | `js/workspace/01-shared.js:172` `projectMemberSelectHtml()` |
| 样机释放 | `js/workspace/01-shared.js:199` `releaseTaskSamples()` |
| 样机新增校验 | `js/samples/01-pool.js:899` `addSample()` |
| 样机去重系统 | `js/samples/02-import-export.js` (6函数链) |
| 样机详情弹窗 | `js/samples/07-detail.js:8` `openSampleDetail()` |
| 样机照片上传(前端) | `js/samples/04-photos.js:177` / 后端 `server.py:5514` |
| 样机批量导入 | `js/samples/02-import-export.js:8` `importSampleBatch()` |
| 样机测试履历 | `js/samples/06-history.js:93` `sampleTestHistoryHtml()` |
| 阶段卡片渲染 | `js/workspace/02-home.js:52-99` |
| 项目人员CRUD | `js/workspace/02-home.js:277-394` |
| 项目位置CRUD | `js/workspace/02-home.js:195-238` |
| 阶段CRUD | `js/workspace/04-stage.js:149-266` |
| 阶段复制 | `js/workspace/04-stage.js:266` `copyStage()` |
| BOM上料清单 | `js/workspace/03-strategy.js:54-104` |
| 测试策略表 | `js/workspace/03-strategy.js:107-166` |
| 策略→进度同步 | `js/workspace/03-strategy.js:229` `autoSyncProgress()` |
| 用例下拉搜索 | `js/workspace/10-dropdown-issue.js:8-131` |
| 任务表格渲染 | `js/workspace/05-task-table.js:134` `workspaceTaskFlowHtml()` |
| 任务筛选器 | `js/app.filters.js:18-53` |
| 任务操作按钮 | `js/workspace/05-task-table.js:358` `taskFlowActionsHtml()` |
| 任务配置弹窗(新版) | `js/workspace/07-task-config.js:320-541` |
| 任务配置CSS | `css/33-task-config-modal.css` |
| 样机选择器UI | `js/workspace/06-sample-picker.js:157` `buildTaskSamplePickerHtml()` |
| 样机选择整卡点击 | `js/workspace/06-sample-picker.js:128` `onTaskSampleRowClick()` |
| 样机新增状态兜底 | 前端 `js/workspace/06-sample-picker.js:157`；后端 `server.py:4650` |
| 样机选择器CSS | `css/34-sample-picker.css` |
| 任务启动 | `js/workspace/08-task-actions.js:44` `startTask()` |
| 任务阻塞 | `js/workspace/08-task-actions.js:386` `blockTask()` |
| 任务临时变更 | `js/workspace/08-task-actions.js:245` `tempChangeTask()` |
| 任务删除 | `js/workspace/08-task-actions.js:8` `deleteTask()` |
| 测试结果列 | `js/workspace/08-task-actions.js:197` `taskIssueSummaryHtml()` |
| 结果录入弹窗 | `js/workspace/09-task-result.js:713` `uploadResult()` |
| 结果表单收集 | `js/workspace/09-task-result.js:313` `collectTaskResultForm()` |
| 结果应用 | `js/workspace/09-task-result.js:485` `applyTaskResult()` |
| 结束任务防重复 | 前端 `js/workspace/09-task-result.js:643` `saveTaskResult()`；后端 `server.py:4631` `existing_finished_task()` |
| 结果图片上传 | `js/workspace/09-task-result.js:252` |
| 问题单录入 | `js/workspace/10-dropdown-issue.js:168` |
| 任务日志展示 | `js/app.logs.js:172` `showTaskLogs()` |
| 导航栏渲染 | `js/app.render.js:70` `renderNav()` |
| 侧栏折叠 | `js/app.render.js:180` `toggleSidebar()` |
| 首页 | `js/app.render.js:25` `renderHome()` |
| 项目删除影响分析 | `js/projects.js:141` `collectProjectDeleteImpact()` |
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
- **内联校验**: `clearFieldValidationMarks()` → `markFieldInvalid(el, msg)` (`app.modal.js:154-171`)
- **持久化**: `app.save()` 立即, `app.scheduleSave()` 450ms debounce
- **样机状态**: 业务变更必须 `app.changeSampleStatus()` (`app.data.js:360`)，数据修复仅用 `app.repairSampleStatus()`
- **任务状态读取**: `app.taskFlowStatus(t)` 标准化 (`01-shared.js:42`)
- **任务状态变更**: 业务变更必须 `app.transitionTaskStatus()` (`01-shared.js:113`)，默认/修复仅用 `app.repairTaskStatus()`
- **唯一ID**: `Utils.id(prefix)` (`utils.js:13`)
- **人员格式**: 统一 `姓名/工号`, 如 `张三/00609513`
- **加载顺序**: `index.html:69-89` 中script标签顺序, `Object.assign` 混入全局 `app`

---

## 技术债务（已知问题）

> 复核时间：2026-06-02。基于 `server.py`、`index.html`、`js/**`、`css/**` 的全量扫描与关键路径抽查。

### 已复核完成

1. ~~**workspace.js 过大** (3594行)~~ ✅ 已解决 — 已拆分为 `js/workspace/01-shared.js` 至 `10-dropdown-issue.js` 共 10 个模块。
2. ~~**samples.js 中 openSampleReadonly 与 app.render.js 重复定义**~~ ✅ 已解决 — 代码扫描确认仅 `js/samples/06-history.js:180` 保留 `openSampleReadonly()`。
3. ~~**`saveTaskPlanConfig()` / `saveTaskSampleConfig()` 死代码**~~ ✅ 已解决 — 旧版单独保存函数已删除，当前由 `js/workspace/07-task-config.js:398` `saveTaskConfigAll()` 统一保存。
4. ~~**完全没有自动化测试入口**~~ ✅ 已缓解 — 已新增 `tests/test_server_core.py` 覆盖后端三向合并/样机占用冲突，新增 `tests/frontend_status_transitions.test.cjs` 覆盖前端状态流转工具和样机状态入口。
5. ~~**照片无缩略图链路**~~ ✅ 已解决 — 前端上传时生成 JPEG 缩略图，服务端保存 `photo` + `photo_thumb` 资产，列表/履历优先显示 `thumbUrl`，预览仍打开原图。
6. ~~**samples.js 最大模块**~~ ✅ 已解决 — `js/samples.js` 仅保留兼容占位，实际拆分到 `js/samples/01-*.js` 至 `07-detail.js`。
7. ~~**样机日志双写 sample.logs/sampleLibrary.logs**~~ ✅ 已解决 — `eventSchema=sample_events_v2` 后样机对象不再保存 `logs`，样机事件只写 `sampleLibrary.logs` 并由后端落 `sample_events`。
8. ~~**CSS 超大文件集中堆叠 / 补丁化**~~ ✅ 已解决 — 样机、工作台、任务流、结果录入 CSS 已按功能拆分，最大相关 CSS 文件降到 454 行；全 `css/**` 的 `!important` 已从 37 处清理到 0 处。
9. ~~**XLSX 解析依赖浏览器能力**~~ ✅ 已解决 — `Utils.unzipXlsxFiles()` 仍优先使用 `DecompressionStream("deflate-raw")`，旧浏览器无该能力时走 `inflateRawBytesFallback()` 纯 JS raw deflate 解压。
10. ~~**样机状态统一入口仍需继续收敛**~~ ✅ 已解决 — 业务入口为 `changeSampleStatus()`；`normalize()` / `reconcileSampleTaskOccupancy()` 的数据修复入口拆为 `repairSampleStatus()` 与 `clearSampleOccupancy()`，不写业务事件日志。
11. ~~**任务状态与 progress 状态已部分收口但未完成**~~ ✅ 已解决 — `transitionTaskStatus()` 复用 `repairTaskStatus()`，progress 状态统一经 `setProgressStatus()`；策略新增 progress 使用 `createProgressRecord()`，任务配置默认状态不再直接写入。

### 仍存在 / 新增

1. **全局 app 混入仍存在** — 代码扫描确认 19 个文件使用 `Object.assign(app, {...})`，状态仍集中在 `app.data/app.view`，无模块隔离或依赖边界。
2. **自动化测试覆盖仍很薄** — 当前只有最小护栏，尚未覆盖照片上传/删除、结果录入表单、样机导入、任务临时变更、SQLite 持久化和浏览器端交互回归。
3. **全量 state 兼容入口仍需继续收窄** — 日常启动、任务分页、样机分页和主要增量写入已绕开 `/api/state`，但导出/调试/异常兜底和少量导入后刷新仍可能触发完整 `compose_state()`；后续应继续压到低频路径。
4. **大量 DOM 字符串拼接和内联事件** — 多数 UI 仍通过 `innerHTML` / `insertAdjacentHTML` 与 `onclick/onchange/oninput` 拼接；虽然大量用户输入走 `Utils.esc()`，但事件绑定、转义漏点和重构成本仍偏高。
