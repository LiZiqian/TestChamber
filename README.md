# TestChamber V7

TestChamber V7 是一个面向测试团队的协同工具，用来管理样机从入库、项目分配、阶段任务、结果录入到履历追踪的完整生命周期。

它的设计取向很朴素：不依赖外部服务，部署简单，数据可追踪，适合在实验室或内网机器上直接运行。

## 当前状态

| 项目 | 说明 |
|------|------|
| 后端 | Python stdlib `ThreadingHTTPServer` + SQLite WAL |
| 前端 | Vanilla JS SPA，`Object.assign(app, {...})` 模块模式 |
| 默认端口 | `9398` |
| 数据库 | `data/testchamber.sqlite` |
| 样机照片 | `data/samples/<sampleId>/photos/` |
| 启动数据 | `GET /api/bootstrap` 只取项目/样机池摘要 |
| 大列表 | 任务表、样机池均走服务端分页，默认 100 条 |

## 功能概览

- 项目、阶段、SKU、BOM、测试策略管理
- 项目成员与测试地点配置
- 任务创建、下发、启动、阻塞、临时变更、完成和异常终止
- 样机档案池、样机分类、批量导入导出、三重标识去重
- 完整数据包导出/导入：支持空白平台整包导入、照片资产随包迁移、冲突预览与提交前一致性校验
- 样机状态流转：闲置、在位等待、测试中、已退库、取走分析
- 结果录入：逐台样机去向、故障描述、图片上传、草稿保存
- 样机照片缩略图链路：列表/履历优先显示缩略图，预览打开原图
- 样机事件日志：统一写入 `sampleLibrary.logs`，后端落 `sample_events`
- 服务端样机占用冲突检测，避免一台样机被多个未完成任务静默抢占
- 样机选择器只允许新增选择“闲置”样机；当前任务已拥有的样机仍可取消
- 结束任务有前后端防重复保护，避免重复点击产生多条“结束任务”日志
- 任务表和样机池分页有短期缓存、加载态和相邻页预取，降低翻页卡顿
- SQLite 持久化、自动备份、revision + 三向合并保存

## 快速开始

Windows 双击：

```text
start_server.bat
```

PowerShell：

```powershell
.\start_server.ps1
```

命令行：

```bash
python server.py --host 127.0.0.1 --port 9398
```

启动后访问：

```text
http://localhost:9398
```

首次运行会自动创建 `data/testchamber.sqlite` 和所需目录。

Codex/PowerShell 调试时优先使用直接命令：

```powershell
python .\server.py --host 127.0.0.1 --port 9398
```

隐藏窗口启动 `.bat` 在某些 PowerShell 环境里可能遇到 `Path/PATH` 环境变量冲突。

## 环境要求

- Python 3.9+
- 现代浏览器：Chrome / Edge / Firefox / Safari
- 无需 `pip install`
- 无需 npm 依赖

XLSX 解析在支持 `DecompressionStream("deflate-raw")` 的浏览器中会优先使用原生解压；旧浏览器会自动走内置 JS raw deflate 兜底。

## 项目结构

```text
TestChamberV7/
├── server.py
├── index.html
├── start_server.bat
├── start_server.ps1
├── README.md
├── css/
│   ├── style.css
│   ├── 00-vars.css
│   ├── 01-layout.css
│   ├── 02-components.css
│   ├── 20-samples.css
│   ├── 21-sample-photos.css
│   ├── 22-sample-archive.css
│   ├── 30-workspace-home.css
│   ├── 30-workspace-members.css
│   ├── 30-workspace-sections.css
│   ├── 31-stage-strategy.css
│   ├── 32-task-flow.css
│   ├── 32-task-flow-actions.css
│   ├── 32-task-issue-record.css
│   ├── 33-task-config-modal.css
│   ├── 34-sample-picker.css
│   ├── 35-task-result.css
│   ├── 35-task-result-modal.css
│   ├── 35-task-sample-list.css
│   ├── 36-task-log.css
│   └── 90-responsive.css
├── js/
│   ├── utils.js
│   ├── app.core.js
│   ├── app.server.js
│   ├── app.data.js
│   ├── app.render.js
│   ├── app.filters.js
│   ├── app.modal.js
│   ├── app.logs.js
│   ├── projects.js
│   ├── samples.js
│   ├── samples/
│   │   ├── 01-pool.js
│   │   ├── 02-import-export.js
│   │   ├── 03-detail-fields.js
│   │   ├── 04-photos.js
│   │   ├── 05-problems.js
│   │   ├── 06-history.js
│   │   └── 07-detail.js
│   ├── workspace/
│   │   ├── 01-shared.js
│   │   ├── 02-home.js
│   │   ├── 03-strategy.js
│   │   ├── 04-stage.js
│   │   ├── 05-task-table.js
│   │   ├── 06-sample-picker.js
│   │   ├── 07-task-config.js
│   │   ├── 08-task-actions.js
│   │   ├── 09-task-result.js
│   │   └── 10-dropdown-issue.js
│   └── debug/
│       └── auditConsistency.js
├── templates/
├── data/
└── backups/
```

## 前端加载顺序

`index.html` 按固定顺序加载脚本：

```text
utils.js
app.core.js
app.server.js
app.data.js
app.render.js
app.filters.js
app.modal.js
app.logs.js
projects.js
workspace/*
samples/*
debug/auditConsistency.js
app.init()
```

所有业务模块通过 `Object.assign(app, {...})` 混入全局 `app` 对象。

## 核心数据流

```text
GET /api/bootstrap
  -> 前端 normalize()
  -> 首页/导航只展示项目摘要和样机池摘要

GET /api/stages/<stageId>/tasks?page=...
GET /api/sample-categories/<catId>/samples?page=...
  -> 任务表/样机池只加载当前页
  -> 前端缓存当前会话内最近分页，并预取相邻页

PATCH /api/tasks/<taskId>/mutation
PATCH /api/projects/<projectId>/mutation
PATCH /api/stages/<stageId>/mutation
PATCH /api/samples/<sampleId>/mutation
PATCH /api/sample-categories/<categoryId>/mutation
  -> 只提交受影响记录、样机事件和任务日志
  -> SQLite WAL 持久化并更新 revision
```

`GET/PUT /api/state` 仍保留为导出、调试、异常兜底和兼容路径，不作为日常启动和大列表浏览的主路径。

完整数据包导入导出链路：

```text
GET /api/export-bundle
  -> 生成 manifest.json + state.json + checksums.json + assets/samples/*

POST /api/import-bundle/preview
  -> 安全解压 zip
  -> 校验照片资产
  -> 生成 autoApply / conflicts / blockers

POST /api/import-bundle/commit
  -> 校验 revision 未变化
  -> 应用冲突决策和新增数据
  -> 重写项目/阶段/任务/样机交叉引用
  -> 校验导入后阶段、任务、样机引用一致性
  -> 保存后前端 reloadFromServer()
```

照片上传/删除是直接变更接口：

```text
POST   /api/samples/<sampleId>/photos
DELETE /api/samples/<sampleId>/photos/<photoId>
GET    /api/samples/<sampleId>/photos/<photoId>
```

上传照片时前端会生成缩略图，服务端保存原图和缩略图资产。

## 状态入口约定

样机状态业务变更必须走：

```js
app.changeSampleStatus(sampleId, nextStatus, ctx)
```

样机数据修复仅使用：

```js
app.repairSampleStatus(sample, nextStatus)
app.clearSampleOccupancy(sample)
```

任务状态业务变更必须走：

```js
app.transitionTaskStatus(stage, task, nextStatus, ctx)
```

任务/progress 修复和默认初始化使用：

```js
app.repairTaskStatus(task, nextStatus)
app.setProgressStatus(progress, nextStatus)
app.createProgressRecord(values)
```

## 数据模型简图

```text
Project
└── Stage
    ├── skuNames
    ├── bom
    ├── strategy
    ├── progress
    └── tasks
        ├── sampleIds
        ├── removedSampleRecords
        ├── sampleFaultRecords
        ├── resultUploads
        ├── resultDraft
        └── logs

sampleLibrary
├── categories
│   └── samples
│       ├── photos
│       └── problemRecords
└── logs
```

## 状态机

样机：

```text
闲置 <-> 在位等待 <-> 测试中
  |          |            |
已退库    取走分析      故障(problemRecords 判定)
```

任务：

```text
待下发 -> 进行中 <-> 阻塞中 -> 正常完成 / 异常终止
```

## API 摘要

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/` | SPA 入口 |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/bootstrap` | 启动骨架：项目摘要、样机池摘要、revision |
| `GET` | `/api/projects/summary` | 项目摘要 |
| `GET` | `/api/projects/<id>` | 项目详情，`includeTasks=1` 时加载任务 |
| `GET` | `/api/stages/<stageId>/tasks` | 阶段任务分页 |
| `GET` | `/api/sample-categories` | 样机池摘要 |
| `GET` | `/api/sample-categories/<id>` | 样机池详情 |
| `GET` | `/api/sample-categories/<id>/samples` | 样机分页 |
| `GET` | `/api/export-bundle` | 导出完整数据包 zip |
| `POST` | `/api/import-bundle/preview` | 预览数据包导入、生成冲突决策项 |
| `POST` | `/api/import-bundle/commit` | 提交数据包导入、写入新增/合并数据 |
| `GET` | `/api/state` | 读取完整状态和 revision，低频兜底 |
| `PUT` | `/api/state` | 保存完整状态，服务端三向合并，低频兜底 |
| `PATCH` | `/api/tasks/<id>/mutation` | 任务增量写入，含结果/结束/阻塞/临时变更 |
| `PATCH` | `/api/stages/<id>/tasks/batch` | 批量任务增量写入 |
| `PATCH` | `/api/projects/<id>/mutation` | 项目增量写入 |
| `PATCH` | `/api/stages/<id>/mutation` | 阶段增量写入 |
| `PATCH` | `/api/samples/<id>/mutation` | 单台样机增量写入 |
| `PATCH` | `/api/sample-categories/<id>/mutation` | 样机池增量写入 |
| `POST` | `/api/samples/<id>/photos` | 上传样机照片和缩略图 |
| `DELETE` | `/api/samples/<id>/photos/<photoId>` | 删除样机照片 |
| `GET` | `/api/samples/<id>/photos` | 按需读取样机照片元数据 |
| `GET` | `/api/samples/<id>/events` | 按需读取样机事件 |
| `GET` | `/api/samples/<id>/photos/<photoId>` | 读取照片资产 |
| `GET` | `/css/*`, `/js/*`, `/templates/*` | 静态资源 |

## 已完成的主要技术债清理

- `workspace.js` 已拆分为 `js/workspace/` 下 10 个模块
- `samples.js` 已拆分为 `js/samples/` 下 7 个模块，根文件仅保留兼容占位
- CSS 已按样机、工作台、任务流、任务结果等区域拆分，`css/**` 中不再使用 `!important`
- 样机照片已有缩略图链路
- 样机日志不再双写 `sample.logs`，统一写 `sampleLibrary.logs`
- 样机状态、任务状态、progress 状态已有集中入口
- XLSX 解压支持旧浏览器 JS 兜底
- 启动改为 `/api/bootstrap`，任务和样机池大列表走服务端分页
- 任务、项目、阶段、样机、样机池主路径已切到 PATCH 增量写入
- 样机新增选择和批量任务写入已有“只有闲置可新增选择”的前后端校验
- 结束任务已有前端 in-flight 防重和后端 `TASK_ALREADY_FINISHED` 幂等兜底
- 样机池分页和任务表分页已有加载态、会话缓存和相邻页预取
- 完整数据包导入已修复空白平台整包导入重复阶段/任务问题，并增加提交前一致性校验

## 仍需关注

- 全局 `app` 混入模式仍未模块隔离
- 前端仍大量使用 DOM 字符串拼接和内联事件
- `GET/PUT /api/state` 仍保留为兼容/导出/调试兜底，后续应继续压缩到低频路径
- 数据包导入后的成功路径当前仍会 `reloadFromServer()`，正确性已覆盖，后续可继续减少全局刷新

## 开发提示

- 所有用户输入进入 HTML 前必须使用 `Utils.esc()`
- 弹窗校验失败返回 `true`，表示保持弹窗打开
- 样机状态不要直接赋值，业务逻辑使用 `changeSampleStatus()`
- 任务状态不要直接赋值，业务逻辑使用 `transitionTaskStatus()`
- 常规业务保存优先使用对应 `commit*Mutation()`；`app.scheduleSave()` / `app.save()` 仅保留旧兼容或低频兜底
- 结束任务只能走 `saveTaskResult(..., true)`，不要绕开按钮防重和后端幂等校验
- 调试一致性可在浏览器控制台运行 `app.auditConsistency()`
