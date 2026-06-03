/* ========================================
   数字治理平台 V7 - 任务表格展示模块
   ======================================== */

Object.assign(app, {

  taskRowsForStage(stage) {
    const progress = stage.progress || [];
    const tasks = this.activeStageTasks(stage);
    const progressById = new Map(progress.map(p => [p.id, p]));
    return tasks.map((t, idx) => ({
      key: t.id || `${t.progressId || "task"}_${idx}`,
      progress: progressById.get(t.progressId) || null,
      task: t
    }));
  },

  taskInfoForRow(stage, row) {
    const p = row.progress || {};
    const t = row.task || {};
    const skuIndex = t.skuIndex || p.skuIndex || 1;
    const category = t.category || p.category || "";
    const testItem = t.testItem || p.testItem || "";
    const owner = t.owner || "";
    const sampleIds = t.sampleIds || [];
    const flowStatus = row.task ? this.taskFlowStatus(t) : "待下发";
    const planStartDate = t.planStartDate || t.planDate || "";
    const planEndDate = t.planEndDate || "";
    return {
      sku: stage.skuNames[skuIndex - 1] || `SKU${skuIndex}`,
      skuIndex,
      category,
      testItem,
      categoryItem: this.taskCategoryItemText(category, testItem),
      owner,
      ownerName: this.taskOwnerName(owner),
      ownerId: this.taskOwnerId(owner),
      planStartDate,
      planEndDate,
      startDate: t.startDate || p.startDate || "",
      endDate: t.endDate || p.endDate || "",
      sampleIds,
      flowStatus
    };
  },

  boundedListPageSize(value, fallback = 100) {
    const n = Number.parseInt(value, 10);
    if (!Number.isFinite(n) || n <= 0) return fallback;
    return Math.min(500, Math.max(20, n));
  },

  taskFlowPagerHtml(page, totalPages, total, pageSize, { loading = false } = {}) {
    const start = total ? (page - 1) * pageSize + 1 : 0;
    const end = total ? Math.min(total, page * pageSize) : 0;
    const pageBtn = (label, target, disabled = false) => `
      <button type="button" class="btn btn-sm btn-outline" ${disabled || loading ? "disabled" : `onclick="app.setTaskFlowPage(${target})"`}>${label}</button>`;
    return `
      <div class="list-pager task-flow-pager ${loading ? "is-loading" : ""}">
        <span class="path">显示 ${start}-${end} / ${total} 条</span>
        <div class="list-pager-controls">
          ${pageBtn("上一页", page - 1, page <= 1)}
          <span class="path">第 ${page} / ${totalPages} 页</span>
          ${pageBtn("下一页", page + 1, page >= totalPages)}
          <select onchange="app.setTaskFlowPageSize(this.value)">
            ${[50, 100, 200, 500].map(size => `<option value="${size}" ${pageSize === size ? "selected" : ""}>每页 ${size}</option>`).join("")}
          </select>
          ${loading ? `<span class="path list-pager-loading">加载中...</span>` : ""}
        </div>
      </div>`;
  },

  setTaskFlowPage(page) {
    this.view.taskFlowPage = Math.max(1, Number.parseInt(page, 10) || 1);
    this.renderPreserveScroll();
  },

  setTaskFlowPageSize(size) {
    this.view.taskFlowPageSize = this.boundedListPageSize(size, 100);
    this.view.taskFlowPage = 1;
    this.renderPreserveScroll();
  },

  taskFlowQueryParams(stage) {
    const f = this.view.taskFlowFilters || {};
    const params = {
      page: Math.max(1, Number.parseInt(this.view.taskFlowPage, 10) || 1),
      pageSize: this.boundedListPageSize(this.view.taskFlowPageSize, 100)
    };
    ["sku", "flowStatus", "ownerName", "categoryKeyword", "caseKeyword", "dtsKeyword", "resultKeyword"].forEach(key => {
      const value = String(f[key] || "").trim();
      if (value) params[key] = value;
    });
    params.stageId = stage?.id || "";
    return params;
  },

  taskFlowCacheKey(stage, params) {
    return JSON.stringify({ stageId: stage?.id || "", ...params });
  },

  storeTaskFlowPageResult(project, stage, key, result = {}) {
    const rows = result.rows || [];
    const byId = new Map((stage.tasks || []).map(task => [String(task.id || ""), task]));
    rows.forEach(row => {
      const task = row.task;
      if (!task?.id) return;
      const existing = byId.get(String(task.id));
      if (existing) {
        Object.assign(existing, task);
        row.task = existing;
      } else {
        if (!Array.isArray(stage.tasks)) stage.tasks = [];
        stage.tasks.push(task);
      }
    });
    if (result.stats) {
      stage.taskCount = Number(result.stats.totalInStage ?? result.total ?? stage.taskCount ?? 0);
      stage.statusCounts = result.stats.statusCounts || stage.statusCounts || {};
      stage.ownerNames = result.stats.ownerNames || stage.ownerNames || [];
    }
    this._taskFlowPageCache = { key, stageId: stage.id, ...result, rows };
    return this._taskFlowPageCache;
  },

  refreshTaskFlowRegion(project, stage) {
    if (typeof document === "undefined" || typeof document.getElementById !== "function") return false;
    const shell = document.getElementById("taskFlowShell");
    if (!shell || shell.dataset.stageId !== String(stage?.id || "")) return false;
    shell.dataset.pageKey = this.taskFlowCacheKey(stage, this.taskFlowQueryParams(stage));
    shell.innerHTML = this.workspaceTaskFlowContentHtml(project, stage);
    this.updateSelectPlaceholderState?.(shell);
    return true;
  },

  async refreshCurrentTaskFlowPage(project, stage) {
    if (!stage?.id || typeof this.fetchStageTasksPage !== "function") return false;
    const params = this.taskFlowQueryParams(stage);
    const key = this.taskFlowCacheKey(stage, params);
    this._taskFlowLoadingKey = key;
    try {
      const result = await this.fetchStageTasksPage(stage.id, params);
      if (this._taskFlowLoadingKey === key) this._taskFlowLoadingKey = "";
      this.storeTaskFlowPageResult(project, stage, key, result);
      if (this.view.module === "projectWorkspace" && this.view.selectedStageId === stage.id) {
        if (!this.refreshTaskFlowRegion(project, stage)) {
          if (typeof this.renderContent === "function") this.renderContent();
          else this.renderPreserveScroll();
        }
      }
      return true;
    } catch (e) {
      if (this._taskFlowLoadingKey === key) this._taskFlowLoadingKey = "";
      this._taskFlowPageCache = { key, stageId: stage.id, error: e.message, rows: [], page: params.page, pageSize: params.pageSize, total: 0, totalPages: 1 };
      console.error("任务分页刷新失败：", e);
      if (this.view.module === "projectWorkspace" && this.view.selectedStageId === stage.id) {
        if (!this.refreshTaskFlowRegion(project, stage)) {
          if (typeof this.renderContent === "function") this.renderContent();
          else this.renderPreserveScroll();
        }
      }
      return false;
    }
  },

  loadTaskFlowPage(project, stage, key, params) {
    if (!stage?.id || this._taskFlowLoadingKey === key) return;
    this._taskFlowLoadingKey = key;
    this.fetchStageTasksPage(stage.id, params)
      .then(result => {
        this._taskFlowLoadingKey = "";
        this.storeTaskFlowPageResult(project, stage, key, result);
        if (this.view.module === "projectWorkspace" && this.view.selectedStageId === stage.id) {
          this.refreshTaskFlowRegion(project, stage) || this.renderPreserveScroll();
        }
      })
      .catch(e => {
        this._taskFlowLoadingKey = "";
        this._taskFlowPageCache = { key, stageId: stage.id, error: e.message, rows: [] };
        console.error("任务分页加载失败：", e);
        if (this.view.module === "projectWorkspace" && this.view.selectedStageId === stage.id) {
          this.refreshTaskFlowRegion(project, stage) || this.renderPreserveScroll();
        }
      });
  },

  workspaceTaskFlowHtml(project, stage) {
    const params = this.taskFlowQueryParams(stage);
    return `<div id="taskFlowShell" class="task-flow-shell" data-stage-id="${Utils.esc(stage?.id || "")}" data-page-key="${Utils.esc(this.taskFlowCacheKey(stage, params))}">
      ${this.workspaceTaskFlowContentHtml(project, stage)}
    </div>`;
  },

  workspaceTaskFlowContentHtml(project, stage) {
    const f = this.view.taskFlowFilters || {};
    const params = this.taskFlowQueryParams(stage);
    const cacheKey = this.taskFlowCacheKey(stage, params);
    const cached = this._taskFlowPageCache?.key === cacheKey ? this._taskFlowPageCache : null;
    if (!cached) this.loadTaskFlowPage(project, stage, cacheKey, params);
    const localRows = cached ? [] : (this._statePartial ? [] : this.taskRowsForStage(stage));
    const stageTaskTotal = Number(stage.taskCount ?? localRows.length) || 0;
    const pageSize = params.pageSize;
    const total = cached?.total ?? stageTaskTotal;
    const totalPages = cached?.totalPages ?? Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(Math.max(1, cached?.page || params.page), totalPages);
    this.view.taskFlowPage = page;
    const rows = cached?.rows || [];
    const pagerHtml = this.taskFlowPagerHtml(page, totalPages, total, pageSize, { loading: !cached });

    const statusCounts = cached?.stats?.statusCounts || stage.statusCounts || {};
    const ownerNames = cached?.stats?.ownerNames || stage.ownerNames || [];
    const hasServerCounts = cached || Object.keys(statusCounts).length > 0 || typeof stage.taskCount !== "undefined";
    const infos = (cached ? rows : localRows).map(row => this.taskInfoForRow(stage, row));
    const localStatusCounts = cached ? {} : infos.reduce((acc, i) => {
      acc[i.flowStatus] = (acc[i.flowStatus] || 0) + 1;
      return acc;
    }, {});
    const pendingTasks = hasServerCounts ? (statusCounts["待下发"] || 0) : (localStatusCounts["待下发"] || 0);
    const runningTasks = hasServerCounts ? (statusCounts["进行中"] || 0) : (localStatusCounts["进行中"] || 0);
    const blockedTasks = hasServerCounts ? (statusCounts["阻塞中"] || 0) : (localStatusCounts["阻塞中"] || 0);
    const abnormalTasks = hasServerCounts ? (statusCounts["异常终止"] || 0) : (localStatusCounts["异常终止"] || 0);
    const finishedTasks = hasServerCounts ? (statusCounts["正常完成"] || 0) : (localStatusCounts["正常完成"] || 0);
    const totalTasks = cached?.stats?.totalInStage ?? stageTaskTotal;

    const optHtml = (values, cur) => {
      const arr = [...new Set((values || []).map(v => String(v ?? "").trim()).filter(v => v))].sort((a, b) => a.localeCompare(b, 'zh-CN', { numeric: true }));
      return `<option value="">全部</option>` + arr.map(v => `<option value="${Utils.esc(v)}" ${String(cur || "") === v ? 'selected' : ''}>${Utils.esc(v)}</option>`).join("");
    };
    const skuOptions = `<option value="">全部</option>` + (stage.skuNames || []).map((name, idx) => {
      const value = String(idx + 1);
      return `<option value="${value}" ${String(f.sku || "") === value ? "selected" : ""}>${Utils.esc(name || `SKU${idx + 1}`)}</option>`;
    }).join("");
    const loadingRow = !cached
      ? `<tr><td colspan="10" class="empty">正在加载服务器分页数据...</td></tr>`
      : (cached.error ? `<tr><td colspan="10" class="empty">任务分页加载失败：${Utils.esc(cached.error)}</td></tr>` : "");

    return `
      <div class="section-head">
        <div class="task-workbench-title">
          ${this.sectionToggleTriangle('taskFlow')}
          <h2 style="margin:0">任务管理工作台 <span>阶段${Utils.esc(stage.name || "-")}</span></h2>
        </div>
        <div></div>
      </div>
      <div class="section-body">
        <div class="task-flow-summary">
          <div class="task-flow-stat stat-total"><b>${totalTasks}</b><span>总任务数</span></div>
          <div class="task-flow-stat stat-pending"><b>${pendingTasks}</b><span>待下发</span></div>
          <div class="task-flow-stat stat-running"><b>${runningTasks}</b><span>进行中</span></div>
          <div class="task-flow-stat stat-blocked"><b>${blockedTasks}</b><span>阻塞中</span></div>
          <div class="task-flow-stat stat-bad"><b>${abnormalTasks}</b><span>异常终止</span></div>
          <div class="task-flow-stat stat-done"><b>${finishedTasks}</b><span>正常完成</span></div>
        </div>
        <div class="task-filter-bar">
          <div class="task-filter-item filter-sku">
            <label>方案(SKU)</label>
            <select onchange="app.setTaskFlowFilter('sku',this.value)">${skuOptions}</select>
          </div>
          <div class="task-filter-item filter-keyword">
            <label>类别搜索</label>
            <input type="text" value="${Utils.esc(f.categoryKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('categoryKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'categoryKeyword',this.value)">
          </div>
          <div class="task-filter-item filter-keyword">
            <label>用例搜索</label>
            <input type="text" value="${Utils.esc(f.caseKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('caseKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'caseKeyword',this.value)">
          </div>
          <div class="task-filter-item filter-person">
            <label>执行人</label>
            <select onchange="app.setTaskFlowFilter('ownerName',this.value)">${optHtml(ownerNames.length ? ownerNames : infos.map(i => i.ownerName), f.ownerName)}</select>
          </div>
          <div class="task-filter-item filter-status">
            <label>状态</label>
            <select onchange="app.setTaskFlowFilter('flowStatus',this.value)">${optHtml(["待下发", "进行中", "阻塞中", "异常终止", "正常完成"], f.flowStatus)}</select>
          </div>
          <div class="task-filter-item filter-short">
            <label>DTS单号</label>
            <input type="text" value="${Utils.esc(f.dtsKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('dtsKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'dtsKeyword',this.value)">
          </div>
          <div class="task-filter-item filter-result">
            <label>测试结果关键词</label>
            <input type="text" value="${Utils.esc(f.resultKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('resultKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'resultKeyword',this.value)">
          </div>
          <div class="task-filter-actions">
            <button class="btn btn-sm btn-outline" onclick="app.clearTaskFlowFilters()">清空筛选</button>
          </div>
        </div>
        ${pagerHtml}
        <div class="table-wrap task-flow-table"><table>
          <thead>
<tr><th style="font-weight:700">序号</th><th style="font-weight:700">方案(SKU)</th><th style="font-weight:700">类别/用例</th><th style="font-weight:700">执行人</th><th style="font-weight:700">启动/完成时间</th><th style="font-weight:700">样机</th><th style="font-weight:700">测试结果</th><th style="font-weight:700">问题单</th><th style="font-weight:700">状态</th><th style="font-weight:700">操作</th></tr>
          </thead>
          <tbody>${loadingRow || rows.map((row, rowIndex) => {
      const t = row.task;
      const progressId = row.progress?.id || t?.progressId || "";
      const taskId = t?.id || "";
      const sequence = (page - 1) * pageSize + rowIndex + 1;
      const i = this.taskInfoForRow(stage, row);
      const pending = i.flowStatus === "待下发";
      const running = i.flowStatus === "进行中";
      const blocked = i.flowStatus === "阻塞中";
      const sampleCount = i.sampleIds.length;
      const flowStatus = i.flowStatus;
      const logs = t ? this.ensureTaskLogs(t) : [];
      const d = (v) => {
        const t = this.taskDateText(v);
        return t && t !== "-" ? t : "待设置";
      };
      const timeHtml = pending
        ? `<span>计划开始：${Utils.esc(d(i.planStartDate))}</span><span>计划终止：${Utils.esc(d(i.planEndDate))}</span>`
        : `<span>开始：${Utils.esc(d(i.startDate))}</span><span>结束：${Utils.esc(d(i.endDate))}</span>`;
      const actionsHtml = this.taskFlowActionsHtml(project, stage, row);
      const catHtml = `<div class="task-type-cell"><span class="task-type-cat">${Utils.esc(i.category || "-")}</span><span class="task-type-item">${Utils.esc(i.testItem || "-")}</span></div>`;
      const execHtml = i.ownerName
        ? `<div class="task-executor-cell"><span class="task-executor-name">${Utils.esc(i.ownerName)}</span>${i.ownerId ? `<span class="task-executor-id">${Utils.esc(i.ownerId)}</span>` : ""}</div>`
        : `<span class="muted">-</span>`;
      const sampleHtml = `<div class="task-sample-cell"><span class="task-sample-count"><span class="task-sample-count-num">${sampleCount}</span> 台</span>${sampleCount && taskId ? `<button class="btn btn-sm btn-outline" onclick="app.showTaskSamples('${project.id}','${stage.id}','${taskId}')">查看</button>` : ""}</div>`;
      return `
              <tr>
                <td class="task-seq-cell">${sequence}</td>
                <td class="task-sku-cell">${Utils.esc(i.sku)}</td>
                <td class="compact-cell">${catHtml}</td>
                <td>${execHtml}</td>
                <td class="task-time-cell">${timeHtml}</td>
                <td>${sampleHtml}</td>
                <td class="task-issue-cell">${t ? this.taskIssueSummaryHtml(project, stage, t) : "-"}</td>
                <td class="task-issue-record-cell" onclick="${taskId ? `app.openTaskIssueRecordModal('${project.id}','${stage.id}','${taskId}')` : ''}" style="${taskId ? 'cursor:pointer' : ''}">${t ? this.taskIssueRecordHtml(t, project, stage) : '<span class="path">-</span>'}</td>
                <td><span class="badge ${this.taskStatusBadgeClass(flowStatus)}">${Utils.esc(flowStatus)}</span></td>
                <td class="op-cell task-op-cell-new">${actionsHtml}</td>
              </tr>`;
    }).join("") || `<tr><td colspan="10" class="empty">暂无任务。请点击"新增任务"，从阶段配置的测试池中选择测试项。</td></tr>`}
      ${rows.length ? `<tr class="task-flow-buffer-row" aria-hidden="true"><td colspan="10"></td></tr>` : ""}</tbody>
        </table></div>
        ${total > pageSize ? pagerHtml : ""}
        <div class="task-add-footer">
          <button class="task-add-main" onclick="app.openAddTasksFromPoolModal()">
            <span class="row-action-btn row-add-btn"></span>
            <span>新增任务</span>
          </button>
        </div>
      </div>`;
  },

  taskMoreMenuHtml(projectId, stageId, taskId, logs) {
    if (!taskId) return "";
    const logText = `日志${(logs || []).length ? `(${logs.length})` : ""}`;
    return `
      <div class="task-more-menu">
        <button type="button" class="btn btn-sm btn-outline task-more-trigger" onclick="event.stopPropagation();app.handleTaskOpMenuClick(this.parentElement)" title="更多">...</button>
        <div class="task-more-panel">
          <button type="button" class="task-more-item" onclick="event.stopPropagation();app.closeTaskOpMenus();app.showTaskLogs('${projectId}','${stageId}','${taskId}')">${logText}</button>
          <button type="button" class="task-more-item danger" onclick="event.stopPropagation();app.closeTaskOpMenus();app.deleteTask('${taskId}')">🗑 删除</button>
        </div>
      </div>`;
  },

  taskDeleteImpactHtml(project, stage, task) {
    if (!project || !stage || !task) return "";
    const executed = this.isTaskExecuted(task);
    const flowStatus = this.taskFlowStatus(task);
    const sampleCount = (task.sampleIds || []).length;
    const removedCount = (task.removedSampleRecords || []).length;
    const logCount = (task.logs || []).length;
    const totalSampleRefs = sampleCount + removedCount;

    const execBadge = executed
      ? `<span class="badge status-running">已执行</span>`
      : `<span class="badge status-pending">未执行</span>`;

    let impactDesc = "";
    if (!executed) {
      impactDesc = `<li><b>未执行任务</b><span>会从任务管理中物理删除，不会保留在归档中。</span></li>
        ${sampleCount ? `<li><b>已分配样机</b><span>${sampleCount} 台样机会被释放为闲置状态，不会删除样机档案。</span></li>` : ""}
        <li><b>任务日志</b><span>${logCount} 条日志会随任务记录一起删除。</span></li>`;
    } else if (flowStatus === "进行中" || flowStatus === "阻塞中") {
      impactDesc = `<li><b>进行中/阻塞中任务</b><span>会从任务管理中隐藏并归档，历史数据继续保留。</span></li>
        ${totalSampleRefs ? `<li><b>关联样机（含退出样机）</b><span>共 ${totalSampleRefs} 台，会按其他未完成任务占用情况自动释放，样机履历继续保留。</span></li>` : ""}
        <li><b>任务日志和样机快照</b><span>${logCount} 条日志继续保留。</span></li>
        <li><b>不会删除样机档案</b><span>样机的外观照片、CT 数据、问题表不受影响。</span></li>`;
    } else {
      impactDesc = `<li><b>已完成任务</b><span>会从任务管理中隐藏并归档，历史数据继续保留。</span></li>
        ${totalSampleRefs ? `<li><b>关联样机（含退出样机）</b><span>共 ${totalSampleRefs} 台，会按其他未完成任务占用情况自动释放。</span></li>` : ""}
        <li><b>任务日志、样机履历、样机快照</b><span>继续保留，不会丢失历史。</span></li>
        <li><b>不会删除样机档案</b><span>样机的外观照片、CT 数据、问题表不受影响。</span></li>`;
    }

    return `<div class="destroy-impact">
      <div class="destroy-impact-title">危险影响确认</div>
      <ul>
        <li><b>任务</b><span>${Utils.esc(project.name || "-")} / ${Utils.esc(stage.name || "-")} / ${Utils.esc(task.testItem || "-")}</span></li>
        <li><b>当前状态</b>${execBadge} <span>${Utils.esc(flowStatus)}</span></li>
        <li><b>涉及样机</b><span>${totalSampleRefs} 台（当前分配 ${sampleCount} 台${removedCount ? `，历史退出 ${removedCount} 台` : ""}）</span></li>
        <li><b>任务日志</b><span>${logCount} 条</span></li>
        ${impactDesc}
      </ul>
    </div>`;
  },

  confirmTaskDeleteKeyword(title, message, onConfirm, detailsHtml) {
    this.showModal(title, `
      <div class="delete-confirm">
        <p>${Utils.esc(message)}</p>
        ${detailsHtml || ""}
        <label>请输入 <strong>DELETE</strong> 确认删除：</label>
        <input id="deleteKeywordInput" autocomplete="off" autofocus>
        <div id="deleteKeywordError" class="delete-confirm-error" style="display:none">请输入 DELETE 后才能继续。</div>
      </div>
    `, () => {
      const input = document.getElementById("deleteKeywordInput");
      const error = document.getElementById("deleteKeywordError");
      if ((input?.value || "") !== "DELETE") {
        if (error) error.style.display = "block";
        input?.focus();
        return true;
      }
      return onConfirm?.();
    }, "确认删除", { okClass: "btn btn-danger" });
    document.getElementById("deleteKeywordInput")?.focus();
  },

  taskFlowActionsHtml(project, stage, row) {
    const t = row.task;
    const taskId = t?.id || "";
    const progressId = row.progress?.id || t?.progressId || "";
    const i = this.taskInfoForRow(stage, row);
    const flowStatus = i.flowStatus;
    const sampleCount = i.sampleIds.length;
    const canStart = taskId && sampleCount > 0 && t?.owner && t?.planStartDate && t?.planEndDate;
    const logs = t ? this.ensureTaskLogs(t) : [];
    const pid = project.id;
    const sid = stage.id;

    const btn = (label, cls, action, disabled = false, title = "") =>
      `<button class="btn btn-sm ${cls}" ${disabled ? "disabled" : ""} ${title ? `title="${Utils.esc(title)}"` : ""} onclick="${action}">${label}</button>`;

    const configBtn = taskId
      ? `<button class="btn btn-sm btn-outline task-op-config" type="button"
           onclick="event.stopPropagation();app.openTaskConfigPanel('${pid}','${sid}','${progressId}','${taskId}','plan')">配置</button>`
      : "";

    const moreMenuHtml = this.taskMoreMenuHtml(pid, sid, taskId, logs);

    let visibleHtml = "";

    if (flowStatus === "待下发") {
      visibleHtml = (canStart
        ? btn("启动", "btn-start", `app.startTask('${pid}','${sid}','${taskId}')`)
        : `<span class="task-start-disabled-tip" data-tooltip="先配置后启动">${btn("启动", "btn-start", "", true)}</span>`)
        + configBtn;
    }

    if (flowStatus === "进行中") {
      visibleHtml = btn("结果", "", `app.uploadResult('${pid}','${sid}','${taskId}')`)
        + btn("阻塞", "btn-warn", `app.blockTask('${pid}','${sid}','${taskId}')`)
        + btn("变更", "btn-outline", `app.tempChangeTask('${pid}','${sid}','${taskId}')`);
    }

    if (flowStatus === "阻塞中") {
      visibleHtml = btn("结果", "", `app.uploadResult('${pid}','${sid}','${taskId}')`)
        + btn("重启", "btn-start", `app.startTask('${pid}','${sid}','${taskId}')`)
        + btn("变更", "btn-outline", `app.tempChangeTask('${pid}','${sid}','${taskId}')`);
    }

    if (flowStatus === "正常完成" || flowStatus === "异常终止") {
      visibleHtml = btn("结果", "", `app.uploadResult('${pid}','${sid}','${taskId}')`);
    }

    return `<div class="task-op-group"><div class="task-op-actions">${visibleHtml}${moreMenuHtml}</div></div>`;
  },

  taskSampleTaskFlowStatus(task, sampleId, entry) {
    // 1. 优先读取未结束前的草稿结果
    const draftItem = (task.resultDraft?.samples || []).find(x => (x.sampleId || x.sid) === sampleId);
    if (draftItem?.destination) return draftItem.destination;

    // 2. 再读取本任务 resultUploads 中最后一次保存的该样机 destination
    const uploads = Array.isArray(task.resultUploads) ? task.resultUploads : [];
    for (let i = uploads.length - 1; i >= 0; i--) {
      const item = (uploads[i].samples || []).find(x => (x.sampleId || x.sid) === sampleId);
      if (item?.destination) return item.destination;
    }

    // 3. 如果是已经被临时变更退出的样机，但没有结果上传记录
    if (entry?.state === "removed") return "变更退出";

    // 4. 根据任务当前流程状态推断（不读样机档案 status）
    const flow = this.taskFlowStatus(task);
    if (flow === "进行中") return "测试中";
    if (flow === "阻塞中") return "在位等待";
    if (flow === "待执行" || flow === "待下发") return "在位等待";

    return "未设置";
  },

  showTaskSamples(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    const entries = this.taskResultSampleEntries(t);
    const activeCount = entries.filter(x => x.state !== "removed").length;
    const removedCount = entries.length - activeCount;
    const taskProblems = this.taskFailureProblemsBySample(p, s, t);
    const rows = entries.map(entry => {
      const id = entry.sampleId;
      const found = this.findSample(id);
      const snapshot = t.sampleSnapshots?.[id] || null;
      const sample = found?.sample || {};
      const info = this.taskSampleIdentityInfo(id, snapshot);
      const displayName = this.taskSampleArchiveName(id, snapshot);
      const hasProblem = found ? this.sampleHasProblem(sample) : false;
      // 身份号优先级：SN > IMEI > 主板SN
      const identity = info.sn !== "-" ? `SN:${Utils.esc(info.sn)}`
        : info.imei !== "-" ? `IMEI:${Utils.esc(info.imei)}`
        : info.boardSn !== "-" ? `主板SN:${Utils.esc(info.boardSn)}`
        : "身份号未录入";
      // 已测项目
      const testedItems = this.sampleTestedItemNames(id);
      const testedText = testedItems.length === 0 ? "-"
        : testedItems.length <= 2
          ? Utils.esc(testedItems.join(" / "))
          : `${Utils.esc(testedItems.slice(0, 3).join(" / "))} 等 ${testedItems.length} 项`;
      // 问题：合并档案问题 + 任务范围内问题，去重
      const archiveProblems = found ? this.sampleProblemRecords(sample).map(r => r.description) : [];
      const taskProblemsForSample = [...(taskProblems.get(id) || [])];
      const allProblems = [...new Set([...archiveProblems, ...taskProblemsForSample])];
      const problemHtml = allProblems.length === 0
        ? `<span class="task-sample-problem-none">-</span>`
        : allProblems.length === 1
          ? `<span class="task-sample-problem-text" title="${Utils.esc(allProblems[0])}">${Utils.esc(allProblems[0].length > 40 ? allProblems[0].slice(0, 40) + "..." : allProblems[0])}</span>`
          : `<span class="task-sample-problem-count" title="${Utils.esc(allProblems.join("\n"))}">${allProblems.length} 项问题</span>`;
      // 状态徽章
      const faultBadge = hasProblem
        ? `<span class="badge sample-fault-badge has-fault">有故障</span>`
        : `<span class="badge sample-fault-badge no-fault">无故障</span>`;
      const taskFlowStatus = this.taskSampleTaskFlowStatus(t, id, entry);
      const flowBadge = `<span class="badge s-${Utils.esc(taskFlowStatus)}">${Utils.esc(taskFlowStatus)}</span>`;
      // 在测 / 已退出
      const relationBadge = entry.state === "removed"
        ? `<span class="task-result-sample-state removed">变更退出样机</span>`
        : `<span class="task-result-sample-state active">当前测试样机</span>`;
      // 退出详情行
      const removedDetail = entry.state === "removed"
        ? `<div class="task-sample-removed-detail"><span>退出：${Utils.esc(entry.removedAt || "-")}</span>${entry.reason ? `<span> · ${Utils.esc(entry.reason)}</span>` : ""}</div>`
        : "";
      // 身份标识（可点击 / 已销毁不可点）
      const identityEl = found
        ? `<span class="task-sample-row-id" onclick="event.stopPropagation();app.openSampleReadonly('${Utils.esc(id)}')" title="查看样机详情">${identity}</span>`
        : `<span class="task-sample-row-id disabled" title="样机档案已销毁">${identity}</span>`;
      return `<div class="task-sample-row ${entry.state === "removed" ? "is-removed" : ""}">
        <div class="task-sample-row-info">
          ${identityEl}
          <span class="task-sample-row-archive">${Utils.esc(displayName)}</span>
        </div>
        <div class="task-sample-row-tested" title="${Utils.esc(testedText)}">
          <span class="task-sample-row-label">已测</span>
          <span>${testedText}</span>
        </div>
        <div class="task-sample-row-problems">
          <span class="task-sample-row-label">问题</span>
          ${problemHtml}
        </div>
        <div class="task-sample-row-status">
          ${faultBadge}
          ${flowBadge}
          ${relationBadge}
        </div>
        ${removedDetail}
      </div>`;
    }).join("");
    this.showModal("任务样机清单", `
      <div class="task-sample-context">项目：${Utils.esc(p?.name || "-")}；阶段：${Utils.esc(s?.name || "-")}；任务：${Utils.esc(t.testItem || "-")}；当前 ${activeCount} 台${removedCount ? `；已退出测试 ${removedCount} 台` : ""}</div>
      <div class="task-sample-row-list">${rows || `<div class="empty">暂无关联样机。</div>`}</div>
    `, () => false, "关闭", { className: "task-sample-modal" });
  },


  sampleTestedItemNames(sampleId) {
    const names = new Set();
    (this.data.projects || []).forEach(project => {
      (project.stages || []).forEach(stage => {
        (stage.tasks || []).forEach(task => {
          if (!task.sampleIds || !task.sampleIds.includes(sampleId)) return;
          if (task.status === "待下发") return;
          const name = String(task.testItem || "").trim();
          if (name) names.add(name);
        });
      });
    });
    return [...names];
  },

});
