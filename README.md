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

## 平台模块使用方法

### 1. 首页与左侧导航

启动后进入首页，首页提供三个主入口：

- **项目管理**：进入项目、阶段、策略和任务管理链路。
- **样机档案池**：进入样机分类、样机档案、照片、问题和履历管理链路。
- **测试设备仓库**：预留模块，当前为占位入口。

左侧导航会常驻显示项目列表和样机池列表。点击项目名会直接进入该项目工作台；点击样机池名会直接进入对应样机池。左下角提供完整数据包的导出和导入入口，底部状态用于观察当前同步/保存状态。

### 2. 项目管理

项目管理用于维护测试项目的基础档案。

常用操作：

- 点击 **新建项目** 创建项目，填写项目名称、编号和负责人。
- 点击项目卡片上的编辑按钮修改项目基础信息。
- 点击 **进入项目** 进入该项目的配置工作台。
- 删除项目会先展示影响分析，并释放该项目未完成任务占用的样机。

建议先完成项目基础信息，再进入项目工作台配置阶段、人员、地点和任务。

### 3. 项目配置工作台

进入项目后，默认展示项目配置工作台。这个页面用于把项目拆成可执行的阶段，并维护项目执行所需的基础配置。

主要区域：

- **项目阶段与方案配置**：新增、编辑、复制、删除阶段；拖拽阶段卡片可调整阶段顺序。
- **SKU / 方案**：在阶段中维护测试方案名称，用于后续策略和任务表展示。
- **测试项概览**：展示阶段内计划执行、已执行、完成率等摘要。
- **项目人员**：维护执行人名单。任务配置里的执行人下拉框来自这里。
- **测试位置**：维护实验室、工位、地点等信息，供任务和样机流转记录使用。

使用顺序建议：

1. 创建阶段。
2. 配置阶段 SKU。
3. 添加项目人员和测试位置。
4. 点击 **配置测试用例集** 进入阶段策略配置。
5. 回到任务管理中创建和下发任务。

### 4. 阶段策略配置

阶段策略配置用于定义当前阶段要执行哪些测试项，以及每个测试项需要多少样机。

常用操作：

- 配置阶段名称、SKU 名称、BOM 信息。
- 新增或编辑测试策略项，填写类别、测试用例、样机数量和备注。
- 导入测试用例 XLSX，批量生成测试池。
- 使用用例搜索下拉快速复用已有用例。
- 保存后，任务管理工作台会按这些策略生成可下发任务。

注意事项：

- 样机数量会影响任务配置中的必选样机数量。
- 修改策略不会自动覆盖已经执行过的任务；已生成的任务会保留自身快照，避免历史任务丢失上下文。

### 5. 任务管理工作台

任务管理工作台用于把阶段策略转成真实任务，并跟踪任务从待下发到完成的全过程。

主要能力：

- **新增任务**：从当前阶段测试池选择测试项，可一次生成一个或多个待下发任务。
- **筛选/分页**：按状态、SKU、执行人、类别、用例、DTS、结果等条件筛选任务；大列表走服务端分页。
- **配置**：打开任务配置弹窗，设置执行人、计划时间和任务样机。
- **启动**：把已配置好的待下发任务切换为进行中，并把样机状态更新为测试中。
- **阻塞**：记录任务阻塞原因，任务进入阻塞中。
- **临时变更**：对进行中任务调整样机、执行人或计划信息，并记录变更日志。
- **结果**：进入结果录入页面，填写每台样机的测试结论、问题、去向和附件。
- **更多操作**：查看日志、删除未执行任务、归档或处理异常任务。

任务状态：

```text
待下发 -> 进行中 <-> 阻塞中 -> 正常完成 / 异常终止
```

### 6. 任务配置弹窗

点击任务行的 **配置** 按钮会打开任务配置弹窗。弹窗分为两个页签：

- **计划配置**：选择执行人、计划开始时间和计划终止时间。
- **样机配置**：按样机池选择任务所需样机。

样机配置规则：

- 顶部 `任务样机数` 显示当前已选数量和策略要求数量。
- 展开样机池后可按包含/排除关键词搜索样机。
- 只有 **闲置** 样机可以新增勾选。
- 当前任务已经拥有的样机可以取消勾选。
- 样机卡片显示 IMEI/SN、阶段/方案、已测项目、OK/故障标记和当前状态。
- 选中样机会出现蓝色边框，保存后样机进入任务占用链路。

保存时平台会同时校验计划信息和样机数量；校验失败会留在弹窗中并显示错误提示。

### 7. 结果录入

点击任务行的 **结果** 进入结果录入。这个模块用于结束任务前逐台记录样机测试结果。

常用操作：

- 为每台样机填写测试结论、是否有问题、DTS 或问题描述。
- 上传结果照片或问题附件。
- 设置样机去向：继续测试、退库、取走分析、闲置等。
- 暂存草稿，避免未完成录入时丢失内容。
- 点击结束任务后，任务进入正常完成或异常终止。

结束任务有防重复保护：前端会禁用重复点击，后端也会识别已经完成的任务，避免重复写入日志和样机事件。

### 8. 样机档案池

样机档案池用于按型号、项目或业务分类维护样机基础档案。

常用操作：

- 新建样机池，例如 SEMPORNA、Sagittarius、Lamborghini。
- 编辑样机池名称和备注。
- 在样机池中新增单台样机。
- 批量导入样机 CSV/XLSX。
- 使用分页、状态筛选、关键词搜索快速定位样机。
- 查看样机状态统计，包括闲置、在位等待、测试中、已退库、取走分析和故障。
- 销毁样机池前会展示影响，并同步释放或清理相关占用。

样机三重标识建议至少维护一个：

- IMEI
- SN
- 主板 SN

导入时平台会用这些标识辅助去重，降低重复建档风险。

### 9. 样机详情

点击样机卡片或任务配置中的样机标识，可打开样机详情。

详情页包含：

- **基础信息**：IMEI、SN、主板 SN、机型、保管人、借用人、位置等。
- **状态变更**：将样机改为闲置、已退库、取走分析等状态，并写入事件。
- **照片**：上传、预览、重命名、删除样机照片；列表优先显示缩略图。
- **问题记录**：维护样机故障、问题描述和处理状态。
- **测试履历**：查看样机参与过的项目、阶段、任务和结果。
- **事件日志**：查看样机入库、借出、任务占用、状态变更等记录。

业务状态变更会记录日志；数据修复类操作只做字段修正，不应代替正常业务流转。

### 10. 数据包导入与导出

左侧导航底部提供完整数据包操作。

导出完整数据包：

- 点击 **导出完整数据包**。
- 平台生成 zip，包含状态数据、manifest、checksum 和样机照片资产。
- 适合迁移到另一台空白平台、备份当前环境或交付测试数据。

导入数据包：

- 点击 **导入数据包** 并选择 zip。
- 平台先进入 preview，检查数据结构、照片资产和冲突。
- 空白平台导入时应自动作为新增数据提交。
- 有冲突时按预览结果选择保留、覆盖或合并。
- 提交后平台刷新数据，项目、阶段、任务、样机和照片引用会重新映射。

导入前建议确认当前平台没有未保存操作。大数据包导入后如发现数据不一致，应先停止继续操作并检查导入预览和服务端日志。

### 11. 系统同步与保存

平台日常操作优先走增量保存，状态会在左侧底部显示。

常见状态：

- **同步正常 / 已加载**：当前数据已从服务器加载。
- **保存中**：正在写入服务器。
- **保存失败**：网络、冲突或后端校验失败，需要根据提示处理。

任务、项目、阶段、样机和样机池的主要操作都会走对应 PATCH 接口，只提交受影响记录。完整 `/api/state` 仍保留为导出、调试和异常兜底路径。

### 12. 推荐业务流程

从零开始使用平台时，推荐顺序如下：

1. 在 **样机档案池** 中创建样机池并导入样机。
2. 在 **项目管理** 中创建项目。
3. 进入项目，创建阶段、SKU、项目人员和测试位置。
4. 在阶段中点击 **配置测试用例集**，维护测试策略。
5. 到 **任务管理工作台** 中从策略池新增任务。
6. 打开任务 **配置**，设置执行人、计划时间和样机。
7. 启动任务，执行测试。
8. 在 **结果** 页面录入测试结论、问题和照片。
9. 结束任务，样机按结果去向回到闲置、退库或取走分析等状态。
10. 需要迁移或备份时，使用 **导出完整数据包**。

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
