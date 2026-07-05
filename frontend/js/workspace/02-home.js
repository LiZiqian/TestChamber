/* ========================================
   数字治理平台 V7 - 项目工作台主页模块
   ======================================== */

app.registerModule("workspace.home", {

  // ==================== 项目工作台主页 ====================
  renderProjectWorkspace() {
    const p = this.currentProject();
    if (!p) { this.renderEmpty("请先在项目管理中新建项目"); return; }
    if (this.stageStrategyId()) { this.renderStageStrategyPage(); return; }

    this.ensureWorkspaceStageSelection(p);
    const s = p.stages.length ? this.currentStage() : null;

    // 各阶段统计
    const stageStats = p.stages.map(st => {
      const progress = st.progress || [];
      const tasks = this.activeStageTasks(st);
      const statusCounts = st.statusCounts || {};
      const hasServerTaskStats = typeof st.taskCount !== "undefined" || Object.keys(statusCounts).length > 0;
      const countStatus = status => hasServerTaskStats
        ? Number(statusCounts[status] || 0)
        : tasks.filter(t => this.taskFlowStatus(t) === status).length;
      const total = progress.length;
      const plannedSampleCount = progress.reduce((sum, item) => sum + (this.getProgressRequiredSampleCount(st, item) || 0), 0);
      const pass = countStatus("正常完成");
      const fail = countStatus("异常终止");
      const testing = countStatus("进行中");
      const pending = countStatus("待下发");
      const blocked = countStatus("阻塞中");
      const executedTasks = pass + fail;
      const usedSampleRuns = tasks
        .filter(t => this.taskFlowStatus(t) !== "待下发")
        .reduce((sum, t) => sum + (t.sampleIds || []).length, 0);
      const runningTasks = tasks.filter(t => this.taskFlowStatus(t) === "进行中");
      const runningSampleCount = new Set(runningTasks.flatMap(t => t.sampleIds || [])).size;
      const passRate = (pass + fail) ? ((pass / (pass + fail)) * 100).toFixed(1) : "0.0";
      const sampleIds = [...new Set(tasks.flatMap(t => t.sampleIds || []))];
      const taskCount = Number(st.taskCount ?? tasks.length) || 0;
      return {
        stage: st, total, plannedSampleCount, executedTasks, usedSampleRuns, runningTasks: hasServerTaskStats ? testing : runningTasks.length,
        runningSampleCount, pass, fail, testing, pending, blocked, passRate, tasks: taskCount, sampleCount: sampleIds.length
      };
    });

    // 项目总计
    const projectTotal = stageStats.reduce((a, x) => a + x.total, 0);
    const projectDispatchedTasks = stageStats.reduce((a, x) => a + x.tasks, 0);
    const projectPass = stageStats.reduce((a, x) => a + x.pass, 0);
    const projectFail = stageStats.reduce((a, x) => a + x.fail, 0);
    const projectTesting = stageStats.reduce((a, x) => a + x.testing, 0);
    const projectPassRate = (projectPass + projectFail) ? ((projectPass / (projectPass + projectFail)) * 100).toFixed(1) : "0.0";
    const sortMode = this.stageSortMode();

    // 阶段卡片（融合进度看板信息）
    const stageCards = stageStats.map(x => {
      const pct = x.total ? ((x.pass / x.total) * 100).toFixed(0) : 0;
      const cardAttrs = sortMode
        ? `data-stage-id="${Utils.esc(x.stage.id)}" draggable="true" data-app-action="stage-drag" data-app-events="dragstart dragover dragleave drop dragend" data-id="${Utils.esc(x.stage.id)}"`
        : `data-app-action="stage-select" data-id="${Utils.esc(x.stage.id)}"`;
      return `
      <div class="stage-summary-card ${x.stage.id === s?.id ? 'active' : ''} ${sortMode ? 'is-sorting' : ''}" ${cardAttrs}>
        <div class="stage-summary-title">
          <div class="stage-summary-name-row">
            <span>${Utils.esc(x.stage.name)}</span>
            ${sortMode ? '' : `<button type="button" class="btn btn-sm btn-purple stage-config-btn" data-app-action="stage-strategy-open" data-stop-propagation="1" data-id="${Utils.esc(x.stage.id)}">配置测试用例集</button>`}
          </div>
          <div class="stage-summary-actions">
            ${sortMode
              ? '<span class="stage-sort-hint">拖动排序</span>'
              : `<button type="button" class="sample-card-destroy-btn" style="position:static" data-app-action="stage-delete" data-stop-propagation="1" data-id="${Utils.esc(x.stage.id)}" title="删除此阶段">🗑</button>
                <button type="button" style="background:none;border:none;font-size:18px;font-weight:900;opacity:0.75;color:#4b5563;cursor:pointer;padding:2px;line-height:1;margin-left:2px;transition:opacity .15s" title="复制为一个新阶段" aria-label="复制为一个新阶段" data-app-action="stage-copy" data-stop-propagation="1" data-id="${Utils.esc(x.stage.id)}">🗐</button>`}
          </div>
        </div>
        <div class="path">方案(SKU)：${(x.stage.skuNames || []).map(n => Utils.esc(n)).join(" / ") || "-"}</div>
        <div class="progress-bar-wrap">
          <div class="progress-bar-fill" style="width:${pct}%;background:${x.passRate > 80 ? 'var(--pass)' : x.passRate > 50 ? 'var(--warn)' : 'var(--primary)'}"></div>
        </div>
        <div class="stage-summary-metrics">
          <div class="stage-metric-card">
            <b>测试项</b>
            <span>计划执行<em>${x.total} 项</em></span>
            <span>已执行<em>${x.executedTasks} 项</em></span>
            <span>进行中<em>${x.runningTasks} 项</em></span>
          </div>
          <div class="stage-metric-card">
            <b>样机数</b>
            <span>计划使用<em>${x.plannedSampleCount} 台</em></span>
            <span>已使用<em>${x.usedSampleRuns} 台次</em></span>
          </div>
          <div class="stage-metric-card">
            <b>进行中</b>
            <span>任务<em>${x.runningTasks} 项</em></span>
            <span>占用样机<em>${x.runningSampleCount} 台</em></span>
          </div>
        </div>
      </div>`;
    }).join("");
    const addStageCard = `
      <div class="card add-card" data-app-action="stage-add" title="新增阶段">
        <div class="add-card-plus">+</div>
        <div class="add-card-label">新增阶段</div>
      </div>`;

    const sampleOwnerCounts = this.sampleOwnerCountsByMemberKey();
    this.replaceWorkspaceContentNodes(
      document.getElementById("content"),
      this.projectWorkspacePageNodes(p, s, {
        stageCards,
        addStageCard,
        sampleOwnerCounts,
        sortMode,
      })
    );
  },

  replaceWorkspaceContentNodes(target, nodes = []) {
    if (!target) return null;
    if (typeof target.replaceChildren === "function") target.replaceChildren(...nodes);
    else {
      target.textContent = "";
      nodes.forEach(node => target.append?.(node));
    }
    return target;
  },

  appendWorkspaceHtml(parent, html) {
    const fragment = typeof this.htmlFragment === "function" ? this.htmlFragment(html) : null;
    if (fragment) parent.append(fragment);
    else {
      const holder = document.createElement("div");
      holder.textContent = String(html || "");
      parent.append(holder);
    }
  },

  projectWorkspacePageNodes(project, stage, { stageCards, addStageCard, sampleOwnerCounts, sortMode }) {
    const nodes = [];
    const configCard = document.createElement("div");
    configCard.className = "card project-config-card";

    const intro = document.createElement("div");
    intro.className = "project-config-intro";
    const title = document.createElement("h2");
    title.textContent = "项目配置工作台";
    const desc = document.createElement("p");
    desc.textContent = "项目需首先完成人员配置、位置配置与阶段方案配置。";
    intro.append(title, desc);
    configCard.append(intro);

    this.appendWorkspaceHtml(configCard, this.workspaceMembersHtml(project, sampleOwnerCounts));
    this.appendWorkspaceHtml(configCard, this.workspaceLocationsHtml(project));
    this.appendWorkspaceHtml(configCard, this.workspaceDefaultSampleCategoryHtml(project));
    configCard.append(this.projectStageConfigSectionNode(stageCards, addStageCard, sortMode));
    nodes.push(configCard);

    if (stage) {
      const taskFlow = document.createElement("div");
      taskFlow.className = `card workspace-section section-green ${this.isCollapsed("taskFlow") ? "is-collapsed" : ""}`.trim();
      this.appendWorkspaceHtml(taskFlow, this.workspaceTaskFlowHtml(project, stage));
      nodes.push(taskFlow);
    }
    return nodes;
  },

  projectStageConfigSectionNode(stageCards, addStageCard, sortMode) {
    const section = document.createElement("div");
    section.className = `project-config-section ${this.isCollapsed("stage") ? "is-collapsed" : ""}`.trim();

    const head = document.createElement("div");
    head.className = "stage-summary-section-head";
    this.appendWorkspaceHtml(head, this.sectionToggleTriangle("stage"));
    const title = document.createElement("div");
    title.className = "stage-summary-section-title";
    title.textContent = "项目阶段与方案配置";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = `btn btn-sm ${sortMode ? "stage-sort-done" : "btn-outline"} stage-sort-toggle stage-sort-toggle-right`;
    toggle.dataset.appAction = "stage-sort-toggle";
    toggle.textContent = sortMode ? "完成排序" : "手动拖动排序";
    head.append(title, toggle);
    section.append(head);

    const desc = document.createElement("div");
    desc.className = "stage-summary-section-desc";
    desc.textContent = "点击 <配置测试用例集> 可为该阶段配置测试用例池，并在 <任务管理> 中下发用例任务。";
    section.append(desc);

    const body = document.createElement("div");
    body.className = "project-config-body";
    const row = document.createElement("div");
    row.className = "stage-cards-row";
    const grid = document.createElement("div");
    grid.className = "stage-summary-grid";
    this.appendWorkspaceHtml(grid, `${stageCards}${addStageCard}`);
    row.append(grid);
    body.append(row);
    section.append(body);
    return section;
  },

  sampleOwnerCountsByMemberKey() {
    const counts = new Map();
    this.sampleCategoryRecords().forEach(category => {
      (category.samples || []).forEach(sample => {
        const identity = Utils.personIdentityFromText(sample.owner || "");
        const key = Utils.memberIdentityKey(identity.name, identity.employeeNo);
        if (key === "||") return;
        counts.set(key, (counts.get(key) || 0) + 1);
      });
    });
    return counts;
  },

  workspaceMembersHtml(project, sampleOwnerCounts = null) {
    if (!Array.isArray(project.members)) project.members = [];
    const collapsed = this.isCollapsed('members');
    const activeMembers = this.projectActiveMembers(project);
    const rows = activeMembers
      .map(m => {
        const stat = this.memberWorkStats(project, m, sampleOwnerCounts);
        const identity = Utils.personText(m.name, m.employeeNo);
        return `
          <div class="project-member-card" data-app-action="project-member-edit" data-app-events="dblclick" data-id="${Utils.esc(m.id)}" tabindex="0" title="双击编辑人员" aria-label="双击编辑人员 ${Utils.esc(identity || "-")}">
            <div class="project-member-identity">${Utils.esc(identity || "-")}</div>
            <div class="project-member-stat">${stat.tasks} 项 · 挂账 ${stat.ownedSamples} 台</div>
            <span class="project-member-remove" data-app-action="project-member-remove" data-stop-propagation="1" data-id="${Utils.esc(m.id)}" title="移出人员">🗑</span>
          </div>`;
      }).join("");

    return `
      <div class="project-config-section project-members-section ${collapsed ? 'is-collapsed' : ''}">
        <div class="stage-summary-section-head">
          ${this.sectionToggleTriangle('members')}
          <div class="stage-summary-section-title">人员配置</div>
          <div class="project-members-head-actions">
            <button class="btn btn-sm btn-outline" data-app-action="project-members-template">下载导入模板</button>
            <button class="btn btn-sm" data-app-action="project-members-import">批量导入人员名单</button>
          </div>
        </div>
        <div class="stage-summary-section-desc">配置项目参与人员，后续可在任务管理中选择执行人和操作人。共 ${activeMembers.length} 人</div>
        <div class="project-members-body">
          <div class="project-members-grid">
            ${rows}
            <div class="card add-card" data-app-action="project-member-add">
              <div class="add-card-plus">+</div>
              <div class="add-card-label">新增人员</div>
            </div>
          </div>
        </div>
      </div>`;
  },

  workspaceLocationsHtml(project) {
    if (!Array.isArray(project.locations)) project.locations = [];
    const collapsed = this.isCollapsed('locations');
    const locations = project.locations.filter(Boolean);
    const cards = locations.map((loc, idx) => `
      <div class="project-location-card" data-app-action="project-location-edit" data-app-events="dblclick" data-value="${idx}" tabindex="0" title="双击编辑位置" aria-label="双击编辑位置 ${Utils.esc(loc)}">
        <b>${Utils.esc(loc)}</b>
        <span class="project-location-remove" data-app-action="project-location-remove" data-stop-propagation="1" data-value="${idx}" title="删除位置">🗑</span>
      </div>`).join("");
    return `
      <div class="project-config-section project-locations-section ${collapsed ? 'is-collapsed' : ''}">
        <div class="stage-summary-section-head">
          ${this.sectionToggleTriangle('locations')}
          <div class="stage-summary-section-title">位置配置</div>
        </div>
        <div class="stage-summary-section-desc">配置项目相关位置信息，用于记录样机实时存放地点，后续可在样机档案中选填。</div>
        <div class="project-locations-body">
          <div class="project-locations-grid">
            ${cards || ''}
            <div class="card add-card" data-app-action="project-location-add">
              <div class="add-card-plus">+</div>
              <div class="add-card-label">新增位置</div>
            </div>
          </div>
        </div>
      </div>`;
  },

  workspaceDefaultSampleCategoryHtml(project) {
    const collapsed = this.isCollapsed("sampleCategoryConfig");
    const categories = this.sampleCategoryRecords();
    const selectedId = this.projectDefaultSampleCategoryId(project);
    const options = [
      `<option value="" ${selectedId ? "" : "selected"}>不设置（默认全部样机池）</option>`,
      ...categories.map(category => {
        const id = String(category.id || "");
        const selected = id === selectedId ? "selected" : "";
        const count = Number(category.sampleCount ?? (category.samples || []).length) || 0;
        const suffix = count ? ` (${count})` : "";
        return `<option value="${Utils.esc(id)}" ${selected}>${Utils.esc(category.name || id)}${suffix}</option>`;
      })
    ].join("");
    const configured = selectedId
      ? `当前默认：${Utils.esc(this.projectDefaultSampleCategoryName(project) || selectedId)}`
      : "当前未设置，任务配置和临时变更默认显示全部样机池。";
    return `
      <div class="project-config-section project-default-sample-section ${collapsed ? 'is-collapsed' : ''}">
        <div class="stage-summary-section-head">
          ${this.sectionToggleTriangle('sampleCategoryConfig')}
          <div class="stage-summary-section-title">样机池配置</div>
        </div>
        <div class="stage-summary-section-desc">设置本项目任务配置、临时变更等样机选择入口的默认候选池。</div>
        <div class="project-default-sample-body project-config-body">
          <label class="project-default-sample-label" for="projectDefaultSampleCategory">默认样机池</label>
          <select id="projectDefaultSampleCategory" class="project-default-sample-select" data-app-action="project-default-sample-category" data-app-events="change">${options}</select>
          <span class="project-default-sample-current">${configured}</span>
        </div>
      </div>`;
  },

  async setProjectDefaultSampleCategory(categoryId) {
    const p = this.currentProject();
    if (!p) return;
    const nextId = String(categoryId || "").trim();
    if (nextId && !this.findSampleCategoryRecord(nextId)) {
      alert("所选样机池不存在或已被删除。");
      this.render();
      return;
    }
    const before = String(p.defaultSampleCategoryId || "");
    if (before === nextId) return;
    const snapshot = this.dataSnapshot();
    p.defaultSampleCategoryId = nextId;
    const saved = await this.commitProjectMutation(p, {
      action: "set_project_default_sample_category",
      remark: nextId ? "设置项目默认样机池" : "清除项目默认样机池",
      user: "管理员"
    });
    if (!saved) {
      this.restoreDataSnapshot(snapshot);
      this.render();
      return;
    }
    Utils.toast(nextId ? "默认样机池已保存" : "已恢复为全部样机池");
  },

  addProjectLocation() {
    this.showModal("新增项目位置", `
      <div class="form-group"><label class="req modal-field-title">位置名称</label><input id="projectLocationName" placeholder="如：溪村-D8-B1F-A08 / 武汉-A3-1F-03R"></div>
    `, async () => {
      this.clearFieldValidationMarks();
      const p = this.currentProject();
      if (!p) return;
      const snapshot = this.dataSnapshot();
      if (!Array.isArray(p.locations)) p.locations = [];
      const el = document.getElementById("projectLocationName");
      const name = el.value.trim();
      if (!name) { this.markFieldInvalid(el, "位置名称不能为空"); return true; }
      if (p.locations.some(x => String(x).trim() === name)) { this.markFieldInvalid(el, "该位置已存在。"); return true; }
      p.locations.push(name);
      const saved = await this.commitProjectMutation(p, { action: "add_project_location", remark: "新增项目位置", user: "管理员" });
      if (!saved) { this.restoreDataSnapshot(snapshot); return true; }
      Utils.toast("位置已新增");
      return false;
    }, "确认", { className: "modal-sm" });
  },

  editProjectLocation(index) {
    const p = this.currentProject();
    if (!p || !Array.isArray(p.locations) || !p.locations[index]) return;
    const currentName = p.locations[index];
    this.showModal("编辑项目位置", `
      <div class="form-group"><label class="req modal-field-title">位置名称</label><input id="projectLocationName" value="${Utils.esc(currentName)}" placeholder="如：溪村-D8-B1F-A08 / 武汉-A3-1F-03R"></div>
    `, async () => {
      this.clearFieldValidationMarks();
      const snapshot = this.dataSnapshot();
      const el = document.getElementById("projectLocationName");
      const name = el.value.trim();
      if (!name) { this.markFieldInvalid(el, "位置名称不能为空"); return true; }
      if (name !== currentName && p.locations.some((x, i) => i !== index && String(x).trim() === name)) {
        this.markFieldInvalid(el, "该位置已存在。"); return true;
      }
      p.locations[index] = name;
      const saved = await this.commitProjectMutation(p, { action: "update_project_location", remark: "编辑项目位置", user: "管理员" });
      if (!saved) { this.restoreDataSnapshot(snapshot); return true; }
      Utils.toast("位置已保存");
      return false;
    }, "确认", { className: "modal-sm" });
  },
  removeProjectLocation(index) {
    const p = this.currentProject();
    if (!p || !Array.isArray(p.locations) || !p.locations[index]) return;
    this.showConfirm(`确认删除位置 ${p.locations[index]}？`, async () => {
      const snapshot = this.dataSnapshot();
      p.locations.splice(index, 1);
      const saved = await this.commitProjectMutation(p, { action: "remove_project_location", remark: "删除项目位置", user: "管理员" });
      if (!saved) { this.restoreDataSnapshot(snapshot); return; }
      this.render();
      Utils.toast("位置已删除");
    }, { title: "删除位置", okText: "删除", okClass: "btn btn-danger" });
  },

  setProjectMemberSearch(value) {
    this.patchViewState({ memberSearch: value });
    const kw = String(value || "").trim().toLowerCase();
    document.querySelectorAll(".project-member-card[data-member-key]").forEach(row => {
      row.style.display = !kw || row.dataset.memberKey.includes(kw) ? "" : "none";
    });
  },
  validateProjectMember(name, employeeNo = "") {
    const text = String(employeeNo || "").trim() ? Utils.personText(name, employeeNo) : String(name || "").trim();
    const parsed = Utils.parsePersonField(text);
    return { ok: parsed.ok, name: parsed.name, employeeNo: parsed.employeeNo, msg: parsed.msg };
  },
  findProjectMemberByIdentity(project, name, employeeNo) {
    const key = Utils.memberIdentityKey(name, employeeNo);
    return (project?.members || []).find(m => Utils.memberIdentityKey(m.name, m.employeeNo) === key);
  },
  hasProjectMemberNameConflict(project, name, employeeNo, excludeId = "") {
    const cleanName = String(name || "").trim();
    const cleanNo = Utils.normalizeEmployeeNoKey(employeeNo || "");
    return (project?.members || []).some(m => {
      if (m.active === false || m.id === excludeId) return false;
      if (String(m.name || "").trim() !== cleanName) return false;
      const otherNo = Utils.normalizeEmployeeNoKey(m.employeeNo || "");
      return !cleanNo || !otherNo;
    });
  },
  addProjectMember() {
    this.showModal("新增项目人员", `
      <div class="form-group"><label class="req modal-field-title">人员</label><input id="memberText" placeholder="姓名/工号，如：张三/00609513"></div>
      <div class="form-hint">人员必须按「姓名/工号」填写，姓名和工号都不能为空。</div>
    `, async () => {
      this.clearFieldValidationMarks();
      const p = this.currentProject();
      if (!p) return;
      const snapshot = this.dataSnapshot();
      if (!Array.isArray(p.members)) p.members = [];
      const memberEl = document.getElementById("memberText");
      const check = this.validateProjectMember(memberEl.value);
      if (!check.ok) { this.markFieldInvalid(memberEl, check.msg); return true; }
      if (this.hasProjectMemberNameConflict(p, check.name, check.employeeNo)) {
        this.markFieldInvalid(memberEl, "项目中已存在同名人员。请为同名人员填写不同工号以区分。");
        return true;
      }
      const existing = this.findProjectMemberByIdentity(p, check.name, check.employeeNo);
      if (existing && existing.active !== false) { this.markFieldInvalid(memberEl, "该人员已在项目人员名单中，不能重复新增。"); return true; }
      if (existing) {
        existing.name = check.name;
        existing.employeeNo = check.employeeNo;
        existing.active = true;
      } else {
        p.members.push({ id: Utils.id("member_"), name: check.name, employeeNo: check.employeeNo, active: true });
      }
      const saved = await this.commitProjectMutation(p, { action: "add_project_member", remark: "新增项目人员", user: Utils.personText(check.name, check.employeeNo) });
      if (!saved) { this.restoreDataSnapshot(snapshot); return true; }
      Utils.toast("人员已新增");
      return false;
    }, "确认", { className: "modal-sm" });
  },
  editProjectMember(memberId) {
    const p = this.currentProject();
    const m = p?.members?.find(x => x.id === memberId);
    if (!m) return;
    const currentIdentity = Utils.personText(m.name, m.employeeNo);
    this.showModal("编辑项目人员", `
      <div class="form-group"><label class="req modal-field-title">人员</label><input id="memberText" value="${Utils.esc(currentIdentity)}" placeholder="姓名/工号，如：张三/00609513"></div>
      <div class="form-hint">人员必须按「姓名/工号」填写，姓名和工号都不能为空。</div>
    `, async () => {
      this.clearFieldValidationMarks();
      const snapshot = this.dataSnapshot();
      const memberEl = document.getElementById("memberText");
      const check = this.validateProjectMember(memberEl.value);
      if (!check.ok) { this.markFieldInvalid(memberEl, check.msg); return true; }
      if (this.hasProjectMemberNameConflict(p, check.name, check.employeeNo, m.id)) {
        this.markFieldInvalid(memberEl, "项目中已存在同名人员。请为同名人员填写不同工号以区分。");
        return true;
      }
      const existingOther = this.findProjectMemberByIdentity(p, check.name, check.employeeNo);
      if (existingOther && existingOther.id !== m.id && existingOther.active !== false) {
        this.markFieldInvalid(memberEl, "该人员已在项目人员名单中，不能重复。");
        return true;
      }
      m.name = check.name;
      m.employeeNo = check.employeeNo;
      const saved = await this.commitProjectMutation(p, { action: "update_project_member", remark: "编辑项目人员", user: Utils.personText(check.name, check.employeeNo) });
      if (!saved) { this.restoreDataSnapshot(snapshot); return true; }
      Utils.toast("人员已保存");
      return false;
    }, "确认", { className: "modal-sm" });
  },
  downloadProjectMembersTemplate() {
    Utils.downloadCsv([
      ["姓名/工号"],
      ["张三/00609513"],
      ["李四/wx517815"]
    ], "项目人员导入模板.csv");
  },
  importProjectMembersCsv() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".csv,text/csv";
    input.addEventListener("change", () => {
      const file = input.files?.[0]; if (!file) return;
      const reader = new FileReader();
      reader.addEventListener("load", async () => {
        const result = Utils.parseProjectMembersCsv(reader.result);
        if (result.error) { alert("人员名单导入失败：" + result.error); return; }
        const p = this.currentProject();
        if (!p) return;
        if (!Array.isArray(p.members)) p.members = [];
        let added = 0, restored = 0, skippedDup = 0;
        let skippedNameConflict = 0;
        const snapshot = this.dataSnapshot();
        result.rows.forEach(row => {
          const check = this.validateProjectMember(Utils.personText(row.name, row.employeeNo));
          if (!check.ok) { skippedNameConflict++; return; }
          if (this.hasProjectMemberNameConflict(p, check.name, check.employeeNo)) {
            skippedNameConflict++;
            return;
          }
          const existing = this.findProjectMemberByIdentity(p, check.name, check.employeeNo);
          if (existing) {
            if (existing.active !== false) {
              skippedDup++;
            } else {
              existing.name = check.name;
              existing.employeeNo = check.employeeNo;
              existing.active = true;
              restored++;
            }
          } else {
            p.members.push({ id: Utils.id("member_"), name: check.name, employeeNo: check.employeeNo, active: true });
            added++;
          }
        });
        const saved = await this.commitProjectMutation(p, { action: "import_project_members", remark: "批量导入项目人员", user: "管理员" });
        if (!saved) { this.restoreDataSnapshot(snapshot); return; }
        this.render();
        Utils.toast(`人员名单导入完成：新增 ${added} 人，恢复 ${restored} 人，重复跳过 ${skippedDup} 人，格式错误跳过 ${skippedNameConflict + (result.skipped || 0)} 行。`);
      }, { once: true });
      reader.readAsText(file, "utf-8");
    }, { once: true });
    input.click();
  },
  removeProjectMember(memberId) {
    const p = this.currentProject();
    const m = p?.members?.find(x => x.id === memberId);
    if (!m) return;
    this.showConfirm(`确认将 ${Utils.personText(m.name, m.employeeNo)} 移出项目人员名单？`, async () => {
      const snapshot = this.dataSnapshot();
      m.active = false;
      const saved = await this.commitProjectMutation(p, { action: "remove_project_member", remark: "移出项目人员", user: "管理员" });
      if (!saved) { this.restoreDataSnapshot(snapshot); return; }
      this.render();
      Utils.toast("人员已移出");
    }, { title: "移出人员", okText: "移出", okClass: "btn btn-danger" });
  },
  memberWorkStats(project, member, sampleOwnerCounts = null) {
    let tasks = 0;
    (project.stages || []).forEach(stage => {
      (stage.tasks || []).forEach(t => {
        const owner = String(t.owner || "");
        if (owner !== member.name && owner !== member.employeeNo && !owner.includes(member.name) && !owner.includes(member.employeeNo)) return;
        tasks++;
      });
    });
    const memberKey = Utils.memberIdentityKey(member.name, member.employeeNo);
    const ownedSamples = sampleOwnerCounts instanceof Map
      ? (sampleOwnerCounts.get(memberKey) || 0)
      : this.allSamples().filter(sample => Utils.personMatchesMember(sample.owner, member)).length;
    return { tasks, ownedSamples };
  },

  toggleStageSortMode() {
    this.setStageSortModeState(!this.stageSortMode());
    this.render();
  },
  onStageDragStart(ev, stageId) {
    if (!this.stageSortMode()) {
      ev.preventDefault();
      return;
    }
    this._dragStageId = stageId;
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", stageId);
    ev.currentTarget.classList.add("dragging");
  },
  onStageDragOver(ev, targetStageId) {
    if (!this.stageSortMode() || !this._dragStageId || this._dragStageId === targetStageId) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".stage-summary-card.drag-over")
      .forEach(el => { if (el !== ev.currentTarget) el.classList.remove("drag-over"); });
    ev.currentTarget.classList.add("drag-over");
  },
  onStageDragLeave(ev) {
    ev.currentTarget.classList.remove("drag-over");
  },
  onStageDrop(ev, targetStageId) {
    ev.preventDefault();
    const p = this.currentProject();
    const sourceStageId = this._dragStageId || ev.dataTransfer.getData("text/plain");
    if (!p || !sourceStageId || sourceStageId === targetStageId) return;

    const fromIdx = p.stages.findIndex(st => st.id === sourceStageId);
    const targetIdx = p.stages.findIndex(st => st.id === targetStageId);
    if (fromIdx < 0 || targetIdx < 0) return;

    const dataSnapshot = this.dataSnapshot();
    const rect = ev.currentTarget.getBoundingClientRect();
    const insertAfter = ev.clientX > rect.left + rect.width / 2;
    const [moved] = p.stages.splice(fromIdx, 1);
    let insertIdx = targetIdx + (insertAfter ? 1 : 0);
    if (fromIdx < insertIdx) insertIdx -= 1;
    p.stages.splice(insertIdx, 0, moved);
    this._dragStageId = null;
    this.commitStageMutation(p, moved, {
      action: "reorder_stages",
      remark: "阶段排序",
      user: "管理员",
      render: false
    }).then(saved => {
      if (!saved) {
        this.restoreDataSnapshot(dataSnapshot);
        this.render();
      }
    });
    this.render();
  },
  onStageDragEnd() {
    this._dragStageId = null;
    document.querySelectorAll(".stage-summary-card.dragging,.stage-summary-card.drag-over")
      .forEach(el => el.classList.remove("dragging", "drag-over"));
  }

});
