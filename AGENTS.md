# TestChamber V7 — 数字治理平台 · AI 代码定位器

> **用途**：让 AI agent 快速定位需要修改的代码。每个函数、CSS 规则组、API 端点都标注 `文件:行号`。

## 项目概要

| 项目 | 值 |
|------|-----|
| 应用 | 数字治理平台 V7 内网协同版 |
| 用途 | 终端硬件测试样机全生命周期：项目→阶段→任务→样机→结果 |
| 部署 | Python stdlib `ThreadingHTTPServer`，端口 9398，SQLite WAL |
| 前端 | Vanilla JS SPA，`Object.assign(app, {...})` 模块模式 |
| 规模 | ~14,100 行源码 |

---

## 文件地图 — 精确到函数

### server.py (1793 行)

| 行号 | 符号 | 职责 |
|------|------|------|
| 35–43 | 全局常量 | `APP_VERSION`, `DB_PATH`, `MAX_UPLOAD_BYTES`(80MB), `DB_LOCK` |
| 48–61 | `empty_data()`, `ensure_dirs()` | 空状态模板, 目录创建 |
| 70–75 | `connect_db()` | SQLite 连接(WAL, 30s timeout) |
| 162–175 | backup 常量 | 节流间隔(5min/50rev), 清理策略(5/小时, 10全局) |
| 185–209 | `_should_backup()`, `write_backup()` | backup 节流判断 + 写入 |
| 225–273 | `prune_backups()` | 每小时保留5个, 全局最多10个 |
| 276–448 | `ensure_schema()` | 10 张表 DDL |
| 633–787 | `sync_sample_library()` | 样机库 → SQLite 同步(upsert+清理) |
| 790–873 | `load_sample_library()` | SQLite → 内存样机库 |
| 876–961 | `list_item_key()`, `merge_record()`, `merge_list_by_id()` | 三向合并引擎 |
| 965–971 | `PROJECT_CHILDREN` | 项目嵌套合并层级声明 |
| 974–980 | `SAMPLE_CATEGORY_CHILDREN` | 样机嵌套合并层级声明 |
| 1003–1027 | `merge_state()` | 顶层三向合并入口 |
| 1030–1207 | `sync_project_library()` | 项目/阶段/任务 → SQLite |
| 1210–1297 | `load_project_library()` | SQLite → 项目列表 |
| 1300–1310 | `compose_state()` | 从 SQLite 拼装完整 state |
| 1313–1342 | `init_db()` | 首次启动建库 + V6→V7 自动迁移 |
| 1355–1397 | `detect_sample_occupancy_conflicts()` | C1 占用冲突检测 |
| 1400–1467 | `save_state()` | PUT /api/state 处理 |
| 1470–1497 | `parse_multipart()` | multipart/form-data 解析 |
| 1500–1529 | `commit_data_mutation()` | 照片上传/删除等直接变更 |
| 1532–1657 | `Handler.do_GET()` | GET 路由 |
| 1570–1590 | `_is_public_static_path()` | 静态文件白名单 |
| 1659–1701 | `Handler.do_POST()` | POST 路由(照片上传) |
| 1703–1736 | `Handler.do_DELETE()` | DELETE 路由(照片软删除) |
| 1738–1763 | `Handler.do_PUT()` | PUT /api/state 路由 |
| 1766–1793 | `main()` | 启动入口 |

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

### js/app.core.js (106 行)

| 行号 | 符号 | 职责 |
|------|------|------|
| 5–35 | `app = {...}` | 全局对象(version, data, view, constants, _baseData, _saveInFlight等) |
| 27–34 | `app.view` | UI状态: module, selectedProjectId, filters, collapsed, sidebarCollapsed |
| 37–38 | `app.constants` | 样机5状态, 任务5状态, 模块名称枚举 |
| 49–105 | `init()` | 入口: GET /api/state → normalize → render → 全局事件绑定 |

### js/app.server.js (177 行) — 服务器通信

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `updateServerStatus()` | 侧栏保存状态指示器 |
| 22 | `reloadFromServer()` | GET /api/state 全量刷新 |
| 42 | `scheduleSave()` | 450ms debounce→`save()` |
| 54 | `save()` | PUT /api/state 持久化(含C1冲突处理) |
| 138 | `hasLocalUnsavedChanges()` | JSON比较 data vs _baseData |
| 142 | `prepareBeforeDirectMutation()` | 照片上传前:清debounce→等inFlight→存草稿 |
| 168 | `syncAfterDirectMutation()` | 照片上传后:从服务器刷新 |

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

### js/app.render.js (244 行) — 渲染引擎

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

### js/app.modal.js (203 行) — 弹窗系统

| 行号 | 函数 | 职责 |
|------|------|------|
| 26 | `showModal()` | **主弹窗**: onOk返回true=保持打开, 返回false/undefined=关闭 |
| 80 | `showConfirm()` | 独立确认框 |
| 111 | `showAlert()` | 纯提示框(隐藏取消) |
| 128 | `closeModal()` | 关闭弹窗(modal stack弹出恢复) |
| 154 | `clearFieldValidationMarks()` | 清除所有.is-invalid+.field-error |
| 162 | `markFieldInvalid(el,msg)` | 标红+插入.field-error+自动滚动 |
| 174 | `showDangerConfirm()` | 危险操作确认(需输入DELETE关键词) |

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

### js/projects.js (253 行) — 项目管理

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `renderProjects()` | 项目列表渲染 |
| 31 | `projectNameExists()` | 项目名唯一性(大小写不敏感) |
| 39 | `addProject()` | 新建项目弹窗 |
| 81 | `editProject()` | 编辑项目弹窗 |
| 119 | `collectProjectDeleteImpact()` | 删除影响分析 |
| 192 | `deleteProject()` | 删除项目(释放样机+showDangerConfirm) |
| 244 | `selectProject()` | 进入项目工作台 |

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

### js/workspace/02-home.js (450 行) — 工作台主页

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `renderProjectWorkspace()` | 主页渲染:阶段卡片+人员+位置+任务管理 |
| 128 | `workspaceMembersHtml()` | 人员配置区域 |
| 167 | `workspaceLocationsHtml()` | 位置配置区域 |
| 195–237 | `add/edit/removeProjectLocation()` | 位置CRUD |
| 265–318 | `add/edit/removeProjectMember()` | 人员CRUD |
| 327 | `importProjectMembersCsv()` | 人员CSV批量导入 |
| 380 | `memberWorkStats()` | 人员工作统计 |
| 399–443 | 拖拽排序回调 | 阶段排序 |

### js/workspace/10-dropdown-issue.js (200 行) — 用例下拉+问题单

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `openCaseDropdown()` | 打开用例搜索下拉 |
| 22 | `positionCaseDropdown()` | 下拉定位(自动上/下) |
| 59 | `renderCaseDropdownOptions()` | 下拉选项渲染(含mousedown选择) |
| 116 | `selectCaseSuggestion()` | 选择用例填充到策略输入框 |
| 145 | `taskIssueRecordHtml()` | 任务问题单展示(DTS/是否重复/备注) |
| 168 | `openTaskIssueRecordModal()` | 问题单录入弹窗 |

### js/workspace/03-strategy.js (307 行) — 阶段策略配置

| 行号 | 函数 | 职责 |
|------|------|------|
| 9 | `openStageStrategy()` | 进入策略页 |
| 33 | `renderStageStrategyPage()` | 策略页渲染(阶段编辑+BOM+策略表) |
| 54–104 | `workspaceBomHtml/addBomRow/updateBom/deleteBomRow` | BOM上料清单 |
| 107–166 | `workspaceStrategyHtml/addStrategyRow/onStrategyInput` | 测试策略表 |
| 197 | `scheduleStrategySync()` | 800ms节流策略同步 |
| 229 | `autoSyncProgress()` | **策略→进度自动同步**(离开策略页时触发) |
| 264 | `importTestCaseXlsx()` | 用例集导入 |

### js/workspace/04-stage.js (276 行) — 阶段与SKU编辑

| 行号 | 函数 | 职责 |
|------|------|------|
| 8 | `inlineStageEditorHtml()` | 策略页内联编辑器(SKU管理) |
| 112 | `skuEditorHtml()` | 弹窗版SKU编辑器 |
| 145 | `addStage()` | 新建阶段弹窗 |
| 173 | `editStage()` | 编辑阶段弹窗 |
| 195 | `deleteStage()` | 删除阶段(安全机制:占用样机时拒绝) |
| 229 | `copyStage()` | 复制阶段(含strategy/progress深层克隆) |

### js/workspace/05-task-table.js (435 行) — 任务表格

| 行号 | 函数 | 职责 |
|------|------|------|
| 47 | `workspaceTaskFlowHtml()` | **任务管理工作台**:统计+筛选栏+表格+新增按钮 |
| 201 | `taskDeleteImpactHtml()` | 任务删除影响分析 |
| 265 | `taskFlowActionsHtml()` | **操作按钮**:按状态显示不同按钮组合 |
| 339 | `showTaskSamples()` | 任务样机清单弹窗 |
| 420 | `sampleTestedItemNames()` | 样机已测项目列表 |

### js/workspace/06-sample-picker.js (222 行) — 样机选择器

| 行号 | 函数 | 职责 |
|------|------|------|
| 7 | `getSelectedTaskSampleIds()` | 读取勾选样机ID |
| 11 | `validateTaskSampleSelection()` | 样机数量校验 |
| 19 | `updateTaskSampleLimitUI()` | 计数胶囊(warn/bad/full状态) |
| 68 | `onTaskSampleCheckboxChange()` | 勾选:超量静默取消+选满禁用 |
| 108 | `buildTaskSamplePickerHtml()` | **样机选择器HTML**(池分组/搜索/勾选/禁用) |
| 174 | `updateDispatchSamplePoolCounts()` | 各池已选计数更新 |
| 187 | `filterDispatchGroup()` | 池内搜索/排除过滤 |
| 210 | `isTaskChangePayloadChanged()` | 变更检测(计划+样机) |

### js/workspace/07-task-config.js (517 行) — 任务配置弹窗

| 行号 | 函数 | 职责 |
|------|------|------|
| 15 | `resolveTaskProgress()` | 解析progress(live vs snapshot) |
| 31 | `createTaskFromProgress()` | 从progress创建任务 |
| 68 | `openAddTasksFromPoolModal()` | 从测试池批量新增任务 |
| 289 | `openTaskConfigPanel()` | **新版双Tab配置弹窗入口** |
| 333 | `taskConfigPanelHtml()` | 弹窗外壳(导航+面板) |
| 356 | `taskPlanConfigPanelHtml()` | 计划配置Tab |
| 381 | `taskSampleConfigPanelHtml()` | 样机配置Tab |
| 398 | `saveTaskConfigAll()` | **统一保存**:plan+sample校验+变更检测 |
| 484 | `hasUnsavedTaskConfigChanges()` | 未保存检测(取消按钮用) |
| 504 | `switchTaskConfigTab()` | Tab切换 |

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

### js/workspace/09-task-result.js (731 行) — 结果录入

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
| 618 | `saveTaskResult()` | **保存/结束入口**:draft vs finish分支 |
| 655 | `uploadResult()` | **结果录入弹窗**:任务级结果+每台样机去向 |

### js/samples/ — 样机档案池（已拆分）

| 文件 | 行数 | 主要职责 |
|------|------|------|
| `js/samples.js` | 4 | 兼容占位，实际实现由 `index.html` 加载子模块 |
| `js/samples/01-pool.js` | 672 | 样机池列表、样机卡片、池/样机 CRUD、销毁影响分析 |
| `js/samples/02-import-export.js` | 198 | 样机批量导入/导出、SN/IMEI/主板SN 去重链 |
| `js/samples/03-detail-fields.js` | 98 | 样机详情字段、人名输入、位置输入、初检问题解析 |
| `js/samples/04-photos.js` | 276 | 照片上传、缩略图生成、预览、重命名、删除 |
| `js/samples/05-problems.js` | 92 | 样机问题表多行编辑 UI |
| `js/samples/06-history.js` | 202 | 样机测试履历、结果图片、只读快照 |
| `js/samples/07-detail.js` | 164 | 样机详情 5 Tab 弹窗 |

### js/debug/auditConsistency.js (191 行)

| 行号 | 函数 | 职责 |
|------|------|------|
| 33 | `auditConsistency()` | 浏览器控制台只读审计(占用冲突/孤立progress/缺失样机/状态不一致/重复ID) |

---

## 功能 → 代码速查

想修改某行为？直接跳到对应位置:

| 要改什么 | 文件:函数(行号) |
|----------|-----------------|
| 后端端口/地址 | `server.py:1768-1769` |
| 最大上传体积 | `server.py:43` `MAX_UPLOAD_BYTES` |
| backup频率/数量 | `server.py:162-175` |
| 数据库表结构 | `server.py:276-448` `ensure_schema()` |
| 样机/任务状态枚举 | `js/app.core.js:37-38` |
| 状态变更统一入口 | `js/app.data.js:360` `changeSampleStatus()` |
| 任务状态标准化 | `js/workspace/01-shared.js:42` `taskFlowStatus()` |
| 数据规范化(旧格式修复) | `js/app.data.js:33` `normalize()` |
| 三向合并(服务端) | `server.py:1003-1027` `merge_state()` |
| 保存流程(前端) | `js/app.server.js:54` `save()` |
| 保存流程(后端) | `server.py:1400` `save_state()` |
| 样机占用冲突C1(后端) | `server.py:1355` `detect_sample_occupancy_conflicts()` |
| 样机占用冲突C1(前端) | `js/app.server.js:85-98` |
| 弹窗onOk行为 | `js/app.modal.js:68-74` (返回true=保持打开) |
| 内联校验标红 | `js/app.modal.js:162` `markFieldInvalid()` |
| DELETE确认弹窗 | `js/app.modal.js:174` `showDangerConfirm()` |
| Toast提示 | `js/utils.js:24` |
| HTML转义 | `js/utils.js:7` `esc()` |
| 人员格式校验 | `js/utils.js:188` `parsePersonField()` |
| 人员下拉生成 | `js/workspace/01-shared.js:172` `projectMemberSelectHtml()` |
| 样机释放 | `js/workspace/01-shared.js:199` `releaseTaskSamples()` |
| 样机新增校验 | `js/samples/01-pool.js:571` `addSample()` |
| 样机去重系统 | `js/samples/02-import-export.js` (6函数链) |
| 样机详情弹窗 | `js/samples/07-detail.js:9` `openSampleDetail()` |
| 样机照片上传(前端) | `js/samples/04-photos.js:165` / 后端 `server.py:1795` |
| 样机批量导入 | `js/samples/02-import-export.js:9` `importSampleBatch()` |
| 样机测试履历 | `js/samples/06-history.js:80` `sampleTestHistoryHtml()` |
| 阶段卡片渲染 | `js/workspace/02-home.js:52-99` |
| 项目人员CRUD | `js/workspace/02-home.js:265-318` |
| 项目位置CRUD | `js/workspace/02-home.js:195-237` |
| 阶段CRUD | `js/workspace/04-stage.js:145-274` |
| 阶段复制 | `js/workspace/04-stage.js:229` `copyStage()` |
| BOM上料清单 | `js/workspace/03-strategy.js:54-104` |
| 测试策略表 | `js/workspace/03-strategy.js:107-166` |
| 策略→进度同步 | `js/workspace/03-strategy.js:229` `autoSyncProgress()` |
| 用例下拉搜索 | `js/workspace/10-dropdown-issue.js:8-131` |
| 任务表格渲染 | `js/workspace/05-task-table.js:47` `workspaceTaskFlowHtml()` |
| 任务筛选器 | `js/app.filters.js:18-53` |
| 任务操作按钮 | `js/workspace/05-task-table.js:265` `taskFlowActionsHtml()` |
| 任务配置弹窗(新版) | `js/workspace/07-task-config.js:289-517` |
| 任务配置CSS | `css/33-task-config-modal.css` |
| 样机选择器UI | `js/workspace/06-sample-picker.js:108` `buildTaskSamplePickerHtml()` |
| 样机选择器CSS | `css/34-sample-picker.css` |
| 任务启动 | `js/workspace/08-task-actions.js:44` `startTask()` |
| 任务阻塞 | `js/workspace/08-task-actions.js:386` `blockTask()` |
| 任务临时变更 | `js/workspace/08-task-actions.js:245` `tempChangeTask()` |
| 任务删除 | `js/workspace/08-task-actions.js:8` `deleteTask()` |
| 测试结果列 | `js/workspace/08-task-actions.js:197` `taskIssueSummaryHtml()` |
| 结果录入弹窗 | `js/workspace/09-task-result.js:655` `uploadResult()` |
| 结果表单收集 | `js/workspace/09-task-result.js:313` `collectTaskResultForm()` |
| 结果应用 | `js/workspace/09-task-result.js:485` `applyTaskResult()` |
| 结果图片上传 | `js/workspace/09-task-result.js:252` |
| 问题单录入 | `js/workspace/10-dropdown-issue.js:168` |
| 任务日志展示 | `js/app.logs.js:172` `showTaskLogs()` |
| 导航栏渲染 | `js/app.render.js:70` `renderNav()` |
| 侧栏折叠 | `js/app.render.js:180` `toggleSidebar()` |
| 首页 | `js/app.render.js:25` `renderHome()` |
| 项目删除影响分析 | `js/projects.js:119` `collectProjectDeleteImpact()` |
| 一致性审计(浏览器) | `js/debug/auditConsistency.js:33` |
| 静态文件白名单 | `server.py:1570-1590` |
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
3. **全量 state 读写仍是性能瓶颈** — 前端 `GET/PUT /api/state` 仍传完整数据，`hasLocalUnsavedChanges()` 使用全量 `JSON.stringify` 比较；后端 `compose_state()` 每次从 SQLite 拼装完整 state。样机/照片/任务增长后会放大同步成本。
4. **大量 DOM 字符串拼接和内联事件** — 多数 UI 仍通过 `innerHTML` / `insertAdjacentHTML` 与 `onclick/onchange/oninput` 拼接；虽然大量用户输入走 `Utils.esc()`，但事件绑定、转义漏点和重构成本仍偏高。
