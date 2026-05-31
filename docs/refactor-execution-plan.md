# TestChamberV7 前端模块化重构 — 执行计划

> 状态：规划中 | 版本：1.0 | 日期：2026-05-31

---

## 执行总则

- **每一轮只拆一个模块**，验证通过后再开始下一轮
- **第一轮只移动代码，不修改逻辑**
- CSS 拆分保持原始规则顺序
- JS 拆分保持函数签名和调用关系不变
- 每次拆分后必须更新 index.html 的 `<script>` 或 `<link>` 加载顺序
- 每次拆分后运行语法检查
- 必须在每轮完成后创建 git commit

---

## 阶段总览

| 阶段 | 目标 | 预计轮次 | 优先级 | 风险 |
|------|------|----------|--------|------|
| Phase 0 | 环境准备 | 1 轮 | P0 | 低 |
| Phase 1 | CSS 拆分 | 14 轮 | P1 | 低 |
| Phase 2 | workspace.js 拆分 | 10 轮 | P2 | 中 |
| Phase 3 | samples.js 拆分 | 7 轮 | P3 | 中 |
| Phase 4 | app.js 拆分 | 5 轮 | P4 | 高 |
| Phase 5 | 收尾验证 | 1 轮 | P5 | 低 |

---

## Phase 0 — 环境准备

### 目标
建立重构工作环境，确保有回滚能力。

### 允许改动范围
- `docs/` 目录

### 不允许改动
- 所有业务源码
- index.html

### 完成标准
- [x] 当前项目文件状态已审查并记录（已完成于 2026-05-31）
- [ ] 所有源码已 git commit（当前项目不在 git 仓库中，需要先 `git init` + 首次提交）
- [ ] 服务端 `server.py` 可正常启动、`GET /api/state` 返回 200
- [ ] 前端页面可正常加载、无控制台报错

### 推荐 commit
```
git init
git add -A
git commit -m "chore: snapshot before modularization refactor"
```

---

## Phase 1 — CSS 拆分

### 总目标
将 `css/style.css`（4,344行）拆分为 14 个文件，原文件变为 `@import` 入口。

### 允许改动范围
- `css/style.css` — 原有规则逐块移动到目标文件
- `css/00-vars.css` 到 `css/90-responsive.css` — 新建
- `index.html` — `<link>` 标签改为指向 `css/style.css`（总入口不变）

### 不允许改动
- 不删除任何 CSS 规则
- 不修改任何 CSS 属性值
- 不修改任何选择器
- 不修改 JS 源码
- 不修改 server.py

### 每轮完成标准
- [ ] `git diff --stat` 只包含 css/ 目录 + index.html（仅 `<link>` 如有需要）
- [ ] 页面人工验收：所有页面无可见布局变化
- [ ] 浏览器 DevTools 无 404（CSS 文件全部加载）
- [ ] 无控制台 CSS-related 报错

### CSS 拆分轮次

#### Round 1.1: 创建 `00-vars.css`
- **移动内容**：style.css 中 `:root { ... }` 块（行 5-26）
- **验证**：页面颜色、字体、CSS 变量值无变化

#### Round 1.2: 创建 `01-layout.css`
- **移动内容**：`* { box-sizing }`、`body`、sidebar、main、header、content、topbar、bottom 等布局规则（行 28-97）
- **验证**：整体布局无偏移

#### Round 1.3: 创建 `02-components.css`
- **移动内容**：button / input / select / textarea / label / table / badge / card / grid / form-row / modal / toast / progress-bar 等通用组件（行 98-230, 966-989）
- **注意**：`@keyframes fadeIn` 随 toast 一起移动
- **验证**：按钮、输入框、表格、徽章、卡片样式无变化

#### Round 1.4: 创建 `10-projects.css`
- **移动内容**：所有 `.project-*` 相关规则
- **验证**：项目管理页布局无变化

#### Round 1.5: 创建 `20-samples.css`
- **移动内容**：
  - 样机卡片（.sample-card, .sample-category-*, .sample-add-card）
  - 样机池头（.sample-pool-*）
  - 样机统计（.sample-category-total, .sample-category-stats, .sample-category-stat）
  - 样机详情模态框（.sample-archive-*）
  - 样机摘要（.sample-summary-*）
  - 样机问题表（.sample-initial-result-*, .sample-result-btn）
  - 样机履历（.sample-history-*）
  - 销毁确认（.destroy-impact）
  - 人员选择器（.sample-person-*）
  - 空态（.sample-archive-empty）
  - 信息分隔线（.sample-info-divider）
  - 响应式中样机部分
- **验证**：样机档案池全部页面无变化

#### Round 1.6: 创建 `30-workspace-home.css`
- **移动内容**：
  - 首页（.home-*）
  - 项目工作台主页（.workspace-section, .section-head, .section-body, .section-toggle-triangle）
  - 阶段摘要卡片（.stage-summary-*）
  - 项目人员卡片（.project-member-*）
  - 项目位置卡片（.project-location-*）
  - 项目配置区（.project-config-*）
  - SKU 编辑器（.sku-editor, .sku-row, .inline-sku-*）
  - 折叠按钮（.collapse-btn）
  - row-action-btn（.row-action-btn）
  - 阶段编辑面板（.stage-edit-panel）
- **验证**：工作台主页无布局变化

#### Round 1.7: 创建 `31-stage-strategy.css`
- **移动内容**：
  - BOM 表格（.bom-config-table, .bom-table, .bom-desc）
  - 策略表格（.strategy-config-table, .strategy-table）
  - 用例下拉（.case-dropdown, .case-option, .case-*）
  - 用例工具（.case-tools, .case-master-badge）
  - 宽表滚动（.wide-table-scroll, .mini-table）
- **验证**：阶段配置页无布局变化

#### Round 1.8: 创建 `32-task-flow.css`
- **移动内容**：
  - 任务流转统计（.task-flow-summary, .task-flow-stat, .stat-*）
  - 任务筛选栏（.task-filter-*）
  - 任务管理表格（.task-flow-table, .task-sku-cell, .task-type-*, .task-executor-*, .task-sample-cell, .task-time-cell）
  - 任务操作列（.task-op-*）
  - 状态徽章（.badge.status-*）
  - 表格中的问题单列（.task-issue-*, .task-issue-record-*）
  - 新增任务按钮（.task-add-*）
  - 任务池弹窗（.task-pool-*）
  - 任务更多菜单（.task-more-*）
  - 启动按钮（.btn-start, .task-start-disabled-tip）
  - 缓冲行（.task-flow-buffer-row）
  - 失效统计（.task-result-summary, .task-result-ratio, .task-result-fail-list, .task-result-tag-removed）
- **验证**：任务管理表格无布局变化

#### Round 1.9: 创建 `33-task-config-modal.css`
- **移动内容**：
  - 任务配置弹窗壳（.task-config-modal, .task-config-shell, .task-config-nav, .task-config-main, .task-config-panel, .task-config-titlebar, .task-config-title-context）
  - 任务配置面板内通用样式
  - PATCH 2026-05-31 的三层滚动修复块（行 4102-4285）
  - PATCH 2026-05-31 的全局样机数提示（行 4288-4343）
- **验证**：任务配置弹窗无布局变化，样机池列表可正常滚动

#### Round 1.10: 创建 `34-sample-picker.css`
- **移动内容**：
  - 样机选择器（.dispatch-sample-*）
  - 分配样机弹窗（.assign-sample-modal）
  - 样机数量提示（.sample-limit-hint, .sample-limit-count, .sample-limit-global）
- **验证**：样机选择器无布局变化

#### Round 1.11: 创建 `35-task-result.css`
- **移动内容**：
  - 结果录入弹窗（.task-result-modal, .task-result-layout, .task-result-fixed-panel, .task-result-scroll-panel, .task-result-form-grid, .task-result-section-title）
  - 样机行（.task-result-sample-row, .task-result-sample-index, .task-result-sample-code, .task-result-sample-state）
  - 去向网格（.task-result-route-grid）
  - 问题表单（.task-result-problem-*, .task-result-existing-*, .task-result-new-problem）
  - 图片上传（.task-result-photo-*, .task-result-sample-photos）
  - 表单校验（.is-invalid, .field-error, .has-error）
  - 挂账人/持有人字段（.task-result-account-row, .sample-destination-extra）
- **验证**：结果录入弹窗无布局变化

#### Round 1.12: 创建 `36-task-log.css`
- **移动内容**：
  - 任务日志列表（.task-log-context, .task-log-list, .task-log-item, .task-log-text, .task-log-meta）
  - 日志序列号（.log-seq, .history-seq）
  - 日志行（.log-line）
  - 样机日志引用（.sample-log-link, .sample-log-ref-missing）
  - 测试结果高亮（.log-result-pass, .log-result-fail）
  - 任务日志多行（.task-log-text-multiline, .task-log-detail-line, .task-log-detail-label, .task-log-detail-value）
- **验证**：任务日志弹窗无布局变化

#### Round 1.13: 创建 `90-responsive.css`
- **移动内容**：所有 `@media` 查询块（行 2636-2648, 2943-2953, 3078-3086, 3532-3559, 3694-3701）
- **验证**：窄屏布局无变化

#### Round 1.14: 收尾 — `style.css` 变为纯 @import
- **将**原 `style.css` 的全部内容替换为 `@import` 语句
- **验证**：全站页面逐一检查，确认无视觉差异

---

## Phase 2 — workspace.js 拆分

### 总目标
将 `js/workspace.js`（3,594行）拆分为 10 个子模块（✅ 已完成）。

### 拆分结果
- `js/workspace/01-shared.js` — 共享工具
- `js/workspace/02-home.js` — 工作台主页
- `js/workspace/10-dropdown-issue.js` — 用例下拉+问题单
- `js/workspace/03-strategy.js` — 阶段策略
- `js/workspace/04-stage.js` — 阶段 CRUD
- `js/workspace/05-task-table.js` — 任务表格
- `js/workspace/06-sample-picker.js` — 样机选择器
- `js/workspace/07-task-config.js` — 任务配置弹窗
- `js/workspace/08-task-actions.js` — 任务操作
- `js/workspace/09-task-result.js` — 结果录入
- `index.html` — `<script>` 加载顺序更新

### 不允许改动
- 不删除任何函数
- 不修改函数签名
- 不修改业务逻辑
- 不修改 CSS
- 不修改 server.py

### 每轮完成标准
- [x] `git diff --stat` 只包含 js/workspace/ 目录 + js/workspace.js（删除）+ index.html（✅ 已完成）
- [ ] 页面可正常加载，无控制台 JS 报错（特别注意 `app.xxx is not a function`）
- [ ] 所有页面功能正常（人工验收）

### workspace.js 拆分轮次

#### Round 2.1: 创建 `js/workspace/workspace.home.js`
- **移动函数**：`renderProjectWorkspace`、`workspaceMembersHtml`、`workspaceLocationsHtml`、`addProjectLocation`、`removeProjectLocation`、`addProjectMember`、`removeProjectMember`、`validateProjectMember`、`findProjectMemberByIdentity`、`hasProjectMemberNameConflict`、`downloadProjectMembersTemplate`、`importProjectMembersCsv`、`memberWorkStats`、`setProjectMemberSearch`
- **移动函数**（阶段排序）：`toggleStageSortMode`、`onStageDragStart`、`onStageDragOver`、`onStageDragLeave`、`onStageDrop`、`onStageDragEnd`
- **行号范围**：约 1-410

#### Round 2.2: 创建 `js/workspace/workspace.stage.js`
- **移动函数**：`inlineStageEditorHtml`、`inlineSkuRowHtml`、`updateInlineStageName`、`normalizeInlineStageName`、`readInlineSkuInputs`、`updateInlineSkus`、`normalizeInlineSkus`、`addInlineSku`、`removeInlineSku`、`refreshInlineSkuIndexes`、`skuEditorHtml`、`addSkuInput`、`removeSkuInput`、`refreshSkuIndexes`、`readSkuInputs`、`addStage`、`editStage`、`deleteStage`、`copyStage`
- **行号范围**：约 714-955

#### Round 2.3: 创建 `js/workspace/workspace.strategy.js`
- **移动函数**：`workspaceBomHtml`、`addBomRow`、`updateBom`、`deleteBomRow`、`workspaceStrategyHtml`、`addStrategyRow`、`onStrategyInput`、`validateSampleSizeInput`、`updateStrategySku`、`scheduleStrategySync`、`deleteStrategyRow`、`syncStrategyFromDom`、`autoSyncProgress`、`downloadTestCaseTemplate`、`importTestCaseXlsx`、`openStageStrategy`、`closeStageStrategy`、`leaveStageStrategy`、`renderStageStrategyPage`
- **行号范围**：约 460-711

#### Round 2.4: 创建 `js/workspace/workspace.task-table.js`
- **移动函数**：`taskOwnerName`、`taskOwnerId`、`taskDateText`、`taskCategoryItemText`、`taskFlowStatus`、`taskStatusBadgeClass`、`taskRowsForStage`、`taskInfoForRow`、`workspaceTaskFlowHtml`、`taskFlowActionsHtml`、`taskMoreMenuHtml`、`taskDeleteImpactHtml`、`confirmTaskDeleteKeyword`、`showTaskSamples`、`taskSampleTaskFlowStatus`
- **行号范围**：约 958-1420

#### Round 2.5: 创建 `js/workspace/workspace.task-config.js`
- **移动函数**：`createTaskFromProgress`、`openAddTasksFromPoolModal`、`setTaskPoolChecked`、`updateTaskPoolSelectionCount`、`ensurePlanTask`、`getProgressRequiredSampleCount`、`getProgressDisplayName`、`getSelectedTaskSampleIds`、`validateTaskSampleSelection`、`updateTaskSampleLimitUI`、`onTaskSampleCheckboxChange`、`openTaskConfigPanel`、`taskConfigPanelHtml`、`taskPlanConfigPanelHtml`、`taskSampleConfigPanelHtml`、`saveTaskPlanConfig`、`saveTaskSampleConfig`、`saveTaskConfigAll`、`hasUnsavedTaskConfigChanges`、`switchTaskConfigTab`、`taskConfigDisplayName`、`projectMemberSelectHtml`、`setPlanTaskSchedule`、`assignPlanTaskSamples`、`isTaskChangePayloadChanged`
- **行号范围**：约 1422-2197

#### Round 2.6: 创建 `js/workspace/workspace.sample-picker.js`
- **移动函数**：`getAssignSampleSearchText`、`sampleTestedItemNames`、`buildTaskSamplePickerHtml`、`updateDispatchSamplePoolCounts`、`toggleDispatchGroup`、`filterDispatchGroup`
- **行号范围**：约 1652-1782

#### Round 2.7: 创建 `js/workspace/workspace.task-actions.js`
- **移动函数**：`statusForOpenTaskUsage`、`releaseTaskSamples`、`deleteTask`、`startTask`、`blockTask`、`tempChangeTask`
- **行号范围**：约 2219-2331, 2254-2287, 2290-2318, 3164-3329

#### Round 2.8: 创建 `js/workspace/workspace.task-result.js`
- **移动函数**：`taskSampleDisplayName`、`taskSampleArchiveName`、`taskSampleIdentityInfo`、`isTaskDirtyProblemText`、`taskFailureProblemsBySample`、`taskFailureStats`、`taskResultSearchText`、`taskIssueSummaryHtml`、`defaultSampleReceiver`、`sampleStatusOptionsHtml`、`taskSampleFaultOptionsHtml`、`taskSampleDestinationOptionsHtml`、`onTaskResultDestinationChange`、`ensureTaskRemovedSampleRecords`、`recordTaskRemovedSamples`、`taskResultSampleEntries`、`taskResultProblemTableHtml`、`taskResultProblemRowHtml`、`removeTaskResultProblemRow`、`taskResultSampleRowsHtml`、`taskResultRowPhotos`、`setTaskResultRowPhotos`、`renderTaskResultPhotoList`、`uploadTaskResultPhotos`、`appendTaskSampleFault`、`collectTaskResultForm`、`validateTaskResultPayload`、`clearTaskResultValidationMarks`、`markTaskResultInvalid`、`markTaskResultValidation`、`taskResultAutoReason`、`syncTaskResultSampleProblems`、`saveTaskResultDraft`、`applyTaskResult`、`isTaskResultSamplesEqual`、`isTaskResultPayloadEqual`、`saveTaskResult`、`uploadResult`、`completeTask`
- **行号范围**：约 2320-3406

#### Round 2.9: 创建 `js/workspace/workspace.case-dropdown.js`
- **移动函数**：`openCaseDropdown`、`positionCaseDropdown`、`repositionCaseDropdown`、`filterCaseDropdown`、`renderCaseDropdownOptions`、`closeCaseDropdown`、`selectCaseSuggestion`
- **行号范围**：约 3408-3533

#### Round 2.10: 创建 `js/workspace/workspace.issue-record.js`
- **移动函数**：`updateIssueRecordRemark`、`taskIssueRecordHtml`、`openTaskIssueRecordModal`
- **行号范围**：约 3535-3592

---

## Phase 3 — samples.js 拆分

### 总目标
将 `js/samples.js`（1,405行）拆分为 7 个子模块，放入 `js/samples/` 目录。

### 每轮完成标准
- [ ] `git diff --stat` 只包含 js/samples/ 目录 + js/samples.js（删除）+ index.html
- [ ] 页面可正常加载，无控制台 JS 报错
- [ ] 样机档案池全部功能正常

### samples.js 拆分轮次

#### Round 3.1: 创建 `js/samples/samples.list.js`
- **移动函数**：`renderSamples`、`sampleCardHtml`、`sampleDisplayCode`、`sampleCategoryStatsHtml`、`sampleStatusStatClass`、`openCategory`

#### Round 3.2: 创建 `js/samples/samples.crud.js`
- **移动函数**：`sampleCategoryNameExists`、`addSampleCategory`、`editSampleCategory`、`deleteSampleCategory`、`collectSampleCategoryDestroyImpact`、`sampleCategoryDestroyImpactHtml`、`applySampleCategoryDestroyImpact`、`canDestroySample`、`collectSingleSampleDestroyImpact`、`singleSampleDestroyImpactHtml`、`applySingleSampleDestroyImpact`、`destroySample`、`confirmDeleteKeyword`、`newSample`、`nextSampleNo`、`addSample`、`addSamples`

#### Round 3.3: 创建 `js/samples/samples.import-export.js`
- **移动函数**：`importSampleBatch`、`importSampleCsv`、`sampleIdentifierSet`、`sampleIdentifierSignature`、`findDuplicateSampleInCategory`、`downloadSampleTemplate`、`exportSampleCsv`

#### Round 3.4: 创建 `js/samples/samples.detail.js`
- **移动函数**：`sampleArchivePlaceholder`、`samplePersonInputHtml`、`validateSamplePersonInput`、`sampleLocationInputHtml`、`sampleInitialResultsValue`、`findSampleSnapshot`、`openSampleReadonly`、`openSampleDetail`、`switchSampleArchiveTab`

#### Round 3.5: 创建 `js/samples/samples.photos.js`
- **移动函数**：`samplePhotosHtml`、`previewSamplePhoto`、`uploadSamplePhotos`、`startPhotoRename`、`finishPhotoRename`、`deleteSamplePhoto`、`sampleTaskResultPhotos`

#### Round 3.6: 创建 `js/samples/samples.problems.js`
- **移动函数**：`sampleProblemsHtml`、`sampleProblemRowHtml`、`addSampleProblemRow`、`removeSampleProblemRow`、`collectSampleProblems`、`sampleInitialResultsHtml`、`addSampleInitialResultRow`、`removeSampleInitialResultRow`、`collectSampleInitialResults`、`showSamplePersonOptions`、`hideSamplePersonOptions`、`filterSamplePersonOptions`、`pickSamplePerson`、`sampleHasArchiveData`

#### Round 3.7: 创建 `js/samples/samples.history.js`
- **移动函数**：`sampleHistoryPhotosHtml`、`sampleTestHistoryHtml`

---

## Phase 4 — app.js 拆分

### 总目标
将 `js/app.js`（1,243行）拆分为 7 个子模块（✅ 已完成）。

### 拆分结果
- `js/app.core.js` — 核心入口
- `js/app.server.js` — 服务器通信
- `js/app.data.js` — 数据工具
- `js/app.render.js` — 渲染引擎
- `js/app.filters.js` — 筛选器
- `js/app.modal.js` — 弹窗系统
- `js/app.logs.js` — 日志系统
- `index.html` — `<script>` 加载顺序更新
- `js/app.*.js` — 新建
- `index.html` — `<script>` 加载顺序更新

### 每轮完成标准
- [ ] `git diff --stat` 只包含 js/app*.js + index.html
- [ ] 页面可正常加载，app.init() 正常执行
- [ ] 所有模块的基础功能正常

### app.js 拆分轮次

#### Round 4.1: 创建 `js/app.core.js`
- **移动内容**：`const app = { ... }` 对象声明（含 version、data、view、constants、serverRevision 等属性）、`init()`、`emptyData()`、`cloneData()`、`serverOnline`/`_saveInFlight`/`_saveQueued`/`_baseData`、`updateServerStatus()`、`reloadFromServer()`、`scheduleSave()`、`save()`
- **注意**：`init()` 中引用的 `normalize()` / `render()` 等在后续模块中，通过 Object.assign 延迟绑定

#### Round 4.2: 创建 `js/app.data.js`
- **移动函数**：`normalizePersonText()`、`projectActiveMembers()`、`normalize()`、`currentProject()`、`currentStage()`、`allSamples()`、`findSample()`、`projectName()`、`stageName()`、`activeStageTasks()`、`sampleProblemRecords()`、`sampleHasProblem()`、`sampleEffectiveStatus()`、`sampleTaskLabelFromCtx()`、`addSampleProblem()`、`changeSampleStatus()`、`activeTaskUsagesForSample()`、`reconcileSampleTaskOccupancy()`、`isTaskCompleted()`、`isTaskExecuted()`、`isSampleUsedByAnotherOpenTask()`、`sampleDisplayCode()`、`openSampleReadonly()`、`getProjectStageTask()`、`taskFlowStatus()`（如果从 workspace 移入）

#### Round 4.3: 创建 `js/app.render.js`
- **移动函数**：`render()`、`renderHome()`、`renderDevices()`、`renderPreserveScroll()`、`renderNav()`、`renderHeader()`、`breadcrumbHtml()`、`go()`、`renderEmpty()`、`toggleSidebar()`、`applySidebarState()`、`isCollapsed()`、`collapseButton()`、`sectionToggleTriangle()`、`toggleSection()`

#### Round 4.4: 创建 `js/app.modal.js`
- **移动函数**：`_syncModalInputsToAttributes()`、`showModal()`、`showConfirm()`、`showAlert()`、`closeConfirm()`、`closeModal()`、`clearFieldValidationMarks()`、`markFieldInvalid()`、`showDangerConfirm()`、`updateSelectPlaceholderState()`

#### Round 4.5: 创建 `js/app.logs.js`
- **移动函数**：`closeTaskOpMenus()`、`handleTaskOpMenuClick()`、`logHtml()`、`ensureTaskLogs()`、`addTaskLog()`、`logSampleRefToken()`、`compactTaskLogText()`、`taskLogContentText()`、`taskLogDetailLines()`、`taskLogContentHtml()`、`findLogSampleRefId()`、`linkSampleRefsInLogText()`、`highlightTestResult()`、`taskLogHtml()`、`showTaskLogs()`

---

## Phase 5 — 收尾验证

### 目标
全量回归验证，确保所有功能正常。

### 验证清单
- [ ] `python server.py` 正常启动
- [ ] 首页加载无报错
- [ ] 项目管理：新建/编辑/删除项目
- [ ] 项目工作台：阶段管理、BOM、策略、任务全生命周期
- [ ] 样机档案池：样机池管理、样机 CRUD、照片、问题表、导入导出
- [ ] 任务操作：配置、启动、阻塞、临时变更、结果上传、结束任务
- [ ] 所有弹窗正常打开/关闭
- [ ] 筛选、搜索功能正常
- [ ] 数据保存和同步正常
- [ ] 浏览器 DevTools Network 标签无 404
- [ ] 浏览器 DevTools Console 无报错

### 推荐 commit
```
git add -A
git commit -m "chore: complete modularization refactor — all phases verified"
```

---

## 推荐 Git Commit 节点

| 节点 | 描述 |
|------|------|
| `init` | 重构前快照 |
| `phase0` | 环境准备完成 |
| `css-vars` | Round 1.1: CSS 变量拆分 |
| `css-layout` | Round 1.2: 布局拆分 |
| `css-components` | Round 1.3: 组件拆分 |
| `css-projects` | Round 1.4: 项目管理样式拆分 |
| `css-samples` | Round 1.5: 样机样式拆分 |
| `css-ws-home` | Round 1.6: 工作台主页样式拆分 |
| `css-ws-strategy` | Round 1.7: 策略/BOM 样式拆分 |
| `css-ws-taskflow` | Round 1.8: 任务表格样式拆分 |
| `css-ws-taskconfig` | Round 1.9: 任务配置样式拆分 |
| `css-ws-picker` | Round 1.10: 样机选择器样式拆分 |
| `css-ws-result` | Round 1.11: 结果录入样式拆分 |
| `css-ws-log` | Round 1.12: 任务日志样式拆分 |
| `css-responsive` | Round 1.13: 响应式拆分 |
| `css-entry` | Round 1.14: style.css → @import |
| `phase1-done` | Phase 1 完成 |
| `ws-home` | Round 2.1: workspace.home.js |
| `ws-stage` | Round 2.2: workspace.stage.js |
| `ws-strategy` | Round 2.3: workspace.strategy.js |
| `ws-tasktable` | Round 2.4: workspace.task-table.js |
| `ws-taskconfig` | Round 2.5: workspace.task-config.js |
| `ws-picker` | Round 2.6: workspace.sample-picker.js |
| `ws-actions` | Round 2.7: workspace.task-actions.js |
| `ws-result` | Round 2.8: workspace.task-result.js |
| `ws-dropdown` | Round 2.9: workspace.case-dropdown.js |
| `ws-issue` | Round 2.10: workspace.issue-record.js |
| `phase2-done` | Phase 2 完成 |
| `samples-list` | Round 3.1 |
| `samples-crud` | Round 3.2 |
| `samples-import` | Round 3.3 |
| `samples-detail` | Round 3.4 |
| `samples-photos` | Round 3.5 |
| `samples-problems` | Round 3.6 |
| `samples-history` | Round 3.7 |
| `phase3-done` | Phase 3 完成 |
| `app-core` | Round 4.1 |
| `app-data` | Round 4.2 |
| `app-render` | Round 4.3 |
| `app-modal` | Round 4.4 |
| `app-logs` | Round 4.5 |
| `phase4-done` | Phase 4 完成 |
| `phase5-done` | Phase 5 收尾验证 |
