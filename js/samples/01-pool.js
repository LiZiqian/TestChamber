/* ========================================
   TestChamber V7 - Sample pool cards, CRUD, destroy impact
   Split from the previous monolithic module.
   ======================================== */

Object.assign(app, {

  samplePagerHtml(page, totalPages, total, pageSize) {
    const start = total ? (page - 1) * pageSize + 1 : 0;
    const end = total ? Math.min(total, page * pageSize) : 0;
    const pageBtn = (label, target, disabled = false) => `
      <button type="button" class="btn btn-sm btn-outline" ${disabled ? "disabled" : `onclick="app.setSamplePage(${target})"`}>${label}</button>`;
    return `
      <div class="list-pager sample-pager">
        <div class="sample-pager-row">
          <span class="path">显示 ${start}-${end} / ${total} 台</span>
          ${pageBtn("上一页", page - 1, page <= 1)}
          <span class="path">第 ${page} / ${totalPages} 页</span>
          ${pageBtn("下一页", page + 1, page >= totalPages)}
          <select class="sample-page-size-select" onchange="app.setSamplePageSize(this.value)">
            ${[50, 100, 200, 500].map(size => `<option value="${size}" ${pageSize === size ? "selected" : ""}>每页 ${size}</option>`).join("")}
          </select>
        </div>
      </div>`;
  },

  setSamplePage(page) {
    this.view.samplePage = Math.max(1, Number.parseInt(page, 10) || 1);
    this.renderSamples();
  },

  setSamplePageSize(size) {
    this.view.samplePageSize = this.boundedListPageSize(size, 100);
    this.view.samplePage = 1;
    this.renderSamples();
  },

  samplePageQueryParams(cat) {
    const params = {
      page: Math.max(1, Number.parseInt(this.view.samplePage, 10) || 1),
      pageSize: this.boundedListPageSize(this.view.samplePageSize, 100)
    };
    const map = {
      keyword: this.view.sampleKeyword,
      status: this.view.sampleStatusFilter,
      problemState: this.view.sampleProblemFilter,
      owner: this.view.sampleOwnerFilter,
      borrower: this.view.sampleBorrowerFilter
    };
    Object.entries(map).forEach(([key, value]) => {
      const text = String(value || "").trim();
      if (text) params[key] = text;
    });
    params.categoryId = cat?.id || "";
    return params;
  },

  samplePageCacheKey(cat, params) {
    return JSON.stringify({ categoryId: cat?.id || "", ...params });
  },

  loadSampleCategorySummary() {
    if (this._sampleCategorySummaryLoaded || this._sampleCategorySummaryLoading) return;
    this._sampleCategorySummaryLoading = true;
    this.fetchSampleCategoriesSummary()
      .then(categories => {
        this._sampleCategorySummaryLoading = false;
        const byId = new Map((this.data.sampleLibrary.categories || []).map(cat => [String(cat.id || ""), cat]));
        categories.forEach(summary => {
          const cat = byId.get(String(summary.id || ""));
          if (cat) Object.assign(cat, summary);
          else this.data.sampleLibrary.categories.push({ ...summary, samples: [] });
        });
        this._sampleCategorySummaryLoaded = true;
        if (this.view.module === "samples" && !this.view.selectedCategoryId) this.renderSamples();
      })
      .catch(e => {
        this._sampleCategorySummaryLoading = false;
        console.error("样机池摘要加载失败：", e);
      });
  },

  loadSamplePage(cat, key, params) {
    if (!cat?.id || this._samplePageLoadingKey === key) return;
    this._samplePageLoadingKey = key;
    this.fetchSamplePage(cat.id, params)
      .then(result => {
        this._samplePageLoadingKey = "";
        const items = result.items || [];
        const byId = new Map((cat.samples || []).map(sample => [String(sample.id || ""), sample]));
        items.forEach(sample => {
          if (!sample?.id) return;
          const existing = byId.get(String(sample.id));
          if (existing) Object.assign(existing, sample);
          else {
            if (!Array.isArray(cat.samples)) cat.samples = [];
            cat.samples.push(sample);
          }
        });
        Object.assign(cat, result.category || {});
        cat.sampleCount = result.stats?.totalInCategory ?? result.total ?? cat.sampleCount;
        cat.statusCounts = result.stats?.statusCounts || cat.statusCounts || {};
        this._samplePageCache = { key, categoryId: cat.id, ...result, items };
        if (this.view.module === "samples" && this.view.selectedCategoryId === cat.id) this.renderSamples();
      })
      .catch(e => {
        this._samplePageLoadingKey = "";
        this._samplePageCache = { key, categoryId: cat.id, error: e.message, items: [] };
        console.error("样机分页加载失败：", e);
        if (this.view.module === "samples" && this.view.selectedCategoryId === cat.id) this.renderSamples();
      });
  },

  renderSamples() {
    const content = document.getElementById("content");
    const cat = this.data.sampleLibrary.categories.find(c => c.id === this.view.selectedCategoryId);

    if (!cat) {
      this.loadSampleCategorySummary();
      const categoryCards = this.data.sampleLibrary.categories.map(c => `
          <div class="card sample-card" onclick="app.openCategory('${c.id}')">
            <div class="sample-pool-card-header">
              <span class="sample-pool-card-name">${Utils.esc(c.name)}</span>
              <button type="button" class="sample-card-edit-btn" onclick="event.stopPropagation();app.editSampleCategory('${c.id}')" title="编辑样机池">✎</button>
            </div>
            ${c.description ? `<div class="sample-pool-card-desc">${Utils.esc(c.description)}</div>` : ""}
            ${this.sampleCategoryStatsHtml(c)}
            <button type="button" class="sample-card-destroy-btn" onclick="event.stopPropagation();app.deleteSampleCategory('${c.id}')" title="档案销毁">🗑</button>
          </div>`).join("");
      content.innerHTML = `
        <div class="grid sample-category-grid">${categoryCards}
          <div class="card add-card" onclick="app.addSampleCategory()">
            <div class="add-card-plus">+</div>
            <div class="add-card-label">新增样机池</div>
          </div>
        </div>`;
        // 页脚说明
        const ft = document.getElementById("pageFooter");
        if (ft) {
          ft.style.display = "";
          ft.innerHTML = `<p class="page-footer-text">📦 可创建多个样机池 &nbsp;&nbsp;|&nbsp;&nbsp; 每个 SN / IMEI / 主板SN 只能存在于一个样机池内 &nbsp;&nbsp;|&nbsp;&nbsp; 项目管理中的测试任务可自由地在多个样机池内选取</p>`;
        }
      return;
    }

    const localFilteredSamples = (cat.samples || []).filter(s => {
      const kw = this.view.sampleKeyword.trim().toLowerCase();
      if (kw) {
        const direct = [s.sampleNo, s.sn, s.imei, s.boardSn, s.model, s.config, s.tag,
          s.schemeNo, s.sourceStageName, s.sourceSkuName, s.notes, s.owner, s.borrower, s.location
        ].filter(Boolean).join(" ").toLowerCase();
        if (direct.includes(kw)) return true;
        const problems = (s.problemRecords || []).map(r => r.description || "").filter(Boolean).join(" ");
        if (problems.toLowerCase().includes(kw)) return true;
        const logs = this.sampleEventLogsForSample(s.id).map(l => [l.testItem, l.projectName, l.stageName].filter(Boolean).join(" ")).join(" ");
        if (logs.toLowerCase().includes(kw)) return true;
        return false;
      }
      return true;
    }).filter(s =>
      (!this.view.sampleStatusFilter || this.sampleEffectiveStatus(s) === this.view.sampleStatusFilter)
      && (!this.view.sampleProblemFilter || (this.view.sampleProblemFilter === "fault" ? this.sampleHasProblem(s) : !this.sampleHasProblem(s)))
      && (!this.view.sampleOwnerFilter || (s.owner || "").includes(this.view.sampleOwnerFilter))
      && (!this.view.sampleBorrowerFilter || (s.borrower || "").includes(this.view.sampleBorrowerFilter))
    );
    const params = this.samplePageQueryParams(cat);
    const cacheKey = this.samplePageCacheKey(cat, params);
    const cached = this._samplePageCache?.key === cacheKey ? this._samplePageCache : null;
    if (!cached) this.loadSamplePage(cat, cacheKey, params);
    const pageSize = params.pageSize;
    const total = cached?.total ?? localFilteredSamples.length;
    const totalPages = cached?.totalPages ?? Math.max(1, Math.ceil(total / pageSize));
    const rawPage = Number.parseInt(cached?.page || params.page, 10) || 1;
    const page = Math.min(Math.max(1, rawPage), totalPages);
    this.view.samplePage = page;
    const pagedSamples = cached?.items || [];
    const pagerHtml = this.samplePagerHtml(page, totalPages, total, pageSize);

    // 进入样机池内部时隐藏页脚
    const ft2 = document.getElementById("pageFooter");
    if (ft2) ft2.style.display = "none";

    content.innerHTML = `
      <div class="card sample-pool-toolbar">
        <div class="sample-pool-toolbar-title">
          <b class="sample-pool-code">${Utils.esc(cat.name)}</b>
          ${cat.description ? `<span class="path sample-pool-desc">${Utils.esc(cat.description)}</span>` : ""}
        </div>
        <div class="sample-pool-toolbar-filters">
          <input class="sample-pool-search" placeholder="样机详情 / 失效 / 履历搜索（回车搜索）" value="${Utils.esc(this.view.sampleKeyword)}" oninput="app.view.sampleKeyword=this.value" onkeydown="if(event.key==='Enter'){app.view.sampleKeyword=this.value;app.view.samplePage=1;app.renderSamples()}">
          <select class="sample-pool-filter-status" onchange="app.view.sampleStatusFilter=this.value;app.view.samplePage=1;app.renderSamples()">
            <option value="">全部状态</option>
            ${this.constants.sampleStatuses.map(x => `<option ${this.view.sampleStatusFilter === x ? 'selected' : ''}>${x}</option>`).join("")}
          </select>
          <select class="sample-pool-filter-result" onchange="app.view.sampleProblemFilter=this.value;app.view.samplePage=1;app.renderSamples()">
            <option value="">全部结果</option>
            <option value="fault" ${this.view.sampleProblemFilter === "fault" ? "selected" : ""}>故障</option>
            <option value="ok" ${this.view.sampleProblemFilter === "ok" ? "selected" : ""}>OK</option>
          </select>
          <select class="sample-pool-filter-person" onchange="app.view.sampleOwnerFilter=this.value;app.view.samplePage=1;app.renderSamples()">
            <option value="">全部挂账人</option>
            ${[...new Set((cat.samples||[]).map(s=>s.owner).filter(Boolean))].sort().map(x=>`<option ${this.view.sampleOwnerFilter===x?'selected':''}>${Utils.esc(x)}</option>`).join("")}
          </select>
          <select class="sample-pool-filter-person" onchange="app.view.sampleBorrowerFilter=this.value;app.view.samplePage=1;app.renderSamples()">
            <option value="">全部持有人</option>
            ${[...new Set((cat.samples||[]).map(s=>s.borrower).filter(Boolean))].sort().map(x=>`<option ${this.view.sampleBorrowerFilter===x?'selected':''}>${Utils.esc(x)}</option>`).join("")}
          </select>
          <button type="button" class="btn btn-sm btn-outline sample-pool-clear-btn" onclick="app.view.sampleKeyword='';app.view.sampleStatusFilter='';app.view.sampleProblemFilter='';app.view.sampleOwnerFilter='';app.view.sampleBorrowerFilter='';app.view.samplePage=1;app.renderSamples()">清空</button>
          <span class="path sample-pool-count">显示 ${total} / ${cached?.stats?.totalInCategory ?? cat.sampleCount ?? (cat.samples || []).length} 台</span>
        </div>
        <div class="sample-pool-toolbar-actions">
          <button class="btn sample-pool-main-btn" onclick="app.downloadSampleTemplate()">下载批量导入模板</button>
          <button class="btn btn-purple sample-pool-main-btn" onclick="app.importSampleBatch('${cat.id}')">批量新增</button>
        </div>
      </div>
      ${pagerHtml}
      <div class="grid-small sample-pool-grid">
        <div class="card add-card" onclick="app.addSample('${cat.id}')">
          <div class="add-card-plus">+</div>
          <div class="add-card-label">新增样机</div>
        </div>
        ${!cached ? `<div class="empty sample-empty-hint">正在加载服务器分页数据...</div>` : cached.error ? `<div class="empty sample-empty-hint">样机分页加载失败：${Utils.esc(cached.error)}</div>` : (pagedSamples.length ? pagedSamples.map(s => this.sampleCardHtml(s)).join("") : `<div class="empty sample-empty-hint">暂无样机</div>`)}
      </div>
      ${total > pageSize ? pagerHtml : ""}`;
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
    const serverCounts = category.statusCounts || {};
    const count = status => serverCounts[status] ?? samples.filter(s => this.sampleEffectiveStatus(s) === status).length;
    const chipClass = {
      "测试中": "testing", "闲置": "idle", "在位等待": "waiting",
      "已退库": "retired", "取走分析": "analysis"
    };
    const chips = this.constants.sampleStatuses
      .filter(s => count(s) > 0)
      .map(s => `<span class="sample-pool-chip ${chipClass[s] || ''}"><b>${count(s)}</b> ${Utils.esc(s)}</span>`);
    const faultN = serverCounts["故障"] ?? samples.filter(s => this.sampleHasProblem(s)).length;
    if (faultN > 0) chips.push(`<span class="sample-pool-chip fault"><b>${faultN}</b> 故障</span>`);

    return `
      <div class="sample-pool-card-total">
        <b>${category.sampleCount ?? samples.length}</b>
        <span>台样机</span>
      </div>
      ${chips.length ? `<div class="sample-pool-card-chips">${chips.join("")}</div>` : ""}`;
  },

  sampleStatusStatClass(status) {
    if (status === "闲置") return "stat-done";
    if (status === "测试中") return "stat-running";
    if (status === "在位等待") return "stat-pending";
    if (status === "故障") return "stat-bad";
    if (["已退库", "取走分析", "已借出"].includes(status)) return "stat-blocked";
    return "stat-total";
  },

  // ---- 类别 CRUD ----,

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
    `, async () => {
      this.clearFieldValidationMarks();
      const snapshot = this.cloneData(this.data);
      const nameEl = document.getElementById("catName");
      const name = nameEl.value.trim();
      if (!name) { this.markFieldInvalid(nameEl, "代号不能为空"); return true; }
      if (this.sampleCategoryNameExists(name)) { this.markFieldInvalid(nameEl, `样机池名称"${name}"已存在，不能重复创建。`); return true; }
      const c = { id: Utils.id("cat_"), name, description: document.getElementById("catDesc").value.trim(), createdAt: Utils.now(), samples: [] };
      this.data.sampleLibrary.categories.push(c);
      this.view.selectedCategoryId = null;
      const saved = await this.commitSampleCategoryMutation(c, {
        action: "create_sample_category",
        remark: "新建样机池",
        user: "管理员",
        createIfMissing: true
      });
      if (!saved) { this.data = snapshot; return true; }
      Utils.toast("样机池已新建");
      return false;
    });
  },

  editSampleCategory(id) {
    const c = this.data.sampleLibrary.categories.find(x => x.id === id);
    if (!c) return;
    this.showModal("编辑样机池", `
      <div class="form-group"><label class="req">代号</label><input id="catName" value="${Utils.esc(c.name)}"></div>
      <div class="form-group"><label>说明</label><textarea id="catDesc" placeholder="如 新一代小内折手机 / TSE是张三 / 此为特稿保密项目">${Utils.esc(c.description || "")}</textarea></div>
    `, async () => {
      this.clearFieldValidationMarks();
      const snapshot = this.cloneData(this.data);
      const nameEl = document.getElementById("catName");
      const name = nameEl.value.trim();
      if (!name) { this.markFieldInvalid(nameEl, "代号不能为空"); return true; }
      if (this.sampleCategoryNameExists(name, c.id)) { this.markFieldInvalid(nameEl, `样机池名称"${name}"已存在，不能重复命名。`); return true; }
      c.name = name;
      c.description = document.getElementById("catDesc").value.trim();
      const saved = await this.commitSampleCategoryMutation(c, {
        action: "update_sample_category",
        remark: "编辑样机池",
        user: "管理员"
      });
      if (!saved) { this.data = snapshot; return true; }
      Utils.toast("样机池已保存");
      return false;
    });
  },

  async deleteSampleCategory(id) {
    if (!await this.ensureFullStateLoaded({ render: false })) return;
    const c = this.data.sampleLibrary.categories.find(x => x.id === id);
    if (!c) return;
    const impact = this.collectSampleCategoryDestroyImpact(c);
    this.confirmDeleteKeyword(
      "档案销毁",
      "档案销毁会物理删除该样机池、池内样机、照片/CT文件、问题表和样机事件数据。此操作不可恢复。",
      async () => {
        const dataSnapshot = this.cloneData(this.data);
        const destroyedIds = new Set((c.samples || []).map(sample => String(sample?.id || "")).filter(Boolean));
        const impactedItems = [
          ...(impact.runningOrBlocked || []),
          ...(impact.pending || [])
        ];
        const affectedSampleIds = new Set();
        impactedItems.forEach(item => {
          (item.allSampleIds || item.task?.sampleIds || []).forEach(id => {
            const sid = String(id || "");
            if (sid && !destroyedIds.has(sid)) affectedSampleIds.add(sid);
          });
        });
        this.applySampleCategoryDestroyImpact(c, impact);
        const taskMutations = impactedItems
          .map(item => this.taskMutationPayloadFor(item.project, item.stage, item.task))
          .filter(item => item?.taskId);
        const affectedSamples = [...affectedSampleIds]
          .map(id => this.findSample(id)?.sample)
          .filter(Boolean);
        const eventSampleIds = new Set([...destroyedIds, ...affectedSampleIds]);
        const sampleEvents = (this.data.sampleLibrary.logs || []).filter(log => eventSampleIds.has(String(log?.sampleId || "")));
        this.data.sampleLibrary.categories = this.data.sampleLibrary.categories.filter(x => x.id !== id);
        this.view.selectedCategoryId = null;
        const saved = await this.commitSampleCategoryMutation(c, {
          action: "destroy_sample_category",
          remark: "样机池档案销毁",
          user: "管理员",
          deleteCategory: true,
          taskMutations,
          samples: affectedSamples,
          sampleEvents,
          render: false
        });
        if (!saved) {
          this.data = dataSnapshot;
          return true;
        }
        this.renderSamples();
        Utils.toast("样机池档案已销毁，关联任务已处理。");
        return false;
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
      this.transitionTaskStatus(item.stage, task, "异常终止", {
        completedAt: now,
        endDate: today,
        progressStatus: "Fail",
        issue: reason
      });
      task.resultDate = today;
      task.latestResult = "Fail";
      const progress = (item.stage.progress || []).find(p => p.id === task.progressId);
      if (progress) progress.sampleIds = [];
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
      this.transitionTaskStatus(item.stage, task, "异常终止", {
        completedAt: now,
        endDate: today,
        progressStatus: "Fail",
        issue: reason
      });
      task.resultDate = today;
      task.latestResult = "Fail";
      const progress = (item.stage.progress || []).find(p => p.id === task.progressId);
      if (progress) progress.sampleIds = [];
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

  async destroySample(sampleId) {
    if (!await this.ensureFullStateLoaded({ render: false })) return;
    const found = this.findSample(sampleId);
    if (!found) return;
    const check = this.canDestroySample(found.sample);
    if (!check.ok) { alert(check.reason); return; }
    const impact = this.collectSingleSampleDestroyImpact(found.sample);
    this.confirmDeleteKeyword(
      "档案销毁",
      `档案销毁会物理删除 ${this.sampleDisplayCode(found.sample)} 的样机档案、照片/CT文件和样机事件数据。此操作不可恢复。`,
      async () => {
        const dataSnapshot = this.cloneData(this.data);
        const impactedItems = [
          ...(impact.runningOrBlocked || []),
          ...(impact.pending || [])
        ];
        const affectedSampleIds = new Set();
        impactedItems.forEach(item => {
          (item.task?.sampleIds || []).forEach(id => {
            const sid = String(id || "");
            if (sid && sid !== sampleId) affectedSampleIds.add(sid);
          });
        });
        // 处理任务影响
        this.applySingleSampleDestroyImpact(found.sample, impact);
        // 写入样机销毁日志（在物理删除前）
        this.changeSampleStatus(sampleId, "已退库", {
          user: "管理员",
          source: "样机档案销毁",
          reason: "样机档案被销毁，物理删除前记录最终状态",
          forceLog: true
        });
        const taskMutations = impactedItems
          .map(item => this.taskMutationPayloadFor(item.project, item.stage, item.task))
          .filter(item => item?.taskId);
        const affectedSamples = [...affectedSampleIds]
          .map(id => this.findSample(id)?.sample)
          .filter(Boolean);
        const eventSampleIds = new Set([sampleId, ...affectedSampleIds]);
        const sampleEvents = (this.data.sampleLibrary.logs || []).filter(log => eventSampleIds.has(String(log?.sampleId || "")));
        // 物理删除
        found.category.samples = (found.category.samples || []).filter(s => s.id !== sampleId);
        const saved = await this.commitSampleMutation(found.sample, {
          action: "destroy_sample",
          remark: "样机档案销毁",
          user: "管理员",
          deleteSample: true,
          taskMutations,
          samples: affectedSamples,
          sampleEvents,
          render: false
        });
        if (!saved) {
          this.data = dataSnapshot;
          return true;
        }
        this.renderSamples();
        Utils.toast("样机档案已销毁，关联任务已处理。");
        return false;
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
      return onConfirm?.();
    }, "确认销毁");
    document.getElementById("deleteKeywordInput")?.focus();
  },

  openCategory(id) { this.view.selectedCategoryId = id; this.view.samplePage = 1; this.render(); },

  // ---- 新建样机（简化：不强制项目/阶段/SKU）----,

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

  async addSample(catId) {
    if (!await this.ensureFullStateLoaded({ render: false })) return;
    this.showModal("新增样机", `
      <div style="display:flex;flex-direction:column;gap:18px">
        <div class="form-row sample-id-row" style="gap:14px">
          <div class="form-group" style="margin-bottom:0"><label>SN</label><input id="sampleSn" placeholder="请输入SN号"></div>
          <div class="form-group" style="margin-bottom:0"><label>IMEI</label><input id="sampleImei" placeholder="请输入IMEI号"></div>
          <div class="form-group" style="margin-bottom:0"><label>主板SN</label><input id="sampleBoardSn" placeholder="请输入主板SN"></div>
        </div>
        <div class="form-row form-row-three" style="gap:14px">
          <div class="form-group" style="margin-bottom:0"><label>阶段</label><input id="sampleStage" placeholder="如 V3-1"></div>
          <div class="form-group" style="margin-bottom:0"><label>方案（制式/配置/型号/SKU）</label><input id="sampleConfig" placeholder="如 VXN-XX 或 SKU2"></div>
          <div class="form-group" style="margin-bottom:0"><label>方案编号</label><input id="sampleSchemeNo" placeholder="如 B1 或 1"></div>
        </div>
        <div class="form-row" style="gap:14px">
          <div class="form-group" style="margin-bottom:0"><label>样机状态</label><select id="sampleStatus">${this.constants.sampleStatuses.map(x => `<option ${x === "闲置" ? "selected" : ""}>${x}</option>`).join("")}</select></div>
          <div class="form-group" style="margin-bottom:0"><label>位置</label>${this.sampleLocationInputHtml("sampleLocation", "")}</div>
        </div>
        <div class="form-row" style="gap:14px">
          <div class="form-group" style="margin-bottom:0"><label>挂账人</label>${this.samplePersonInputHtml("sampleOwner", "", "姓名/工号")}</div>
          <div class="form-group" style="margin-bottom:0"><label>持有人/取走人</label>${this.samplePersonInputHtml("sampleBorrower", "", "姓名/工号")}</div>
        </div>
        <div class="form-group" style="margin-bottom:0"><label>其他备注信息</label><textarea id="sampleNotes" rows="1" style="min-height:38px;height:38px"></textarea></div>
        <div class="sample-info-divider" style="margin:4px 0"></div>
        <div class="form-group" style="margin-bottom:0"><label>样机问题表</label>${this.sampleProblemsHtml("sampleInitialResults", [])}</div>
      </div>
    `, async () => {
      this.clearFieldValidationMarks();
      const category = this.data.sampleLibrary.categories.find(x => x.id === catId);
      if (!category) return;
      const snapshot = this.cloneData(this.data);
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

      // 人员字段校验（复用全局 parsePersonField）
      const ownerEl = document.getElementById("sampleOwner");
      const borrowerEl = document.getElementById("sampleBorrower");
      const ownerRaw = ownerEl.value.trim();
      const borrowerRaw = borrowerEl?.value.trim() || "";
      let ownerText = "", borrowerText = "";
      if (ownerRaw) {
        const parsed = Utils.parsePersonField(ownerRaw);
        if (!parsed.ok) { this.markFieldInvalid(ownerEl, parsed.msg); return true; }
        ownerText = Utils.personText(parsed.name, parsed.employeeNo);
      }
      if (borrowerRaw) {
        const parsed = Utils.parsePersonField(borrowerRaw);
        if (!parsed.ok) { this.markFieldInvalid(borrowerEl, parsed.msg); return true; }
        borrowerText = Utils.personText(parsed.name, parsed.employeeNo);
      }

      if (!Array.isArray(category.samples)) category.samples = [];

      // 自校验：同一台样机的 SN/IMEI/主板SN 互不相同
      const selfDup = this.validateSampleSelfDuplicate(sn, imei, boardSn, "sample");
      if (selfDup) { this.markFieldInvalid(document.getElementById(selfDup.field), selfDup.msg); return true; }

      // 池内查重
      const inCat = this._checkInCategoryDuplicate(category, sn, imei, boardSn, "", "sample");
      if (inCat) { this.markFieldInvalid(document.getElementById(inCat.fieldId), inCat.msg); return true; }

      // 跨池查重
      const global = this._checkGlobalDuplicate(sn, imei, boardSn, catId, "", "sample");
      if (global) { this.markFieldInvalid(document.getElementById(global.fieldId), global.msg); return true; }
      const sample = this.newSample(catId, sn || imei || boardSn, sn, imei, {
        stage,
        boardSn,
        standard: config,
        schemeNo: document.getElementById("sampleSchemeNo").value.trim(),
        initialResult: initialResults.join("\n"),
        initialResults,
        problemRecords,
        status: document.getElementById("sampleStatus").value,
        location,
        owner: ownerText,
        borrower: borrowerText,
        notes: document.getElementById("sampleNotes").value.trim(),
        sourceType: "manual"
      });
      category.samples.push(sample);
      const saved = await this.commitSampleCategoryMutation(category, {
        action: "create_sample",
        remark: "新增样机",
        user: "管理员",
        createSamples: true,
        samples: [sample]
      });
      if (!saved) { this.data = snapshot; return true; }
      Utils.toast("已新增 1 台样机。");
      return false;
    });
  },

  addSamples(catId) {
    this.addSample(catId);
  },

  // ---- 模板导入 ----,

});
