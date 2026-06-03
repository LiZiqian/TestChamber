/* ========================================
   数字治理平台 V7 - 项目工作台主页模块
   ======================================== */

Object.assign(app, {

  // ==================== 项目工作台主页 ====================
  renderProjectWorkspace() {
    const p = this.currentProject();
    if (!p) { this.renderEmpty("请先在项目管理中新建项目"); return; }
    if (this.view.stageStrategyId) { this.renderStageStrategyPage(); return; }

    if (p.stages.length && (!this.view.selectedStageId || !p.stages.some(st => st.id === this.view.selectedStageId)))
      this.view.selectedStageId = p.stages[0].id;
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
    const sortMode = !!this.view.stageSortMode;

    // 阶段卡片（融合进度看板信息）
    const stageCards = stageStats.map(x => {
      const pct = x.total ? ((x.pass / x.total) * 100).toFixed(0) : 0;
      const cardAttrs = sortMode
        ? `data-stage-id="${x.stage.id}" draggable="true" ondragstart="app.onStageDragStart(event,'${x.stage.id}')" ondragover="app.onStageDragOver(event,'${x.stage.id}')" ondragleave="app.onStageDragLeave(event)" ondrop="app.onStageDrop(event,'${x.stage.id}')" ondragend="app.onStageDragEnd(event)"`
        : `onclick="app.view.selectedStageId='${x.stage.id}';app.render()"`;
      return `
      <div class="stage-summary-card ${x.stage.id === s?.id ? 'active' : ''} ${sortMode ? 'is-sorting' : ''}" ${cardAttrs}>
        <div class="stage-summary-title">
          <div class="stage-summary-name-row">
            <span>${Utils.esc(x.stage.name)}</span>
            ${sortMode ? '' : `<button type="button" class="btn btn-sm btn-purple stage-config-btn" onclick="event.stopPropagation();app.openStageStrategy('${x.stage.id}')">配置测试用例集</button>`}
          </div>
          <div class="stage-summary-actions">
            ${sortMode
              ? '<span class="stage-sort-hint">拖动排序</span>'
              : `<button type="button" class="sample-card-destroy-btn" style="position:static" onclick="event.stopPropagation();app.deleteStage('${x.stage.id}')" title="删除此阶段">🗑</button>
                <button type="button" style="background:none;border:none;font-size:18px;font-weight:900;opacity:0.75;color:#4b5563;cursor:pointer;padding:2px;line-height:1;margin-left:2px;transition:opacity .15s" title="复制为一个新阶段" aria-label="复制为一个新阶段" onclick="event.stopPropagation();app.copyStage('${x.stage.id}')">🗐</button>`}
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
      <div class="card add-card" onclick="app.addStage()" title="新增阶段">
        <div class="add-card-plus">+</div>
        <div class="add-card-label">新增阶段</div>
      </div>`;

    const sampleOwnerCounts = this.sampleOwnerCountsByMemberKey();
    document.getElementById("content").innerHTML = `
      <div class="card project-config-card">
        <div class="project-config-intro">
          <h2>项目配置工作台</h2>
          <p>项目需首先完成阶段配置、人员配置与位置配置。</p>
        </div>
        <div class="project-config-section ${this.isCollapsed('stage') ? 'is-collapsed' : ''}">
          <div class="stage-summary-section-head">
            ${this.sectionToggleTriangle('stage')}
            <div class="stage-summary-section-title">项目阶段与方案配置</div>
            <button type="button" class="btn btn-sm ${sortMode ? 'stage-sort-done' : 'btn-outline'} stage-sort-toggle stage-sort-toggle-right" onclick="app.toggleStageSortMode()">${sortMode ? '完成排序' : '手动拖动排序'}</button>
          </div>
          <div class="stage-summary-section-desc">点击 <配置测试用例集> 可为该阶段配置测试用例池，并在 <任务管理> 中下发用例任务。</div>
          <div class="project-config-body">
            <div class="stage-cards-row">
              <div class="stage-summary-grid">${stageCards}${addStageCard}</div>
            </div>
          </div>
        </div>
        ${this.workspaceMembersHtml(p, sampleOwnerCounts)}
        ${this.workspaceLocationsHtml(p)}
      </div>

      ${s ? `<div class="card workspace-section section-green ${this.isCollapsed('taskFlow') ? 'is-collapsed' : ''}">${this.workspaceTaskFlowHtml(p, s)}</div>` : ''}
    `;
  },

  sampleOwnerCountsByMemberKey() {
    const counts = new Map();
    (this.data?.sampleLibrary?.categories || []).forEach(category => {
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
          <div class="project-member-card" ondblclick="app.editProjectMember('${m.id}')">
            <div class="project-member-identity">${Utils.esc(identity || "-")}</div>
            <div class="project-member-stat">${stat.tasks} 项 / ${stat.hours.toFixed(1)}h · 挂账 ${stat.ownedSamples} 台</div>
            <span class="project-member-remove" onclick="event.stopPropagation();app.removeProjectMember('${m.id}')" title="移出人员">🗑</span>
          </div>`;
      }).join("");

    return `
      <div class="project-config-section project-members-section ${collapsed ? 'is-collapsed' : ''}">
        <div class="stage-summary-section-head">
          ${this.sectionToggleTriangle('members')}
          <div class="stage-summary-section-title">人员配置</div>
          <div class="project-members-head-actions">
            <button class="btn btn-sm btn-outline" onclick="app.downloadProjectMembersTemplate()">下载导入模板</button>
            <button class="btn btn-sm" onclick="app.importProjectMembersCsv()">批量导入人员名单</button>
          </div>
        </div>
        <div class="stage-summary-section-desc">配置项目参与人员，后续可在任务管理中选择执行人和操作人。共 ${activeMembers.length} 人</div>
        <div class="project-members-body">
          <div class="project-members-grid">
            ${rows}
            <div class="card add-card" onclick="app.addProjectMember()">
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
      <div class="project-location-card" ondblclick="app.editProjectLocation(${idx})">
        <b>${Utils.esc(loc)}</b>
        <span class="project-location-remove" onclick="event.stopPropagation();app.removeProjectLocation(${idx})" title="删除位置">🗑</span>
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
            <div class="card add-card" onclick="app.addProjectLocation()">
              <div class="add-card-plus">+</div>
              <div class="add-card-label">新增位置</div>
            </div>
          </div>
        </div>
      </div>`;
  },

  addProjectLocation() {
    this.showModal("新增项目位置", `
      <div class="form-group"><label class="req modal-field-title">位置名称</label><input id="projectLocationName" placeholder="如：溪村-D8-B1F-A08 / 武汉-A3-1F-03R"></div>
    `, async () => {
      this.clearFieldValidationMarks();
      const p = this.currentProject();
      if (!p) return;
      const snapshot = this.cloneData(this.data);
      if (!Array.isArray(p.locations)) p.locations = [];
      const el = document.getElementById("projectLocationName");
      const name = el.value.trim();
      if (!name) { this.markFieldInvalid(el, "位置名称不能为空"); return true; }
      if (p.locations.some(x => String(x).trim() === name)) { this.markFieldInvalid(el, "该位置已存在。"); return true; }
      p.locations.push(name);
      const saved = await this.commitProjectMutation(p, { action: "add_project_location", remark: "新增项目位置", user: "管理员" });
      if (!saved) { this.data = snapshot; return true; }
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
      const snapshot = this.cloneData(this.data);
      const el = document.getElementById("projectLocationName");
      const name = el.value.trim();
      if (!name) { this.markFieldInvalid(el, "位置名称不能为空"); return true; }
      if (name !== currentName && p.locations.some((x, i) => i !== index && String(x).trim() === name)) {
        this.markFieldInvalid(el, "该位置已存在。"); return true;
      }
      p.locations[index] = name;
      const saved = await this.commitProjectMutation(p, { action: "update_project_location", remark: "编辑项目位置", user: "管理员" });
      if (!saved) { this.data = snapshot; return true; }
      Utils.toast("位置已保存");
      return false;
    }, "确认", { className: "modal-sm" });
  },
  removeProjectLocation(index) {
    const p = this.currentProject();
    if (!p || !Array.isArray(p.locations) || !p.locations[index]) return;
    this.showConfirm(`确认删除位置 ${p.locations[index]}？`, async () => {
      const snapshot = this.cloneData(this.data);
      p.locations.splice(index, 1);
      const saved = await this.commitProjectMutation(p, { action: "remove_project_location", remark: "删除项目位置", user: "管理员" });
      if (!saved) { this.data = snapshot; return; }
      this.render();
      Utils.toast("位置已删除");
    }, { title: "删除位置", okText: "删除", okClass: "btn btn-danger" });
  },

  setProjectMemberSearch(value) {
    this.view.memberSearch = value;
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
      const snapshot = this.cloneData(this.data);
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
      if (!saved) { this.data = snapshot; return true; }
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
      const snapshot = this.cloneData(this.data);
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
      if (!saved) { this.data = snapshot; return true; }
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
    input.onchange = () => {
      const file = input.files?.[0]; if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {
        const result = Utils.parseProjectMembersCsv(reader.result);
        if (result.error) { alert("人员名单导入失败：" + result.error); return; }
        const p = this.currentProject();
        if (!p) return;
        if (!Array.isArray(p.members)) p.members = [];
        let added = 0, restored = 0, skippedDup = 0;
        let skippedNameConflict = 0;
        const snapshot = this.cloneData(this.data);
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
        if (!saved) { this.data = snapshot; return; }
        this.render();
        Utils.toast(`人员名单导入完成：新增 ${added} 人，恢复 ${restored} 人，重复跳过 ${skippedDup} 人，格式错误跳过 ${skippedNameConflict + (result.skipped || 0)} 行。`);
      };
      reader.readAsText(file, "utf-8");
    };
    input.click();
  },
  removeProjectMember(memberId) {
    const p = this.currentProject();
    const m = p?.members?.find(x => x.id === memberId);
    if (!m) return;
    this.showConfirm(`确认将 ${Utils.personText(m.name, m.employeeNo)} 移出项目人员名单？`, async () => {
      const snapshot = this.cloneData(this.data);
      m.active = false;
      const saved = await this.commitProjectMutation(p, { action: "remove_project_member", remark: "移出项目人员", user: "管理员" });
      if (!saved) { this.data = snapshot; return; }
      this.render();
      Utils.toast("人员已移出");
    }, { title: "移出人员", okText: "移出", okClass: "btn btn-danger" });
  },
  memberWorkStats(project, member, sampleOwnerCounts = null) {
    let tasks = 0, hours = 0;
    (project.stages || []).forEach(stage => {
      (stage.tasks || []).forEach(t => {
        const owner = String(t.owner || "");
        if (owner !== member.name && owner !== member.employeeNo && !owner.includes(member.name) && !owner.includes(member.employeeNo)) return;
        tasks++;
        const start = t.startedAt || t.startTime || t.startDate;
        const end = t.completedAt || t.endTime || t.endDate;
        if (start && end) {
          const diff = new Date(end).getTime() - new Date(start).getTime();
          if (Number.isFinite(diff) && diff > 0) hours += diff / 3600000;
        }
      });
    });
    const memberKey = Utils.memberIdentityKey(member.name, member.employeeNo);
    const ownedSamples = sampleOwnerCounts instanceof Map
      ? (sampleOwnerCounts.get(memberKey) || 0)
      : this.allSamples().filter(sample => Utils.personMatchesMember(sample.owner, member)).length;
    return { tasks, hours, ownedSamples };
  },

  toggleStageSortMode() {
    this.view.stageSortMode = !this.view.stageSortMode;
    this.render();
  },
  onStageDragStart(ev, stageId) {
    if (!this.view.stageSortMode) {
      ev.preventDefault();
      return;
    }
    this._dragStageId = stageId;
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", stageId);
    ev.currentTarget.classList.add("dragging");
  },
  onStageDragOver(ev, targetStageId) {
    if (!this.view.stageSortMode || !this._dragStageId || this._dragStageId === targetStageId) return;
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
      if (!saved) this.reloadFromServer();
    });
    this.render();
  },
  onStageDragEnd() {
    this._dragStageId = null;
    document.querySelectorAll(".stage-summary-card.dragging,.stage-summary-card.drag-over")
      .forEach(el => el.classList.remove("dragging", "drag-over"));
  }

});
