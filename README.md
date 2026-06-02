# 数字治理平台 V7 · TestChamber

> 测试活动管理系统

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Vanilla JS](https://img.shields.io/badge/JavaScript-ES2020+-F7DF1E?logo=javascript&logoColor=000)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![SQLite](https://img.shields.io/badge/SQLite-3.x-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)

TestChamber 是一套面向硬件测试实验室的单机 Web 应用，用于管理终端设备（手机、平板、IoT 终端等）在测试生命周期中的全流程：从样机入库、分配到项目→阶段→任务的层级化测试计划，再到测试执行、结果录入与样机流转归档。

**设计目标：零依赖、单文件部署、内网即开即用。**

---

## 目录

- [设计原则](#设计原则)
- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [操作指南](#操作指南)
  - [启动服务器](#启动服务器)
  - [创建项目](#创建项目)
  - [配置项目工作台](#配置项目工作台)
  - [管理样机档案](#管理样机档案)
  - [执行测试任务](#执行测试任务)
  - [录入测试结果](#录入测试结果)
- [项目架构](#项目架构)
- [目录结构](#目录结构)
- [数据模型](#数据模型)
- [API 参考](#api-参考)
- [浏览器兼容性](#浏览器兼容性)
- [技术债务](#技术债务)

---

## 设计原则

### 1. 零外部依赖

**后端**仅使用 Python 3 标准库（`http.server` + `sqlite3`），无需 `pip install`。**前端**不依赖任何 npm 包、CDN 或第三方框架 — 纯 Vanilla JS + CSS，连 XLSX 解析都由手写的 `unzipXlsxFiles()` + `parseXlsxSheet()` 完成。

> 这意味着你可以把整个目录拷贝到一台刚装完操作系统、仅安装了 Python 3 的内网机器上，双击 `start_server.bat` 即可运行。

### 2. 数据即文档

所有数据存储在单个 SQLite 文件中（`data/testchamber.sqlite`）。备份、迁移、审计只需复制这一个目录。没有 Redis、没有消息队列、没有微服务。

### 3. 乐观并发与离线容忍

多用户同时编辑同一项目时，采用 **revision + 三向合并（3-way merge）** 策略而非锁定。样机占用冲突（同一台样机被两个任务同时分配）在服务端检测并返回 409，前端弹窗展示冲突详情，拒绝静默覆盖。

### 4. 渐进式复杂度

- **主页**只有两个入口卡片，新手 3 秒理解
- **项目管理**是简单的 CRUD 列表
- **工作台**逐层展开：阶段 → 任务 → 样机分配 → 结果录入
- 高级功能（BOM 上料清单、测试策略表、用例集导入/导出）按需深入

### 5. 不可变审计

所有关键操作（样机状态变更、任务创建/完成、人员调整）自动写入 `audit_log` 表和业务日志。已销毁的样机保留只读快照，历史永远可追溯。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **项目管理** | 创建/编辑/删除项目，配置项目人员（姓名/工号）和测试地点 |
| **阶段管理** | 每个项目包含多个阶段，支持拖拽排序、复制、SKU 方案编辑 |
| **任务管理** | 三级结构（项目→阶段→任务），多维度筛选，启动/阻塞/变更/删除 |
| **样机分配** | 从样机档案池按池分组选择，数量校验、占用冲突检测、智能搜索过滤 |
| **结果录入** | 每台样机独立去向（完成/退库/取走分析）、问题记录、图片附件 |
| **样机档案池** | SN/IMEI/主板SN 三重标识，5 种状态流转，照片管理，CSV/XLSX 批量导入导出 |
| **BOM 与测试策略** | 上料清单管理，测试策略表配置，用例集导入/导出（XLSX） |
| **审计日志** | 全量操作日志，样机事件时间线，任务操作历史 |

---

## 快速开始

### 环境要求

- **Python 3.9+**（推荐 Miniforge / Conda）
- **现代浏览器**：Chrome 80+ / Edge 80+（需 `DecompressionStream` 支持）
- **操作系统**：Windows / macOS / Linux
- **磁盘空间**：源码 ~600KB，数据库和样机照片按需增长

### 启动

**Windows（双击）：**
```
双击 start_server.bat
```

**PowerShell：**
```powershell
.\start_server.ps1
```

**命令行：**
```bash
python server.py --host 0.0.0.0 --port 9398
```

浏览器访问 `http://localhost:9398`。

### 启动脚本做了什么

`start_server.bat` 自动按优先级发现 Python：
1. `PYTHON_EXE` 环境变量
2. Conda/MiniForge 环境中的 Python
3. Windows Python Launcher (`py -3`)
4. PATH 中的 `python`

无需手动配置环境变量。

---

## 操作指南

### 启动服务器

```
双击 start_server.bat → 浏览器访问 http://localhost:9398
```

首次运行会自动创建 `data/testchamber.sqlite` 数据库文件。

### 创建项目

1. 进入 **项目管理**（左侧导航）
2. 点击 **＋ 新建项目**
3. 填写项目名称（全系统唯一，大小写不敏感）
4. 可选填写项目描述
5. 保存后，项目出现在列表中

### 配置项目工作台

点击项目卡片进入 **项目工作台**：

1. **在项目主页添加人员和测试地点**
   - 展开"项目人员"区域，点击 ＋ 添加成员（`姓名/工号` 格式）
   - 展开"项目地点"区域，添加测试地点

2. **创建阶段**
   - 点击 ＋ 新建阶段
   - 填写阶段名称（如"功能测试"、"可靠性测试"）
   - 可选添加 SKU 方案（不同硬件配置的测试组合）

3. **进入阶段策略页（可选）**
   - 点击阶段卡片的 ⚙ 进入策略配置
   - 配置测试策略表（测试项 × 要求 × 方法）
   - 配置 BOM 上料清单
   - 导入用例集（XLSX）

4. **创建任务**
   - 在任务管理工作台中点击 **＋ 新建任务**
   - 填写执行人、计划时间、选择样机
   - 任务支持"从样机池批量创建"（一键为每台样机生成独立任务）

### 管理样机档案

1. 进入 **样机档案池**（左侧导航）
2. 先创建样机分类（如"手机"、"平板"、"路由器"）
3. 点击分类中的 **＋ 新建样机**
4. 填写：
   - **SN**（序列号，分类内唯一）
   - **IMEI**（可选，分类内唯一）
   - **主板SN**（可选）
   - **初始状态**（默认"闲置"）
   - **位置**（如"A-3-12"）
   - **来源阶段/方案**（标注样机来源）

5. 批量导入：点击 **导入**，支持 CSV 和 XLSX 格式（模板在 `templates/` 目录）

### 执行测试任务

1. 在工作台任务列表中，找到"待下发"的任务
2. 点击 **▶ 启动**，任务状态变为"进行中"
3. 过程中可点击 **⏸ 阻塞** 暂停（需填写原因），之后可 **▶ 继续**
4. 如需更换样机，点击 **⇄ 临时变更**（保留原任务上下文）

### 录入测试结果

1. 任务启动后，点击 **📋 录入结果**
2. 对每台分配的样机，选择：
   - **去向**：正常完成 / 退库 / 取走分析
   - **问题描述**：多行录入，关联来源任务
   - **故障图片**：拍照或上传
3. 点击 **应用**（可多次保存草稿）→ **完成任务**
4. 任务标记为"正常完成"或"异常终止"

---

## 项目架构

```
浏览器 (Chrome/Edge)
    │
    ├─ GET  /api/state      → 全量 JSON + revision
    ├─ PUT  /api/state      → 增量保存（三向合并）
    ├─ POST /api/samples/.../photos  → 照片上传
    ├─ GET  /api/samples/.../photos  → 照片服务
    └─ GET  /css/*, /js/*, /templates/* → 静态文件
    │
    ▼
Python ThreadingHTTPServer (:9398)
    │
    ├─ HTTP 路由 + 静态文件
    ├─ SQLite WAL 模式（读写并发）
    ├─ 三向合并引擎 (merge_state)
    ├─ 乐观并发控制 (revision + baseData)
    ├─ 样机占用冲突检测 (C1)
    └─ 自动备份（最多 10 个 JSON 快照）
```

### 前端模块依赖

```
utils.js → app.core.js → app.server.js → app.data.js → app.render.js
→ app.filters.js → app.modal.js → app.logs.js
→ projects.js
→ workspace/01-shared.js → 02-home.js → 10-dropdown-issue.js
→ 03-strategy.js → 04-stage.js → 05-task-table.js
→ 06-sample-picker.js → 07-task-config.js → 08-task-actions.js
→ 09-task-result.js
→ samples.js → debug/auditConsistency.js → app.init()
```

所有模块通过 `Object.assign(app, {...})` 混入全局 `app` 对象。

---

## 目录结构

```
TestChamberV7/
├── server.py              # 后端：HTTP API + SQLite (1763行)
├── index.html             # SPA 外壳 (90行)
├── start_server.bat       # Windows 启动脚本
├── start_server.ps1       # PowerShell 启动脚本
├── css/                   # 样式表 13 文件
│   ├── style.css          # CSS 总入口 @import
│   ├── 00-vars.css        # CSS 变量
│   ├── 01-layout.css      # 全局布局
│   ├── 02-components.css  # 基础组件
│   ├── 20-samples.css     # 样机档案池
│   ├── 30-workspace-home.css   # 工作台主页
│   ├── 31-stage-strategy.css   # 阶段策略
│   ├── 32-task-flow.css        # 任务管理
│   ├── 33-task-config-modal.css # 任务配置弹窗
│   ├── 34-sample-picker.css    # 样机选择器
│   ├── 35-task-result.css      # 结果录入
│   ├── 36-task-log.css         # 任务日志
│   └── 90-responsive.css       # 响应式
├── js/                    # JavaScript 21 文件
│   ├── utils.js           # 工具函数集
│   ├── app.core.js        # 核心入口
│   ├── app.server.js      # 服务器通信
│   ├── app.data.js        # 数据工具
│   ├── app.render.js      # 渲染引擎
│   ├── app.filters.js     # 筛选器
│   ├── app.modal.js       # 弹窗系统
│   ├── app.logs.js        # 日志系统
│   ├── projects.js        # 项目管理
│   ├── samples.js         # 样机全生命周期
│   ├── debug/             # 调试工具
│   └── workspace/         # 项目工作台 (10模块)
├── data/
│   ├── testchamber.sqlite # 主数据库
│   └── samples/           # 样机照片
├── backups/               # JSON 备份快照
├── templates/             # 导入模板
│   ├── sample_import_template.xlsx
│   └── 用例集导入模板.xlsx
└── docs/                  # 开发文档
```

---

## 数据模型

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

### 核心实体关系

```
项目 (Project)
  ├── 阶段 (Stage) × N
  │     ├── 进度条目 (Progress) × N  — 每个条目定义所需样机数
  │     ├── 任务 (Task) × N
  │     │     └── 样机分配 (sampleIds[])
  │     ├── SKU 方案 (skus[])
  │     ├── BOM 上料清单
  │     └── 测试策略表
  ├── 人员 (members[])  — 姓名/工号 格式
  └── 地点 (locations[])
```

---

## API 参考

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | SPA shell (index.html) |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/state` | 全量状态 + `revision` 乐观锁字段 |
| `PUT` | `/api/state` | 保存状态 — body: `{revision, baseData, data}` |
| `POST` | `/api/samples/<id>/photos` | multipart 照片上传 (≤80MB) |
| `DELETE` | `/api/samples/<id>/photos/<photoId>` | 软删除照片 |
| `GET` | `/api/samples/<id>/photos/<photoId>` | 照片文件服务 |
| `GET` | `/css/*`, `/js/*`, `/templates/*` | 静态文件 |

### 保存流程

1. 前端修改内存中的 `app.data`
2. `app.scheduleSave()` 450ms debounce → `app.save()`
3. `PUT /api/state` 发送 `{revision, baseData, data}`
4. 服务器做三向合并（base vs new vs current）
5. **200** → 更新 `_baseData` 和 `revision`
6. **409** (普通冲突) → `reloadFromServer()` 静默刷新
7. **409** (SAMPLE_OCCUPANCY_CONFLICT / C1) → 弹窗提示冲突详情，拒绝静默刷新

### 三向合并策略

- **项目** → **阶段** → **任务** → **任务日志**（嵌套合并）
- **样机库** → **分类** → **样机** → **照片索引** + **样机日志**（嵌套合并）
- 用 `id`（优先）或内容 `hash`（回退）做 identity tracking
- 规则：base vs new 不同 → 采用 new；current 独有且未在 new → 保留

---

## 浏览器兼容性

| 浏览器 | 最低版本 | 备注 |
|--------|---------|------|
| Chrome | 80+ | 推荐，需 `DecompressionStream` for XLSX |
| Edge | 80+ | 与 Chrome 同内核 |
| Firefox | 113+ | `DecompressionStream` 支持较晚 |
| Safari | 16.4+ | 未充分测试 |

---

## 技术债务

1. ~~**workspace.js 过大** (3594行)~~ ✅ 已解决 — 拆分为 10 个模块 (3722行)
2. ~~**samples.js 中 openSampleReadonly 与 app.render.js 重复定义**~~ ✅ 已解决 — 已从 app.render.js 和 app.data.js 中移除重复定义，仅保留 samples.js 中的版本
3. **全局变量污染** — 所有状态在 app.data/app.view 中，无模块隔离
4. **无前端测试** — 纯手动测试
5. **CSS 部分模块过大** — 20-samples 923行、35-task-result 782行、32-task-flow 588行，大量 `!important` patch 堆叠，建议后续引入 CSS 变量层级管理
6. **内存全量加载** — 样机数量大时可能影响性能
7. **照片无缩略图** — 原图直接展示在列表/网格中
8. **日志字段混杂** — sampleLibrary.logs 和 sample.logs 双写，字段命名不统一
9. **大量 DOM 字符串拼接** — 无 Virtual DOM 或模板引擎
10. **XLSX 解析依赖浏览器** — DecompressionStream 在新版 Chrome 才可用
11. **samples.js 仍然最大** (1580行, 62函数) — 样机全生命周期逻辑集中，建议后续拆分为 2-3 个子模块
12. **`saveTaskPlanConfig()` / `saveTaskSampleConfig()` 死代码** — 旧版单独保存函数 (`js/workspace/07-task-config.js:397-466`)，已被 `saveTaskConfigAll()` 取代但未删除

