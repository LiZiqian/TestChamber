# TestChamberV7 前端模块化重构 — 目标架构

> 状态：规划中 | 版本：1.0 | 日期：2026-05-31

---

## 1. 当前架构摘要

### 1.1 规模

| 文件 | 行数 | 职责 |
|------|------|------|
| server.py | 1,704 | Python HTTP API + SQLite（本轮不涉及） |
| index.html | 74 | SPA 外壳，`<script>` 顺序加载 5 个 JS，末尾 `app.init()` |
| css/style.css | 16 | CSS 总入口，@import 13 模块文件 |
| js/utils.js | 468 | 纯工具函数（CSV/XLSX/日期/人员格式/HTML转义） |
| js/app.core.js | 106 | 核心入口：app 对象定义 + init() |
| js/app.server.js | 178 | 服务器通信：save/reload + syncAfterDirectMutation |
| js/app.data.js | 413 | 数据工具：normalize/查找/状态变更 + eachSample |
| js/app.render.js | 197 | 渲染引擎：render/nav/breadcrumb/侧栏 |
| js/app.filters.js | 55 | 筛选器：进度/任务流 |
| js/app.modal.js | 203 | 弹窗系统：modal/confirm/校验 |
| js/app.logs.js | 181 | 日志系统：任务日志/样机引用 |
| js/projects.js | 220 | 项目管理 CRUD + 删除影响分析 |
| js/workspace/01-shared.js ~ 10-dropdown-issue.js | 3,722 | 项目工作台 10 模块（阶段/策略/任务/样机选择/结果/日志） |
| js/samples.js | 1,405 | 样机档案池：CRUD/照片/问题表/导入导出/销毁 |
| js/debug/auditConsistency.js | 191 | 只读一致性审计脚本 |
| **总计** | **~13,776** | |

### 1.2 当前架构问题

1. **单文件过大** — workspace.js (3,594行) 和 style.css (4,344行) 难以维护
2. **无模块边界** — 所有函数通过 `Object.assign(app, {...})` 混入，无私有/公开区分
3. **CSS 无分层** — 全局样式、组件样式、页面样式、patch 修复混在一起
4. **查找困难** — 修改一个功能需要在大文件中定位

---

## 2. 保留的技术路线

| 项目 | 决定 |
|------|------|
| 框架 | **保留 Vanilla JS**，不引入任何框架 |
| 全局对象 | **保留 `app` 全局对象**，所有核心状态和数据在 `app` 上 |
| 模块混入 | **保留 `Object.assign(app, {...})` 扩展模式** |
| 打包工具 | 不引入 React / Vue / Vite / Webpack / Babel |
| 类型系统 | 不引入 TypeScript |
| 后端 | **不改变 server.py**，API 不变 |
| 数据库 | **不改变 SQLite 结构** |
| 业务逻辑 | **不改变任何业务逻辑** |
| 函数名 | **不改变现有函数名、DOM id、className**（除非单独批准） |
| 页面行为 | **不改变任何可见的页面行为** |
| 加载顺序 | `app.init()` 必须始终最后执行 |
| ESM | 不使用 ES modules（import/export），保持 `<script>` 标签加载 |

---

## 3. 目标目录结构

```
TestChamberV7/
├── index.html                   # 更新 <script> 加载顺序 + CSS @import
├── server.py                    # 不修改
│
├── css/
│   ├── style.css                # 总入口，仅 @import 语句
│   ├── 00-vars.css              # CSS 变量、基础颜色、字体
│   ├── 01-layout.css            # body / sidebar / main / header / content
│   ├── 02-components.css        # button / input / select / table / badge / card / modal / toast
│   ├── 10-projects.css          # 项目管理页
│   ├── 20-samples.css           # 样机档案池全部样式
│   ├── 30-workspace-home.css    # 项目工作台主页、阶段卡片、人员/位置
│   ├── 31-stage-strategy.css    # 阶段配置、BOM 上料清单、测试策略表格
│   ├── 32-task-flow.css         # 任务管理工作台表格
│   ├── 33-task-config-modal.css # 任务配置弹窗（计划+样机面板）
│   ├── 34-sample-picker.css     # 样机选择器 / dispatch-sample-*
│   ├── 35-task-result.css       # 结果录入、样机去向、问题记录
│   ├── 36-task-log.css          # 任务日志、日志序列号
│   └── 90-responsive.css        # 响应式媒体查询
│
├── js/
│   ├── utils.js                 # 不拆分（468行，纯函数，职责清晰）
│   ├── app.core.js              # app 对象声明、init、emptyData、cloneData
│   ├── app.data.js              # normalize、样机状态、任务状态、查找函数
│   ├── app.render.js            # render / renderNav / renderHeader / breadcrumb / sidebar
│   ├── app.modal.js             # showModal / showConfirm / showDangerConfirm / closeModal / 校验标记
│   ├── app.logs.js              # 任务日志渲染（taskLogHtml / logHtml / 样机引用链接）
│   ├── projects.js              # 不拆分（220行，职责清晰）
│   │
│   ├── workspace/
│   │   ├── workspace.home.js        # renderProjectWorkspace / 阶段卡片 / 人员/位置配置
│   │   ├── workspace.stage.js       # 阶段 CRUD / SKU 编辑器 / 拖拽排序 / 复制阶段
│   │   ├── workspace.strategy.js    # BOM / 测试策略配置 / 用例导入 / autoSyncProgress
│   │   ├── workspace.task-table.js  # 任务表格渲染 / 筛选栏 / 状态统计 / 操作列 / 查看样机
│   │   ├── workspace.task-config.js # 任务配置弹窗 / 计划配置 / 样机配置 / 两面板保存
│   │   ├── workspace.sample-picker.js # buildTaskSamplePickerHtml / 样机搜索 / 折叠/计数
│   │   ├── workspace.task-actions.js  # 启动 / 删除 / 释放 / 阻塞 / 重启 / 临时变更
│   │   ├── workspace.task-result.js   # 结果录入弹窗 / 结束任务 / 样机去向 / 故障记录 / 图片上传
│   │   ├── workspace.case-dropdown.js # 用例搜索下拉框
│   │   └── workspace.issue-record.js  # 问题单 / DTS 录入
│   │
│   └── samples/
│       ├── samples.list.js          # 样机池列表 / 筛选 / 卡片 / 统计
│       ├── samples.crud.js          # 样机 CRUD / 编辑 / 档案销毁
│       ├── samples.import-export.js # 批量导入（CSV/XLSX）/ 模板下载 / 导出 CSV
│       ├── samples.detail.js        # 样机详情弹窗（多标签页壳）
│       ├── samples.photos.js        # 照片上传 / 预览（缩放+拖拽）/ 重命名 / 删除
│       ├── samples.problems.js      # 问题表 / 初检问题 / 问题行 CRUD
│       └── samples.history.js       # 测试履历 / 结果图片 / 样机快照
│
├── data/                         # 不修改
├── backups/                      # 不修改
├── templates/                    # 不修改
└── docs/                         # 本文档目录
```

---

## 4. JS 加载顺序原则

```
utils.js
  → app.core.js
  → app.data.js
  → app.render.js
  → app.modal.js
  → app.logs.js
  → projects.js
  → workspace.home.js
  → workspace.stage.js
  → workspace.strategy.js
  → workspace.task-table.js
  → workspace.task-config.js
  → workspace.sample-picker.js
  → workspace.task-actions.js
  → workspace.task-result.js
  → workspace.case-dropdown.js
  → workspace.issue-record.js
  → samples.list.js
  → samples.crud.js
  → samples.import-export.js
  → samples.detail.js
  → samples.photos.js
  → samples.problems.js
  → samples.history.js
  → app.init()
```

核心原则：
- 被依赖的模块必须在前
- `app.core.js`（对象壳 + init）必须最先加载
- `app.init()` 始终是最后一行 `<script>`
- workspace 模块内部：home → stage → strategy → task-table → task-config → sample-picker → task-actions → task-result → case-dropdown → issue-record
- samples 模块内部：list → crud → import-export → detail → photos → problems → history

---

## 5. CSS @import 顺序原则

```css
/* style.css — 总入口，只有 @import */
@import '00-vars.css';
@import '01-layout.css';
@import '02-components.css';
@import '10-projects.css';
@import '20-samples.css';
@import '30-workspace-home.css';
@import '31-stage-strategy.css';
@import '32-task-flow.css';
@import '33-task-config-modal.css';
@import '34-sample-picker.css';
@import '35-task-result.css';
@import '36-task-log.css';
@import '90-responsive.css';
```

核心原则：
- 变量和基础必须在最前面
- 组件级样式在页面级样式之前
- 响应式补丁在最后
- 保持与原始 style.css 相同的规则声明顺序（即原文件中规则出现的先后）
- 原文件中被后续 `!important` patch 覆盖的规则，在拆分时不改变优先级关系

---

## 6. 禁止事项

- 禁止删除任何 CSS 规则（只移动，不删除，不改值）
- 禁止删除任何 JS 函数（只移动，不删除，不改签名）
- 禁止修改函数名、参数名、参数顺序
- 禁止修改 DOM id、className、data-* 属性名
- 禁止修改 API 调用路径或参数
- 禁止修改 `app.data` / `app.view` 的结构
- 禁止改变 `Object.assign(app, {...})` 的混入模式
- 禁止引入任何 npm 依赖
- 禁止修改 server.py
- 禁止修改 .claude/memory
- 第一轮禁止改写业务逻辑（只移动代码位置）

---

## 7. 不拆分的模块及理由

| 模块 | 理由 |
|------|------|
| utils.js (468行) | 纯函数集合，职责单一，调用关系清晰 |
| projects.js (220行) | 代码量小，功能内聚 |
| app.core.js + app.data.js | 从 app.js 拆出，作为核心壳层 |
| server.py | 本轮不涉及前端重构范围外的文件 |

---

## 8. app.js 拆分边界（仅供参考，不作为第一轮目标）

| 子模块 | 从 app.js 移入的函数 |
|--------|---------------------|
| app.core.js | `app` 对象声明、`version`、`data`/`view`/`constants`、`init()`、`emptyData()`、`cloneData()`、`serverOnline`、`_saveInFlight`/`_saveQueued` |
| app.data.js | `normalize()`、`normalizePersonText()`、`projectActiveMembers()`、`currentProject()`、`currentStage()`、`allSamples()`、`findSample()`、`projectName()`、`stageName()`、`sampleProblemRecords()`、`sampleHasProblem()`、`sampleEffectiveStatus()`、`addSampleProblem()`、`changeSampleStatus()`、`activeTaskUsagesForSample()`、`reconcileSampleTaskOccupancy()`、`isTaskCompleted()`、`isTaskExecuted()`、`isSampleUsedByAnotherOpenTask()`、`sampleDisplayCode()`、`getProjectStageTask()` 等数据访问函数 |
| app.render.js | `render()`、`renderHome()`、`renderDevices()`、`renderPreserveScroll()`、`renderNav()`、`renderHeader()`、`breadcrumbHtml()`、`go()`、`renderEmpty()` |
| app.modal.js | `showModal()`、`_syncModalInputsToAttributes()`、`showConfirm()`、`showAlert()`、`closeConfirm()`、`closeModal()`、`clearFieldValidationMarks()`、`markFieldInvalid()`、`showDangerConfirm()`、`updateSelectPlaceholderState()` |
| app.logs.js | `logHtml()`、`ensureTaskLogs()`、`addTaskLog()`、`logSampleRefToken()`、`compactTaskLogText()`、`taskLogContentText()`、`taskLogDetailLines()`、`taskLogContentHtml()`、`findLogSampleRefId()`、`linkSampleRefsInLogText()`、`highlightTestResult()`、`taskLogHtml()`、`showTaskLogs()` |
