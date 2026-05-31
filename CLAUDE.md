# TestChamber V7 — 数字治理平台 (Digital Governance Platform)

内网协同版硬件测试样机全生命周期管理系统。单文件 Python 后端 + Vanilla JS SPA 前端，SQLite 持久化。

## 项目概览

| 维度 | 说明 |
|------|------|
| 应用名 | 数字治理平台 V7 内网协同版 |
| 目录版本 | V7 |
| 用途 | 终端硬件测试样机的全生命周期管理：项目→阶段→任务→样机分配→测试执行→结果录入→样机流转 |
| 部署 | 内网单机，Python stdlib HTTP Server，端口 9398 |
| 浏览器 | 现代 Chrome/Edge（需 DecompressionStream for XLSX） |

## 文件结构

```
TestChamberV7/
├── server.py              # 后端：HTTP API + SQLite (1703行)
├── index.html             # SPA 外壳 (89行)
├── css/
│   ├── style.css          # CSS 总入口，统一 @import 各模块文件
│   ├── 00-vars.css        # CSS 变量：颜色、字体、圆角、阴影
│   ├── 01-layout.css      # 全局布局：body/sidebar/topbar/content/bottom
│   ├── 02-components.css  # 基础组件：button/input/table/badge/card/modal/toast
│   ├── 20-samples.css     # 样机档案池
│   ├── 30-workspace-home.css  # 工作台主页、阶段卡片、人员/位置
│   ├── 31-stage-strategy.css  # 阶段配置、BOM、测试策略表
│   ├── 32-task-flow.css       # 任务管理工作台表格
│   ├── 33-task-config-modal.css # 任务配置弹窗
│   ├── 34-sample-picker.css   # 样机选择器
│   ├── 35-task-result.css     # 结果录入、样机去向、问题记录
│   ├── 36-task-log.css        # 任务日志
│   └── 90-responsive.css      # 响应式补丁
├── js/
│   ├── utils.js           # 纯工具函数：CSV/XLSX/日期/人员 (468行)
│   ├── app.core.js        # 核心入口：app 对象定义 + init() (106行)
│   ├── app.server.js      # 服务器通信：save/reload/conflict (121行)
│   ├── app.data.js        # 数据工具：normalize/查找/状态变更 (411行)
│   ├── app.render.js      # 渲染引擎：render/nav/breadcrumb/侧栏 (207行)
│   ├── app.filters.js     # 筛选器：进度/任务流 (55行)
│   ├── app.modal.js       # 弹窗系统：modal/confirm/校验 (203行)
│   ├── app.logs.js        # 日志系统：任务日志/样机引用 (181行)
│   ├── projects.js        # 项目管理 CRUD (220行)
│   ├── samples.js         # 样机档案池：CRUD/照片/问题表/导入导出 (1405行)
│   └── workspace/         # 项目工作台模块（10文件，3662行）
│       ├── 01-shared.js        # 共享工具：taskFlowStatus/releaseTaskSamples等 (155行)
│       ├── 02-home.js          # 工作台主页：阶段卡片/人员/位置/拖拽 (413行)
│       ├── 03-strategy.js      # 阶段策略：BOM/测试策略/用例导入 (307行)
│       ├── 04-stage.js         # 阶段CRUD：inline/modal SKU编辑器 (251行)
│       ├── 05-task-table.js    # 任务表格：行数据/操作列/查看样机 (435行)
│       ├── 06-sample-picker.js # 样机选择器：池筛选/数量限制 (208行)
│       ├── 07-task-config.js   # 任务配置弹窗：计划+样机双Tab (555行)
│       ├── 08-task-actions.js  # 任务操作：启动/阻塞/变更/删除 (412行)
│       ├── 09-task-result.js   # 结果录入：去向/问题/图片/完成 (733行)
│       └── 10-dropdown-issue.js # 用例下拉搜索+问题单弹窗 (193行)
├── data/
│   ├── testchamber.sqlite # 主数据库（自动创建）
│   └── samples/           # 样机照片文件存储
│       └── <sampleId>/photos/
├── backups/               # JSON 备份快照（自动管理，最多10个）
├── templates/             # 导入模板文件
│   ├── sample_import_template.xlsx
│   └── 用例集导入模板.xlsx
├── start_server.bat       # Windows 启动脚本（自动发现 Python）
└── start_server.ps1       # PowerShell 启动脚本
```

## 加载顺序与依赖

```
utils.js → app.core.js → app.server.js → app.data.js → app.render.js
→ app.filters.js → app.modal.js → app.logs.js
→ projects.js
→ workspace/01-shared.js → 02-home.js → 10-dropdown-issue.js
→ 03-strategy.js → 04-stage.js → 05-task-table.js
→ 06-sample-picker.js → 07-task-config.js → 08-task-actions.js
→ 09-task-result.js
→ samples.js → app.init()
```

所有模块通过 `Object.assign(app, {...})` 混入 `app` 全局对象。无模块系统，无打包工具。

`this.xxx()` 调用在运行时懒解析，因此跨文件引用无需关心物理加载顺序（只要在 `app.init()` 前完成加载）。

## 后端架构 (server.py)

### HTTP 层
- `http.server.ThreadingHTTPServer`，单进程多线程
- 监听 `0.0.0.0:9398`
- 纯 Python stdlib，零外部依赖
- 最大上传体积：80MB

### 数据库 (SQLite WAL, 10 张表)
- **app_state** — 顶层 JSON blob + revision 乐观锁
- **audit_log** — 审计日志（时间/用户/操作/revision/client_ip）
- **sample_categories** — 样机池（软删除）
- **sample_records** — 样机记录，含 SN/IMEI/状态/位置/挂账人（软删除）
- **sample_assets** — 照片文件索引，文件存 `data/samples/<id>/photos/`
- **sample_events** — 样机事件日志
- **project_records** — 项目（软删除）
- **project_stages** — 阶段（软删除）
- **project_tasks** — 任务，含 sample_ids_json（软删除）
- **task_logs** — 任务操作日志

### API 端点
| Method | Path | 用途 |
|--------|------|------|
| GET | `/` | index.html |
| GET | `/api/health` | 健康检查 |
| GET | `/api/state` | 全量状态 + revision |
| PUT | `/api/state` | 保存状态（revision + baseData 三向合并） |
| POST | `/api/samples/<id>/photos` | multipart 照片上传 |
| DELETE | `/api/samples/<id>/photos/<photoId>` | 软删除照片 |
| GET | `/api/samples/<id>/photos/<photoId>` | 照片文件服务 |
| GET | `/css/*`, `/js/*`, `/templates/*` | 静态文件 |

### 关键设计
1. **外置存储**：项目和样机已从 JSON blob 迁移到 SQLite 表（保留历史 V6 系列数据自动迁移能力）
2. **DB_LOCK (threading.Lock)**：所有写操作串行化
3. **乐观并发**：PUT 携带 revision + baseData，冲突时在服务端做三向合并
4. **Backup 节流**：普通保存 5min/50rev 才写 backup；照片上传/删除 1s 即可
5. **Backup 清理**：每小时保留 5 个，全局最多 10 个

### 三向合并 (merge_state)
- 项目层级：`projects[] → stages[] → tasks[] → logs[]`
- 样机层级：`categories[] → samples[] → photos[], logs[]`
- 用 `list_item_key(id优先, hash回退)` 做 identity tracking
- 规则：base vs new 不同 → 采用 new；current 独有且未在 new → 保留

## 前端架构

### 全局对象

**`Utils`** — 纯函数工具集
- `esc()` HTML 转义，`id()` 唯一 ID，`now()` / `today()` 时间
- `toast()` 轻提示，`normalizeDigits()` 全角→半角
- `personIdentityFromText()` / `personText()` / `parsePersonField()` — 人员 `姓名/工号` 格式
- `memberIdentityKey()` — 人员去重 key
- `parseCsvLine()` CSV 解析（含引号转义）
- `parseXlsxSheet()` / `unzipXlsxFiles()` — 纯 JS ZIP+XLSX 解析（无第三方库）
- `parseSampleImportCsv()` / `parseSampleImportXlsx()` — 样机批量导入
- `downloadCsv()` / `downloadText()` — 浏览器端文件下载

**`app`** — 核心框架
- `app.data` — 内存全量状态（与服务器同步）
- `app.view` — UI 状态（module, selectedProjectId, filters, collapsed, sidebarCollapsed 等）
- `app.constants` — 枚举（样机状态 5 种，任务状态 8 种）
- `app._baseData` — 上次保存时的数据快照（用于冲突合并）
- `app.serverRevision` — 乐观锁版本号
- `app._saveInFlight` / `app._saveQueued` — 保存队列化

### 核心数据流
1. `GET /api/state` → `app.data` + `app._baseData` + `app.serverRevision`
2. 用户操作直接修改 `app.data`
3. `app.scheduleSave()` 450ms debounce → `app.save()`
4. `PUT /api/state` 发送 `{revision, baseData, data}`
5. 409 → `reloadFromServer()` 静默刷新（silent mode）
6. 照片上传直接 POST multipart，绕过 revision

### 模块职责

**app.core.js** — 入口定义、初始化引导
- `app` 全局对象定义（version, data, view, constants, 内部状态）
- `init()` — 加载数据、规范化、渲染、绑定全局事件、侧栏状态恢复

**app.server.js** — 服务器通信
- `reloadFromServer()` — 从服务器拉取全量状态
- `save()` — 带乐观锁的持久化（409 冲突检测、保存队列化）
- `scheduleSave()` — 450ms debounce 保存
- `updateServerStatus()` — 顶部保存状态指示器

**app.data.js** — 数据工具
- `normalize()` — 修复旧格式数据（字符串成员→对象、状态映射、problemRecords 迁移）
- `currentProject()` / `currentStage()` / `allSamples()` / `findSample()` — 数据访问器
- `getProjectStageTask()` — 项目/阶段/任务三元组查找
- `changeSampleStatus()` — 样机状态变更统一入口（含日志）
- `sampleEffectiveStatus()` / `sampleHasProblem()` / `sampleProblemRecords()` — 样机状态判定
- `reconcileSampleTaskOccupancy()` — 样机任务占用一致性修复

**app.render.js** — 渲染引擎
- `render()` — 根据 `app.view.module` 分发渲染
- `renderHome()` / `renderDevices()` / `renderPreserveScroll()` / `renderEmpty()`
- `renderNav()` / `renderHeader()` / `breadcrumbHtml()`
- `go(module)` — 模块导航
- `toggleSidebar()` / `applySidebarState()` — 侧栏折叠
- `isCollapsed()` / `collapseButton()` / `sectionToggleTriangle()` / `toggleSection()` — 折叠面板
- `openSampleReadonly()` — 样机只读查看
- `closeTaskOpMenus()` / `handleTaskOpMenuClick()` — 任务操作菜单管理

**app.filters.js** — 筛选器
- `setProgressFilter()` / `clearProgressFilters()` — 进度筛选
- `setTaskFlowFilter()` / `setTaskFlowTextFilter()` / `clearTaskFlowFilters()` — 任务流筛选

**app.modal.js** — 弹窗系统
- `showModal()` / `closeModal()` — 标准弹窗（支持嵌套堆栈）
- `showConfirm()` / `closeConfirm()` / `showAlert()` — 确认框
- `showDangerConfirm()` — 危险操作确认
- `clearFieldValidationMarks()` / `markFieldInvalid()` — 表单校验标记

**app.logs.js** — 日志系统
- `addTaskLog()` / `ensureTaskLogs()` — 任务日志写入
- `showTaskLogs()` / `taskLogHtml()` / `taskLogContentHtml()` — 任务日志弹窗
- `toggleSampleHistoryItem()` / `logHtml()` — 样机日志折叠

**projects.js** — 项目 CRUD + 删除影响分析
- 项目名称唯一性校验（大小写不敏感）
- `collectProjectDeleteImpact()` — 分析删除对各状态样机/各状态任务的影响
- `deleteProject()` — 释放未完成任务样机，物理删除项目

**samples.js** — 样机全生命周期
- 样机池 CRUD + 统计卡片
- 样机 CRUD：SN/IMEI/主板SN 三重标识，同池唯一
- 样机详情：5 标签页（信息/测试履历/图片/CT/其他）
- 照片管理：上传（multipart API）、预览（滚轮缩放+拖动）、重命名、删除
- 问题表：多行编辑（描述/来源/关联任务）
- 批量导入：CSV/XLSX，列名别名自动匹配
- 档案销毁：单台/整池销毁，完整影响分析

**workspace/** (10 模块，3662 行) — 项目工作台完整生命周期

| 文件 | 职责 |
|------|------|
| `01-shared.js` | 跨模块共享工具：taskFlowStatus, projectMemberSelectHtml, releaseTaskSamples 等 14 函数 |
| `02-home.js` | 工作台主页渲染：阶段卡片/人员配置/位置配置/拖拽排序 20 函数 |
| `03-strategy.js` | 阶段策略页：BOM 上料清单/测试策略表/用例导入导出/autoSyncProgress 19 函数 |
| `04-stage.js` | 阶段 CRUD + SKU 编辑器：inline editor + modal editor 双系统 19 函数 |
| `05-task-table.js` | 任务管理工作台表格：多维度筛选/状态统计/操作列/查看样机 10 函数 |
| `06-sample-picker.js` | 样机选择器：池分组/关键词过滤/数量限制/勾选校验 10 函数 |
| `07-task-config.js` | 任务配置弹窗：计划+样机双 Tab/保存/未保存检测 17 函数 |
| `08-task-actions.js` | 任务生命周期操作：启动/阻塞/临时变更/删除/失效统计 8 函数 |
| `09-task-result.js` | 结果录入：样机去向/问题记录/图片上传/apply/save/完成任务 31 函数 |
| `10-dropdown-issue.js` | 用例搜索下拉框 + 问题单(DTS)录入弹窗 10 函数 |
- 样机池 CRUD + 统计卡片
- 样机 CRUD：SN/IMEI/主板SN 三重标识，同池唯一
- 样机详情：5 标签页（信息/测试履历/图片/CT/其他）
- 照片管理：上传（multipart API）、预览（滚轮缩放+拖动）、重命名、删除
- 问题表：多行编辑（描述/来源/关联任务）
- 批量导入：CSV/XLSX，列名别名自动匹配
- 档案销毁：单台/整池销毁，完整影响分析（进行中→异常终止，待下发→移除样机）
- 测试履历：按任务聚合，展示状态/故障/结果图片/日志
- 样机快照：已销毁样机的只读历史快照

## 关键数据模型

### 样机状态机
```
闲置 ←→ 在位等待 ←→ 测试中
  ↓         ↓          ↓
已退库   取走分析   故障(problemRecords判定)
```

### 任务状态机
```
待下发 → 进行中 ⇄ 阻塞中 → 正常完成 / 异常终止
```

### 人员格式
全项目统一 `姓名/工号`，如 `张三/00609513`。姓名字段仅汉字/字母，工号仅字母/数字。

## 编码规范

- 所有用户输入的 HTML 输出必须经 `Utils.esc()` 转义
- `Utils.id(prefix)` 生成唯一 ID（prefix + timestamp36 + random6）
- `app.save()` 自动持久化；输入实时保存用 `app.scheduleSave()`
- `app.findSample(id)` 返回 `{category, sample}` 或 null
- `app.getProjectStageTask(pid, sid, tid)` 返回 `{p, s, t}`
- `app.showModal(title, bodyHtml, onOk, okText, options)` — 标准弹窗
- `Utils.parsePositiveInt()` 解析正整数，失败返回 null
- `Utils.isNoSampleIssueText()` 判断是否"无问题"占位文本
- 样机状态不可直接赋值，应通过 `app.changeSampleStatus()` 统一处理

## 技术债务（已知问题）

1. ~~**workspace.js 过大** (3594行)~~ ✅ 已解决 — 拆分为 10 个模块 (3662行)，每个模块 <750 行
2. **全局变量污染** — 所有状态在 app.data/app.view 中，无模块隔离
3. **无前端测试** — 纯手动测试
4. **CSS 已模块化** — 4344行拆分为 13 个文件，但部分模块仍偏大（20-samples 919行、35-task-result 766行），且大量 `!important` patch 堆叠，建议后续引入 CSS 变量层级管理
5. **内存全量加载** — 样机数量大时可能影响性能
6. **照片无缩略图** — 原图直接展示在列表/网格中
7. **日志字段混杂** — sampleLibrary.logs 和 sample.logs 双写，字段命名不统一
8. **大量 DOM 字符串拼接** — 无 Virtual DOM 或模板引擎
9. **XLSX 解析依赖浏览器** — DecompressionStream 在新版 Chrome 才可用
10. **samples.js 中 `openSampleReadonly` 和 `sampleDisplayCode` 与 app.render.js / app.data.js 重复定义**
