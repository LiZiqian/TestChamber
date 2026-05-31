/* ========================================
   数字治理平台 V7 - 阶段与SKU编辑模块
   ======================================== */

Object.assign(app, {

  // ==================== 阶段 CRUD ====================
  inlineStageEditorHtml(stage) {
    const skuNames = stage.skuNames?.length ? stage.skuNames : ["SKU1"];
    return `
      <div class="inline-stage-name">
        <label>阶段名称<span class="req-star">*</span></label>
        <input id="inlineStageName" value="${Utils.esc(stage.name || "")}" oninput="app.updateInlineStageName(this.value)" onblur="app.normalizeInlineStageName(this)">
      </div>
      <div class="inline-sku-editor">
        <label>方案（SKU）设置<span class="req-star">*</span></label>
        <div id="inlineSkuList">
          ${skuNames.map((name, idx) => this.inlineSkuRowHtml(name, idx)).join("")}
        </div>
        <button type="button" class="btn btn-sm btn-outline" onclick="app.addInlineSku()">+ 增加方案名称(SKU)</button>
      </div>`;
  },
  inlineSkuRowHtml(name = "", idx = 0) {
    return `<div class="inline-sku-row">
      <div class="idx">#${idx + 1}</div>
      <input class="inline-sku-name-input" value="${Utils.esc(name || "")}" placeholder="输入方案名" oninput="app.updateInlineSkus()" onblur="app.normalizeInlineSkus()">
      <button type="button" class="icon-btn" onclick="app.removeInlineSku(this)">−</button>
    </div>`;
  },
  updateInlineStageName(value) {
    const s = this.currentStage();
    if (!s) return;
    s.name = String(value || "").trim();
    this.scheduleSave();
    this.renderHeader();
  },
  normalizeInlineStageName(input) {
    const s = this.currentStage();
    if (!s || !input) return;
    const name = String(input.value || "").trim();
    if (!name) {
      input.value = s.name || "阶段";
      return;
    }
    s.name = name;
    this.save();
    this.renderHeader();
  },
  readInlineSkuInputs() {
    return [...document.querySelectorAll("#inlineSkuList .inline-sku-name-input")]
      .map(x => x.value.trim())
      .filter(Boolean);
  },
  updateInlineSkus() {
    const s = this.currentStage();
    if (!s) return;
    const names = this.readInlineSkuInputs();
    if (!names.length) return;
    s.skuNames = names;
    this.scheduleSave();
  },
  normalizeInlineSkus() {
    const s = this.currentStage();
    if (!s) return;
    const names = this.readInlineSkuInputs();
    if (!names.length) {
      s.skuNames = ["SKU1"];
      this.render();
      return;
    }
    s.skuNames = names;
    this.save();
    this.render();
  },
  addInlineSku(value = "") {
    const s = this.currentStage();
    if (!s) return;
    const list = document.getElementById("inlineSkuList");
    if (list) {
      const idx = list.querySelectorAll(".inline-sku-row").length;
      const wrapper = document.createElement("div");
      wrapper.innerHTML = this.inlineSkuRowHtml(value, idx).trim();
      list.appendChild(wrapper.firstElementChild);
      this.refreshInlineSkuIndexes();
      return;
    }
    if (!Array.isArray(s.skuNames) || !s.skuNames.length) s.skuNames = [];
    if (value) s.skuNames.push(value);
    this.save();
    this.render();
  },
  removeInlineSku(btn) {
    const s = this.currentStage();
    if (!s || !Array.isArray(s.skuNames)) return;
    const row = btn.closest(".inline-sku-row");
    const rows = [...document.querySelectorAll("#inlineSkuList .inline-sku-row")];
    const idx = rows.indexOf(row);
    if (rows.length <= 1) { alert("至少保留一个 SKU"); return; }
    row?.remove();
    const names = this.readInlineSkuInputs();
    s.skuNames = names.length ? names : (s.skuNames.length ? s.skuNames : ["SKU1"]);
    this.save();
    this.render();
  },
  refreshInlineSkuIndexes() {
    document.querySelectorAll("#inlineSkuList .inline-sku-row").forEach((row, idx) => {
      const label = row.querySelector(".idx");
      if (label) label.innerText = "#" + (idx + 1);
    });
  },

  skuEditorHtml(names, options = {}) {
    const placeholder = options.placeholder || "输入方案名，如：主方案、A1、B7";
    const rows = (names || ["SKU1"]).map((name, idx) => `
      <div class="sku-row">
        <div class="idx">#${idx + 1}</div>
        <input class="sku-name-input" value="${Utils.esc(name || "")}" placeholder="${Utils.esc(placeholder)}">
        <button type="button" class="icon-btn" onclick="app.removeSkuInput(this)">−</button>
      </div>
    `).join("");
    return `<div class="sku-editor"><div id="skuList">${rows}</div>
      <button type="button" class="btn btn-sm btn-outline" onclick="app.addSkuInput()">+ 增加方案名称(SKU)</button></div>`;
  },
  addSkuInput(value = "") {
    const list = document.getElementById("skuList"); if (!list) return;
    const idx = list.querySelectorAll(".sku-row").length + 1;
    const div = document.createElement("div"); div.className = "sku-row";
    div.innerHTML = `<div class="idx">#${idx}</div><input class="sku-name-input" value="${Utils.esc(value)}" placeholder="输入方案名，如：主方案、A1、B7"><button type="button" class="icon-btn" onclick="app.removeSkuInput(this)">−</button>`;
    list.appendChild(div); this.refreshSkuIndexes();
  },
  removeSkuInput(btn) {
    const list = document.getElementById("skuList"); if (!list) return;
    if (list.querySelectorAll(".sku-row").length <= 1) { alert("至少保留一个 SKU"); return; }
    btn.closest(".sku-row").remove(); this.refreshSkuIndexes();
  },
  refreshSkuIndexes() {
    document.querySelectorAll("#skuList .sku-row").forEach((row, idx) => {
      const label = row.querySelector(".idx"); if (label) label.innerText = "#" + (idx + 1);
    });
  },
  readSkuInputs() {
    return [...document.querySelectorAll("#skuList .sku-name-input")].map(x => x.value.trim()).filter(Boolean);
  },

  addStage() {
    this.showModal("新建阶段", `
      <div class="form-group"><label class="req modal-field-title">阶段名称</label><input id="stageName" placeholder="输入阶段名称，如：V1、V3-1、VN1、VN2"></div>
      <div class="form-group"><label class="req modal-field-title">方案（SKU）设置</label>${this.skuEditorHtml(["", ""], { placeholder: "输入方案名，如：主方案、A1、B7" })}</div>
    `, () => {
      this.clearFieldValidationMarks();
      const p = this.currentProject();
      const stageNameEl = document.getElementById("stageName");
      const name = stageNameEl.value.trim();
      if (!name) { this.markFieldInvalid(stageNameEl, "阶段名称不能为空"); return true; }
      const skuNames = this.readSkuInputs();
      if (!skuNames.length) {
        const skuInput = document.querySelector(".sku-name-input");
        this.markFieldInvalid(skuInput || stageNameEl, "请至少输入一个方案名称");
        return true;
      }
      if (new Set(skuNames).size !== skuNames.length) {
        const skuInput = document.querySelector(".sku-name-input");
        this.markFieldInvalid(skuInput || stageNameEl, "方案名称不能重复");
        return true;
      }
      const s = { id: Utils.id("stage_"), name, skuNames, bom: [], strategy: [], progress: [], tasks: [] };
      p.stages.push(s);
      this.view.selectedStageId = s.id;
      this.save(); this.render();
    });
  },

  editStage(id) {
    const s = this.currentProject()?.stages.find(x => x.id === id);
    if (!s) return;
    this.showModal("编辑阶段与 SKU", `
      <div class="form-group"><label class="req modal-field-title">阶段名称</label><input id="stageName" value="${Utils.esc(s.name)}"></div>
      <div class="form-group"><label class="req modal-field-title">方案（SKU）设置</label>${this.skuEditorHtml(s.skuNames?.length ? s.skuNames : ["SKU1"], { placeholder: "输入方案名" })}</div>
    `, () => {
      this.clearFieldValidationMarks();
      const stageNameEl = document.getElementById("stageName");
      const name = stageNameEl.value.trim();
      if (!name) { this.markFieldInvalid(stageNameEl, "阶段名称不能为空"); return true; }
      const skuNames = this.readSkuInputs();
      if (!skuNames.length) {
        const skuInput = document.querySelector(".sku-name-input");
        this.markFieldInvalid(skuInput || stageNameEl, "至少保留一个 SKU");
        return true;
      }
      s.name = name; s.skuNames = skuNames;
      this.save(); this.render();
    });
  },

  deleteStage(id) {
    const p = this.currentProject();
    if (!p) return;
    const stage = (p.stages || []).find(s => s.id === id);
    if (!stage) return;
    // 安全机制：阶段下存在「进行中/未完成」任务且占用样机时，禁止直接删除，避免样机占用状态丢失
    const tasks = (stage.tasks || []).filter(t => !t.archived);
    const activeTasks = tasks.filter(t => !this.isTaskCompleted(t));
    const occupyingTasks = activeTasks.filter(t => (t.sampleIds || []).length > 0);
    if (occupyingTasks.length) {
      const names = occupyingTasks.map(t => t.testItem || "未命名任务").slice(0, 5).join("、");
      alert(`无法删除阶段「${stage.name}」：该阶段存在 ${occupyingTasks.length} 个未完成且占用样机的任务（${names}${occupyingTasks.length > 5 ? " 等" : ""}）。\n\n请先结束或释放这些任务的样机后再删除阶段。`);
      return;
    }
    const taskCount = tasks.length;
    const extraWarn = taskCount
      ? `\n\n该阶段含 ${taskCount} 个任务及其测试履历/日志，删除后不可恢复。`
      : "";
    this.showConfirm(`确认删除阶段「${stage.name}」？${extraWarn}`, () => {
      // 只释放未完成任务占用的样机；已完成任务的样机状态不变。
      const affectedSampleIds = new Set();
      activeTasks.forEach(t => (t.sampleIds || []).forEach(id => affectedSampleIds.add(id)));
      p.stages = p.stages.filter(s => s.id !== id);
      this.view.selectedStageId = p.stages[0]?.id || null;
      affectedSampleIds.forEach(id => {
        if (typeof this.isSampleUsedByAnotherOpenTask === "function"
            && !this.isSampleUsedByAnotherOpenTask(id, null)
            && typeof this.changeSampleStatus === "function") {
          this.changeSampleStatus(id, "闲置", { user: "管理员", source: "删除阶段", reason: `删除阶段「${stage.name}」回收样机` });
        }
      });
      this.save(); this.render();
    }, { title: "删除阶段", okText: "删除", okClass: "btn btn-danger" });
  },
  copyStage(id) {
    const p = this.currentProject();
    const source = p?.stages?.find(s => s.id === id);
    if (!p || !source) return;
    this.showModal("复制阶段", `
      <div class="form-group">
        <label class="req modal-field-title">新阶段名称</label>
        <input id="copyStageName" placeholder="可自定义阶段名称，如：V2-1，V3 等">
      </div>
    `, () => {
      this.clearFieldValidationMarks();
      const copyNameEl = document.getElementById("copyStageName");
      const name = copyNameEl.value.trim();
      if (!name) { this.markFieldInvalid(copyNameEl, "阶段名称不能为空"); return true; }
      if (p.stages.some(s => s.name === name)) { this.markFieldInvalid(copyNameEl, "阶段名称已存在"); return true; }

      const cloned = JSON.parse(JSON.stringify(source));
      cloned.id = Utils.id("stage_");
      cloned.name = name;
      cloned.bom = (cloned.bom || []).map(row => ({ ...row }));
      const strategyIdMap = new Map();
      cloned.strategy = (cloned.strategy || []).map(row => {
        const newId = Utils.id("strat_");
        strategyIdMap.set(row.id, newId);
        return { ...row, id: newId };
      });
      cloned.progress = (cloned.progress || []).map(item => ({
        ...item,
        id: Utils.id("prog_"),
        strategyId: strategyIdMap.get(item.strategyId) || item.strategyId,
        status: "待启动",
        owner: "",
        startDate: "",
        endDate: "",
        issue: "",
        sampleIds: []
      }));
      cloned.tasks = [];

      const sourceIdx = p.stages.findIndex(s => s.id === id);
      p.stages.splice(sourceIdx + 1, 0, cloned);
      this.view.selectedStageId = cloned.id;
      this.save(); this.render();
      Utils.toast(`已复制阶段：${name}`);
    });
  },

});
