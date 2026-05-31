
/* ========================================
   数字治理平台 V7 - 样机档案池模块
   样机档案与照片文件分离存储
   ======================================== */

Object.assign(app, {

  renderSamples() {
    const content = document.getElementById("content");
    const cat = this.data.sampleLibrary.categories.find(c => c.id === this.view.selectedCategoryId);

    if (!cat) {
      const categoryCards = this.data.sampleLibrary.categories.map(c => `
          <div class="card sample-card" style="padding-bottom:28px" onclick="app.openCategory('${c.id}')">
            <h3 style="margin:0 0 8px">样机池：${Utils.esc(c.name)}<button type="button" class="sample-card-edit-btn" style="vertical-align:baseline;margin-left:4px" onclick="event.stopPropagation();app.editSampleCategory('${c.id}')" title="编辑样机池">✎</button></h3>
            <div class="path">备注说明：${Utils.esc(c.description || "无")}</div>
            ${this.sampleCategoryStatsHtml(c)}
            <button type="button" class="sample-card-destroy-btn" onclick="event.stopPropagation();app.deleteSampleCategory('${c.id}')" title="档案销毁">🗑</button>
          </div>`).join("");
      content.innerHTML = `
        <div class="grid sample-category-grid">${categoryCards}
          <button type="button" class="sample-category-add-card" onclick="app.addSampleCategory()">
            <span class="sample-category-add-main">
              <span class="row-action-btn row-add-btn"></span>
              <span>新增样机池</span>
            </span>
            <span class="sample-category-add-help">
              <span>1. 可创建一个样机档案池，每个样机池相互独立；</span>
              <span>2. 样机池里的样机可被项目管理选中作为测试样机</span>
            </span>
          </button>
        </div>`;
      return;
    }

    const samples = (cat.samples || []).filter(s => {
      const kw = this.view.sampleKeyword.trim().toLowerCase();
      if (kw) {
        const direct = [s.sampleNo, s.sn, s.imei, s.boardSn, s.model, s.config, s.tag,
          s.schemeNo, s.sourceStageName, s.sourceSkuName, s.notes, s.owner, s.borrower, s.location
        ].filter(Boolean).join(" ").toLowerCase();
        if (direct.includes(kw)) return true;
        const problems = (s.problemRecords || []).map(r => r.description || "").filter(Boolean).join(" ");
        if (problems.toLowerCase().includes(kw)) return true;
        const logs = (s.logs || []).map(l => [l.testItem, l.projectName, l.stageName].filter(Boolean).join(" ")).join(" ");
        if (logs.toLowerCase().includes(kw)) return true;
        return false;
      }
      return true;
    }).filter(s =>
      (!this.view.sampleStatusFilter || this.sampleEffectiveStatus(s) === this.view.sampleStatusFilter)
      && (!this.view.sampleOwnerFilter || (s.owner || "").includes(this.view.sampleOwnerFilter))
      && (!this.view.sampleBorrowerFilter || (s.borrower || "").includes(this.view.sampleBorrowerFilter))
    );

    content.innerHTML = `
      <div class="card sample-pool-head">
        <div class="sample-pool-left">
          <div>
            <b class="sample-pool-code">${Utils.esc(cat.name)}</b>
            <span class="path sample-pool-desc">${Utils.esc(cat.description || "")}</span>
          </div>
          <div class="sample-pool-actions">
            <button class="btn sample-pool-main-btn" onclick="app.downloadSampleTemplate()">下载批量导入模板</button>
            <button class="btn btn-purple sample-pool-main-btn" onclick="app.importSampleBatch('${cat.id}')">批量新增</button>
          </div>
        </div>
      </div>
      <div class="card" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <input style="max-width:280px" placeholder="样机详情 / 失效 / 履历搜索（回车搜索）" value="${Utils.esc(this.view.sampleKeyword)}" oninput="app.view.sampleKeyword=this.value" onkeydown="if(event.key==='Enter'){app.view.sampleKeyword=this.value;app.renderSamples()}">
        <select style="max-width:170px" onchange="app.view.sampleStatusFilter=this.value;app.renderSamples()">
          <option value="">全部状态</option>
          ${this.constants.sampleStatuses.map(x => `<option ${this.view.sampleStatusFilter === x ? 'selected' : ''}>${x}</option>`).join("")}
        </select>
        <select style="max-width:160px" onchange="app.view.sampleOwnerFilter=this.value;app.renderSamples()">
          <option value="">全部挂账人</option>
          ${[...new Set((cat.samples||[]).map(s=>s.owner).filter(Boolean))].sort().map(x=>`<option ${this.view.sampleOwnerFilter===x?'selected':''}>${Utils.esc(x)}</option>`).join("")}
        </select>
        <select style="max-width:160px" onchange="app.view.sampleBorrowerFilter=this.value;app.renderSamples()">
          <option value="">全部持有人</option>
          ${[...new Set((cat.samples||[]).map(s=>s.borrower).filter(Boolean))].sort().map(x=>`<option ${this.view.sampleBorrowerFilter===x?'selected':''}>${Utils.esc(x)}</option>`).join("")}
        </select>
        <button type="button" class="btn btn-sm btn-outline" onclick="app.view.sampleKeyword='';app.view.sampleStatusFilter='';app.view.sampleOwnerFilter='';app.view.sampleBorrowerFilter='';app.renderSamples()">清空</button>
        <span class="path">显示 ${samples.length} / ${(cat.samples || []).length} 台</span>
      </div>
      <div class="grid-small sample-pool-grid">
        <button type="button" class="sample-add-card" onclick="app.addSample('${cat.id}')">
          <span class="row-action-btn row-add-btn"></span>
          <span>新增样机</span>
        </button>
        ${samples.length ? samples.map(s => this.sampleCardHtml(s)).join("") : `<div class="empty sample-empty-hint">暂无样机</div>`}
      </div>`;
  },

  sampleCardHtml(s) {
    const status = this.sampleEffectiveStatus(s);
    const busy = ["在位等待", "已退库", "取走分析", "已借出", "测试中"].includes(status);
    const bad = ["故障"].includes(status);
    return `<div class="card sample-card ${busy ? 'status-busy' : bad ? 'status-bad' : 'status-idle'}" onclick="app.openSampleDetail('${s.id}')">
      <div style="display:flex;justify-content:space-between;gap:8px"><b>${Utils.esc(this.sampleDisplayCode(s))}</b><span class="badge s-${Utils.esc(status)}">${Utils.esc(status)}</span></div>
      <div class="path" style="margin-top:8px">SN：${Utils.esc(s.sn || "NA")}</div>
      <div class="path">IMEI：${Utils.esc(s.imei || "NA")}</div>
      <div class="path">主板SN：${Utils.esc(s.boardSn || "NA")}</div>
      <div class="path">阶段：${Utils.esc(s.sourceStageName || "-")} · ${Utils.esc(s.sourceSkuName || "-")}</div>
      ${s.tag ? `<div class="path">标签：${Utils.esc(s.tag)}</div>` : ''}
      <div class="path">问题：${Utils.esc((s.problemRecords || []).map(r => r.description || r).filter(Boolean).join(" / ") || "-")}</div>
      <button type="button" class="sample-card-destroy-btn" onclick="event.stopPropagation();app.destroySample('${s.id}')" title="档案销毁">🗑</button>
    </div>`;
  },

  sampleDisplayCode(s) {
    const sn = String(s?.sn || "").trim();
    const imei = String(s?.imei || "").trim();
    const boardSn = String(s?.boardSn || "").trim();
    // 末 6 位足够避免大多数串号重码；同时仍保持简洁
    if (sn) return `SN#${sn.slice(-6)}`;
    if (imei) return `IMEI#${imei.slice(-6)}`;
    if (boardSn) return `主板SN#${boardSn.slice(-6)}`;
    return "未录入SN/IMEI/主板SN";
  },

  sampleCategoryStatsHtml(category) {
    const samples = category.samples || [];
    const count = status => samples.filter(s => this.sampleEffectiveStatus(s) === status).length;
    const items = this.constants.sampleStatuses.map(status => ({
        label: status,
        value: count(status),
        cls: this.sampleStatusStatClass(status)
      }));
    const faultCount = samples.filter(s => this.sampleHasProblem(s)).length;
    items.push({ label: "故障", value: faultCount, cls: "stat-bad" });

    // 第一行：测试中、闲置、在位等待
    const row1 = items.filter(item => ["测试中", "闲置", "在位等待"].includes(item.label));
    // 第二行：故障、取走分析、已退库
    const row2Order = ["故障", "取走分析", "已退库"];
    const row2 = row2Order.map(label => items.find(item => item.label === label)).filter(Boolean);

    return `
      <div class="sample-category-total">
        <b>${samples.length}</b>
        <span>总数</span>
      </div>
      <div class="sample-category-stats">${row1.map(item => `
        <div class="sample-category-stat ${item.cls}">
          <b>${item.value}</b>
          <span>${Utils.esc(item.label)}</span>
        </div>`).join("")}</div>
      <div class="sample-category-stats sample-category-stats-row2">${row2.map(item => `
        <div class="sample-category-stat ${item.cls}">
          <b>${item.value}</b>
          <span>${Utils.esc(item.label)}</span>
        </div>`).join("")}</div>`;
  },

  sampleStatusStatClass(status) {
    if (status === "闲置") return "stat-done";
    if (status === "测试中") return "stat-running";
    if (status === "在位等待") return "stat-pending";
    if (status === "故障") return "stat-bad";
    if (["已退库", "取走分析", "已借出"].includes(status)) return "stat-blocked";
    return "stat-total";
  },

  // ---- 类别 CRUD ----
  sampleCategoryNameExists(name, excludeId = "") {
    const normalized = String(name || "").trim().toLowerCase();
    if (!normalized) return false;
    return (this.data.sampleLibrary.categories || []).some(c =>
      c.id !== excludeId && String(c.name || "").trim().toLowerCase() === normalized
    );
  },

  addSampleCategory() {
    this.showModal("新建样机池", `
      <div class="form-group"><label class="req">代号</label><input id="catName"></div>
      <div class="form-group"><label>说明</label><textarea id="catDesc" placeholder="如 新一代小内折手机 / TSE是张三 / 此为特稿保密项目"></textarea></div>
    `, () => {
      this.clearFieldValidationMarks();
      const nameEl = document.getElementById("catName");
      const name = nameEl.value.trim();
      if (!name) { this.markFieldInvalid(nameEl, "代号不能为空"); return true; }
      if (this.sampleCategoryNameExists(name)) { this.markFieldInvalid(nameEl, `样机池名称"${name}"已存在，不能重复创建。`); return true; }
      const c = { id: Utils.id("cat_"), name, description: document.getElementById("catDesc").value.trim(), createdAt: Utils.now(), samples: [] };
      this.data.sampleLibrary.categories.push(c);
      this.view.selectedCategoryId = null;
      this.save(); this.renderSamples();
    });
  },

  editSampleCategory(id) {
    const c = this.data.sampleLibrary.categories.find(x => x.id === id);
    if (!c) return;
    this.showModal("编辑样机池", `
      <div class="form-group"><label class="req">代号</label><input id="catName" value="${Utils.esc(c.name)}"></div>
      <div class="form-group"><label>说明</label><textarea id="catDesc" placeholder="如 新一代小内折手机 / TSE是张三 / 此为特稿保密项目">${Utils.esc(c.description || "")}</textarea></div>
    `, () => {
      this.clearFieldValidationMarks();
      const nameEl = document.getElementById("catName");
      const name = nameEl.value.trim();
      if (!name) { this.markFieldInvalid(nameEl, "代号不能为空"); return true; }
      if (this.sampleCategoryNameExists(name, c.id)) { this.markFieldInvalid(nameEl, `样机池名称"${name}"已存在，不能重复命名。`); return true; }
      c.name = name;
      c.description = document.getElementById("catDesc").value.trim();
      this.save(); this.renderSamples();
    });
  },

  deleteSampleCategory(id) {
    const c = this.data.sampleLibrary.categories.find(x => x.id === id);
    if (!c) return;
    const impact = this.collectSampleCategoryDestroyImpact(c);
    this.confirmDeleteKeyword(
      "档案销毁",
      "档案销毁会物理删除该样机池、池内样机、照片/CT文件、问题表和样机事件数据。此操作不可恢复。",
      () => {
        this.applySampleCategoryDestroyImpact(c, impact);
        this.data.sampleLibrary.categories = this.data.sampleLibrary.categories.filter(x => x.id !== id);
        this.view.selectedCategoryId = null;
        this.save(); this.renderSamples();
        Utils.toast("样机池档案已销毁，关联任务已处理。");
      },
      this.sampleCategoryDestroyImpactHtml(impact)
    );
  },

  collectSampleCategoryDestroyImpact(category) {
    const samples = category?.samples || [];
    const sampleIds = new Set(samples.map(s => s.id).filter(Boolean));
    const sampleName = id => {
      const sample = samples.find(s => s.id === id) || this.findSample(id)?.sample;
      return sample ? this.sampleDisplayCode(sample) : id;
    };
    const hasArchive = samples.filter(s =>
      this.sampleHasArchiveData(s) ||
      (s.problemRecords || []).length ||
      (s.initialResults || []).length ||
      String(s.initialResult || "").trim()
    ).length;
    const runningOrBlocked = [];
    const pending = [];
    (this.data.projects || []).forEach(project => (project.stages || []).forEach(stage => (stage.tasks || []).forEach(task => {
      if (!task || task.archived || this.isTaskCompleted(task)) return;
      const matchedIds = (task.sampleIds || []).filter(id => sampleIds.has(id));
      if (!matchedIds.length) return;
      const flow = this.taskFlowStatus(task);
      const item = {
        project, stage, task, flow,
        matchedIds,
        matchedNames: matchedIds.map(sampleName),
        allSampleIds: [...(task.sampleIds || [])],
        allSampleNames: (task.sampleIds || []).map(sampleName)
      };
      if (["进行中", "阻塞中"].includes(flow)) runningOrBlocked.push(item);
      else pending.push(item);
    })));
    return {
      categoryName: category?.name || "未命名样机池",
      sampleCount: samples.length,
      archiveCount: hasArchive,
      runningOrBlocked,
      pending
    };
  },

  sampleCategoryDestroyImpactHtml(impact) {
    const taskLine = item => `
      <li>
        <b>${Utils.esc(item.project.name)} / ${Utils.esc(item.stage.name)} / ${Utils.esc(item.task.testItem || "-")}</b>
        <span>${Utils.esc(item.flow)}；涉及 ${item.matchedNames.map(x => Utils.esc(x)).join("、")}</span>
      </li>`;
    return `<div class="destroy-impact">
      <div class="destroy-impact-title">危险影响确认</div>
      <ul>
        <li><b>将删除样机池：</b><span>${Utils.esc(impact.categoryName)}，共 ${impact.sampleCount} 台样机。</span></li>
        <li><b>档案数据：</b><span>${impact.archiveCount} 台样机含履历/照片/CT/问题表，销毁后会一起物理删除。</span></li>
        <li><b>进行中/阻塞中任务：</b><span>${impact.runningOrBlocked.length} 个任务会被自动设置为"异常终止"，任务样机列表会被清空。</span></li>
        <li><b>未启动任务：</b><span>${impact.pending.length} 个未启动任务会移除被销毁样机，并保留任务等待重新分配。</span></li>
      </ul>
      ${impact.runningOrBlocked.length ? `<div class="destroy-impact-subtitle">会异常终止的任务</div><ul>${impact.runningOrBlocked.map(taskLine).join("")}</ul>` : ""}
      ${impact.pending.length ? `<div class="destroy-impact-subtitle">会移除样机的未启动任务</div><ul>${impact.pending.map(taskLine).join("")}</ul>` : ""}
    </div>`;
  },

  applySampleCategoryDestroyImpact(category, impact) {
    const samples = category?.samples || [];
    const destroyedIds = new Set(samples.map(s => s.id).filter(Boolean));
    const sampleName = id => {
      const sample = samples.find(s => s.id === id) || this.findSample(id)?.sample;
      return sample ? this.sampleDisplayCode(sample) : id;
    };
    const today = Utils.today();
    const now = Utils.now();
    (impact.runningOrBlocked || []).forEach(item => {
      const task = item.task;
      const oldFlow = item.flow;
      const originalSampleIds = [...(task.sampleIds || [])];
      const destroyedNames = item.matchedNames.join("、") || "样机";
      const reason = `${destroyedNames} 样机档案被销毁，任务无法继续。`;
      originalSampleIds.filter(id => !destroyedIds.has(id)).forEach(id => {
        if (this.findSample(id)) {
          const otherUsage = this.activeTaskUsagesForSample(id, task.id)[0];
          this.changeSampleStatus(id, otherUsage ? this.statusForOpenTaskUsage(otherUsage.task) : "闲置", {
            user: "管理员",
            source: "样机池档案销毁",
            reason: otherUsage ? `关联任务异常终止，样机仍被其他任务占用；${reason}` : `关联任务异常终止，释放样机；${reason}`,
            projectId: otherUsage?.project?.id || item.project.id,
            stageId: otherUsage?.stage?.id || item.stage.id,
            taskId: otherUsage?.task?.id || task.id,
            testItem: otherUsage?.task?.testItem || task.testItem,
            forceLog: true
          });
        }
      });
      task.sampleIds = [];
      task.status = "异常终止";
      task.completed = true;
      task.completionType = "异常终止";
      task.completedAt = now;
      task.endDate = today;
      task.resultDate = today;
      task.latestResult = "Fail";
      const progress = (item.stage.progress || []).find(p => p.id === task.progressId);
      if (progress) {
        progress.status = "Fail";
        progress.endDate = today;
        progress.issue = reason;
        progress.sampleIds = [];
      }
      this.addTaskLog(task, "样机池档案销毁", {
        user: "管理员",
        reason,
        fromStatus: oldFlow,
        toStatus: "异常终止",
        detail: `已清空任务样机：${originalSampleIds.map(sampleName).join("、") || "-"}`
      });
    });
    (impact.pending || []).forEach(item => {
      const task = item.task;
      const before = [...(task.sampleIds || [])];
      task.sampleIds = before.filter(id => !destroyedIds.has(id));
      const progress = (item.stage.progress || []).find(p => p.id === task.progressId);
      if (progress) progress.sampleIds = (progress.sampleIds || []).filter(id => !destroyedIds.has(id));
      this.addTaskLog(task, "样机池档案销毁", {
        user: "管理员",
        reason: `${item.matchedNames.join("、")} 样机档案被销毁，已从未启动任务中移除。`,
        fromStatus: item.flow,
        toStatus: this.taskFlowStatus(task),
        detail: `任务样机：${before.map(sampleName).join("、") || "-"} → ${(task.sampleIds || []).map(sampleName).join("、") || "空"}`
      });
    });
  },

  sampleHasArchiveData(sample) {
    return !!(
      (sample?.logs || []).length ||
      (sample?.photos || []).length ||
      (sample?.ctData || []).length ||
      (sample?.ctFiles || []).length
    );
  },

  canDestroySample(sample) {
    if (!sample) return { ok: false, reason: "样机不存在。" };
    return { ok: true, reason: "" };
  },

  collectSingleSampleDestroyImpact(sample) {
    const sampleId = sample?.id;
    if (!sampleId) return { runningOrBlocked: [], pending: [], completed: [], sample };
    const runningOrBlocked = [];
    const pending = [];
    const completedTaskRefs = [];
    (this.data.projects || []).forEach(project => (project.stages || []).forEach(stage => (stage.tasks || []).forEach(task => {
      if (!task || task.archived) return;
      if (!(task.sampleIds || []).includes(sampleId) && !(task.removedSampleRecords || []).some(item => item?.sampleId === sampleId)) return;
      const flow = this.taskFlowStatus(task);
      const item = { project, stage, task, flow };
      if (this.isTaskCompleted(task)) completedTaskRefs.push(item);
      else if (["进行中", "阻塞中"].includes(flow)) runningOrBlocked.push(item);
      else pending.push(item);
    })));
    return { runningOrBlocked, pending, completed: completedTaskRefs, sample };
  },

  singleSampleDestroyImpactHtml(impact) {
    const name = impact.sample ? this.sampleDisplayCode(impact.sample) : "样机";
    const archiveCount = impact.sample && this.sampleHasArchiveData(impact.sample) ? 1 : 0;
    const runningCount = (impact.runningOrBlocked || []).length;
    const pendingCount = (impact.pending || []).length;
    const completedCount = (impact.completed || []).length;
    const taskLine = item => `<li><b>${Utils.esc(item.project.name)} / ${Utils.esc(item.stage.name)} / ${Utils.esc(item.task.testItem || "-")}</b><span>${Utils.esc(item.flow)}</span></li>`;
    return `<div class="destroy-impact">
      <div class="destroy-impact-title">危险影响确认</div>
      <ul>
        <li><b>将销毁样机：</b><span>${Utils.esc(name)}${archiveCount ? "，含履历/照片/CT/问题表" : ""}。</span></li>
        ${runningCount ? `<li><b>进行中/阻塞中任务：</b><span>${runningCount} 个任务会被自动设置为"异常终止"，任务样机列表会被清空。</span></li>` : ""}
        ${pendingCount ? `<li><b>未启动任务：</b><span>${pendingCount} 个未启动任务会移除该样机，并保留任务等待重新分配。</span></li>` : ""}
        ${completedCount ? `<li><b>已完成任务：</b><span>${completedCount} 个已完成任务不受影响，依赖样机快照继续展示历史。</span></li>` : ""}
        ${!runningCount && !pendingCount && !completedCount ? `<li><b>无关联任务</b><span>该样机未关联任何任务。</span></li>` : ""}
      </ul>
      ${runningCount ? `<div class="destroy-impact-subtitle">会异常终止的任务</div><ul>${(impact.runningOrBlocked || []).map(taskLine).join("")}</ul>` : ""}
      ${pendingCount ? `<div class="destroy-impact-subtitle">会移除样机的未启动任务</div><ul>${(impact.pending || []).map(taskLine).join("")}</ul>` : ""}
      ${completedCount ? `<div class="destroy-impact-subtitle">已有快照的已完成任务</div><ul>${(impact.completed || []).map(taskLine).join("")}</ul>` : ""}
    </div>`;
  },

  applySingleSampleDestroyImpact(sample, impact) {
    const sampleId = sample.id;
    const destroyedName = this.sampleDisplayCode(sample);
    const today = Utils.today();
    const now = Utils.now();
    // 处理进行中/阻塞中任务 → 异常终止
    (impact.runningOrBlocked || []).forEach(item => {
      const task = item.task;
      const oldFlow = item.flow;
      const originalSampleIds = [...(task.sampleIds || [])];
      const reason = `${destroyedName} 样机档案被销毁，任务无法继续。`;
      // 释放该任务下其它样机
      originalSampleIds.filter(id => id !== sampleId).forEach(id => {
        if (this.findSample(id)) {
          const otherUsage = this.activeTaskUsagesForSample(id, task.id)[0];
          this.changeSampleStatus(id, otherUsage ? this.statusForOpenTaskUsage(otherUsage.task) : "闲置", {
            user: "管理员",
            source: "样机档案销毁",
            reason: otherUsage ? `关联任务异常终止，样机仍被其他任务占用；${reason}` : `关联任务异常终止，释放样机；${reason}`,
            projectId: otherUsage?.project?.id || item.project.id,
            stageId: otherUsage?.stage?.id || item.stage.id,
            taskId: otherUsage?.task?.id || task.id,
            testItem: otherUsage?.task?.testItem || task.testItem,
            forceLog: true
          });
        }
      });
      // 记录退出样机
      this.recordTaskRemovedSamples(task, [sampleId], { user: "管理员", reason, removedAt: now });
      task.sampleIds = [];
      task.status = "异常终止";
      task.completed = true;
      task.completionType = "异常终止";
      task.completedAt = now;
      task.endDate = today;
      task.resultDate = today;
      task.latestResult = "Fail";
      const progress = (item.stage.progress || []).find(p => p.id === task.progressId);
      if (progress) {
        progress.status = "Fail";
        progress.endDate = today;
        progress.issue = reason;
        progress.sampleIds = [];
      }
      this.addTaskLog(task, "样机档案销毁", {
        user: "管理员",
        reason,
        fromStatus: oldFlow,
        toStatus: "异常终止",
        detail: `已清空任务样机：${originalSampleIds.map(id => this.taskSampleDisplayName(id)).join("、") || "-"}`
      });
    });
    // 处理待下发任务 → 仅移除样机，不终止任务
    (impact.pending || []).forEach(item => {
      const task = item.task;
      const before = [...(task.sampleIds || [])];
      const reason = `${destroyedName} 样机档案被销毁，已从未启动任务中移除。`;
      this.recordTaskRemovedSamples(task, [sampleId], { user: "管理员", reason, removedAt: now });
      task.sampleIds = before.filter(id => id !== sampleId);
      const progress = (item.stage.progress || []).find(p => p.id === task.progressId);
      if (progress) progress.sampleIds = (progress.sampleIds || []).filter(id => id !== sampleId);
      this.addTaskLog(task, "样机档案销毁", {
        user: "管理员",
        reason,
        fromStatus: item.flow,
        toStatus: this.taskFlowStatus(task),
        detail: `任务样机：${before.map(id => this.taskSampleDisplayName(id)).join("、") || "-"} → ${(task.sampleIds || []).map(id => this.taskSampleDisplayName(id)).join("、") || "空"}`
      });
    });
    // 已完成任务：不做任何修改，快照已在 attachSampleSnapshotToTasks 中保存
  },

  destroySample(sampleId) {
    const found = this.findSample(sampleId);
    if (!found) return;
    const check = this.canDestroySample(found.sample);
    if (!check.ok) { alert(check.reason); return; }
    const impact = this.collectSingleSampleDestroyImpact(found.sample);
    this.confirmDeleteKeyword(
      "档案销毁",
      `档案销毁会物理删除 ${this.sampleDisplayCode(found.sample)} 的样机档案、照片/CT文件和样机事件数据。此操作不可恢复。`,
      () => {
        // 处理任务影响
        this.applySingleSampleDestroyImpact(found.sample, impact);
        // 写入样机销毁日志（在物理删除前）
        this.changeSampleStatus(sampleId, "已退库", {
          user: "管理员",
          source: "样机档案销毁",
          reason: "样机档案被销毁，物理删除前记录最终状态",
          forceLog: true
        });
        // 物理删除
        found.category.samples = (found.category.samples || []).filter(s => s.id !== sampleId);
        this.save(); this.renderSamples();
        Utils.toast("样机档案已销毁，关联任务已处理。");
      },
      this.singleSampleDestroyImpactHtml(impact)
    );
  },

  confirmDeleteKeyword(title, message, onConfirm, detailsHtml = "") {
    this.showModal(title, `
      <div class="delete-confirm">
        <p>${Utils.esc(message)}</p>
        ${detailsHtml || ""}
        <label>请输入 <strong>DELETE</strong> 确认销毁：</label>
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
      onConfirm?.();
    }, "确认销毁");
    document.getElementById("deleteKeywordInput")?.focus();
  },

  openCategory(id) { this.view.selectedCategoryId = id; this.render(); },

  // ---- 新建样机（简化：不强制项目/阶段/SKU）----
  newSample(catId, sampleNo, sn, imei, sourceInfo = {}) {
    return {
      id: Utils.id("sample_"),
      categoryId: catId,
      sampleNo: sampleNo || `TMP-${Date.now()}`,
      sn: sn || "",
      imei: imei || "",
      boardSn: sourceInfo.boardSn || "",
      model: sourceInfo.platform || "",
      config: sourceInfo.standard || "",
      schemeNo: sourceInfo.schemeNo || "",
      initialResult: sourceInfo.initialResult || "",
      initialResults: Array.isArray(sourceInfo.initialResults)
        ? sourceInfo.initialResults.filter(x => !Utils.isNoSampleIssueText(x))
        : Utils.parseSampleIssueText(sourceInfo.initialResult || ""),
      problemRecords: Array.isArray(sourceInfo.problemRecords)
        ? sourceInfo.problemRecords.filter(x => !Utils.isNoSampleIssueText(x?.description || x))
        : (Array.isArray(sourceInfo.initialResults)
          ? sourceInfo.initialResults
          : Utils.parseSampleIssueText(sourceInfo.initialResult || "")
        ).filter(x => !Utils.isNoSampleIssueText(x)).map(desc => ({ id: Utils.id("problem_"), description: desc, source: "初检", taskLabel: "" })),
      status: sourceInfo.status || "闲置",
      location: sourceInfo.location || "",
      owner: sourceInfo.owner || "",
      borrower: sourceInfo.borrower || "",
      borrowDate: sourceInfo.borrowDate || "",
      tag: sourceInfo.tag || "",
      sourceType: sourceInfo.sourceType || "manual",
      sourceProjectId: null,
      sourceProjectName: "",
      sourceStageId: null,
      sourceStageName: sourceInfo.stage || "Unknown",
      sourceSkuIndex: null,
      sourceSkuName: sourceInfo.skuName || sourceInfo.standard || "Unknown",
      currentProjectId: null, currentStageId: null, currentTaskId: null, currentTestItem: "",
      notes: sourceInfo.notes || "",
      importDate: sourceInfo.importDate || Utils.today(),
      photos: [],
      createdAt: Utils.now(), updatedAt: Utils.now(),
      logs: []
    };
  },

  nextSampleNo(category, prefix, offset = 0) {
    const existing = new Set((category.samples || []).map(s => String(s.sampleNo || "")));
    let n = (category.samples || []).length + 1 + offset;
    let no = `${prefix}-${String(n).padStart(3, "0")}`;
    while (existing.has(no)) { n++; no = `${prefix}-${String(n).padStart(3, "0")}`; }
    return no;
  },

  addSample(catId) {
    this.showModal("新增样机", `
      <div class="form-row sample-id-row">
        <div class="form-group"><label>SN</label><input id="sampleSn" placeholder="请输入SN号"></div>
        <div class="form-group"><label>IMEI</label><input id="sampleImei" placeholder="请输入IMEI号"></div>
        <div class="form-group"><label>主板SN</label><input id="sampleBoardSn" placeholder="请输入主板SN"></div>
      </div>
      <div class="form-row form-row-three">
        <div class="form-group"><label>阶段</label><input id="sampleStage" placeholder="如 V3-1"></div>
        <div class="form-group"><label>方案（制式/配置/型号/SKU）</label><input id="sampleConfig" placeholder="如 VXN-XX 或 SKU2"></div>
        <div class="form-group"><label>方案编号</label><input id="sampleSchemeNo" placeholder="如 B1 或 1"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>样机状态</label><select id="sampleStatus">${this.constants.sampleStatuses.map(x => `<option ${x === "闲置" ? "selected" : ""}>${x}</option>`).join("")}</select></div>
        <div class="form-group"><label>位置</label>${this.sampleLocationInputHtml("sampleLocation", "")}</div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>挂账人</label>${this.samplePersonInputHtml("sampleOwner", "", "任意填写，如：张三/wx001")}</div>
        <div class="form-group"><label>持有人/取走人</label>${this.samplePersonInputHtml("sampleBorrower", "", "任意填写，如：张三/wx001")}</div>
      </div>
      <div class="form-group"><label>其他备注信息</label><textarea id="sampleNotes" rows="2"></textarea></div>
      <div class="sample-info-divider"></div>
      <div class="form-group"><label>样机问题表</label>${this.sampleProblemsHtml("sampleInitialResults", [])}</div>
    `, () => {
      this.clearFieldValidationMarks();
      const category = this.data.sampleLibrary.categories.find(x => x.id === catId);
      if (!category) return;
      const sn = document.getElementById("sampleSn").value.trim();
      const imei = document.getElementById("sampleImei").value.trim();
      const boardSn = document.getElementById("sampleBoardSn").value.trim();
      if (!sn && !imei && !boardSn) {
        this.markFieldInvalid(document.getElementById("sampleSn"), "SN、IMEI 和主板SN至少需要填写一个。");
        this.markFieldInvalid(document.getElementById("sampleImei"), "SN、IMEI 和主板SN至少需要填写一个。");
        this.markFieldInvalid(document.getElementById("sampleBoardSn"), "SN、IMEI 和主板SN至少需要填写一个。");
        return true;
      }
      const stage = document.getElementById("sampleStage").value.trim();
      const config = document.getElementById("sampleConfig").value.trim();
      const problemRecords = this.collectSampleProblems("sampleInitialResults");
      const initialResults = problemRecords.map(x => x.description);
      const location = document.getElementById("sampleLocation").value.trim();

      if (!Array.isArray(category.samples)) category.samples = [];
      const duplicate = this.findDuplicateSampleInCategory(category, { sn, imei, boardSn });
      if (duplicate) {
        this.markFieldInvalid(document.getElementById("sampleSn"), `该样机池中已存在相同 SN/IMEI/主板SN 的样机：${this.sampleDisplayCode(duplicate)}`);
        return true;
      }
      category.samples.push(this.newSample(catId, sn || imei || boardSn, sn, imei, {
        stage,
        boardSn,
        standard: config,
        schemeNo: document.getElementById("sampleSchemeNo").value.trim(),
        initialResult: initialResults.join("\n"),
        initialResults,
        problemRecords,
        status: document.getElementById("sampleStatus").value,
        location,
        owner: document.getElementById("sampleOwner").value.trim(),
        borrower: document.getElementById("sampleBorrower")?.value.trim() || "",
        notes: document.getElementById("sampleNotes").value.trim(),
        sourceType: "manual"
      }));
      this.save(); this.renderSamples();
      Utils.toast("已新增 1 台样机。");
    });
  },

  addSamples(catId) {
    this.addSample(catId);
  },

  // ---- 模板导入 ----
  importSampleBatch(catId) {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv";
    input.onchange = e => {
      const file = e.target.files[0]; if (!file) return;
      const r = new FileReader();
      r.onload = async () => {
        const isXlsx = /\.xlsx$/i.test(file.name);
        const result = isXlsx ? await Utils.parseSampleImportXlsx(r.result) : Utils.parseSampleImportCsv(r.result);
        if (result.error) { alert("模板解析失败：" + result.error); return; }
        if (!result.rows.length) { alert("模板中没有有效数据行。"); return; }

        const category = this.data.sampleLibrary.categories.find(x => x.id === catId);
        if (!category) return;
        if (!Array.isArray(category.samples)) category.samples = [];

        let imported = 0, skippedDup = 0;
        result.rows.forEach((row, idx) => {
          // 用 IMEI 或 SN 作为样机编号
          const sampleNo = row.sn || row.imei || row.boardSn || this.nextSampleNo(category, row.stage || "CSV", idx);
          const duplicate = this.findDuplicateSampleInCategory(category, row);
          if (duplicate) { skippedDup++; return; }
          const location = String(row.location || "").trim();
          const initialResults = Utils.parseSampleIssueText(row.initialResult);
          const normalizedStatus = row.status === "已借出" || row.status === "借出" ? "取走分析" : row.status;
          category.samples.push(this.newSample(catId, sampleNo, row.sn, row.imei, {
            stage: row.stage,
            boardSn: row.boardSn,
            skuName: row.standard || "Unknown",
            standard: row.standard,
            platform: "",
            schemeNo: row.schemeNo,
            initialResult: row.initialResult,
            initialResults,
            problemRecords: initialResults.map(desc => ({ id: Utils.id("problem_"), description: desc, source: "初检", taskLabel: "" })),
            status: this.constants.sampleStatuses.includes(normalizedStatus) ? normalizedStatus : "闲置",
            location,
            tag: row.tag,
            owner: row.owner,
            borrower: row.borrower,
            borrowDate: row.borrowDate,
            notes: row.notes,
            importDate: row.importDate,
            sourceType: isXlsx ? "xlsx_import" : "csv_import"
          }));
          imported++;
        });

        this.save(); this.renderSamples();
        const warn = result.invalidPersonCount
          ? `；其中 ${result.invalidPersonCount} 条挂账人字段格式不合法，已按空处理`
          : "";
        Utils.toast(`已从模板导入 ${imported} 台样机${skippedDup ? `，跳过 ${skippedDup} 条重复样机` : ""}${warn}。`);
      };
      if (/\.xlsx$/i.test(file.name)) r.readAsArrayBuffer(file);
      else r.readAsText(file, "utf-8");
    };
    input.click();
  },

  importSampleCsv(catId) {
    this.importSampleBatch(catId);
  },

  sampleIdentifierSet(sample = {}) {
    return new Set([sample.sn, sample.imei, sample.boardSn]
      .map(v => String(v || "").trim().toLowerCase())
      .filter(Boolean));
  },

  sampleIdentifierSignature(sample = {}) {
    return [...this.sampleIdentifierSet(sample)].sort().join("|");
  },

  findDuplicateSampleInCategory(category, row = {}, excludeSampleId = "") {
    const incoming = this.sampleIdentifierSet(row);
    if (!incoming.size) return null;
    return (category.samples || []).find(sample => {
      if (excludeSampleId && sample.id === excludeSampleId) return false;
      const existing = this.sampleIdentifierSet(sample);
      return [...incoming].some(id => existing.has(id));
    }) || null;
  },

  downloadSampleTemplate() {
    const a = document.createElement("a");
    a.href = "/templates/sample_import_template.xlsx";
    a.download = "样机批量导入模板.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  },

  exportSampleCsv() {
    const rows = [["类别", "显示编号", "SN", "IMEI", "主板SN", "型号/方案", "配置/制式", "方案编号", "样机问题表", "阶段", "SKU/版本", "状态", "位置", "挂账人", "持有人", "标签", "备注"]];
    this.data.sampleLibrary.categories.forEach(c => (c.samples || []).forEach(s =>
      rows.push([c.name, this.sampleDisplayCode(s), s.sn, s.imei || "", s.boardSn || "", s.model, s.config, s.schemeNo || "", this.sampleInitialResultsValue(s).join("\n"), s.sourceStageName, s.sourceSkuName, this.sampleEffectiveStatus(s), s.location, s.owner, "", s.tag || "", s.notes])
    ));
    Utils.downloadCsv(rows, `样机档案池_${Utils.exportTimestamp()}.csv`);
  },

  sampleArchivePlaceholder(title, text) {
    return `<div class="sample-archive-empty">
      <b>${Utils.esc(title)}</b>
      <span>${Utils.esc(text)}</span>
    </div>`;
  },

  samplePersonInputHtml(id, value = "", placeholder = "任意填写") {
    // 失焦时严格按 "姓名/工号" 校验，不合法直接清空（不再保留残留串）。
    // 允许整字段为空，但只要填了就必须合法。
    return `<input id="${id}" value="${Utils.esc(value || "")}" placeholder="${Utils.esc(placeholder)}" autocomplete="off"
      onblur="app.validateSamplePersonInput(this)">`;
  },

  validateSamplePersonInput(input) {
    if (!input) return;
    const raw = String(input.value || "").trim();
    if (!raw) { input.value = ""; return; }
    const parsed = Utils.parsePersonField(raw);
    if (!parsed.ok) {
      input.value = "";
      Utils.toast(`"${raw}" 不是合法的"姓名/工号"格式，已清空（姓名仅汉字/字母，工号仅字母/数字）。`);
    } else {
      input.value = Utils.personText(parsed.name, parsed.employeeNo);
    }
  },

  sampleLocationInputHtml(id, value = "") {
    const seen = new Set();
    const locations = [];
    (this.data.projects || []).forEach(p => (p.locations || []).forEach(loc => {
      const name = String(loc || "").trim();
      if (!name || seen.has(name)) return;
      seen.add(name);
      locations.push(name);
    }));
    const listId = `${id}List`;
    const options = locations.map(loc => `<option value="${Utils.esc(loc)}"></option>`).join("");
    return `<input id="${id}" list="${listId}" value="${Utils.esc(value || "")}" placeholder="请选择或输入位置">
      <datalist id="${listId}">${options}</datalist>`;
  },

  sampleInitialResultsValue(sample) {
    const rows = this.sampleProblemRecords(sample).length
      ? this.sampleProblemRecords(sample).map(x => x.description)
      : Array.isArray(sample?.initialResults) && sample.initialResults.length
        ? sample.initialResults
      : String(sample?.initialResult || "").split(/\r?\n|；|;/);
    return rows.map(x => String(x || "").trim()).filter(Boolean);
  },

  samplePhotosHtml(sample) {
    const photos = Array.isArray(sample?.photos) ? sample.photos : [];
    return `<div class="sample-photo-actions">
      <button type="button" class="btn" onclick="app.uploadSamplePhotos('${sample.id}')">上传图片</button>
    </div>
    <div class="sample-photo-desc">图片会存入当前样机档案，随样机一起保存和迁移。<br>可上传外观照片、失效分析图片、问题定位图片、测试过程图片及其他相关图片数据。</div>
    <div class="sample-photo-grid">
      ${photos.length ? photos.map(photo => `
        <div class="sample-photo-card">
          <div class="sample-photo-thumb-wrap">
            <button type="button" class="sample-photo-thumb" onclick="app.previewSamplePhoto('${sample.id}','${photo.id}')" title="查看大图">
              <img src="${Utils.esc(photo.url || photo.dataUrl || "")}" alt="${Utils.esc(photo.name || "图片数据")}">
            </button>
            <button type="button" class="sample-photo-delete-btn" onclick="event.stopPropagation();app.deleteSamplePhoto('${sample.id}','${photo.id}')" title="删除照片">✕</button>
          </div>
          <div class="sample-photo-meta">
            <div class="sample-photo-name-row">
              <b title="${Utils.esc(photo.name || "")}">${Utils.esc(photo.name || "图片数据")}</b>
              <button type="button" class="sample-photo-rename-icon" onclick="event.stopPropagation();app.startPhotoRename(this,'${sample.id}','${photo.id}')" title="重命名">✎</button>
            </div>
          </div>
        </div>`).join("") : ""}
    </div>`;
  },

  previewSamplePhoto(sampleId, photoId) {
    const sample = this.findSample(sampleId)?.sample;
    const photo = (sample?.photos || []).find(x => x.id === photoId);
    if (!photo) return;
    const src = photo.url || photo.dataUrl || "";
    if (!src) return;
    const existing = document.querySelector(".sample-photo-preview-mask");
    if (existing) existing.remove();
    document.body.insertAdjacentHTML("beforeend", `
      <div class="sample-photo-preview-mask" onclick="if(event.target===this)this.remove()">
        <div class="sample-photo-preview">
          <div class="sample-photo-preview-head">
            <b>${Utils.esc(photo.name || "外观照片")}</b>
            <span class="path" style="font-size:12px">滚轮缩放 · 点击背景关闭</span>
            <button type="button" class="btn btn-sm btn-outline" onclick="this.closest('.sample-photo-preview-mask').remove()">关闭</button>
          </div>
          <div class="sample-photo-preview-body">
            <img src="${Utils.esc(src)}" alt="${Utils.esc(photo.name || "外观照片")}" style="transform-origin:center center;transition:transform 0.15s">
          </div>
        </div>
      </div>
    `);
    // 鼠标滚轮缩放 + 左键拖动平移
    const mask = document.querySelector(".sample-photo-preview-mask");
    const img = mask?.querySelector(".sample-photo-preview-body img");
    if (img) {
      let scale = 1, tx = 0, ty = 0, dragging = false, startX = 0, startY = 0;
      const maxScale = 5;
      const updateTransform = () => {
        img.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
      };
      const clampTranslate = () => {
        if (scale <= 1) { tx = 0; ty = 0; return; }
        const rect = img.getBoundingClientRect();
        const cw = body.clientWidth, ch = body.clientHeight;
        const iw = rect.width / scale, ih = rect.height / scale;
        const vw = iw * scale, vh = ih * scale;
        const maxX = Math.max(0, (vw - cw) / 2);
        const maxY = Math.max(0, (vh - ch) / 2);
        tx = Math.max(-maxX, Math.min(maxX, tx));
        ty = Math.max(-maxY, Math.min(maxY, ty));
      };
      const body = mask.querySelector(".sample-photo-preview-body");
      body.addEventListener("wheel", (e) => {
        e.preventDefault();
        const rect = img.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const oldScale = scale;
        scale *= e.deltaY < 0 ? 1.02 : 1 / 1.02;
        if (scale < 1) { scale = 1; tx = 0; ty = 0; }
        else if (scale > maxScale) scale = maxScale;
        else { tx = mx - (mx - tx) * (scale / oldScale); ty = my - (my - ty) * (scale / oldScale); }
        clampTranslate();
        updateTransform();
        body.style.cursor = scale > 1 ? "grab" : "zoom-in";
      }, { passive: false });
      img.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        dragging = true; startX = e.clientX - tx; startY = e.clientY - ty;
        img.style.cursor = "grabbing";
        e.preventDefault();
      });
      window.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        tx = e.clientX - startX; ty = e.clientY - startY;
        clampTranslate();
        updateTransform();
      });
      window.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        img.style.cursor = scale > 1 ? "grab" : "zoom-in";
      });
      const observer = new MutationObserver(() => {
        if (!document.body.contains(mask)) observer.disconnect();
      });
      observer.observe(document.body, { childList: true });
    }
  },

  uploadSamplePhotos(sampleId) {
    const found = this.findSample(sampleId);
    if (!found) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = true;
    input.onchange = async () => {
      const files = [...(input.files || [])];
      if (!files.length) return;
      try {
        if (!(await this.prepareBeforeDirectMutation("上传样机外观照片前同步"))) return;
        const form = new FormData();
        files.forEach(file => form.append("photos", file, file.name));
        form.append("revision", String(this.serverRevision || 0));
        form.append("remark", "上传样机外观照片");
        const res = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/photos`, {
          method: "POST",
          body: form
        });
        const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
        if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
        await this.syncAfterDirectMutation({ render: false, statusText: "已保存" });
        const latest = this.findSample(sampleId);
        const panel = document.querySelector('[data-sample-archive-panel="photos"]');
        if (panel && latest?.sample) panel.innerHTML = this.samplePhotosHtml(latest.sample);
        Utils.toast(`已上传 ${files.length} 张外观照片。`);
      } catch (e) {
        alert("照片上传失败：" + (e.message || e));
      }
    };
    input.click();
  },

  startPhotoRename(btn, sampleId, photoId) {
    const nameRow = btn.closest(".sample-photo-name-row");
    if (!nameRow) return;
    const nameB = nameRow.querySelector("b");
    if (!nameB) return;
    const originalName = nameB.textContent.trim();

    // Replace display with inline input
    nameRow.innerHTML = `<input class="sample-photo-name-input" value="${Utils.esc(originalName)}">`;
    const input = nameRow.querySelector(".sample-photo-name-input");
    if (!input) return;
    input.focus();
    input.select();

    let committed = false;

    const commit = () => {
      if (committed) return;
      committed = true;
      const newName = input.value.trim();
      // Empty or unchanged -> restore original, no save
      if (!newName || newName === originalName) {
        this.finishPhotoRename(nameRow, sampleId, photoId, originalName);
        return;
      }
      // Persist to data
      const found = this.findSample(sampleId);
      const photo = found?.sample?.photos?.find(x => x.id === photoId);
      if (found && photo) {
        photo.name = newName;
        found.sample.updatedAt = Utils.now();
        this.save();
      }
      this.finishPhotoRename(nameRow, sampleId, photoId, photo ? newName : originalName);
    };

    const cancel = () => {
      if (committed) return;
      committed = true;
      this.finishPhotoRename(nameRow, sampleId, photoId, originalName);
    };

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      if (e.key === "Escape") { e.preventDefault(); cancel(); }
    });
    input.addEventListener("blur", () => {
      setTimeout(() => commit(), 100);
    });
  },

  finishPhotoRename(nameRow, sampleId, photoId, name) {
    nameRow.innerHTML = `
      <b title="${Utils.esc(name)}">${Utils.esc(name)}</b>
      <button type="button" class="sample-photo-rename-icon" onclick="event.stopPropagation();app.startPhotoRename(this,'${Utils.esc(sampleId)}','${Utils.esc(photoId)}')" title="重命名">✎</button>
    `;
  },

  deleteSamplePhoto(sampleId, photoId) {
    const found = this.findSample(sampleId);
    if (!found || !Array.isArray(found.sample.photos)) return;
    this.showConfirm("确认删除这张外观照片？", async () => {
      try {
        if (!(await this.prepareBeforeDirectMutation("删除样机外观照片前同步"))) return;
        const res = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/photos/${encodeURIComponent(photoId)}`, { method: "DELETE" });
        const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
        if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
        await this.syncAfterDirectMutation({ render: false, statusText: "已保存" });
        const latest = this.findSample(sampleId);
        const panel = document.querySelector('[data-sample-archive-panel="photos"]');
        if (panel && latest?.sample) panel.innerHTML = this.samplePhotosHtml(latest.sample);
      } catch (e) {
        alert("删除照片失败：" + (e.message || e));
      }
    }, { title: "删除照片", okText: "删除", okClass: "btn btn-danger" });
  },

  sampleProblemsHtml(containerId, records = []) {
    const rows = records.length ? records : [{ description: "", source: "初检", taskLabel: "" }];
    return `<div id="${containerId}" class="sample-initial-results sample-problem-table">
      ${rows.map(v => this.sampleProblemRowHtml(containerId, v)).join("")}
    </div>`;
  },

  sampleProblemRowHtml(containerId, record = {}) {
    const item = typeof record === "string" ? { description: record, source: "初检", taskLabel: "" } : record;
    return `<div class="sample-initial-result-row">
      <input class="sample-problem-desc" value="${Utils.esc(item.description || "")}" placeholder="问题描述，如 有碎亮点">
      <input class="sample-problem-source" value="${Utils.esc(item.source || "初检")}" placeholder="来源">
      <input class="sample-problem-task" value="${Utils.esc(item.taskLabel || "")}" placeholder="关联任务项">
      <button type="button" class="sample-result-btn add" title="增加一行" onclick="app.addSampleProblemRow('${containerId}')">+</button>
      <button type="button" class="sample-result-btn remove" title="删除此行" onclick="app.removeSampleProblemRow(this)">-</button>
    </div>`;
  },

  addSampleProblemRow(containerId) {
    document.getElementById(containerId)?.insertAdjacentHTML("beforeend", this.sampleProblemRowHtml(containerId, { description: "", source: "手动补录", taskLabel: "" }));
  },

  removeSampleProblemRow(btn) {
    const row = btn.closest(".sample-initial-result-row");
    const wrap = btn.closest(".sample-initial-results");
    if (!row || !wrap) return;
    if (wrap.querySelectorAll(".sample-initial-result-row").length <= 1) {
      row.querySelectorAll("input").forEach(input => input.value = "");
      return;
    }
    row.remove();
  },

  collectSampleProblems(containerId) {
    return [...(document.getElementById(containerId)?.querySelectorAll(".sample-initial-result-row") || [])]
      .map(row => ({
        id: Utils.id("problem_"),
        description: row.querySelector(".sample-problem-desc")?.value.trim() || "",
        source: row.querySelector(".sample-problem-source")?.value.trim() || "手动补录",
        taskLabel: row.querySelector(".sample-problem-task")?.value.trim() || ""
      }))
      .filter(item => item.description && !Utils.isNoSampleIssueText(item.description));
  },

  sampleInitialResultsHtml(containerId, values = []) {
    return this.sampleProblemsHtml(containerId, values.map(v => ({ description: v, source: "初检", taskLabel: "" })));
  },

  addSampleInitialResultRow(containerId) {
    this.addSampleProblemRow(containerId);
  },

  removeSampleInitialResultRow(btn) {
    this.removeSampleProblemRow(btn);
  },

  collectSampleInitialResults(containerId) {
    return this.collectSampleProblems(containerId).map(x => x.description);
  },

  showSamplePersonOptions(id) {
    document.querySelectorAll(".sample-person-options.show").forEach(el => {
      if (el.dataset.pickerFor !== id) el.classList.remove("show");
    });
    document.querySelector(`[data-picker-for="${id}"]`)?.classList.add("show");
    this.filterSamplePersonOptions(id);
  },

  hideSamplePersonOptions(id) {
    document.querySelector(`[data-picker-for="${id}"]`)?.classList.remove("show");
  },

  filterSamplePersonOptions(id) {
    const input = document.getElementById(id);
    const panel = document.querySelector(`[data-picker-for="${id}"]`);
    if (!input || !panel) return;
    const kw = input.value.trim().toLowerCase();
    panel.querySelectorAll(".sample-person-option").forEach(btn => {
      btn.style.display = !kw || btn.dataset.person.toLowerCase().includes(kw) ? "" : "none";
    });
  },

  pickSamplePerson(id, value) {
    const input = document.getElementById(id);
    if (input) input.value = value || "";
    this.hideSamplePersonOptions(id);
  },

  switchSampleArchiveTab(tab) {
    document.querySelectorAll("[data-sample-archive-tab]").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.sampleArchiveTab === tab);
    });
    document.querySelectorAll("[data-sample-archive-panel]").forEach(panel => {
      panel.classList.toggle("active", panel.dataset.sampleArchivePanel === tab);
    });
  },

  sampleTaskResultPhotos(task, sampleId) {
    if (!task) return [];
    const sample = this.findSample(sampleId)?.sample || {};
    const photoById = new Map((sample.photos || []).filter(p => p?.id).map(p => [p.id, p]));
    const photos = [];
    (task.resultUploads || []).forEach(upload => {
      (upload.samples || [])
        .filter(item => item?.sampleId === sampleId)
        .forEach(item => {
          (item.photos || []).forEach(ref => {
            if (!ref?.id) return;
            const full = photoById.get(ref.id) || {};
            photos.push({
              id: ref.id,
              name: ref.name || full.name || "结果图片",
              url: ref.url || full.url || "",
              uploadedAt: ref.uploadedAt || full.uploadedAt || upload.time || "",
              result: upload.result || "",
              user: upload.user || "",
              uploadTime: upload.time || ""
            });
          });
        });
    });
    const seen = new Set();
    return photos.filter(photo => {
      const key = `${photo.uploadTime || ""}_${photo.id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  },

  sampleHistoryPhotosHtml(sampleId, photos = []) {
    if (!photos.length) return "";
    return `<div class="sample-history-photos">
      <div class="sample-history-photos-title">结果图片</div>
      <div class="sample-history-photo-grid">
        ${photos.map(photo => `
          <button type="button" class="sample-history-photo" onclick="app.previewSamplePhoto('${Utils.esc(sampleId)}','${Utils.esc(photo.id)}')" title="${Utils.esc(photo.name || "结果图片")}">
            ${photo.url ? `<img src="${Utils.esc(photo.url)}" alt="${Utils.esc(photo.name || "结果图片")}">` : ""}
            <span>${Utils.esc(photo.result || "-")} · ${Utils.esc(photo.user || "-")}</span>
          </button>
        `).join("")}
      </div>
    </div>`;
  },

  sampleTestHistoryHtml(sampleId) {
    const sampleLogsAll = this.findSample(sampleId)?.sample?.logs || [];
    const rows = new Map();
    sampleLogsAll.forEach(log => {
      const key = log.taskId || `log_${log.id}`;
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          task: null,
          projectName: log.projectName || this.projectName(log.projectId),
          stageName: log.stageName || this.stageName(log.projectId, log.stageId),
          testItem: log.testItem || "-",
          logs: []
        });
      }
      rows.get(key).logs.push(log);
    });
    (this.data.projects || []).forEach(project => (project.stages || []).forEach(stage => (stage.tasks || []).forEach(task => {
      const taskOwnsSample = (task.sampleIds || []).includes(sampleId)
        || (task.removedSampleRecords || []).some(item => item?.sampleId === sampleId);
      const taskTouchedSample = rows.has(task.id);
      if (!taskOwnsSample && !taskTouchedSample) return;
      const key = task.id;
      if (!rows.has(key)) {
        rows.set(key, { key, task, projectName: project.name, stageName: stage.name, testItem: task.testItem || "-", logs: [] });
      }
      const item = rows.get(key);
      item.task = task;
      item.projectName = project.name;
      item.stageName = stage.name;
      item.testItem = task.testItem || item.testItem || "-";
    })));
    const list = [...rows.values()].sort((a, b) => {
      const at = a.task?.completedAt || a.task?.resultDate || a.task?.startDate || a.logs[0]?.time || "";
      const bt = b.task?.completedAt || b.task?.resultDate || b.task?.startDate || b.logs[0]?.time || "";
      return String(bt).localeCompare(String(at));
    });
    if (!list.length) return this.sampleArchivePlaceholder("暂无测试履历", "该样机还没有被分配到任何测试任务。");

    return `<div class="sample-history-list">${list.map(({ task, projectName, stageName, testItem, logs }, idx) => {
      const historySeq = list.length - idx;
      const status = task ? this.taskFlowStatus(task) : "历史记录";
      const result = task?.latestResult || task?.result || "-";
      const date = task?.resultDate || task?.completedAt || task?.planDate || logs[logs.length - 1]?.time || "-";
      const taskSampleCount = task
        ? new Set([...(task.sampleIds || []), ...(task.removedSampleRecords || []).map(item => item?.sampleId).filter(Boolean)]).size
        : 0;
      const sampleFaultRecords = (task?.sampleFaultRecords || []).filter(x => x.sampleId === sampleId);
      const faultMarked = logs.some(log => log.faultMarked || log.flowStatus === "故障")
        || !!(task?.sampleFaults?.[sampleId]?.fault)
        || sampleFaultRecords.some(x => x.fault || x.problem);
      const problems = [...new Set([
        ...logs.map(log => log.problemDescription).filter(Boolean),
        task?.sampleFaults?.[sampleId]?.problem,
        ...sampleFaultRecords.map(x => x.problem).filter(Boolean)
      ].filter(Boolean))];
      const resultPhotos = this.sampleTaskResultPhotos(task, sampleId);
      const orderedLogs = logs.slice().reverse();
      return `<div class="sample-history-item">
        <button type="button" class="sample-history-summary" aria-expanded="false" onclick="app.toggleSampleHistoryItem(this)">
          <span class="history-seq">履历 #${historySeq}</span>
          <b>${Utils.esc(testItem || "-")}</b>
          <span class="badge s-${Utils.esc(status)}">${Utils.esc(status)}</span>
          <span class="badge ${faultMarked ? "status-bad" : "status-done"}">${faultMarked ? "已标记故障" : "未标记故障"}</span>
          <span class="sample-history-toggle"></span>
        </button>
        <div class="sample-history-detail">
          <div class="sample-history-grid">
            <span>任务ID：<b>${Utils.esc(task?.id || logs[0]?.taskId || "-")}</b></span>
            <span>项目：<b>${Utils.esc(projectName || "-")}</b></span>
            <span>阶段：<b>${Utils.esc(stageName || "-")}</b></span>
            <span>执行人：<b>${Utils.esc(task?.owner || logs[0]?.user || "-")}</b></span>
            <span>结果：<b>${Utils.esc(result)}</b></span>
            <span>日期：<b>${Utils.esc(date)}</b></span>
            <span>样机数：<b>${taskSampleCount || "-"} 台</b></span>
          </div>
          ${problems.length ? `<div class="sample-history-problems">问题：${problems.map(x => Utils.esc(x)).join("；")}</div>` : ""}
          ${this.sampleHistoryPhotosHtml(sampleId, resultPhotos)}
          ${orderedLogs.length ? `<div class="sample-history-logs">${orderedLogs.map((log, logIdx) => this.logHtml(log, orderedLogs.length - logIdx, "日志 #")).join("")}</div>` : `<div class="path">暂无该任务下的样机状态记录。</div>`}
        </div>
      </div>`;
    }).join("")}</div>`;
  },

  // ---- 样机数字档案（含 IMEI）----
  findSampleSnapshot(sampleId) {
    for (const project of (this.data.projects || [])) {
      for (const stage of (project.stages || [])) {
        for (const task of (stage.tasks || [])) {
          const snap = task?.sampleSnapshots?.[sampleId];
          if (snap) return { snapshot: snap, project, stage, task };
        }
      }
    }
    return null;
  },

  openSampleReadonly(sampleId) {
    const found = this.findSample(sampleId);
    if (found) {
      this.openSampleDetail(sampleId, { readonly: true });
      return;
    }
    const hit = this.findSampleSnapshot(sampleId);
    if (!hit) { alert("该样机档案不存在，可能已被销毁且没有保留快照。"); return; }
    const snap = hit.snapshot;
    this.showModal("样机档案快照：" + (snap.code || sampleId), `
      <div class="sample-archive-summary">
        <div><span>档案编号</span><b>${Utils.esc(snap.code || sampleId)}</b></div>
        <div><span>所属样机池</span><b>${Utils.esc(snap.categoryName || "-")}</b></div>
        <div><span>快照时间</span><b>${Utils.esc(snap.destroyedAt || "-")}</b></div>
      </div>
      <div class="sample-archive-summary">
        <div><span>SN</span><b>${Utils.esc(snap.sn || "-")}</b></div>
        <div><span>IMEI</span><b>${Utils.esc(snap.imei || "-")}</b></div>
        <div><span>主板SN</span><b>${Utils.esc(snap.boardSn || "-")}</b></div>
      </div>
      <div class="empty">该样机档案已销毁，这里仅显示任务日志保留的只读快照。</div>
    `, () => false, "关闭", { hideCancel: true, className: "sample-archive-modal", headerHint: "只读快照，不能编辑" });
  },

  openSampleDetail(sampleId, options = {}) {
    const found = this.findSample(sampleId);
    if (!found) return;
    const readonly = !!options.readonly;
    const s = found.sample;
    this.showModal("样机详情：" + this.sampleDisplayCode(s), `
      <div class="sample-summary-bar">
        <div class="sample-summary-card"><span class="sample-summary-label">档案编号</span><b class="sample-summary-value">${Utils.esc(this.sampleDisplayCode(s))}</b></div>
        <div class="sample-summary-card"><span class="sample-summary-label">故障</span><b class="sample-summary-value" style="color:${this.sampleHasProblem(s) ? '#b91c1c' : '#15803d'}">${this.sampleHasProblem(s) ? '有' : '无'}</b></div>
        <div class="sample-summary-card"><span class="sample-summary-label">当前状态</span><b class="sample-summary-value">${Utils.esc(this.sampleEffectiveStatus(s) || "-")}</b></div>
        <div class="sample-summary-card"><span class="sample-summary-label">当前任务</span><b class="sample-summary-value">${Utils.esc(s.currentTestItem || "-")}</b></div>
      </div>
      <div class="sample-archive-shell">
        <aside class="sample-archive-nav">
          <button type="button" class="active" data-sample-archive-tab="info" onclick="app.switchSampleArchiveTab('info')">样机信息</button>
          <button type="button" data-sample-archive-tab="history" onclick="app.switchSampleArchiveTab('history')">测试履历</button>
          <button type="button" data-sample-archive-tab="photos" onclick="app.switchSampleArchiveTab('photos')">图片数据</button>
          <button type="button" data-sample-archive-tab="ct" onclick="app.switchSampleArchiveTab('ct')">CT数据</button>
          <button type="button" data-sample-archive-tab="other" onclick="app.switchSampleArchiveTab('other')">其他</button>
        </aside>
        <div class="sample-archive-content">
          <section class="sample-archive-panel active" data-sample-archive-panel="info">
            <div class="form-row sample-id-row">
              <div class="form-group"><label>SN</label><input id="sdSn" value="${Utils.esc(s.sn || "")}"></div>
              <div class="form-group"><label>IMEI</label><input id="sdImei" value="${Utils.esc(s.imei || "")}" placeholder="IMEI号（选填）"></div>
              <div class="form-group"><label>主板SN</label><input id="sdBoardSn" value="${Utils.esc(s.boardSn || "")}" placeholder="主板SN（选填）"></div>
            </div>
            <div class="form-row form-row-three">
              <div class="form-group"><label>阶段</label><input id="sdStage" value="${Utils.esc(s.sourceStageName || "")}" placeholder="如 V3-1"></div>
              <div class="form-group"><label>方案（制式/配置/型号/SKU）</label><input id="sdConfig" value="${Utils.esc(s.config || s.model || "")}" placeholder="如 VXN-XX 或 SKU2"></div>
              <div class="form-group"><label>方案编号</label><input id="sdSchemeNo" value="${Utils.esc(s.schemeNo || "")}" placeholder="如 B1 或 1"></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label>样机状态</label><select id="sdStatus">${this.constants.sampleStatuses.map(x => `<option ${s.status === x ? 'selected' : ''}>${x}</option>`).join("")}</select></div>
              <div class="form-group"><label>当前位置</label>${this.sampleLocationInputHtml("sdLocation", s.location || "")}</div>
            </div>
            <div class="form-row">
              <div class="form-group"><label>挂账人(姓名/工号)</label>${this.samplePersonInputHtml("sdOwner", s.owner || "", "任意填写")}</div>
              <div class="form-group"><label>持有人/取走人(姓名/工号)</label>${this.samplePersonInputHtml("sdBorrower", s.borrower || "", "任意填写")}</div>
            </div>
            <div class="form-group"><label>其他备注信息</label><textarea id="sdNotes" rows="2">${Utils.esc(s.notes || "")}</textarea></div>
            <div class="sample-info-divider"></div>
            <div class="form-group"><label>样机问题表</label>${this.sampleProblemsHtml("sdInitialResults", this.sampleProblemRecords(s))}</div>
          </section>
          <section class="sample-archive-panel" data-sample-archive-panel="photos">
            ${this.samplePhotosHtml(s)}
          </section>
          <section class="sample-archive-panel" data-sample-archive-panel="history">
            ${this.sampleTestHistoryHtml(s.id)}
          </section>
          <section class="sample-archive-panel" data-sample-archive-panel="ct">
            ${this.sampleArchivePlaceholder("暂无CT数据", "后续可在这里归档CT图像、扫描批次、结构分析结论等数据。")}
          </section>
          <section class="sample-archive-panel" data-sample-archive-panel="other">
            ${this.sampleArchivePlaceholder("暂无内容", "其他功能模块尚未定义，后续可在此处扩展。")}
          </section>
        </div>
      </div>
    `, () => {
      if (readonly) return false;
      this.clearFieldValidationMarks();
      const newSn = document.getElementById("sdSn").value.trim();
      const newImei = document.getElementById("sdImei").value.trim();
      const newBoardSn = document.getElementById("sdBoardSn").value.trim();
      if (!newSn && !newImei && !newBoardSn) {
        this.markFieldInvalid(document.getElementById("sdSn"), "SN、IMEI 和主板SN至少需要填写一个。");
        this.markFieldInvalid(document.getElementById("sdImei"), "SN、IMEI 和主板SN至少需要填写一个。");
        this.markFieldInvalid(document.getElementById("sdBoardSn"), "SN、IMEI 和主板SN至少需要填写一个。");
        return true;
      }

      const newIdentity = { sn: newSn, imei: newImei, boardSn: newBoardSn };
      const identityChanged = this.sampleIdentifierSignature(s) !== this.sampleIdentifierSignature(newIdentity);
      if (identityChanged) {
        const duplicate = this.findDuplicateSampleInCategory(found.category, newIdentity, s.id);
        if (duplicate) {
          this.markFieldInvalid(document.getElementById("sdSn"), `该样机池中已存在相同 SN/IMEI/主板SN 的样机：${this.sampleDisplayCode(duplicate)}`);
          return true;
        }
      }
      const location = document.getElementById("sdLocation").value.trim();
      s.sn = newSn;
      s.imei = newImei;
      s.boardSn = newBoardSn;
      s.sampleNo = newSn || newImei || newBoardSn || s.sampleNo;
      s.model = "";
      s.config = document.getElementById("sdConfig").value.trim();
      s.schemeNo = document.getElementById("sdSchemeNo").value.trim();
      s.problemRecords = this.collectSampleProblems("sdInitialResults");
      s.initialResults = s.problemRecords.map(x => x.description);
      s.initialResult = s.initialResults.join("\n");
      s.sourceStageName = document.getElementById("sdStage").value.trim();
      s.sourceSkuName = s.config || "Unknown";
      s.status = document.getElementById("sdStatus").value;
      s.location = location;
      s.owner = document.getElementById("sdOwner").value.trim();
      s.borrower = document.getElementById("sdBorrower")?.value.trim() || "";
      s.notes = document.getElementById("sdNotes").value.trim();
      s.updatedAt = Utils.now();
      this.save(); this.render();
    }, readonly ? "关闭" : "确认", { hideCancel: readonly, headerHint: readonly ? "只读查看，不能编辑" : "" });
    document.querySelector(".modal")?.classList.add("sample-archive-modal");
    if (readonly) {
      const body = document.getElementById("modalBody");
      body?.querySelectorAll(".sample-archive-content input, .sample-archive-content select, .sample-archive-content textarea").forEach(el => { el.disabled = true; });
      body?.querySelectorAll(".sample-archive-content button:not(.sample-history-photo):not(.sample-photo-thumb):not(.sample-history-summary)").forEach(el => { el.disabled = true; });
    }
  }
});
