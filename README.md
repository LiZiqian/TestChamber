# TestChamber V7

数字治理平台 V7 是一个面向终端硬件测试团队的内网协同工具，用来管理样机从入库、项目分配、阶段任务、结果录入到履历追踪的完整生命周期。

它的设计取向很朴素：不依赖外部服务，部署简单，数据可追踪，适合在实验室或内网机器上直接运行。

## 当前状态

| 项目 | 说明 |
|------|------|
| 后端 | Python stdlib `ThreadingHTTPServer` + SQLite WAL |
| 前端 | Vanilla JS SPA，`Object.assign(app, {...})` 模块模式 |
| 默认端口 | `9398` |
| 数据库 | `data/testchamber.sqlite` |
| 样机照片 | `data/samples/<sampleId>/photos/` |

## 功能概览

- 项目、阶段、SKU、BOM、测试策略管理
- 项目成员与测试地点配置
- 任务创建、下发、启动、阻塞、临时变更、完成和异常终止
- 样机档案池、样机分类、批量导入导出、三重标识去重
- 样机状态流转：闲置、在位等待、测试中、已退库、取走分析
- 结果录入：逐台样机去向、故障描述、图片上传、草稿保存
- 样机照片缩略图链路：列表/履历优先显示缩略图，预览打开原图
- 样机事件日志：统一写入 `sampleLibrary.logs`，后端落 `sample_events`
- 服务端样机占用冲突检测，避免一台样机被多个未完成任务静默抢占
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
python server.py --host 0.0.0.0 --port 9398
```

启动后访问：

```text
http://localhost:9398
```

首次运行会自动创建 `data/testchamber.sqlite` 和所需目录。

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
GET /api/state
  -> 前端 normalize()
  -> 用户编辑 app.data
  -> app.scheduleSave()
  -> PUT /api/state { revision, baseData, data }
  -> 服务端三向合并
  -> SQLite WAL 持久化
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
| `GET` | `/api/state` | 读取完整状态和 revision |
| `PUT` | `/api/state` | 保存状态，服务端三向合并 |
| `POST` | `/api/samples/<id>/photos` | 上传样机照片和缩略图 |
| `DELETE` | `/api/samples/<id>/photos/<photoId>` | 删除样机照片 |
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

## 仍需关注

- 全局 `app` 混入模式仍未模块隔离
- 前端仍大量使用 DOM 字符串拼接和内联事件
- `GET/PUT /api/state` 仍是全量 state 读写，数据量增长后可能成为性能瓶颈

## 开发提示

- 所有用户输入进入 HTML 前必须使用 `Utils.esc()`
- 弹窗校验失败返回 `true`，表示保持弹窗打开
- 样机状态不要直接赋值，业务逻辑使用 `changeSampleStatus()`
- 任务状态不要直接赋值，业务逻辑使用 `transitionTaskStatus()`
- 保存用 `app.scheduleSave()` 或 `app.save()`
- 调试一致性可在浏览器控制台运行 `app.auditConsistency()`
