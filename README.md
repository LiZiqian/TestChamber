# TestChamber

<p align="center">
  <a href="https://github.com/LiZiqian/TestChamber/releases/tag/v7.2.0"><img alt="Version 7.2.0" src="https://img.shields.io/badge/version-v7.2.0-2f80ed"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white">
  <img alt="Windows Intranet" src="https://img.shields.io/badge/platform-Windows%20Intranet-0078D4?logo=windows&logoColor=white">
  <img alt="SQLite WAL" src="https://img.shields.io/badge/database-SQLite%20WAL-003B57?logo=sqlite&logoColor=white">
  <img alt="No pip or npm dependencies" src="https://img.shields.io/badge/dependencies-no%20pip%20%7C%20no%20npm-22a06b">
  <img alt="Default port 9398" src="https://img.shields.io/badge/default%20port-9398-f59e0b">
</p>

面向硬件测试实验室的样机、任务、结果与数据包治理平台。

TestChamber 把“项目 -> 阶段 -> 测试任务 -> 样机 -> 结果 -> 履历”这条链路收进一个可以在 Windows 内网机器上直接运行的轻量系统。它不依赖外部云服务，不需要安装数据库服务器，也不需要 npm / pip 依赖；下载源码、启动 Python 服务、打开浏览器即可开始使用。

> [!NOTE]
> - 当前版本：`7.2.0`
> - 默认端口：`9398`（可自定义）
> - 默认数据目录：项目内 `data/`
> - 推荐运行环境：Windows + Python 3.9+ + Chrome / Edge

## 目录

- [为什么需要 TestChamber](#为什么需要-testchamber)
- [核心能力](#核心能力)
- [适合谁使用](#适合谁使用)
- [快速部署](#快速部署)
- [Windows 详细部署教程](#windows-详细部署教程)
- [启动方式对比](#启动方式对比)
- [端口选择建议](#端口选择建议)
- [Python 找不到怎么办](#python-找不到怎么办)
- [第一次使用路线](#第一次使用路线)
- [数据、导出与迁移](#数据导出与迁移)
- [常见问题](#常见问题)
- [开发者信息](#开发者信息)
- [发布与仓库卫生](#发布与仓库卫生)

## 为什么需要 TestChamber

硬件测试项目里，最容易失控的不是单个测试动作，而是跨项目、跨阶段、跨人员、跨样机的状态同步：

- 哪些样机已经被任务占用，哪些还能下发？
- 某台样机经历过哪些项目、阶段、测试项和故障？
- 一个阶段里有多少任务待下发、进行中、阻塞、已完成？
- 结果照片、DTS、问题描述和样机去向是否能和任务绑定？
- 换电脑、换平台或交付测试数据时，能不能把数据和照片完整迁移？

TestChamber 的目标是把这些分散在 Excel、聊天记录、文件夹和个人记忆里的信息，变成可追踪、可查询、可迁移的测试运行台账。

## 核心能力

| 模块 | 能做什么 | 价值 |
|------|----------|------|
| 项目管理 | 管理项目、阶段、SKU、BOM、测试策略、人员和地点 | 把测试计划拆成可执行的阶段和任务 |
| 任务管理 | 创建、配置、启动、阻塞、临时变更、结束任务 | 让任务状态、执行人、计划时间和样机占用可追踪 |
| 样机档案池 | 维护样机池、样机基础信息、状态、保管人、借用人 | 避免样机重复建档、重复占用和去向不清 |
| 结果录入 | 逐台样机填写结论、问题、DTS、去向和照片 | 让测试结论和样机履历绑定 |
| 照片与履历 | 上传照片、生成缩略图、查看样机事件和测试历史 | 保留故障证据和生命周期记录 |
| 数据包导入导出 | 导出完整 zip，导入前预览冲突，支持选择性迁移和单台样机档案包 | 支持跨电脑迁移、交付、手动留存、空白平台整包导入和样机独立流转 |
| 安全兜底 | 样机占用冲突检测、结束任务防重复、导入一致性校验 | 降低误操作和数据错乱风险 |
| 大数据性能 | 启动骨架、服务端分页、SQLite 索引、增量写入 | 面对大量任务、样机和照片元数据时仍能保持流畅 |

## 适合谁使用

TestChamber 特别适合这些场景：

- 实验室或测试团队需要在内网机器上共享一个测试平台。
- 项目有多个阶段、多个测试项，样机需要在任务之间流转。
- 团队现在用 Excel 记录样机、任务和结果，但经常出现状态不同步。
- 测试结果需要保留照片、DTS、故障描述和样机去向。
- 平台需要简单部署，不希望引入复杂后端、云服务或专门数据库运维。
- 数据需要能打包导出，方便手动留存、迁移或交付。

## 系统一眼看懂

系统流程：

<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="820" viewBox="0 0 1120 820" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="title desc">
  <title id="title">TestChamber V7 system workflow</title>
  <desc id="desc">Project workflow and sample workflow converge into task execution, result entry, history, and data migration.</desc>
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L8,3 L0,6 Z" fill="#cbd5e1" />
    </marker>
    <filter id="cardShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#0f172a" flood-opacity="0.12" />
    </filter>
  </defs>
  <style>
    .canvas { fill: transparent; }
    .group-title { font: 700 22px -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; fill: #94a3b8; }
    .card-title { font: 700 22px -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; fill: #0f172a; }
    .card-detail { font: 400 14px -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; fill: #64748b; }
    .arrow { fill: none; stroke: #cbd5e1; stroke-width: 2; marker-end: url(#arrow); }
    .group { rx: 8; }
    .node { rx: 6; }
  </style>

  <rect class="canvas" width="1120" height="820" />

  <rect class="group" x="70" y="34" width="420" height="276" fill="#f8fbff" fill-opacity="0.04" stroke="#60a5fa" stroke-opacity="0.35" stroke-width="1.5" />
  <text class="group-title" x="280" y="62" text-anchor="middle">项目链路</text>
  <rect class="node" x="118" y="86" width="324" height="86" fill="#eff6ff" stroke="#60a5fa" stroke-width="2.5" />
  <text class="card-title" x="280" y="123" text-anchor="middle">项目管理</text>
  <text class="card-detail" x="280" y="148" text-anchor="middle">阶段 / 方案 / 人员</text>
  <path class="arrow" d="M280 172 L280 198" />
  <rect class="node" x="118" y="198" width="324" height="86" fill="#eff6ff" stroke="#60a5fa" stroke-width="2.5" />
  <text class="card-title" x="280" y="235" text-anchor="middle">测试任务工作表</text>
  <text class="card-detail" x="280" y="260" text-anchor="middle">任务生成 / 筛选 / 跟踪</text>

  <rect class="group" x="630" y="34" width="420" height="276" fill="#f7fef9" fill-opacity="0.04" stroke="#86efac" stroke-opacity="0.35" stroke-width="1.5" />
  <text class="group-title" x="840" y="62" text-anchor="middle">样机链路</text>
  <rect class="node" x="678" y="86" width="324" height="86" fill="#f0fdf4" stroke="#86efac" stroke-width="2.5" />
  <text class="card-title" x="840" y="123" text-anchor="middle">样机档案库</text>
  <text class="card-detail" x="840" y="148" text-anchor="middle">样机池 A / B</text>
  <path class="arrow" d="M840 172 L840 198" />
  <rect class="node" x="678" y="198" width="324" height="86" fill="#f0fdf4" stroke="#86efac" stroke-width="2.5" />
  <text class="card-title" x="840" y="235" text-anchor="middle">样机卡片</text>
  <text class="card-detail" x="840" y="260" text-anchor="middle">详情 / 履历 / 图片 / CT 数据</text>

  <rect class="group" x="270" y="418" width="580" height="372" fill="#fffdf5" fill-opacity="0.04" stroke="#fbbf24" stroke-opacity="0.35" stroke-width="1.5" />
  <text class="group-title" x="560" y="450" text-anchor="middle">执行闭环</text>
  <rect class="node" x="350" y="476" width="420" height="78" fill="#fffbeb" stroke="#fbbf24" stroke-width="2.5" />
  <text class="card-title" x="560" y="509" text-anchor="middle">任务执行</text>
  <text class="card-detail" x="560" y="533" text-anchor="middle">执行人 / 样机 / 启动 / 阻塞</text>
  <path class="arrow" d="M560 554 L560 582" />
  <rect class="node" x="350" y="582" width="420" height="78" fill="#fff7ed" stroke="#fb923c" stroke-width="2.5" />
  <text class="card-title" x="560" y="615" text-anchor="middle">结果录入</text>
  <text class="card-detail" x="560" y="639" text-anchor="middle">结论 / 故障照片 / 分析照片 / 样机去向</text>
  <path class="arrow" d="M560 660 L560 688" />
  <rect class="node" x="350" y="688" width="420" height="78" fill="#f8fafc" stroke="#94a3b8" stroke-width="2.5" />
  <text class="card-title" x="560" y="721" text-anchor="middle">履历与迁移</text>
  <text class="card-detail" x="560" y="745" text-anchor="middle">样机履历 / 数据包迁移</text>

  <path class="arrow" d="M280 284 C280 360, 430 398, 505 476" />
  <path class="arrow" d="M840 284 C840 360, 690 398, 615 476" />
</svg>

技术结构：

<svg xmlns="http://www.w3.org/2000/svg" width="920" height="220" viewBox="0 0 920 220" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="title desc">
  <title id="title">TestChamber V7 technical architecture</title>
  <desc id="desc">The browser single page application talks to the Python server, which stores data in local SQLite, photo assets, and export bundles.</desc>
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L8,3 L0,6 Z" fill="#cbd5e1" />
    </marker>
    <filter id="cardShadow" x="-10%" y="-15%" width="120%" height="130%">
      <feDropShadow dx="0" dy="7" stdDeviation="10" flood-color="#0f172a" flood-opacity="0.14" />
    </filter>
  </defs>
  <style>
    .canvas { fill: transparent; }
    .card { rx: 8; filter: url(#cardShadow); }
    .card-title { font: 700 22px -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; fill: #0f172a; }
    .card-detail { font: 400 14px -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; fill: #64748b; }
    .arrow { fill: none; stroke: #cbd5e1; stroke-width: 2.5; marker-end: url(#arrow); }
    .label { font: 600 12px -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; fill: #94a3b8; letter-spacing: 0.5px; }
  </style>

  <rect class="canvas" width="920" height="220" />

  <text class="label" x="112" y="45" text-anchor="middle">CLIENT</text>
  <rect class="card" x="42" y="64" width="224" height="104" fill="#eff6ff" stroke="#60a5fa" stroke-width="2.5" />
  <text class="card-title" x="154" y="106" text-anchor="middle">浏览器 SPA</text>
  <text class="card-detail" x="154" y="134" text-anchor="middle">Vanilla JS + CSS</text>

  <path class="arrow" d="M278 116 L354 116" />

  <text class="label" x="460" y="45" text-anchor="middle">SERVER</text>
  <rect class="card" x="348" y="64" width="224" height="104" fill="#fffbeb" stroke="#fbbf24" stroke-width="2.5" />
  <text class="card-title" x="460" y="106" text-anchor="middle">Python 服务</text>
  <text class="card-detail" x="460" y="134" text-anchor="middle">backend/server.py / HTTP API</text>

  <path class="arrow" d="M584 116 L660 116" />

  <text class="label" x="808" y="45" text-anchor="middle">STORAGE</text>
  <rect class="card" x="654" y="64" width="264" height="104" fill="#f0fdf4" stroke="#86efac" stroke-width="2.5" />
  <text class="card-title" x="786" y="106" text-anchor="middle">本地数据</text>
  <text class="card-detail" x="786" y="134" text-anchor="middle">SQLite / 照片 / 数据包</text>
</svg>

## 快速部署

### 1. 准备 Python

安装 Python 3.9 或更高版本。Windows 推荐任选一种：

- Python 官网安装包
- Miniforge
- Mambaforge
- Anaconda

安装后可以在终端里验证：

```powershell
python --version
```

### 2. 下载并解压项目

从 GitHub 下载源码压缩包，解压到一个稳定目录，例如：

```text
C:\TestChamber
```

不要放在会频繁同步、自动清理或权限受限的目录里。

### 3. 双击启动

在项目目录里双击：

```text
start_server.bat
```

启动脚本会做三件事：

1. 询问是否使用默认端口 `9398`。
2. 自动寻找 Python，包括 `PYTHON_EXE`、`CONDA_PREFIX`、Miniforge、Mambaforge、Anaconda、`py -3` 和 `python`。
3. 找不到 Python 时，提示你输入或拖入 `python.exe` 路径。

### 4. 打开浏览器

启动成功后，在本机浏览器访问：

```text
http://127.0.0.1:9398/
```

如果你在 `.bat` 里选择了其他端口，把 `9398` 换成你输入的端口。

### 5. 内网访问

如果要让同一局域网的其他电脑访问，服务器电脑需要保持启动窗口不关闭，然后其他电脑访问：

```text
http://服务器IP:9398/
```

例如：

```text
http://192.168.1.20:9398/
```

> [!TIP]
> 有线网络能访问但无线网络不能访问时，通常不是 TestChamber 程序问题，而是无线网络隔离、访客 Wi-Fi、VLAN、ACL 或防火墙策略导致。优先检查网络路径和端口连通性。

## Windows 详细部署教程

### 步骤 1：确认电脑有 Python

打开 PowerShell，执行：

```powershell
python --version
```

能看到版本号即可，例如：

```text
Python 3.10.11
```

如果提示找不到 Python，也可以继续双击 `start_server.bat`。启动脚本会尝试自动寻找常见安装目录；实在找不到时，会让你手动输入 `python.exe` 路径。

### 步骤 2：进入项目目录

项目目录里至少应看到这些文件：

```text
frontend/
backend/
data/
start_server.bat
README.md
```

### 步骤 3：启动服务

推荐普通用户使用：

```text
start_server.bat
```

推荐开发或调试时使用：

```powershell
python -m backend.server --host 127.0.0.1 --port 9398
```

如果需要允许局域网访问：

```powershell
python -m backend.server --host 0.0.0.0 --port 9398
```

### 步骤 4：验证服务

本机访问：

```text
http://127.0.0.1:9398/
```

健康检查：

```text
http://127.0.0.1:9398/api/health
```

如果返回 JSON，说明后端已经正常运行。

### 步骤 5：停止服务

关闭启动窗口，或在终端按：

```text
Ctrl + C
```

## 启动方式对比

| 启动方式 | 适合人群 | 端口 | Python 查找 | 说明 |
|----------|----------|------|-------------|------|
| `start_server.bat` | 普通 Windows 用户 | 可选择默认 `9398` 或自定义 | 自动查找，找不到会循环询问路径 | 最推荐的双击启动方式 |
| `python -m backend.server --host 127.0.0.1 --port 9398` | 开发调试 | 手动指定 | 使用当前终端 Python | 本机访问最清晰 |
| `python -m backend.server --host 0.0.0.0 --port 9398` | 内网部署 | 手动指定 | 使用当前终端 Python | 允许局域网其他电脑访问 |

## 端口选择建议

默认端口是：

```text
9398
```

如果端口被占用，`start_server.bat` 可以选择自定义端口。建议使用：

```text
1024 - 49151
```

尽量避开这些常见端口：

| 端口 | 常见用途 |
|------|----------|
| `3000` | 前端开发服务器 |
| `3306` | MySQL |
| `5000` | Flask / 开发服务 |
| `5432` | PostgreSQL |
| `6379` | Redis |
| `8000` | 开发服务器 |
| `8080` | 代理 / Web 服务 |
| `8888` | Notebook / 工具服务 |
| `9000` | 对象存储 / 工具服务 |

如果只是 TestChamber 自己使用，优先保留 `9398`。

## Python 找不到怎么办

有些电脑上，即使打开 Miniforge Terminal 再把 `.bat` 拖进去，也可能提示找不到 Python。常见原因包括：

- 当前终端的环境变量没有传给 `.bat`。
- Miniforge / Anaconda 没装在默认目录。
- `python.exe` 存在，但没有加入 `PATH`。
- 用户把 `.bat` 从压缩包内直接运行，当前目录不完整。
- 安装的是 Microsoft Store 的 Python 占位启动器。
- 公司电脑策略限制了脚本读取某些路径。

`start_server.bat` 已经做了兜底：

1. 先打印 `PYTHON_EXE`、`CONDA_PREFIX`、`where python`、`where py`。
2. 自动检查常见 Conda / Miniforge / Anaconda 路径。
3. 尝试 `py -3` 和 `python`。
4. 仍然找不到时，让用户输入或拖入 `python.exe`。
5. 如果输入的是目录，会自动尝试 `<目录>\python.exe`。
6. 每次输入都会验证是否真的能执行 Python。

你可以手动输入类似路径：

```text
C:\Users\你的用户名\miniforge3\python.exe
C:\Users\你的用户名\Anaconda3\python.exe
C:\ProgramData\Anaconda3\python.exe
D:\Miniforge3\python.exe
```

输入 `Q` 可以退出启动脚本。

## 第一次使用路线

建议按这个顺序建立你的第一套测试数据：

1. 进入 **样机档案池**，创建一个样机池。
2. 新增样机，或用模板批量导入样机。
3. 进入 **项目管理**，创建一个测试项目。
4. 进入项目，创建阶段、SKU、项目人员和测试地点。
5. 在阶段里配置测试策略和用例集。
6. 进入任务管理，从测试策略生成任务。
7. 打开任务配置，选择执行人、计划时间和样机。
8. 启动任务，执行测试。
9. 在结果页面逐台录入测试结论、问题、照片和去向。
10. 结束任务，查看样机履历和项目进度。
11. 需要迁移或留存时，导出完整数据包或单台样机档案包。

## 主要工作流

### 项目与阶段

- 新建项目，维护项目编号、负责人和备注。
- 在项目内新建阶段，按阶段管理 SKU、BOM 和测试策略。
- 维护项目成员和测试地点，供任务配置和结果记录使用。

### 任务下发与执行

- 从阶段策略生成任务。
- 配置执行人、计划时间和样机。
- 启动任务后，样机进入任务占用链路。
- 任务可进入 `进行中`、`阻塞中`、`正常完成` 或 `异常终止`。

### 状态模型

TestChamber 的状态不是一个单独字段。平台把任务流转、测试结果、样机使用状态、样机质量和重组标签分开处理，这样可以避免把“任务结束了”“测试结论是什么”“样机还在分析”“样机有故障”“这台是重组样机”混成同一个状态。`stage.progress[]` 只表示阶段计划项，不再保存执行状态。

| 状态域 | 标准值 | 说明 |
|--------|--------|------|
| 任务流转 | `待下发` / `进行中` / `阻塞中` / `正常完成` / `异常终止` | 描述任务生命周期。 |
| 测试结果 | `通过` / `不通过` | 描述任务测试结论；不要和任务流转的完成态混用。 |
| progress 计划项 | 无独立状态 | 只保存 `id / strategyId / category / testItem / skuIndex / sampleSize`；UI 显示状态由关联任务派生。 |
| 样机使用 | `闲置` / `在位等待` / `测试中` / `已退库` / `取走分析` | 描述样机当前占用和去向；这是样机池筛选与统计的主状态。 |
| 样机质量 | `无故障` / `有故障` | 描述样机是否存在问题记录；不是样机使用状态。 |
| 重组 | `非重组` / `重组` | 描述样机身份标签；不是样机使用状态。 |

任务流转、测试结果与 progress 计划项显示的关系：

```text
任务流转: 待下发 -> 进行中 <-> 阻塞中 -> 正常完成 / 异常终止
测试结果: 通过 / 不通过
progress: 计划项定义，不保存状态
```

- 任务流转是唯一生命周期状态源。
- 测试结果只写入 `task.latestResult` 和 `task.resultUploads[].result`。
- `正常完成` 不等于 `通过`：任务可以按计划完整结束，但测试结果为 `不通过`。
- `异常终止` 时测试结果必须是 `不通过`。
- UI 如需展示计划项状态，按关联任务派生：未生成任务显示 `待下发`；未完成任务显示任务流转；完成任务显示测试结果。

任务流转与样机使用状态的关系：

```text
样机闲置
  --分配到待下发任务--> 在位等待
  --启动任务/重启任务--> 测试中
  --阻塞任务--> 在位等待
  --结束任务/结果录入选择去向--> 闲置 / 取走分析 / 已退库
```

- 新增加入任务的样机必须是 `闲置`。
- 待下发任务分配样机后，样机进入 `在位等待`。
- 启动或重启任务后，任务样机进入 `测试中`。
- 阻塞任务后，任务样机回到 `在位等待`。
- 结束任务或录入结果时，每台样机单独选择去向：`闲置`、`取走分析` 或 `已退库`。
- 如果样机被多个未完成任务引用，释放当前任务时会按其它任务恢复为 `在位等待` 或 `测试中`；否则回到 `闲置`。

样机质量与重组标签的关系：

- `无故障 / 有故障` 来自样机问题记录。填写了有效问题后，样机会显示为 `有故障`；清空问题记录后恢复为 `无故障`。
- `非重组 / 重组` 来自样机是否重组的标记。它影响筛选、卡片标签和身份查重策略。
- `有故障` 和 `重组` 都不是 `sample.status`，不会替代 `闲置 / 在位等待 / 测试中 / 已退库 / 取走分析`。

### 样机档案与履历

- 样机按样机池分类管理。
- 支持 IMEI、SN、主板 SN 等标识。
- 支持状态、保管人、借用人、位置、照片、问题和事件日志。
- 样机参与任务后，会形成跨项目、跨阶段的测试履历。

### 结果录入

- 对任务里的每台样机填写测试结论。
- 记录 DTS、故障描述、问题照片和最终去向。
- 支持草稿，避免结果未录完就丢失。
- 结束任务时有前端防重复和后端幂等兜底。

### 数据包导入导出

完整数据包采用 `ChamberData` 域拆分格式，包含：

- `manifest.json`
- `domains/*.json`，包括 app、projects、stages、tasks、sample-categories、samples、sample-assets 和 sample-events
- `assets/index.json`
- `checksums.json`
- 样机照片原图和缩略图资产

导入前会先预览，检查结构、冲突、资产 hash 和引用一致性。预览弹窗可以选择导入项目、阶段、任务、样机池或单台样机；提交时只写入勾选范围。导入提交成功后会优先按 `mutationSummary` 局部刷新受影响的项目、样机池和样机详情，不再把完整 `/api/state` 作为成功路径。

单台样机还可以导出为样机档案包。样机档案包同样使用 `manifest + domains + assets/index + checksums`，额外包含 `dossier.json`、`sample/info.json`、`sample/photos.json`、`sample/events.json` 和 `sample/history.json`。导入单台样机档案包时，默认只进入样机档案池，不重建来源项目、阶段或任务；外部履历会作为样机履历事件显示。

## 数据、导出与迁移

### 本地数据目录

首次运行会自动创建项目内数据目录；例如平台在 `TestChamberV7/` 时，默认数据目录是 `TestChamberV7/data/`。

```text
TestChamberV7/data/
├── testchamber.sqlite
├── deployment.json
├── platform-data.json
├── samples/
│   └── <sampleId>/
│       └── photos/
├── import-previews/
└── exports/
```

其中：

| 路径 | 说明 |
|------|------|
| `data/testchamber.sqlite` | SQLite 主数据库 |
| `data/deployment.json` | 当前部署身份 |
| `data/platform-data.json` | 数据根目录标记文件，用于确认当前 data/ 属于本平台 |
| `data/samples/.../photos/` | 样机照片和缩略图 |
| `data/import-previews/` | 导入预览临时目录 |
| `data/exports/` | 导出临时 zip 目录 |

如果旧版本已经在平台目录同级存在 `TestChamberV7_data/`，新版本启动时会先复制到项目内 `data/`；旧目录不会自动删除。旧版 `backups/` 不再迁移，也不会自动生成。

也可以手动执行同一套迁移逻辑：

```powershell
python dev\tools\migrate_data_root.py
python dev\tools\migrate_data_root.py --data-dir .\data
```

迁移采用 `copy-then-promote`：先复制到临时 staging 目录，逐文件校验通过后才提升为正式项目内数据目录；旧同级数据目录不会被删除。命令输出中的 `verified_files` 和 `copied_bytes` 可作为本次迁移的核对信号。

### 不要上传运行数据

仓库的 `.gitignore` 已忽略：

```text
data/
__pycache__/
*.sqlite
*.db
```

不要把真实数据库、照片或公司测试数据提交到 GitHub。

### 推荐导出方式

日常数据留存优先使用平台内的：

```text
导出完整数据包
```

这样可以同时带走数据库状态、样机照片和引用关系。需要跨服务器只迁移单台样机时，在样机详情里导出“样机档案包”，再在目标样机池中导入。直接复制项目内 `data/` 也可以作为本机级留存，但跨电脑迁移时更推荐数据包导出导入。

## 常见问题

### 双击 `.bat` 时 Windows 提示“无法验证发布者”

这是 Windows 对从网络下载的脚本文件做的安全提醒，不代表 TestChamber 本身有问题。源码项目通常没有商业代码签名证书，所以会出现这个提示。

常见处理方式：

- 确认文件来源是你信任的 GitHub 仓库。
- 解压后右键文件，检查属性里是否有“解除锁定”。
- 点击“仍要运行”继续启动。

如果后续要给大量非技术用户分发，可以考虑制作签名的 MSI 或 EXE 安装包；当前源码部署方式更轻量，维护成本更低。

### 浏览器打不开 `http://127.0.0.1:9398/`

依次检查：

1. 启动窗口是否还开着。
2. 端口是否被其他程序占用。
3. 启动日志里是否有 Python 报错。
4. 是否选择了非 `9398` 的自定义端口。
5. 访问 `/api/health` 是否返回 JSON。

### 局域网其他电脑打不开

本机能打开，但其他电脑打不开时，优先检查：

- 启动参数是否是 `--host 0.0.0.0`。
- Windows 防火墙是否允许该端口入站。
- 服务器 IP 是否正确。
- 访问电脑和服务器是否在同一网段。
- 公司 Wi-Fi 是否开启客户端隔离或访客网络隔离。
- VLAN / ACL 是否阻止访问服务器端口。

快速测试：

```powershell
Test-NetConnection 服务器IP -Port 9398
```

### 端口已经被占用

可以：

- 关闭占用该端口的旧 TestChamber 窗口。
- 在 `start_server.bat` 中选择自定义端口。
- 手动启动时改端口：

```powershell
python -m backend.server --host 0.0.0.0 --port 9400
```

然后访问：

```text
http://127.0.0.1:9400/
```

### 导入数据包前要注意什么

建议先确认：

- 当前没有未保存的操作。
- 数据包来源可信。
- 预览页没有 blocker。
- 冲突项的保留、覆盖或合并选择符合预期。

空白平台整包导入已经有一致性校验，导入后会检查项目、阶段、任务和样机引用关系。

## 开发者信息

### 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.9+ |
| 浏览器 | Chrome / Edge / Firefox / Safari |
| 后端依赖 | Python 标准库 |
| 前端依赖 | 无构建依赖 |
| 数据库 | SQLite WAL |

无需执行：

```text
pip install
npm install
```

### 项目结构

```text
TestChamber/
├── start_server.bat          # Windows double-click launcher
├── README.md
├── backend/                  # Python stdlib HTTP server + SQLite persistence
│   ├── server.py
│   └── server_modules/
├── frontend/                 # SPA entry and frontend assets
│   ├── index.html
│   ├── css/                  # Split stylesheets
│   ├── js/
│   │   ├── app.core.js       # App bootstrap
│   │   ├── app.server.js     # API calls and incremental mutations
│   │   ├── app.data.js       # Data normalization and state helpers
│   │   ├── app.render.js     # Main render dispatcher
│   │   ├── projects.js
│   │   ├── samples/
│   │   └── workspace/
│   └── templates/            # CSV / XLSX import templates
├── data/                     # Runtime database and photos; ignored by git
└── dev/                      # Development-only tests and maintenance tooling
    ├── tests/                # Python and frontend regression tests
    └── tools/                # Migration, map refresh, and benchmark tooling
```

运行数据默认在项目内 `data/`，但仍由 `.gitignore` 排除，不属于源码提交内容。

### 核心数据流

启动时：

```text
GET /api/bootstrap
  -> 项目摘要 + 样机池摘要 + revision
  -> 前端初始化导航和首页
```

大列表：

```text
GET /api/stages/<stageId>/tasks?page=...
GET /api/sample-categories/<catId>/samples?page=...
GET /api/task-sample-candidates?page=...
GET /api/samples/<sampleId>/history?page=...
  -> 服务端分页
  -> 前端缓存当前页并预取相邻页
```

日常写入：

```text
PATCH /api/tasks/<taskId>/mutation
PATCH /api/projects/<projectId>/mutation
PATCH /api/stages/<stageId>/mutation
PATCH /api/samples/<sampleId>/mutation
PATCH /api/sample-categories/<categoryId>/mutation
  -> 只提交受影响记录
  -> SQLite 更新 revision
```

完整状态：

```text
GET /api/state
PUT /api/state
```

完整状态接口仍保留为手动调试和异常兜底路径，不作为日常启动和大列表浏览主路径。

### API 摘要

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/` | SPA 入口 |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/bootstrap` | 启动骨架 |
| `GET` | `/api/projects/summary` | 项目摘要 |
| `GET` | `/api/projects/<id>` | 项目详情 |
| `GET` | `/api/stages/<stageId>/tasks` | 阶段任务分页 |
| `GET` | `/api/task-sample-candidates` | 任务样机候选分页 |
| `GET` | `/api/sample-categories` | 样机池摘要 |
| `GET` | `/api/sample-categories/<id>` | 样机池详情 |
| `GET` | `/api/sample-categories/<id>/samples` | 样机分页 |
| `GET` | `/api/sample-destroy-impact` | 样机或样机池销毁影响范围 |
| `PATCH` | `/api/tasks/<id>/mutation` | 任务增量写入 |
| `PATCH` | `/api/stages/<id>/tasks/batch` | 批量任务增量写入 |
| `PATCH` | `/api/projects/<id>/mutation` | 项目增量写入 |
| `PATCH` | `/api/stages/<id>/mutation` | 阶段增量写入 |
| `PATCH` | `/api/samples/<id>/mutation` | 单台样机增量写入 |
| `PATCH` | `/api/sample-categories/<id>/mutation` | 样机池增量写入 |
| `POST` | `/api/samples/<id>/photos` | 上传样机照片 |
| `DELETE` | `/api/samples/<id>/photos/<photoId>` | 删除样机照片 |
| `PATCH` | `/api/samples/<id>/photos/<photoId>` | 重命名样机照片 |
| `GET` | `/api/samples/<id>/photos` | 按需读取样机照片 |
| `GET` | `/api/samples/<id>/events` | 按需读取样机事件 |
| `GET` | `/api/samples/<id>/history` | 样机测试履历分页 |
| `GET` | `/api/samples/<id>/archive` | 导出单台样机档案包 |
| `GET` | `/api/export-bundle` | 导出完整或按查询参数选择范围的数据包 |
| `POST` | `/api/import-bundle/preview` | 数据包导入预览 |
| `POST` | `/api/import-bundle/commit` | 数据包导入提交 |
| `POST` | `/api/samples/archive/preview` | 单台样机档案包导入预览 |
| `POST` | `/api/samples/archive/commit` | 单台样机档案包导入提交 |
| `POST` | `/api/sample-identity-check` | 样机身份查重 |
| `POST` | `/api/browser-cache/clear` | 清理当前浏览器对平台的缓存并刷新 |
| `GET` | `/api/state` | 完整状态读取，低频兜底 |
| `PUT` | `/api/state` | 完整状态保存，低频兜底 |

### 验证命令

发布或改动核心代码前建议运行：

```powershell
python -m py_compile backend\server.py
python dev\tests\test_server_core.py
python dev\tests\test_import_conflicts.py
node dev\tests\frontend_architecture_guard.test.cjs
node dev\tests\frontend_pagination_perf.test.cjs
node dev\tests\frontend_status_transitions.test.cjs
```

启动验证：

```powershell
python -m backend.server --host 127.0.0.1 --port 9398
```

另开一个 PowerShell：

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:9398/api/health -UseBasicParsing
```

## 已完成的关键优化

- 启动入口改为 `/api/bootstrap`，避免首屏直接拉完整状态。
- 任务表和样机池走服务端分页。
- SQLite 查询列和索引用于任务状态、样机状态、分页和统计。
- 项目、阶段、任务、样机、样机池主路径改为 PATCH 增量写入。
- 样机照片和事件按需加载。
- 样机测试履历、任务样机候选列表走服务端分页。
- 样机选择器限制只有“闲置”样机可新增选择。
- 结束任务有前端 in-flight 防重和后端 `TASK_ALREADY_FINISHED` 幂等兜底。
- 完整数据包导入支持空白平台整包导入、选择性迁移、冲突预览、提交前一致性校验和成功后的局部同步。
- 单台样机档案包支持跨服务器导出/导入，默认只进入样机档案池，不重建来源项目结构。
- 前端主干已迁移到 `app.registerModule()` 和 `data-app-action` 事件委托，并有架构护栏测试防止回退。
- 首页提供浏览器缓存清理入口，用于处理旧 Chrome 缓存导致的前后端版本不一致或本地状态异常。
- Windows 启动脚本增强 Python 自动发现、路径输入兜底和 `.bat` 端口选择。

## 后续方向

- 补充结果录入、任务临时变更、SQLite 持久化迁移和浏览器端交互回归专项覆盖。
- 继续把复杂字符串模板逐步迁移为更可维护的 DOM helper 或小组件。
- 在任务详情、样机详情、照片区继续做大数据量渲染压测。

## 发布与仓库卫生

### 发布前检查

1. 更新 `backend/server.py` 的 `APP_VERSION` / `SERVER_VERSION`。
2. 更新 `frontend/js/app.core.js` 的 `app.version`。
3. 同步 `frontend/index.html` 和 `frontend/css/style.css` 的静态资源 cachebuster。
4. 跑完核心测试。
5. 确认没有提交运行数据。

### 不应提交到仓库

- `data/`
- `TestChamberV7_data/`
- `__pycache__/`
- `*.sqlite`
- `*.db`
- 本地私有 AI 指令文件，例如 `CLAUDE.md` 或未纳入仓库约定的个人提示文件

仓库内的 `AGENTS.md` 是项目代码定位器，不属于运行数据；只有在需要刷新代码地图时才单独更新。

本地私有忽略规则可以写入：

```text
.git/info/exclude
```

这样不会污染仓库里的 `.gitignore`。

### Release 提醒

`7.1` 系列复用同一个 GitHub Release/tag 入口 `v7.1.0`；`7.2.0` 是新的主线版本，使用独立 tag / Release：`v7.2.0`。

如果某个 tag 或 release 已经创建，旧 release 源码包会保留当时的文件快照。即使后续从 `main` 删除了某个文件，旧 release 包也不会自动变化。需要让旧版本源码包也变干净时，应重新打 tag 或重新发布 release。
