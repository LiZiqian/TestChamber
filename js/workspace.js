/* ========================================
   数字治理平台 V7 - 项目工作台模块
   含阶段配置·BOM·策略·任务管理
   ======================================== */

Object.assign(app, {

  // ==================== 阶段策略配置页 ====================
  openStageStrategy(stageId) {
    this.view.selectedStageId = stageId;
    this.view.stageStrategyId = stageId;
    this.view.module = "projectWorkspace";
    this.save();
    this.render();
  },

  closeStageStrategy() {
    // 自动同步策略进展
    this.autoSyncProgress();
    this.view.stageStrategyId = null;
    this.render();
  },

  leaveStageStrategy(targetModule = "projectWorkspace") {
    this.autoSyncProgress();
    this.view.stageStrategyId = null;
    this.view.module = targetModule;
    if (targetModule !== "projectWorkspace") this.view.selectedCategoryId = null;
    this.save();
    this.render();
  },

  renderStageStrategyPage() {
    const p = this.currentProject();
    const s = p?.stages.find(st => st.id === this.view.stageStrategyId) || this.currentStage();
    if (!p || !s) { this.view.stageStrategyId = null; this.render(); return; }
    this.view.selectedStageId = s.id;
    document.getElementById("content").innerHTML = `
      <div class="card stage-edit-panel">
        <div>
          <h3 style="margin:0">阶段与方案设置</h3>
          <div class="path">可随时修改阶段名称，并通过 + / - 调整该阶段包含的方案。</div>
        </div>
        <div class="inline-stage-editor">
          ${this.inlineStageEditorHtml(s)}
        </div>
      </div>
      <div class="card workspace-section section-purple">${this.workspaceBomHtml(s)}</div>
      <div class="card workspace-section section-purple">${this.workspaceStrategyHtml(s)}</div>
    `;
  },

  // ==================== BOM 上料清单（删除规格/说明列）====================
  workspaceBomHtml(stage) {
    const bomMinWidth = 56 + 320 + (stage.skuNames.length * 220) + 86;
    return `
      <div class="section-head">
        <div>
          <h3 style="margin:0">BOM 上料清单</h3>
          <div class="bom-desc">BOM 上料清单用于记录不同方案之间的物料组成差异。每一行代表一种物料或配置项，每一列代表一个方案。<br>STEP1：请先点击「新增物料」添加物料行。<br>STEP2：为每个方案录入物料、规格、版本、数量或差异说明。</div>
        </div>
        <button class="btn btn-sm" onclick="app.addBomRow()">+ 新增物料</button>
      </div>
      <div class="mini-table wide-table-scroll bom-table"><table class="bom-config-table" style="min-width:${bomMinWidth}px">
        <colgroup>
          <col class="col-row-no">
          <col class="col-bom-material">
          ${stage.skuNames.map(() => `<col class="col-bom-sku">`).join("")}
          <col class="col-action">
        </colgroup>
        <thead><tr>
          <th></th>
          <th style="color:var(--primary);font-weight:900">物料名称<span class="req-star">*</span></th>
          ${stage.skuNames.map(n => `<th style="color:var(--primary);font-weight:900">${Utils.esc(n)}</th>`).join("")}
          <th>操作</th>
        </tr></thead>
        <tbody>${(stage.bom || []).map((r, idx) => `
          <tr>
            <td class="row-no">${idx + 1}</td>
            <td><input value="${Utils.esc(r.materialName || "")}" onchange="app.updateBom(${idx},'materialName',this.value)" placeholder="必填"></td>
            ${stage.skuNames.map((n, i) => `<td><input value="${Utils.esc(r['sku' + (i + 1)] || "")}" onchange="app.updateBom(${idx},'sku${i + 1}',this.value)" placeholder="SKU/版本说明"></td>`).join("")}
            <td><button class="btn btn-sm btn-danger" onclick="app.deleteBomRow(${idx})">删除</button></td>
          </tr>`).join("") || `<tr><td colspan="${stage.skuNames.length + 3}" class="empty">暂无 BOM 物料</td></tr>`}</tbody>
      </table></div>`;
  },

  addBomRow() {
    const s = this.currentStage();
    if (!s.bom) s.bom = [];
    s.bom.push({ materialName: "" });
    this.save(); this.render();
  },
  updateBom(idx, field, val) {
    const s = this.currentStage();
    if (!s || !s.bom || !s.bom[idx]) return;
    s.bom[idx][field] = val;
    this.save();
  },
  deleteBomRow(idx) {
    const s = this.currentStage();
    if (!s || !s.bom) return;
    s.bom.splice(idx, 1);
    this.save(); this.render();
  },

  // ==================== 测试策略配置（删除"生成/同步进展"按钮）====================
  workspaceStrategyHtml(stage) {
    const p = this.currentProject();
    const caseCount = (p?.testCaseMaster || []).length;
    const strategyMinWidth = 56 + 236 + 276 + 140 + (stage.skuNames.length * 92) + 86;
    return `
      <div class="section-head">
        <div>
          <h3 style="margin:0">测试策略配置</h3>
          <div class="path">STEP1（可选）：可以手动导入一个测试用例集<br>STEP2：点击 <新增测试项>，在测试项列表中新增一行测试用例<br>STEP3：搜索选择或手动输入测试项<br>STEP4：勾选需要被执行的方案</div>
        </div>
        <div class="case-tools">
          <span class="case-master-badge">用例库：${caseCount} 条</span>
          <button class="btn btn-sm btn-outline" onclick="app.downloadTestCaseTemplate()">下载导入用例模板</button>
          <button class="btn btn-sm btn-outline" onclick="app.importTestCaseXlsx()">导入用例集</button>
        </div>
      </div>
      <div class="mini-table wide-table-scroll strategy-table"><table class="strategy-config-table" style="min-width:${strategyMinWidth}px">
        <colgroup>
          <col class="col-row-no">
          <col class="col-test-category">
          <col class="col-test-item">
          <col class="col-sample-size">
          ${stage.skuNames.map(() => `<col class="col-strategy-sku">`).join("")}
          <col class="col-action">
        </colgroup>
        <thead><tr>
          <th></th>
          <th style="color:var(--primary);font-weight:900">测量类别<span class="req-star">*</span></th>
          <th style="color:var(--primary);font-weight:900">用例名称<span class="req-star">*</span></th>
          <th style="color:var(--primary);font-weight:900">样机数<span class="req-star">*</span></th>
          ${stage.skuNames.map(n => `<th style="color:var(--primary);font-weight:900;text-align:center">${Utils.esc(n)}</th>`).join("")}
          <th>操作</th>
        </tr></thead>
        <tbody>${stage.strategy.map((r, idx) => `
          <tr data-strategy-row="${idx}">
            <td class="row-no">${idx + 1}</td>
            <td><input data-field="category" value="${Utils.esc(r.category || "")}" autocomplete="off"
              onfocus="app.openCaseDropdown(${idx},'category',this)"
              onclick="app.openCaseDropdown(${idx},'category',this)"
              oninput="app.onStrategyInput(${idx},'category',this);app.openCaseDropdown(${idx},'category',this)"
              placeholder="选择或输入"></td>
            <td><input data-field="item" value="${Utils.esc(r.item || "")}" autocomplete="off"
              onfocus="app.openCaseDropdown(${idx},'item',this)"
              onclick="app.openCaseDropdown(${idx},'item',this)"
              oninput="app.onStrategyInput(${idx},'item',this);app.openCaseDropdown(${idx},'item',this)"
              placeholder="搜索/选择/输入"></td>
            <td><input data-field="sampleSize" type="number" min="1" step="1" value="${Utils.esc(r.sampleSize || "")}"
              oninput="app.onStrategyInput(${idx},'sampleSize',this)"
              onblur="app.validateSampleSizeInput(this)" placeholder="正整数"></td>
            ${stage.skuNames.map((n, i) => `<td style="text-align:center;vertical-align:middle"><input data-sku="${i + 1}" type="checkbox" style="width:auto;vertical-align:middle" ${r.skuMap?.[i + 1] ? 'checked' : ''} onchange="app.updateStrategySku(${idx},${i + 1},this.checked)"></td>`).join("")}
            <td><button class="btn btn-sm btn-danger" onclick="app.deleteStrategyRow(${idx})">删除</button></td>
          </tr>`).join("") || `<tr><td colspan="${stage.skuNames.length + 5}" class="empty">暂无策略。先新增测试项。</td></tr>`}</tbody>
      </table></div>
        <div class="task-add-footer">
          <button class="task-add-main" onclick="app.addStrategyRow()">
            <span class="row-action-btn row-add-btn"></span>
            <span>新增测试项</span>
          </button>
        </div>`;
  },

  addStrategyRow() {
    const s = this.currentStage();
    s.strategy.push({ id: Utils.id("strat_"), category: "", item: "", sampleSize: 1, skuMap: { 1: true } });
    this.save(); this.render();
  },
  onStrategyInput(idx, field, el) {
    const s = this.currentStage();
    if (!s || !s.strategy[idx]) return;
    s.strategy[idx][field] = field === 'sampleSize' ? Utils.parsePositiveInt(el.value) : el.value;
    if (field === 'sampleSize') el.classList.toggle('invalid', Utils.parsePositiveInt(el.value) === null && String(el.value || '').trim() !== '');
    // P1.6：方案输入实时静默同步到 progress，避免折叠/关页/导航前未同步导致工作台进度丢失
    this.scheduleStrategySync();
    this.scheduleSave();
  },
  validateSampleSizeInput(el) {
    const n = Utils.parsePositiveInt(el.value);
    el.classList.toggle('invalid', n === null && String(el.value || '').trim() !== '');
    if (n !== null) el.value = String(n);
  },
  updateStrategySku(idx, sku, val) {
    const s = this.currentStage();
    if (!s.strategy[idx].skuMap) s.strategy[idx].skuMap = {};
    s.strategy[idx].skuMap[sku] = val;
    // P1.6：SKU 勾选立刻同步到进度并保存
    this.autoSyncProgress();
    this.save();
  },

  /** P1.6：方案输入实时静默同步到 progress（节流），避免离开页面/关闭浏览器时丢同步。 */
  scheduleStrategySync(delay = 800) {
    clearTimeout(this._strategySyncTimer);
    this._strategySyncTimer = setTimeout(() => {
      this._strategySyncTimer = null;
      if (!this.view.stageStrategyId) return;
      try { this.autoSyncProgress(); } catch (e) { console.warn("autoSyncProgress 静默同步失败：", e); }
    }, delay);
  },
  deleteStrategyRow(idx) {
    const s = this.currentStage();
    s.strategy.splice(idx, 1);
    this.save(); this.render();
  },

  syncStrategyFromDom() {
    const s = this.currentStage();
    if (!s) return;
    document.querySelectorAll('tr[data-strategy-row]').forEach(tr => {
      const idx = Number(tr.dataset.strategyRow);
      const r = s.strategy[idx];
      if (!r) return;
      const category = tr.querySelector('input[data-field="category"]');
      const item = tr.querySelector('input[data-field="item"]');
      const sampleSize = tr.querySelector('input[data-field="sampleSize"]');
      if (category) r.category = category.value.trim();
      if (item) r.item = item.value.trim();
      if (sampleSize) r.sampleSize = Utils.normalizeDigits(sampleSize.value);
      if (!r.skuMap) r.skuMap = {};
      tr.querySelectorAll('input[data-sku]').forEach(cb => { r.skuMap[cb.dataset.sku] = cb.checked; });
    });
  },

  /** 自动同步进展（返回工作台时调用，静默执行）*/
  autoSyncProgress() {
    const s = this.currentStage();
    if (!s) return;
    this.syncStrategyFromDom();

    const expected = new Map();
    s.strategy.forEach(r => {
      const n = Utils.parsePositiveInt(r.sampleSize);
      r.sampleSize = n === null ? Utils.normalizeDigits(r.sampleSize) : n;
      if (!r.item || n === null) return;
      s.skuNames.forEach((skuName, i) => {
        const sku = i + 1;
        if (r.skuMap?.[sku]) expected.set(`${r.id}_${sku}`, { strategyId: r.id, testItem: r.item, category: r.category, skuIndex: sku, sampleSize: n });
      });
    });

    let kept = [], addedCount = 0, removedCount = 0;
    (s.progress || []).forEach(p => {
      const key = `${p.strategyId}_${p.skuIndex}`;
      if (expected.has(key)) { kept.push({ ...p, ...expected.get(key) }); expected.delete(key); }
      else removedCount++;
    });
    expected.forEach(v => {
      kept.push({ id: Utils.id("prog_"), ...v, status: "待启动", owner: "", startDate: "", endDate: "", issue: "", sampleIds: [] });
      addedCount++;
    });
    s.progress = kept;

    if (addedCount || removedCount) {
      this.save();
      Utils.toast(`进展已自动同步：新增 ${addedCount}，移除 ${removedCount}，当前 ${s.progress.length} 条。`);
    }
  },

  downloadTestCaseTemplate() {
    const a = document.createElement("a");
    a.href = "/templates/用例集导入模板.xlsx";
    a.download = "用例集导入模板.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  },

  async importTestCaseXlsx() {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file) return;
      try {
        const buffer = await file.arrayBuffer();
        const files = await Utils.unzipXlsxFiles(buffer);
        const sharedStrings = Utils.parseXlsxSharedStrings(files["xl/sharedStrings.xml"] || "");
        const sheetPath = Object.keys(files).find(x => /^xl\/worksheets\/sheet\d+\.xml$/i.test(x));
        if (!sheetPath) { alert("XLSX中没有找到工作表。"); return; }
        const matrix = Utils.parseXlsxSheet(files[sheetPath], sharedStrings, new Set());
        const rows = [];
        for (let i = 1; i < matrix.length; i++) {
          const cols = matrix[i] || [];
          const category = String(cols[0] || "").trim();
          const item = String(cols[1] || "").trim();
          if (!category || !item) continue;
          if (category.startsWith("如：") || category === "测试大类") continue;
          rows.push({ category, item });
        }
        const p = this.currentProject();
        if (!p) { alert("请先选择一个项目。"); return; }
        p.testCaseMaster = rows;
        this.save();
        Utils.toast(`已导入 ${rows.length} 条测试用例。`);
        this.render();
      } catch (e) {
        alert("导入用例集失败：" + (e.message || e));
      }
    };
    input.click();
  },

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
    this.showConfirm("确认删除该阶段？", () => {
      p.stages = p.stages.filter(s => s.id !== id);
      this.view.selectedStageId = p.stages[0]?.id || null;
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

  workspaceTaskFlowHtml(project, stage) {
    const f = this.view.taskFlowFilters || {};
    const allRows = this.taskRowsForStage(stage);
    const match = (actual, expected) => !expected || String(actual || "") === String(expected);
    const catKw = String(f.categoryKeyword || "").trim().toLowerCase();
    const caseKw = String(f.caseKeyword || "").trim().toLowerCase();
    const dtsKw = String(f.dtsKeyword || "").trim().toLowerCase();
    const resultKw = String(f.resultKeyword || "").trim().toLowerCase();
    const filtered = allRows.filter(row => {
      const i = this.taskInfoForRow(stage, row);
      if (!match(i.sku, f.sku)) return false;
      if (catKw && !i.category.toLowerCase().includes(catKw)) return false;
      if (caseKw && !i.testItem.toLowerCase().includes(caseKw)) return false;
      if (!match(i.ownerName, f.ownerName)) return false;
      if (!match(i.flowStatus, f.flowStatus)) return false;
      if (dtsKw) {
        const dtsNo = String(row.task?.issueRecord?.dtsNo || "").toLowerCase();
        if (!dtsNo.includes(dtsKw)) return false;
      }
      if (resultKw) {
        const searchText = this.taskResultSearchText(project, stage, row.task);
        if (!searchText.includes(resultKw)) return false;
      }
      return true;
    });
    const rows = filtered;

    const pendingTasks = allRows.filter(row => this.taskInfoForRow(stage, row).flowStatus === "待下发").length;
    const runningTasks = allRows.filter(row => this.taskInfoForRow(stage, row).flowStatus === "进行中").length;
    const blockedTasks = allRows.filter(row => this.taskInfoForRow(stage, row).flowStatus === "阻塞中").length;
    const abnormalTasks = allRows.filter(row => this.taskInfoForRow(stage, row).flowStatus === "异常终止").length;
    const finishedTasks = allRows.filter(row => this.taskInfoForRow(stage, row).flowStatus === "正常完成").length;

    const infos = allRows.map(row => this.taskInfoForRow(stage, row));
    const optHtml = (values, cur) => {
      const arr = [...new Set((values || []).map(v => String(v ?? "").trim()).filter(v => v))].sort((a, b) => a.localeCompare(b, 'zh-CN', { numeric: true }));
      return `<option value="">全部</option>` + arr.map(v => `<option value="${Utils.esc(v)}" ${String(cur || "") === v ? 'selected' : ''}>${Utils.esc(v)}</option>`).join("");
    };

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
          <div class="task-flow-stat stat-total"><b>${allRows.length}</b><span>总任务数</span></div>
          <div class="task-flow-stat stat-pending"><b>${pendingTasks}</b><span>待下发</span></div>
          <div class="task-flow-stat stat-running"><b>${runningTasks}</b><span>进行中</span></div>
          <div class="task-flow-stat stat-blocked"><b>${blockedTasks}</b><span>阻塞中</span></div>
          <div class="task-flow-stat stat-bad"><b>${abnormalTasks}</b><span>异常终止</span></div>
          <div class="task-flow-stat stat-done"><b>${finishedTasks}</b><span>正常完成</span></div>
        </div>
        <div class="task-filter-bar">
          <div class="task-filter-item">
            <label>方案(SKU)</label>
            <select onchange="app.setTaskFlowFilter('sku',this.value)">${optHtml(infos.map(i => i.sku), f.sku)}</select>
          </div>
          <div class="task-filter-item">
            <label>类别搜索</label>
            <input type="text" value="${Utils.esc(f.categoryKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('categoryKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'categoryKeyword',this.value)">
          </div>
          <div class="task-filter-item">
            <label>用例搜索</label>
            <input type="text" value="${Utils.esc(f.caseKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('caseKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'caseKeyword',this.value)">
          </div>
          <div class="task-filter-item">
            <label>执行人</label>
            <select onchange="app.setTaskFlowFilter('ownerName',this.value)">${optHtml(infos.map(i => i.ownerName), f.ownerName)}</select>
          </div>
          <div class="task-filter-item">
            <label>状态</label>
            <select onchange="app.setTaskFlowFilter('flowStatus',this.value)">${optHtml(["待下发", "进行中", "阻塞中", "异常终止", "正常完成"], f.flowStatus)}</select>
          </div>
          <div class="task-filter-item">
            <label>DTS单号</label>
            <input type="text" value="${Utils.esc(f.dtsKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('dtsKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'dtsKeyword',this.value)">
          </div>
          <div class="task-filter-item">
            <label>测试结果关键词</label>
            <input type="text" value="${Utils.esc(f.resultKeyword || "")}" placeholder="回车搜索" oninput="app.setTaskFlowTextFilter('resultKeyword',this.value)" onkeydown="app.handleTaskFlowTextFilterKeydown(event,'resultKeyword',this.value)">
          </div>
          <div class="task-filter-actions">
            <button class="btn btn-sm btn-outline" onclick="app.clearTaskFlowFilters()">清空筛选</button>
          </div>
        </div>
        <div class="table-wrap task-flow-table"><table>
          <thead>
<tr><th style="font-weight:700">方案(SKU)</th><th style="font-weight:700">类别/用例</th><th style="font-weight:700">执行人</th><th style="font-weight:700">启动/完成时间</th><th style="font-weight:700">样机</th><th style="font-weight:700">测试结果</th><th style="font-weight:700">问题单</th><th style="font-weight:700">状态</th><th style="font-weight:700">操作</th></tr>
          </thead>
          <tbody>${rows.map(row => {
      const t = row.task;
      const progressId = row.progress?.id || t?.progressId || "";
      const taskId = t?.id || "";
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
                <td class="task-sku-cell">${Utils.esc(i.sku)}</td>
                <td class="compact-cell">${catHtml}</td>
                <td>${execHtml}</td>
                <td class="task-time-cell">${timeHtml}</td>
                <td>${sampleHtml}</td>
                <td class="task-issue-cell">${t ? this.taskIssueSummaryHtml(project, stage, t) : "-"}</td>
                <td class="task-issue-record-cell" onclick="${taskId ? `app.openTaskIssueRecordModal('${project.id}','${stage.id}','${taskId}')` : ''}" style="${taskId ? 'cursor:pointer' : ''}">${t ? this.taskIssueRecordHtml(t) : '<span class="path">-</span>'}</td>
                <td><span class="badge ${this.taskStatusBadgeClass(flowStatus)}">${Utils.esc(flowStatus)}</span></td>
                <td class="op-cell task-op-cell-new">${actionsHtml}</td>
              </tr>`;
    }).join("") || `<tr><td colspan="9" class="empty">暂无任务。请点击"新增任务"，从阶段配置的测试池中选择测试项。</td></tr>`}
      ${rows.length ? `<tr class="task-flow-buffer-row" aria-hidden="true"><td colspan="9"></td></tr>` : ""}</tbody>
        </table></div>
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
      onConfirm?.();
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

  createTaskFromProgress(stage, progress, seed = {}) {
    if (!stage || !progress) return null;
    if (!Array.isArray(stage.tasks)) stage.tasks = [];
    const task = {
      id: Utils.id("task_"),
      progressId: progress.id,
      strategyId: progress.strategyId || "",
      category: progress.category || "",
      testItem: progress.testItem || "",
      skuIndex: progress.skuIndex || 1,
      owner: seed.owner || "",
      planStartDate: seed.planStartDate || "",
      planEndDate: seed.planEndDate || "",
      planDate: seed.planDate || seed.planStartDate || "",
      status: seed.status || "待下发",
      sampleIds: [...(seed.sampleIds || [])],
      removedSampleRecords: [],
      sampleFaultRecords: [],
      resultUploads: [],
      createdAt: Utils.now(),
      logs: [],
      completed: false,
      requiredSampleCount: this.getProgressRequiredSampleCount(stage, progress)
    };
    stage.tasks.push(task);
    if (seed.log !== false) {
      this.addTaskLog(task, seed.logAction || "新增待下发任务", {
        user: seed.user || "管理员",
        reason: seed.reason || "从阶段配置测试池新增",
        toStatus: this.taskFlowStatus(task)
      });
    }
    return task;
  },

  openAddTasksFromPoolModal() {
    const stage = this.currentStage();
    if (!stage) return;
    const pool = (stage.progress || []).filter(p => p && p.testItem);
    if (!pool.length) {
      alert("当前阶段测试池为空。请先在「配置测试用例集」的测试策略配置中新增测试项。");
      return;
    }
    const taskCountByProgress = new Map();
    (stage.tasks || []).forEach(t => {
      if (!t.progressId) return;
      taskCountByProgress.set(t.progressId, (taskCountByProgress.get(t.progressId) || 0) + 1);
    });
    const rows = pool.map((p, idx) => {
      const required = this.getProgressRequiredSampleCount(stage, p);
      const existing = taskCountByProgress.get(p.id) || 0;
      return `
        <tr>
          <td style="text-align:center"><input class="task-pool-check" type="checkbox" data-index="${idx}" onchange="app.updateTaskPoolSelectionCount()" style="width:auto"></td>
          <td>${Utils.esc(stage.skuNames?.[p.skuIndex - 1] || `SKU${p.skuIndex}`)}</td>
          <td class="compact-cell"><b>${Utils.esc(this.taskCategoryItemText(p.category, p.testItem))}</b></td>
          <td>${required === null ? "-" : `${required} 台`}</td>
          <td>${existing ? `${existing} 个` : "-"}</td>
          <td><input class="task-pool-count" data-index="${idx}" type="number" min="1" step="1" value="1" oninput="app.updateTaskPoolSelectionCount()"></td>
        </tr>`;
    }).join("");
    this.showModal("新增任务", `
      <div class="path">从当前阶段测试池选择测试项生成真实任务。可重复新增，新增后默认均为"待下发"。</div>
      <div class="task-pool-toolbar">
        <button type="button" class="btn btn-sm btn-outline" onclick="app.setTaskPoolChecked(true)">全选</button>
        <button type="button" class="btn btn-sm btn-outline" onclick="app.setTaskPoolChecked(false)">清空</button>
        <span id="taskPoolSelectionHint" class="task-pool-hint">已选 0 项，将新增 0 个任务</span>
      </div>
      <div class="table-wrap task-pool-table"><table>
        <thead><tr><th style="width:46px"></th><th>方案(SKU)</th><th>类别/用例</th><th>样机数</th><th>已有任务</th><th>新增次数</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    `, () => {
      let added = 0;
      const selected = [...document.querySelectorAll(".task-pool-check:checked")];
      if (!selected.length) {
        this.clearFieldValidationMarks();
        this.markFieldInvalid(document.getElementById("taskPoolSelectionHint"), "请至少选择一个测试项。");
        return true;
      }
      selected.forEach(cb => {
        const idx = Number(cb.dataset.index);
        const progress = pool[idx];
        const input = document.querySelector(`.task-pool-count[data-index="${idx}"]`);
        const count = Math.max(1, Utils.parsePositiveInt(input?.value) || 1);
        for (let i = 0; i < count; i++) {
          this.createTaskFromProgress(stage, progress, { status: "待下发" });
          added++;
        }
      });
      this.save(); this.render();
      Utils.toast(`已新增 ${added} 个待下发任务。`);
    });
    setTimeout(() => this.updateTaskPoolSelectionCount(), 0);
  },

  setTaskPoolChecked(checked) {
    document.querySelectorAll(".task-pool-check").forEach(cb => { cb.checked = checked; });
    this.updateTaskPoolSelectionCount();
  },

  updateTaskPoolSelectionCount() {
    const hint = document.getElementById("taskPoolSelectionHint");
    if (!hint) return;
    const selected = [...document.querySelectorAll(".task-pool-check:checked")];
    const taskCount = selected.reduce((sum, cb) => {
      const idx = cb.dataset.index;
      const input = document.querySelector(`.task-pool-count[data-index="${idx}"]`);
      return sum + Math.max(1, Utils.parsePositiveInt(input?.value) || 1);
    }, 0);
    hint.innerText = `已选 ${selected.length} 项，将新增 ${taskCount} 个任务`;
  },

  // ==================== 任务操作 ====================
  ensurePlanTask(stage, progress, seed = {}) {
    if (!stage || !progress) return null;
    if (!Array.isArray(stage.tasks)) stage.tasks = [];
    let task = seed.taskId ? stage.tasks.find(t => t.id === seed.taskId) : null;
    if (task) return task;
    task = {
      id: Utils.id("task_"),
      progressId: progress.id,
      strategyId: progress.strategyId || "",
      category: progress.category || "",
      testItem: progress.testItem,
      skuIndex: progress.skuIndex,
      owner: seed.owner || progress.owner || "",
      planStartDate: seed.planStartDate || progress.planStartDate || "",
      planEndDate: seed.planEndDate || progress.planEndDate || "",
      planDate: seed.planStartDate || progress.planStartDate || "",
      status: seed.status || "待下发",
      sampleIds: [...(seed.sampleIds || progress.sampleIds || [])],
      removedSampleRecords: [],
      sampleFaultRecords: [],
      resultUploads: [],
      createdAt: Utils.now(),
      logs: [],
      completed: false,
      requiredSampleCount: this.getProgressRequiredSampleCount(stage, progress)
    };
    stage.tasks.push(task);
    return task;
  },

  getSelectedTaskSampleIds(inputName) {
    return [...document.querySelectorAll(`input[name='${inputName}']:checked`)].map(x => x.value);
  },

  validateTaskSampleSelection(progress, sampleIds, contextLabel = "任务") {
    const s = this.currentStage();
    const required = this.getProgressRequiredSampleCount(s, progress);
    if (required === null) return { ok: false, required: null, count: sampleIds.length, msg: `${contextLabel}无法读取样机数配置。` };
    if (sampleIds.length !== required) return { ok: false, required, count: sampleIds.length, msg: `${contextLabel}需要 ${required} 台样机，当前选择 ${sampleIds.length} 台。` };
    return { ok: true, required, count: sampleIds.length, msg: "" };
  },

  updateTaskSampleLimitUI(progressSelectId, inputName, hintId) {
    this.updateDispatchSamplePoolCounts(inputName);
    const s = this.currentStage();
    const select = document.getElementById(progressSelectId);
    const hint = document.getElementById(hintId);
    if (!s || !select || !hint) return;
    const progress = s.progress.find(x => x.id === select.value);
    const sampleIds = this.getSelectedTaskSampleIds(inputName);
    const required = this.getProgressRequiredSampleCount(s, progress);
    const isGlobalCompact = hint.classList.contains('sample-limit-global');
    hint.classList.remove('warn', 'bad');
    if (required === null) {
      hint.classList.add('bad');
      if (isGlobalCompact) {
        hint.title = `无法读取样机数配置。当前已选 ${sampleIds.length} 台。`;
        hint.innerHTML = `<span class="sample-limit-count">${sampleIds.length}/?</span>`;
      } else {
        hint.innerHTML = `无法读取样机数配置。<span class="sample-limit-count">已选 ${sampleIds.length}</span>`;
      }
      return;
    }
    const countText = `${sampleIds.length}/${required}`;
    if (sampleIds.length === required) {
      if (isGlobalCompact) {
        hint.title = `样机已满足：需 ${required} 台，已选 ${sampleIds.length} 台。`;
        hint.innerHTML = `<span class="sample-limit-count">${countText}</span>`;
      } else {
        hint.innerHTML = `样机已满足：需 ${required} 台，已选 ${sampleIds.length} 台。<span class="sample-limit-count">OK</span>`;
      }
    } else if (sampleIds.length < required) {
      hint.classList.add('warn');
      if (isGlobalCompact) {
        hint.title = `不足：需 ${required} 台，已选 ${sampleIds.length} 台。`;
        hint.innerHTML = `<span class="sample-limit-count">${countText}</span>`;
      } else {
        hint.innerHTML = `不足：需 ${required} 台，已选 ${sampleIds.length} 台。<span class="sample-limit-count">${countText}</span>`;
      }
    } else {
      hint.classList.add('bad');
      if (isGlobalCompact) {
        hint.title = `超出：需 ${required} 台，已选 ${sampleIds.length} 台。`;
        hint.innerHTML = `<span class="sample-limit-count">${countText}</span>`;
      } else {
        hint.innerHTML = `超出：需 ${required} 台，已选 ${sampleIds.length} 台。<span class="sample-limit-count">${countText}</span>`;
      }
    }
  },

  onTaskSampleCheckboxChange(progressSelectId, inputName, hintId, checkboxEl) {
    const s = this.currentStage();
    const progress = s?.progress?.find(x => x.id === document.getElementById(progressSelectId)?.value);
    const required = this.getProgressRequiredSampleCount(s, progress);
    let sampleIds = this.getSelectedTaskSampleIds(inputName);
    if (required !== null && checkboxEl?.checked && sampleIds.length > required) {
      checkboxEl.checked = false;
      alert(`该测试项要求 ${required} 台样机。`);
    }
    this.updateTaskSampleLimitUI(progressSelectId, inputName, hintId);
  },

  getAssignSampleSearchText(sample) {
    if (!sample) return "";
    const parts = [
      sample.sn || "",
      sample.imei || "",
      sample.boardSn || "",
      sample.sourceStageName || "",
      sample.sourceSkuName || "",
      sample.status || "",
      ...this.sampleTestedItemNames(sample.id || ""),
      ...(sample.problemRecords || []).map(r => r.description || "").filter(Boolean)
    ];
    return parts.map(v => String(v || "").trim()).filter(Boolean).join(" ").toLowerCase();
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

  buildTaskSamplePickerHtml(selectedIds = [], inputName = "samplePick", progressSelectId = "", hintId = "", excludeTaskId = "") {
    const selectedSet = new Set(selectedIds || []);
    const hardBlockedStatuses = new Set(["已退库", "取走分析", "已借出"]);
    const candidates = this.allSamples();
    const grouped = {};
    candidates.forEach(x => { const key = x.categoryName || "未分类"; if (!grouped[key]) grouped[key] = []; grouped[key].push(x); });
    const changeAttr = progressSelectId && hintId ? `onchange="app.onTaskSampleCheckboxChange('${progressSelectId}','${inputName}','${hintId}', this)"` : '';
    return Object.keys(grouped).map((cat, idx) => {
      const safeKey = `task_sample_${inputName}_${idx}`.replace(/[^a-zA-Z0-9_]/g, "_");
      const groupId = `${safeKey}_group`, searchId = `${safeKey}_search`, excludeId = `${safeKey}_exclude`, countId = `${safeKey}_count`;
      const samples = grouped[cat];
      const selectedInGroup = samples.filter(x => selectedSet.has(x.id)).length;
      return `
        <div class="dispatch-sample-group" data-sample-input-name="${inputName}">
          <div class="dispatch-sample-head">
            <div class="dispatch-sample-title-wrap">
              <div class="dispatch-sample-title">${Utils.esc(cat)} · ${samples.length} 台</div>
              <span class="dispatch-selected-count" data-total="${samples.length}">${selectedInGroup}/${samples.length}</span>
            </div>
            <div class="dispatch-sample-tools">
              <button type="button" class="btn btn-sm btn-outline" onclick="app.toggleDispatchGroup('${groupId}',this)">展开</button>
              <input id="${searchId}" class="dispatch-search-input" placeholder="包含搜索" onkeydown="if(event.key==='Enter'){app.filterDispatchGroup('${groupId}',this.value,document.getElementById('${excludeId}').value,'${countId}')}">
              <input id="${excludeId}" class="dispatch-search-input dispatch-search-exclude" placeholder="排除搜索" onkeydown="if(event.key==='Enter'){app.filterDispatchGroup('${groupId}',document.getElementById('${searchId}').value,this.value,'${countId}')}">
              <button type="button" class="dispatch-search-btn" onclick="app.filterDispatchGroup('${groupId}',document.getElementById('${searchId}').value,document.getElementById('${excludeId}').value,'${countId}')" title="搜索">🔍</button>
              <span id="${countId}" class="dispatch-match-count"></span>
            </div>
          </div>
          <div id="${groupId}" class="dispatch-sample-body">
            ${samples.map(x => {
        const selected = selectedSet.has(x.id);
        const occupiedByOpenTask = this.isSampleUsedByAnotherOpenTask(x.id, excludeTaskId);
        const hardBlocked = hardBlockedStatuses.has(x.status);
        const canPick = selected || (!occupiedByOpenTask && !hardBlocked);
        const disabledReason = occupiedByOpenTask ? "样机已被其他未完成任务占用" : (hardBlocked ? "当前状态不能加入测试任务" : "");
        // 身份号优先级：SN > IMEI > 主板SN
        const identity = x.sn ? `SN: ${Utils.esc(x.sn)}` : x.imei ? `IMEI: ${Utils.esc(x.imei)}` : x.boardSn ? `主板SN: ${Utils.esc(x.boardSn)}` : "身份号未录入";
        // 阶段/方案
        const stageName = String(x.sourceStageName || "").trim();
        const skuName = String(x.sourceSkuName || "").trim();
        const stageSku = stageName && skuName ? `${Utils.esc(stageName)} · ${Utils.esc(skuName)}`
          : stageName ? `${Utils.esc(stageName)} · 未配置`
          : skuName ? `未配置 · ${Utils.esc(skuName)}`
          : "未配置";
        // 已测
        const testedItems = this.sampleTestedItemNames(x.id);
        const testedText = testedItems.length === 0
          ? "无"
          : testedItems.length <= 3
            ? Utils.esc(testedItems.join("、"))
            : `${Utils.esc(testedItems.slice(0, 3).join("、"))} 等 ${testedItems.length} 项`;
        return `
              <div class="dispatch-sample-row ${canPick ? "" : "is-disabled"}" title="${Utils.esc(disabledReason)}" data-search-text="${Utils.esc(this.getAssignSampleSearchText(x))}">
                <label class="dispatch-sample-check"><input type="checkbox" name="${inputName}" value="${x.id}" data-sample-pick="${inputName}" ${selected ? "checked" : ""} ${canPick ? "" : "disabled"} ${canPick ? changeAttr : ""}></label>
                <div class="dispatch-sample-info">
                  <span class="dispatch-sample-id" onclick="event.preventDefault();event.stopPropagation();app.openSampleReadonly('${x.id}')">${identity}</span>
                  <span class="dispatch-sample-stage">阶段/方案：${stageSku}</span>
                  <span class="dispatch-sample-tested">已测：${testedText}</span>
                </div>
                <span class="dispatch-sample-status"><span class="badge ${this.sampleHasProblem(x) ? 's-故障' : 's-OK'}">${this.sampleHasProblem(x) ? '故障' : 'OK'}</span> <span class="badge s-${Utils.esc(x.status)}">${Utils.esc(x.status)}</span></span>
              </div>`;
      }).join("")}
          </div>
        </div>`;
    }).join("") || `<div class="empty">暂无可用样机。请先到"样机档案池"新增。</div>`;
  },

  updateDispatchSamplePoolCounts(inputName) {
    document.querySelectorAll(`.dispatch-sample-group[data-sample-input-name="${inputName}"]`).forEach(group => {
      const boxes = [...group.querySelectorAll(`input[type="checkbox"][name="${inputName}"]`)];
      const checked = boxes.filter(cb => cb.checked).length;
      const counter = group.querySelector(".dispatch-selected-count");
      if (counter) {
        const total = Number(counter.dataset.total || boxes.length);
        counter.textContent = `${checked}/${total}`;
        counter.classList.toggle("has-selected", checked > 0);
      }
    });
  },

  toggleDispatchGroup(groupId, btn) {
    const el = document.getElementById(groupId); if (!el) return;
    const isOpen = el.classList.toggle("open");
    if (btn) btn.innerText = isOpen ? "折叠" : "展开";
  },
  filterDispatchGroup(groupId, keyword, excludeKw, countId) {
    const body = document.getElementById(groupId); if (!body) return;
    body.classList.add("open");
    const kw = String(keyword || "").trim().toLowerCase();
    const ex = String(excludeKw || "").trim().toLowerCase();
    let visible = 0;
    body.querySelectorAll(".dispatch-sample-row").forEach(row => {
      const text = (row.dataset.searchText || "").toLowerCase();
      const matchInclude = !kw || text.includes(kw);
      const matchExclude = ex && text.includes(ex);
      const show = matchInclude && !matchExclude;
      row.style.display = show ? "flex" : "none";
      if (show) visible++;
    });
    const counter = document.getElementById(countId);
    if (counter) counter.innerText = (kw || ex) ? `${visible} 台` : "";
  },

  isTaskChangePayloadChanged(t, after) {
    if (!t) return false;
    const norm = (v) => String(v || "").trim();
    if (norm(t.owner) !== norm(after.owner)) return true;
    if (norm(t.planStartDate || t.planDate || "") !== norm(after.planStartDate || "")) return true;
    if (norm(t.planEndDate || t.endDate || "") !== norm(after.planEndDate || "")) return true;
    const beforeIds = (t.sampleIds || []).slice().sort().join(",");
    const afterIds = (after.sampleIds || []).slice().sort().join(",");
    if (beforeIds !== afterIds) return true;
    return false;
  },

  assignPlanTaskSamples(projectId, stageId, progressId, taskId = "") {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const progress = s?.progress.find(x => x.id === progressId);
    let t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s || !progress) return;
    if (t && this.taskFlowStatus(t) !== "待下发") { alert("只有未下发任务可以分配或重新分配样机。"); return; }
    const selectedIds = t?.sampleIds || [];
    const sampleCards = this.buildTaskSamplePickerHtml(selectedIds, "assignSamplePick", "assignProgress", "assignSampleLimitHint", t?.id || "");
    this.showModal(t?.sampleIds?.length ? "重新分配样机" : "分配样机", `
      <input type="hidden" id="assignProgress" value="${Utils.esc(progress.id)}">
      <div class="path">计划任务：${Utils.esc(this.getProgressDisplayName(s, progress))}</div>
      <div id="assignSampleLimitHint" class="sample-limit-hint"></div>
      <div class="form-group"><label class="req">选择样机</label><div class="dispatch-sample-select">${sampleCards}</div></div>
    `, () => {
      const operator = t?.owner || "管理员";
      const sampleIds = this.getSelectedTaskSampleIds("assignSamplePick");
      const check = this.validateTaskSampleSelection(progress, sampleIds, "样机分配");
      if (t && !this.isTaskChangePayloadChanged(t, { owner: t.owner, planStartDate: t.planStartDate || t.planDate || "", planEndDate: t.planEndDate || "", sampleIds })) {
        Utils.toast("未检测到变更");
        this.closeModal();
        return;
      }
      if (!check.ok) { alert(check.msg); return true; }
      const oldSampleIds = [...(t?.sampleIds || [])];
      t = t || this.ensurePlanTask(s, progress);
      const removed = oldSampleIds.filter(id => !sampleIds.includes(id));
      const added = sampleIds.filter(id => !oldSampleIds.includes(id));
      t.sampleIds = sampleIds;
      t.requiredSampleCount = check.required;
      if (!t.status) t.status = "待下发";
      removed.forEach(id => {
        if (!this.isSampleUsedByAnotherOpenTask(id, t.id)) {
          this.changeSampleStatus(id, "闲置", { user: operator, source: "任务样机重新分配", reason: "未下发任务调整样机", projectId: p.id, stageId: s.id });
        }
      });
      added.forEach(id => this.changeSampleStatus(id, "在位等待", { user: operator, source: "任务样机分配", reason: "未下发任务分配样机", projectId: p.id, stageId: s.id, taskId: t.id, testItem: t.testItem }));
      this.addTaskLog(t, oldSampleIds.length ? "重新分配样机" : "分配样机", { user: operator, reason: "未下发任务样机配置", detail: `样机：${sampleIds.map(id => this.findSample(id)?.sample.sampleNo || id).join(", ")}` });
      this.save(); this.render();
    }, "确认", { className: "assign-sample-modal" });
    setTimeout(() => this.updateTaskSampleLimitUI('assignProgress', 'assignSamplePick', 'assignSampleLimitHint'), 0);
  },

  setPlanTaskSchedule(projectId, stageId, progressId, taskId = "") {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const progress = s?.progress.find(x => x.id === progressId);
    let t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s || !progress) return;
    if (t && this.taskFlowStatus(t) !== "待下发") { alert("只有未下发任务可以修改计划时间。"); return; }
    const planStartDate = t?.planStartDate || t?.planDate || "";
    const planEndDate = t?.planEndDate || "";
    // P1.4：项目还没人员时，直接给个红色提示和快速新增入口
    const activeMembers = this.projectActiveMembers(p);
    const memberMissingHint = activeMembers.length
      ? ""
      : `<div class="field-error" style="display:block;margin-top:6px">
          ⚠ 项目人员名单为空，无法选择执行人。
          <button type="button" class="btn btn-sm" style="margin-left:8px"
            onclick="app.closeModal();app.addProjectMember();">立即新增人员</button>
        </div>`;
    this.showModal("设置计划时间", `
      <div class="path">计划任务：${Utils.esc(this.getProgressDisplayName(s, progress))}</div>
      <div class="form-group">
        <label class="req" style="color:var(--muted);font-weight:700">执行人<span class="req-star">*</span></label>
        ${this.projectMemberSelectHtml("planOwner", t?.owner || progress.owner || "", "请选择执行人")}
        ${memberMissingHint}
      </div>
      <div class="form-row">
        <div class="form-group"><label class="req" style="color:var(--muted);font-weight:700">计划开始时间<span class="req-star">*</span></label><input type="date" id="planStartDate" value="${Utils.esc(planStartDate)}"></div>
        <div class="form-group"><label class="req" style="color:var(--muted);font-weight:700">计划终止时间<span class="req-star">*</span></label><input type="date" id="planEndDate" value="${Utils.esc(planEndDate)}"></div>
      </div>
    `, () => {
      const owner = document.getElementById("planOwner").value.trim();
      const start = document.getElementById("planStartDate").value;
      const end = document.getElementById("planEndDate").value;
      this.clearFieldValidationMarks();
      if (!owner) { this.markFieldInvalid(document.getElementById("planOwner"), "请选择执行人。请先在项目人员配置中新增人员。"); return true; }
      if (!start || !end) {
        if (!start) this.markFieldInvalid(document.getElementById("planStartDate"), "必须填写计划开始时间");
        if (!end) this.markFieldInvalid(document.getElementById("planEndDate"), "必须填写计划终止时间");
        return true;
      }
      if (start > end) {
        this.markFieldInvalid(document.getElementById("planEndDate"), "计划终止时间不能早于计划开始时间");
        return true;
      }
      if (t && !this.isTaskChangePayloadChanged(t, { owner, planStartDate: start, planEndDate: end })) {
        Utils.toast("未检测到变更");
        this.closeModal();
        return;
      }
      t = t || this.ensurePlanTask(s, progress, { owner, planStartDate: start, planEndDate: end });
      t.owner = owner;
      t.planStartDate = start;
      t.planEndDate = end;
      t.planDate = start;
      if (!t.status) t.status = "待下发";
      this.addTaskLog(t, "设置计划时间", { user: owner, reason: `计划开始 ${start}，计划终止 ${end}` });
      this.save(); this.render();
    });
  },

  taskConfigDisplayName(stage, progress, task) {
    const category = task?.category || progress?.category || "";
    const testItem = task?.testItem || progress?.testItem || "";
    if (category && testItem) return `${category} -> ${testItem}`;
    if (testItem) return testItem;
    if (category) return category;
    return "未知测试项";
  },

  openTaskConfigPanel(projectId, stageId, progressId, taskId = "", initialTab = "plan") {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const progress = s?.progress.find(x => x.id === progressId);
    const t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s || !progress) return;
    if (t && this.taskFlowStatus(t) !== "待下发") { alert("只有未下发任务可以修改配置。"); return; }
    const html = this.taskConfigPanelHtml(p, s, progress, t, initialTab);
    this.showModal("任务配置", html,
      () => this.saveTaskConfigAll(projectId, stageId, progressId, taskId),
      "保存并关闭",
      { className: "task-config-modal", hideCancel: false, cancelText: "取消" }
    );
    // 标题栏替换为左右布局（showModal 使用 innerText，这里用 innerHTML 覆盖）
    setTimeout(() => {
      const titleEl = document.getElementById("modalTitle");
      if (titleEl) {
        titleEl.innerHTML = `<div class="task-config-titlebar">
          <span>任务配置</span>
          <span class="task-config-title-context">计划任务：${Utils.esc(this.taskConfigDisplayName(stage, progress, t))}</span>
        </div>`;
      }
    }, 0);
    // 覆盖取消按钮：检查未保存修改
    setTimeout(() => {
      const cancelBtn = document.getElementById("modalCancel");
      if (cancelBtn) {
        cancelBtn.onclick = () => {
          if (this.hasUnsavedTaskConfigChanges(projectId, stageId, progressId, taskId)) {
            this.showConfirm("有未保存的修改，确定放弃吗？", () => this.closeModal(), {
              title: "放弃修改", okText: "放弃", okClass: "btn btn-danger", cancelText: "继续编辑"
            });
          } else {
            this.closeModal();
          }
        };
      }
    }, 0);
    // 若默认进入样机配置页，初始化数量提示
    if (initialTab === "sample") {
      setTimeout(() => this.updateTaskSampleLimitUI("tcSampleProgress", "tcSamplePick", "tcSampleLimitHint"), 0);
    }
  },

  taskConfigPanelHtml(project, stage, progress, task, activeTab) {
    const planActive = activeTab === "plan" ? "active" : "";
    const sampleActive = activeTab === "sample" ? "active" : "";
    return `<div class="task-config-shell">
      <div class="task-config-nav">
        <div class="task-config-nav-card ${planActive}" onclick="app.switchTaskConfigTab('plan')">
          <b>计划配置</b>
        </div>
        <div class="task-config-nav-card ${sampleActive}" onclick="app.switchTaskConfigTab('sample')">
          <b>样机配置</b>
        </div>
      </div>
      <div class="task-config-main">
        <div class="task-config-panel ${planActive}" id="tcPanelPlan">
          ${this.taskPlanConfigPanelHtml(project, stage, progress, task)}
        </div>
        <div class="task-config-panel ${sampleActive}" id="tcPanelSample">
          ${this.taskSampleConfigPanelHtml(project, stage, progress, task)}
        </div>
      </div>
    </div>`;
  },

  taskPlanConfigPanelHtml(project, stage, progress, task) {
    const t = task;
    const planStartDate = t?.planStartDate || t?.planDate || "";
    const planEndDate = t?.planEndDate || "";
    const activeMembers = this.projectActiveMembers(project);
    const memberMissingHint = activeMembers.length
      ? ""
      : `<div class="field-error" style="display:block;margin-top:6px">
          ⚠ 项目人员名单为空，无法选择执行人。
          <button type="button" class="btn btn-sm" style="margin-left:8px"
            onclick="app.closeModal();app.addProjectMember();">立即新增人员</button>
        </div>`;
    return `
      <div class="form-group">
        <label class="req">执行人<span class="req-star">*</span></label>
        ${this.projectMemberSelectHtml("tcPlanOwner", t?.owner || progress.owner || "", "请选择执行人")}
        ${memberMissingHint}
      </div>
      <div class="form-row">
        <div class="form-group"><label class="req">计划开始时间<span class="req-star">*</span></label><input type="date" id="tcPlanStartDate" value="${Utils.esc(planStartDate)}"></div>
        <div class="form-group"><label class="req">计划终止时间<span class="req-star">*</span></label><input type="date" id="tcPlanEndDate" value="${Utils.esc(planEndDate)}"></div>
      </div>
`;
  },

  taskSampleConfigPanelHtml(project, stage, progress, task) {
    const t = task;
    const selectedIds = t?.sampleIds || [];
    const sampleCards = this.buildTaskSamplePickerHtml(selectedIds, "tcSamplePick", "tcSampleProgress", "tcSampleLimitHint", t?.id || "");
    return `
      <input type="hidden" id="tcSampleProgress" value="${Utils.esc(progress.id)}">
      <div class="form-group task-sample-config-group">
        <div class="task-sample-label-row task-sample-label-row-compact">
          <label class="req">选择样机 <span class="req-star">*</span></label>
          <div id="tcSampleLimitHint" class="sample-limit-hint sample-limit-global" title="当前已选 / 任务要求样机数"></div>
        </div>
        <div class="dispatch-sample-select task-config-sample-scroll">${sampleCards}</div>
      </div>
`;
  },

  saveTaskPlanConfig(projectId, stageId, progressId, taskId) {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const progress = s?.progress.find(x => x.id === progressId);
    let t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s || !progress) return;
    const owner = document.getElementById("tcPlanOwner")?.value.trim() || "";
    const start = document.getElementById("tcPlanStartDate")?.value || "";
    const end = document.getElementById("tcPlanEndDate")?.value || "";
    this.clearFieldValidationMarks();
    if (!owner) { this.markFieldInvalid(document.getElementById("tcPlanOwner"), "请选择执行人。请先在项目人员配置中新增人员。"); return; }
    if (!start || !end) {
      if (!start) this.markFieldInvalid(document.getElementById("tcPlanStartDate"), "必须填写计划开始时间");
      if (!end) this.markFieldInvalid(document.getElementById("tcPlanEndDate"), "必须填写计划终止时间");
      return;
    }
    if (start > end) {
      this.markFieldInvalid(document.getElementById("tcPlanEndDate"), "计划终止时间不能早于计划开始时间");
      return;
    }
    if (t && !this.isTaskChangePayloadChanged(t, { owner, planStartDate: start, planEndDate: end })) {
      Utils.toast("未检测到变更");
      this.closeModal();
      return;
    }
    t = t || this.ensurePlanTask(s, progress, { owner, planStartDate: start, planEndDate: end });
    t.owner = owner;
    t.planStartDate = start;
    t.planEndDate = end;
    t.planDate = start;
    if (!t.status) t.status = "待下发";
    this.addTaskLog(t, "设置计划时间", { user: owner, reason: `计划开始 ${start}，计划终止 ${end}` });
    this.save(); this.render();
    Utils.toast("计划配置已保存");
    this.closeModal();
  },

  saveTaskSampleConfig(projectId, stageId, progressId, taskId) {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const progress = s?.progress.find(x => x.id === progressId);
    let t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s || !progress) return;
    const operator = t?.owner || "管理员";
    const sampleIds = this.getSelectedTaskSampleIds("tcSamplePick");
    const check = this.validateTaskSampleSelection(progress, sampleIds, "样机分配");
    if (t && !this.isTaskChangePayloadChanged(t, { owner: t.owner, planStartDate: t.planStartDate || t.planDate || "", planEndDate: t.planEndDate || "", sampleIds })) {
      Utils.toast("未检测到变更");
      this.closeModal();
      return;
    }
    if (!check.ok) { alert(check.msg); return; }
    const oldSampleIds = [...(t?.sampleIds || [])];
    t = t || this.ensurePlanTask(s, progress);
    const removed = oldSampleIds.filter(id => !sampleIds.includes(id));
    const added = sampleIds.filter(id => !oldSampleIds.includes(id));
    t.sampleIds = sampleIds;
    t.requiredSampleCount = check.required;
    if (!t.status) t.status = "待下发";
    removed.forEach(id => {
      if (!this.isSampleUsedByAnotherOpenTask(id, t.id)) {
        this.changeSampleStatus(id, "闲置", { user: operator, source: "任务样机重新分配", reason: "未下发任务调整样机", projectId: p.id, stageId: s.id });
      }
    });
    added.forEach(id => this.changeSampleStatus(id, "在位等待", { user: operator, source: "任务样机分配", reason: "未下发任务分配样机", projectId: p.id, stageId: s.id, taskId: t.id, testItem: t.testItem }));
    this.addTaskLog(t, oldSampleIds.length ? "重新分配样机" : "分配样机", { user: operator, reason: "未下发任务样机配置", detail: `样机：${sampleIds.map(id => this.findSample(id)?.sample.sampleNo || id).join(", ")}` });
    this.save(); this.render();
    Utils.toast("样机配置已保存");
    this.closeModal();
  },

  saveTaskConfigAll(projectId, stageId, progressId, taskId) {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const progress = s?.progress.find(x => x.id === progressId);
    let t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s || !progress) return;
    // 读取 plan 字段
    const owner = document.getElementById("tcPlanOwner")?.value.trim() || "";
    const start = document.getElementById("tcPlanStartDate")?.value || "";
    const end = document.getElementById("tcPlanEndDate")?.value || "";
    // 读取 sample 字段
    const sampleIds = this.getSelectedTaskSampleIds("tcSamplePick");
    const check = this.validateTaskSampleSelection(progress, sampleIds, "样机分配");
    // 验证 plan
    this.clearFieldValidationMarks();
    if (!owner) { this.markFieldInvalid(document.getElementById("tcPlanOwner"), "请选择执行人。请先在项目人员配置中新增人员。"); return; }
    if (!start || !end) {
      if (!start) this.markFieldInvalid(document.getElementById("tcPlanStartDate"), "必须填写计划开始时间");
      if (!end) this.markFieldInvalid(document.getElementById("tcPlanEndDate"), "必须填写计划终止时间");
      return;
    }
    if (start > end) { this.markFieldInvalid(document.getElementById("tcPlanEndDate"), "计划终止时间不能早于计划开始时间"); return; }
    // 验证 sample
    if (!check.ok) { alert(check.msg); return; }
    // 变更检测（合并 payload）
    if (t && !this.isTaskChangePayloadChanged(t, { owner, planStartDate: start, planEndDate: end, sampleIds })) {
      Utils.toast("未检测到变更");
      this.closeModal();
      return;
    }
    // ensure（task 已存在，仅防御）
    t = t || this.ensurePlanTask(s, progress);
    // 检测各维度变更
    const planChanged = (t.owner || "") !== owner
      || (t.planStartDate || t.planDate || "") !== start
      || (t.planEndDate || "") !== end;
    const oldSampleIds = [...(t.sampleIds || [])];
    const sampleChanged = oldSampleIds.slice().sort().join(",") !== sampleIds.slice().sort().join(",");
    // 施加 plan 变更
    if (planChanged) {
      t.owner = owner;
      t.planStartDate = start;
      t.planEndDate = end;
      t.planDate = start;
    }
    // 施加 sample 变更
    if (sampleChanged) {
      const operator = owner || t.owner || "管理员";
      const removed = oldSampleIds.filter(id => !sampleIds.includes(id));
      const added = sampleIds.filter(id => !oldSampleIds.includes(id));
      t.sampleIds = sampleIds;
      t.requiredSampleCount = check.required;
      removed.forEach(id => {
        if (!this.isSampleUsedByAnotherOpenTask(id, t.id)) {
          this.changeSampleStatus(id, "闲置", { user: operator, source: "任务样机重新分配", reason: "未下发任务调整样机", projectId: p.id, stageId: s.id });
        }
      });
      added.forEach(id => this.changeSampleStatus(id, "在位等待", { user: operator, source: "任务样机分配", reason: "未下发任务分配样机", projectId: p.id, stageId: s.id, taskId: t.id, testItem: t.testItem }));
    }
    // 状态 + 日志
    if (!t.status) t.status = "待下发";
    if (planChanged) {
      this.addTaskLog(t, "设置计划时间", { user: owner, reason: `计划开始 ${start}，计划终止 ${end}` });
    }
    if (sampleChanged) {
      this.addTaskLog(t, oldSampleIds.length ? "重新分配样机" : "分配样机", {
        user: owner || t.owner || "管理员",
        reason: "未下发任务样机配置",
        detail: `样机：${sampleIds.map(id => this.findSample(id)?.sample.sampleNo || id).join(", ")}`
      });
    }
    // 统一持久化
    this.save(); this.render();
    if (planChanged && sampleChanged) Utils.toast("任务配置已保存");
    else if (planChanged) Utils.toast("计划配置已保存");
    else Utils.toast("样机配置已保存");
    this.closeModal();
  },

  hasUnsavedTaskConfigChanges(projectId, stageId, progressId, taskId) {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const t = taskId ? s?.tasks.find(x => x.id === taskId) : null;
    if (!p || !s) return false;
    // Plan fields
    const domOwner = (document.getElementById("tcPlanOwner")?.value || "").trim();
    const domStart = document.getElementById("tcPlanStartDate")?.value || "";
    const domEnd = document.getElementById("tcPlanEndDate")?.value || "";
    const origOwner = (t?.owner || "").trim();
    const origStart = t?.planStartDate || t?.planDate || "";
    const origEnd = t?.planEndDate || "";
    if (domOwner !== origOwner || domStart !== origStart || domEnd !== origEnd) return true;
    // Sample fields
    const domSampleIds = this.getSelectedTaskSampleIds("tcSamplePick").sort().join(",");
    const origSampleIds = (t?.sampleIds || []).slice().sort().join(",");
    if (domSampleIds !== origSampleIds) return true;
    return false;
  },

  switchTaskConfigTab(tab) {
    document.querySelectorAll(".task-config-nav-card").forEach(el => el.classList.toggle("active", false));
    document.querySelectorAll(".task-config-panel").forEach(el => el.classList.toggle("active", false));
    const navCards = document.querySelectorAll(".task-config-nav-card");
    if (tab === "plan" && navCards[0]) navCards[0].classList.add("active");
    if (tab === "sample" && navCards[1]) navCards[1].classList.add("active");
    const panel = document.getElementById(tab === "plan" ? "tcPanelPlan" : "tcPanelSample");
    if (panel) panel.classList.add("active");
    if (tab === "sample") {
      this.updateTaskSampleLimitUI("tcSampleProgress", "tcSamplePick", "tcSampleLimitHint");
    }
  },

  deleteTask(taskId) {
    const p = this.currentProject();
    const s = this.currentStage();
    const t = s?.tasks.find(x => x.id === taskId);
    if (!p || !s || !t) return;
    const executed = this.isTaskExecuted(t);
    const detailsHtml = this.taskDeleteImpactHtml(p, s, t);
    this.confirmTaskDeleteKeyword(
      "删除任务",
      executed
        ? "该任务已经执行过，删除后会从任务管理中隐藏并归档，历史数据继续保留。"
        : "该任务尚未执行，删除后会从任务管理中物理移除。",
      () => {
        this.releaseTaskSamples(t, {
          user: "管理员",
          source: executed ? "任务归档删除" : "任务删除",
          reason: executed ? "任务从任务管理中删除并归档" : "未执行任务被删除",
          projectId: p.id,
          stageId: s.id,
          forceLog: executed
        });
        if (executed) {
          t.archived = true;
          t.deletedAt = Utils.now();
          this.addTaskLog(t, "任务归档删除", { user: "管理员", reason: "任务从任务管理中删除，样机履历保留" });
        } else {
          s.tasks = s.tasks.filter(x => x.id !== taskId);
        }
        this.save(); this.render();
        Utils.toast(executed ? "任务已归档隐藏，样机履历已保留。" : "任务已删除。");
      },
      detailsHtml
    );
  },

  // 启动任务
  startTask(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    if (this.isTaskCompleted(t)) { alert("任务已完成。"); return; }
    if (t.status === "进行中") { alert("任务已在进行中。"); return; }
    if (!(t.sampleIds || []).length) { alert("请先分配样机，再启动任务。"); return; }
    const isRestart = this.taskFlowStatus(t) === "阻塞中";
    if (!t.owner || !t.planStartDate || !t.planEndDate) {
      alert("请先在「设置计划」中填写执行人、计划开始时间和计划终止时间。");
      return;
    }
    if (t.planStartDate > t.planEndDate) {
      alert("计划终止时间不能早于计划开始时间。请先修改计划。");
      return;
    }
    this.showConfirm("开始测试？", () => {
      const user = t.owner;
      const reason = isRestart ? "恢复测试" : "开始测试";
      const from = t.status;
      t.status = "进行中";
      t.completed = false;
      if (!isRestart || !t.startDate) t.startDate = Utils.today();
      const prog = s.progress.find(x => x.id === t.progressId);
      if (prog) { prog.status = "Testing"; prog.owner = t.owner; prog.startDate = t.startDate; }
      (t.sampleIds || []).forEach(id => this.changeSampleStatus(id, "测试中", { user, source: isRestart ? "任务重启" : "任务启动", reason, projectId: p.id, stageId: s.id, taskId: t.id, testItem: t.testItem }));
      this.addTaskLog(t, isRestart ? "重启任务" : "启动任务", { user, reason, fromStatus: from, toStatus: t.status });
      this.save(); this.render();
    }, { title: "启动任务", okText: "开始测试", okClass: "btn btn-pass" });
  },

  /**
   * 判断一段"问题描述"是否是历史脏数据（来自旧版本把"系统自动记录…"长文本误塞入 problemRecords 的情况），
   * 这种文本不应进入"测试结果"的失效问题清单。
   */
  isTaskDirtyProblemText(text) {
    const t = String(text || "");
    if (!t) return true;
    return /系统自动记录|录入样机\s*\d+\s*台|完成计划，正常结束|未完成计划，异常结束|去向：[^；]*\s*\d+\s*台/.test(t);
  },

  /**
   * 收集"本任务"范围内，每台样机被记录到的新增问题（按 sampleId 分组），返回 Map<sampleId, Set<description>>
   * 数据来源（去重 + 过滤脏数据）：
   *   - task.sampleFaultRecords[].problem
   *   - task.resultUploads[].samples[].problem 与 .problemRecords[]（taskLabel 命中本任务）
   *   - task.resultDraft.samples[].problem 与 .problemRecords[]（taskLabel 命中本任务）
   *   - 样机档案 problemRecords[]（taskLabel 命中本任务）
   */
  taskFailureProblemsBySample(project, stage, task) {
    const groups = new Map();
    if (!task) return groups;
    const label = this.sampleTaskLabelFromCtx({
      projectId: project?.id,
      stageId: stage?.id,
      testItem: task.testItem
    });
    const add = (sampleId, text) => {
      const sid = String(sampleId || "").trim();
      const desc = String(text || "").trim();
      if (!sid || !desc) return;
      if (Utils.isNoSampleIssueText(desc)) return;
      if (this.isTaskDirtyProblemText(desc)) return;
      if (!groups.has(sid)) groups.set(sid, new Set());
      groups.get(sid).add(desc);
    };
    (task.sampleFaultRecords || []).forEach(record => add(record.sampleId, record.problem));
    (task.resultUploads || []).forEach(upload => (upload.samples || []).forEach(item => {
      add(item.sampleId || item.sid, item.problem);
      (item.problemRecords || []).forEach(record => {
        if (String(record.taskLabel || "").trim() === label) add(item.sampleId || item.sid, record.description);
      });
    }));
    (task.resultDraft?.samples || []).forEach(item => {
      add(item.sampleId || item.sid, item.problem);
      (item.problemRecords || []).forEach(record => {
        if (String(record.taskLabel || "").trim() === label) add(item.sampleId || item.sid, record.description);
      });
    });
    this.taskResultSampleEntries(task).forEach(entry => {
      const found = this.findSample(entry.sampleId);
      this.sampleProblemRecords(found?.sample).forEach(record => {
        if (String(record.taskLabel || "").trim() === label) add(entry.sampleId, record.description);
      });
    });
    return groups;
  },

  /**
   * 基于"参与过本任务的全部样机"和"问题分组"计算失效统计：
   *   - active：当前仍在 task.sampleIds 中的样机（=正式完成测试的样机）
   *   - removed：在任务进行中被临时变更剔除的样机
   * 每台样机只要在本任务范围内有任何有效问题记录即记一次 F。
   */
  taskFailureStats(project, stage, task) {
    const problems = this.taskFailureProblemsBySample(project, stage, task);
    const entries = this.taskResultSampleEntries(task);
    let activeTotal = 0, activeFail = 0, removedTotal = 0, removedFail = 0;
    entries.forEach(e => {
      const hasProblem = (problems.get(e.sampleId)?.size || 0) > 0;
      if (e.state === "removed") {
        removedTotal++;
        if (hasProblem) removedFail++;
      } else {
        activeTotal++;
        if (hasProblem) activeFail++;
      }
    });
    return { activeTotal, activeFail, removedTotal, removedFail, problems, entries };
  },

  /**
   * 任务"测试结果"列摘要：
   *   行1 失效比例： {F}F/{N}  · 变更 {F}F/{N}（仅在临时变更过的样机存在时显示后半段）
   *   行2..n 失效样机问题清单：每台一行，"{档案号} ：问题1；问题2"，档案号可点击查看样机卡片
   * 无样机或未启动时显示 "-"。
   */
  /**
   * 拼接任务"测试结果"列可见的纯文本，用于关键词搜索。
   * 不产生 DOM/HTML，只返回纯文本字符串。
   */
  taskResultSearchText(project, stage, task) {
    if (!task) return "";
    const parts = [];
    const stats = this.taskFailureStats(project, stage, task);
    // DTS 单号
    if (task.issueRecord?.dtsNo) parts.push(task.issueRecord.dtsNo);
    // 问题确认说明
    if (task.issueRecord?.issueNote) parts.push(task.issueRecord.issueNote);
    // 失效比例统计文字
    if (stats.activeTotal > 0) {
      parts.push(`正式样机 ${stats.activeFail}F/${stats.activeTotal}`);
    }
    if (stats.removedTotal > 0) {
      parts.push(`变更样机 ${stats.removedFail}F/${stats.removedTotal}`);
    }
    // 失效样机的问题描述 + 样机编号
    this.taskResultSampleEntries(task).forEach(entry => {
      const set = stats.problems.get(entry.sampleId);
      if (!set || !set.size) return;
      const found = this.findSample(entry.sampleId);
      const snapshot = task.sampleSnapshots?.[entry.sampleId] || null;
      const code = found?.sample
        ? this.sampleDisplayCode(found.sample)
        : (snapshot?.code || snapshot?.sampleNo || entry.sampleId);
      parts.push(code);
      parts.push([...set].join("；"));
    });
    // 最后一次上传结果
    const lastUpload = (task.resultUploads || []).slice(-1)[0];
    if (lastUpload?.result) parts.push(lastUpload.result);
    return parts.filter(Boolean).join(" ").toLowerCase();
  },

  taskIssueSummaryHtml(project, stage, task) {
    if (!task) return "-";
    const flowStatus = this.taskFlowStatus(task);
    const stats = this.taskFailureStats(project, stage, task);
    const { activeTotal, activeFail, removedTotal, removedFail, problems } = stats;

    // 待下发且没录入过任何结果：保持 "-"
    if (flowStatus === "待下发" && !problems.size && !(task.resultUploads || []).length && !task.resultDraft) {
      return `<span class="muted">-</span>`;
    }
    if (activeTotal === 0 && removedTotal === 0) {
      return `<span class="muted">-</span>`;
    }

    const ratioCls = activeFail > 0 ? "task-result-ratio is-fail" : "task-result-ratio is-pass";
    const removedCls = removedFail > 0 ? "task-result-ratio-removed is-fail" : "task-result-ratio-removed";
    // 失效比例：正式样机 / 变更样机 两组，分别显示完整标签
    const ratioHtml = `<span class="${ratioCls}">正式样机 ${activeFail}F/${activeTotal}</span>`
      + (removedTotal > 0
        ? `<span class="task-result-ratio-sep">·</span><span class="${removedCls}">变更样机 ${removedFail}F/${removedTotal}</span>`
        : "");



    // 失效样机问题清单：按"先 active 后 removed"的顺序遍历
    const failLines = [];
    this.taskResultSampleEntries(task).forEach(entry => {
      const set = problems.get(entry.sampleId);
      if (!set || !set.size) return;
      const found = this.findSample(entry.sampleId);
      const snapshot = task.sampleSnapshots?.[entry.sampleId] || null;
      const code = found?.sample
        ? this.sampleDisplayCode(found.sample)
        : (snapshot?.code || snapshot?.sampleNo || entry.sampleId);
      const codeHtml = found?.sample
        ? `<button type="button" class="sample-log-link" onclick="event.stopPropagation();app.openSampleReadonly('${Utils.esc(entry.sampleId)}')">${Utils.esc(code)}</button>`
        : `<span class="sample-log-ref-missing" title="样机档案不存在或已销毁">${Utils.esc(code)}</span>`;
      const removedTag = entry.state === "removed" ? `<span class="task-result-tag-removed">变更</span>` : "";
      const problemText = Utils.esc([...set].join("；"));
      failLines.push(`<div class="task-result-fail-line">${codeHtml}${removedTag}：${problemText}</div>`);
    });

    return `<div class="task-result-summary">
      <div class="task-result-summary-ratio">${ratioHtml}</div>
      ${failLines.length ? `<div class="task-result-fail-list">${failLines.join("")}</div>` : ""}
    </div>`;
  },

  defaultSampleReceiver(sample, task) {
    return sample?.borrower || "";
  },

  sampleStatusOptionsHtml(selected = "") {
    const selectedStatus = selected === "已借出" ? "取走分析" : selected;
    return this.constants.sampleStatuses.map(status =>
      `<option value="${Utils.esc(status)}" ${status === selectedStatus ? "selected" : ""}>${Utils.esc(status)}</option>`
    ).join("");
  },

  taskSampleFaultOptionsHtml(hasProblem = false, selected = "") {
    const value = selected || (hasProblem ? "故障" : "OK");
    return `<option value="OK" ${value === "OK" ? "selected" : ""}>OK</option><option value="故障" ${value === "故障" ? "selected" : ""}>故障</option>`;
  },

  taskSampleDestinationOptionsHtml(selected = "") {
    const value = ["闲置", "取走分析", "已退库"].includes(selected) ? selected : "闲置";
    return ["闲置", "取走分析", "已退库"].map(dest =>
      `<option value="${Utils.esc(dest)}" ${dest === value ? "selected" : ""}>${Utils.esc(dest)}</option>`
    ).join("");
  },

  onTaskResultDestinationChange(selectEl) {
    const row = selectEl.closest(".task-result-sample-row");
    if (!row) return;
    const dest = selectEl.value;
    const takerSel = row.querySelector("select[id^='taskResultTaker_']");
    if (dest === "取走分析") {
      if (takerSel) { takerSel.disabled = false; takerSel.required = true; }
    } else {
      if (takerSel) { takerSel.disabled = true; takerSel.value = ""; takerSel.required = false; }
    }
    // 更新取走人占位文案
    if (takerSel?.options?.[0]) {
      takerSel.options[0].textContent = dest === "取走分析" ? "请选择取走人" : "无需填写";
    }
    // 更新取走人标签上的必填星号
    const takerLabel = row.querySelector(".task-result-route-grid .form-group:nth-child(3) > label");
    if (takerLabel) {
      const star = takerLabel.querySelector(".req-star");
      if (dest === "取走分析") {
        if (!star) takerLabel.insertAdjacentHTML("beforeend", '<span class="req-star">*</span>');
      } else {
        if (star) star.remove();
      }
    }
  },


  ensureTaskRemovedSampleRecords(task) {
    if (!task) return [];
    if (!Array.isArray(task.removedSampleRecords)) task.removedSampleRecords = [];
    task.removedSampleRecords = task.removedSampleRecords.map(item => {
      if (typeof item === "string") {
        return { id: Utils.id("removed_"), sampleId: item, sampleNo: item, removedAt: "", user: "", reason: "历史退出记录" };
      }
      if (!item || typeof item !== "object") return null;
      return {
        id: item.id || Utils.id("removed_"),
        sampleId: item.sampleId || "",
        sampleNo: item.sampleNo || item.code || item.sampleId || "",
        removedAt: item.removedAt || item.time || "",
        user: item.user || "",
        reason: item.reason || "",
        fromStatus: item.fromStatus || "",
        receiver: item.receiver || ""
      };
    }).filter(item => item?.sampleId);
    return task.removedSampleRecords;
  },

  recordTaskRemovedSamples(task, sampleIds = [], ctx = {}) {
    if (!task || !sampleIds.length) return;
    const records = this.ensureTaskRemovedSampleRecords(task);
    const removedAt = ctx.removedAt || Utils.now();
    sampleIds.forEach(sampleId => {
      const found = this.findSample(sampleId);
      const sample = found?.sample || {};
      records.push({
        id: Utils.id("removed_"),
        sampleId,
        sampleNo: this.taskSampleDisplayName(sampleId),
        sn: sample.sn || "",
        imei: sample.imei || "",
        boardSn: sample.boardSn || "",
        removedAt,
        user: ctx.user || "",
        reason: ctx.reason || "",
        fromStatus: found ? this.sampleEffectiveStatus(sample) : "",
        receiver: ctx.receiver || ""
      });
    });
  },

  taskResultSampleEntries(task) {
    if (!task) return [];
    const activeIds = [...new Set(task.sampleIds || [])];
    const activeSet = new Set(activeIds);
    const removedBySample = new Map();
    this.ensureTaskRemovedSampleRecords(task).forEach(record => {
      if (!record.sampleId || activeSet.has(record.sampleId)) return;
      removedBySample.set(record.sampleId, { ...record, state: "removed" });
    });
    return [
      ...activeIds.map(sampleId => ({ sampleId, state: "active" })),
      ...[...removedBySample.values()]
    ];
  },

  taskResultProblemTableHtml(sample, rowIdx, draftItem = null) {
    const problems = Array.isArray(draftItem?.problemRecords)
      ? draftItem.problemRecords
      : (sample ? this.sampleProblemRecords(sample) : []);
    const rows = problems.map(item => this.taskResultProblemRowHtml(item)).join("");
    const photos = Array.isArray(draftItem?.photos) ? draftItem.photos : [];
    return `
      <div class="task-result-new-problem">
        <label>本次新增失效/问题</label>
        <div class="task-result-problem-line">
          <input class="task-result-sample-problem" value="${Utils.esc(draftItem?.problem || "")}" placeholder="不填则不追加问题记录">
          <button type="button" class="btn btn-outline task-result-photo-btn" ${sample ? "" : "disabled"} onclick="app.uploadTaskResultPhotos(this)">上传图片</button>
        </div>
        <input type="hidden" class="task-result-sample-photos" value="${Utils.esc(JSON.stringify(photos))}">
        <div class="task-result-photo-list"></div>
      </div>
      <div class="task-result-problem-board">
        <div class="task-result-problem-head">
          <b>样机问题表</b>
          <span>这里和样机档案里的问题表同步；修改或删除后，点击保存。</span>
        </div>
        <div class="task-result-existing-problems">
          ${rows || `<div class="task-result-problem-empty">当前档案暂无问题记录。</div>`}
        </div>
      </div>`;
  },

  taskResultProblemRowHtml(record = {}) {
    const item = typeof record === "string" ? { description: record, source: "手动补录", taskLabel: "" } : record;
    return `<div class="task-result-existing-problem-row" data-problem-id="${Utils.esc(item.id || Utils.id("problem_"))}">
      <div class="task-result-problem-no">已有</div>
      <input class="task-result-existing-problem-desc" value="${Utils.esc(item.description || "")}" placeholder="问题描述">
      <input class="task-result-existing-problem-source" value="${Utils.esc(item.source || "手动补录")}" placeholder="来源">
      <input class="task-result-existing-problem-task" value="${Utils.esc(item.taskLabel || "")}" placeholder="关联任务">
      <button type="button" class="sample-result-btn remove" title="从样机问题表删除" onclick="app.removeTaskResultProblemRow(this)">-</button>
    </div>`;
  },

  removeTaskResultProblemRow(btn) {
    const row = btn?.closest?.(".task-result-existing-problem-row");
    const wrap = btn?.closest?.(".task-result-existing-problems");
    if (!row || !wrap) return;
    row.remove();
    if (!wrap.querySelector(".task-result-existing-problem-row")) {
      wrap.innerHTML = `<div class="task-result-problem-empty">当前档案暂无问题记录。</div>`;
    }
  },

  taskResultSampleRowsHtml(task, draft = null) {
    const entries = this.taskResultSampleEntries(task);
    const draftBySample = new Map((draft?.samples || []).map(item => [item.sampleId || item.sid, item]));
    return entries.map((entry, idx) => {
      const id = entry.sampleId;
      const draftItem = draftBySample.get(id) || null;
      const found = this.findSample(id);
      const sample = found?.sample || {};
      const snapshot = task.sampleSnapshots?.[id] || null;
      const status = found ? this.sampleEffectiveStatus(sample) : "闲置";
      const receiver = draftItem?.receiver || this.defaultSampleReceiver(sample, task);
      const destination = draftItem?.destination || (status === "取走分析" || status === "已退库" ? status : "闲置");
      const accountOwner = draftItem?.accountOwner || sample.owner || "";
      const destLocation = draftItem?.destLocation || sample.location || "";
      const isTakerDisabled = destination !== "取走分析";
      const takerPlaceholder = isTakerDisabled ? "无需填写" : "请选择取走人";
      const removedInfo = entry.state === "removed"
        ? `<span class="task-result-sample-state removed">已退出测试</span><span>退出时间：${Utils.esc(entry.removedAt || "-")}</span>${entry.reason ? `<span>退出原因：${Utils.esc(entry.reason)}</span>` : ""}`
        : `<span class="task-result-sample-state active">当前测试样机</span>`;
      // 项目位置列表（供去向位置 datalist 使用）
      const p = this.currentProject();
      const locationOptions = (p?.locations || []).map(loc => `<option value="${Utils.esc(loc)}">`).join("");
      return `<div class="task-result-sample-row ${entry.state === "removed" ? "is-removed" : ""}" data-sid="${Utils.esc(id)}" data-sample-state="${Utils.esc(entry.state)}">
        <div class="task-result-sample-index">${idx + 1}</div>
        <div class="task-result-sample-code">
          <b>${Utils.esc(this.taskSampleArchiveName(id, snapshot))}</b>
          ${removedInfo}
        </div>
        <div class="task-result-route-grid">
          <div class="form-group">
            <label class="req">样机去向</label>
            <select class="task-result-sample-destination" onchange="app.onTaskResultDestinationChange(this)">${this.taskSampleDestinationOptionsHtml(destination)}</select>
          </div>
          <div class="form-group">
            <label class="req">去向位置</label>
            <input class="task-result-sample-location" list="taskResultLocationList_${idx}" value="${Utils.esc(destLocation)}" placeholder="如：失效分析区">
            <datalist id="taskResultLocationList_${idx}">${locationOptions}</datalist>
          </div>
          <div class="form-group">
            <label>取走人${destination === '取走分析' ? '<span class="req-star">*</span>' : ''}</label>
            ${this.projectMemberSelectHtml(`taskResultTaker_${idx}`, receiver, takerPlaceholder, isTakerDisabled)}
          </div>
          <div class="form-group">
            <label>挂账人</label>
            ${this.projectMemberSelectHtml(`taskResultAccountOwner_${idx}`, accountOwner, "请选择挂账人")}
          </div>
        </div>
        <div class="form-group task-result-problem-field">
          ${this.taskResultProblemTableHtml(found ? sample : null, idx, draftItem)}
        </div>
      </div>`;
    }).join("") || `<div class="empty">该任务暂无样机。</div>`;
  },

  taskResultRowPhotos(row) {
    const input = row?.querySelector(".task-result-sample-photos");
    if (!input) return [];
    try {
      const parsed = JSON.parse(input.value || "[]");
      return Array.isArray(parsed) ? parsed.filter(x => x && x.id) : [];
    } catch {
      return [];
    }
  },

  setTaskResultRowPhotos(row, photos) {
    const input = row?.querySelector(".task-result-sample-photos");
    if (!input) return;
    const byId = new Map((photos || []).filter(x => x && x.id).map(x => [x.id, x]));
    input.value = JSON.stringify([...byId.values()]);
    this.renderTaskResultPhotoList(row);
  },

  renderTaskResultPhotoList(row) {
    const list = row?.querySelector(".task-result-photo-list");
    if (!list) return;
    const sampleId = row.dataset.sid || "";
    const photos = this.taskResultRowPhotos(row);
    list.innerHTML = photos.length ? photos.map(photo => `
      <button type="button" class="task-result-photo-chip" onclick="app.previewSamplePhoto('${Utils.esc(sampleId)}','${Utils.esc(photo.id)}')" title="${Utils.esc(photo.name || "结果图片")}">
        ${photo.url ? `<img src="${Utils.esc(photo.url)}" alt="${Utils.esc(photo.name || "结果图片")}">` : ""}
        <span>${Utils.esc(photo.name || "结果图片")}</span>
      </button>
    `).join("") : "";
  },

  uploadTaskResultPhotos(btn) {
    const row = btn?.closest?.(".task-result-sample-row");
    const sampleId = row?.dataset?.sid || "";
    const found = this.findSample(sampleId);
    if (!row || !found) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = true;
    input.onchange = async () => {
      const files = [...(input.files || [])];
      if (!files.length) return;
      const oldText = btn.innerText;
      btn.disabled = true;
      btn.innerText = "上传中...";
      try {
        const form = new FormData();
        files.forEach(file => form.append("photos", file, file.name));
        form.append("revision", String(this.serverRevision || 0));
        const ctx = this._taskResultUploadContext || {};
        form.append("remark", `任务结果图片：${ctx.taskLabel || "未命名任务"}`);
        const res = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/photos`, { method: "POST", body: form });
        const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
        if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
        found.sample.photos = Array.isArray(obj.photos) ? obj.photos : (found.sample.photos || []);
        found.sample.updatedAt = Utils.now();
        if (obj.revision) this.serverRevision = obj.revision;
        if (obj.updated_at) this.serverUpdatedAt = obj.updated_at;
        const uploaded = (obj.uploaded || []).map(photo => ({
          id: photo.id,
          name: photo.name || "结果图片",
          url: photo.url || "",
          uploadedAt: photo.uploadedAt || Utils.now(),
          type: photo.type || "",
          size: photo.size || 0
        })).filter(photo => photo.id);
        this.setTaskResultRowPhotos(row, [...this.taskResultRowPhotos(row), ...uploaded]);
        this._baseData = this.cloneData(this.data);
        this.updateServerStatus("已保存");
        Utils.toast(`已上传 ${uploaded.length || files.length} 张结果图片。`);
      } catch (e) {
        alert("结果图片上传失败：" + (e.message || e));
      } finally {
        btn.disabled = false;
        btn.innerText = oldText;
      }
    };
    input.click();
  },

  appendTaskSampleFault(task, sampleId, record) {
    if (!task || !sampleId || !record) return;
    if (!Array.isArray(task.sampleFaultRecords)) task.sampleFaultRecords = [];
    const item = { id: Utils.id("fault_"), sampleId, ...record };
    task.sampleFaultRecords.push(item);
    if (!task.sampleFaults || typeof task.sampleFaults !== "object" || Array.isArray(task.sampleFaults)) task.sampleFaults = {};
    task.sampleFaults[sampleId] = {
      fault: !!record.fault,
      problem: record.problem || "",
      source: record.source || "结果上传",
      time: record.time || Utils.now(),
      result: record.result || ""
    };
  },

  collectTaskResultForm() {
    const result = document.getElementById("taskResultValue")?.value || "";
    const user = document.getElementById("taskResultUser")?.value.trim() || "";
    const resultDate = document.getElementById("taskResultDate")?.value || Utils.today();
    const finishType = document.getElementById("taskFinishType")?.value || "正常完成";
    const samples = [...document.querySelectorAll(".task-result-sample-row")].map(row => {
      const sid = row.dataset.sid;
      const state = row.dataset.sampleState || "active";
      const destination = row.querySelector(".task-result-sample-destination")?.value || "闲置";
      const destLocation = row.querySelector(".task-result-sample-location")?.value.trim() || "";
      const accountOwner = row.querySelector("select[id^='taskResultAccountOwner_']")?.value.trim() || "";
      const receiver = row.querySelector("select[id^='taskResultTaker_']")?.value.trim() || "";
      const problem = row.querySelector(".task-result-sample-problem")?.value.trim() || "";
      const problemRecords = [...row.querySelectorAll(".task-result-existing-problem-row")].map(problemRow => ({
        id: problemRow.dataset.problemId || Utils.id("problem_"),
        description: problemRow.querySelector(".task-result-existing-problem-desc")?.value.trim() || "",
        source: problemRow.querySelector(".task-result-existing-problem-source")?.value.trim() || "手动补录",
        taskLabel: problemRow.querySelector(".task-result-existing-problem-task")?.value.trim() || ""
      })).filter(item => item.description && !Utils.isNoSampleIssueText(item.description));
      // 自动判断：只有本次填写了新增失效才算故障，已有问题表不参与故障判定
      const hasNewProblem = !!problem && !Utils.isNoSampleIssueText(problem);
      const fault = hasNewProblem ? "故障" : "OK";
      const photos = this.taskResultRowPhotos(row).map(photo => ({
        id: photo.id,
        name: photo.name || "结果图片",
        url: photo.url || "",
        uploadedAt: photo.uploadedAt || "",
        type: photo.type || "",
        size: photo.size || 0
      }));
      return { sid, state, fault, destination, destLocation, accountOwner, receiver, problem, problemRecords, photos };
    });
    return { result, user, resultDate, finishType, samples };
  },

  validateTaskResultPayload(payload, finishTask = false) {
    if (!payload.result) return "请选择 PASS / FAIL。";
    if (!payload.user) return "请选择操作人。请先在项目人员配置中新增人员。";
    if (finishTask && payload.finishType === "异常完成" && payload.result !== "Fail") {
      return "没有完成预定计划时，结果必须选择 Fail。";
    }
    const missingLocation = payload.samples.find(x => !x.destLocation);
    if (missingLocation) return `样机 ${this.taskSampleDisplayName(missingLocation.sid)} 必须填写去向位置。`;
    const missingTaker = payload.samples.find(x => x.destination === "取走分析" && !x.receiver);
    if (missingTaker) return `样机 ${this.taskSampleDisplayName(missingTaker.sid)} 去向为"取走分析"时，必须选择取走人。`;
    const missingProblem = payload.samples.find(x => x.fault === "故障" && !x.problem && !(x.problemRecords || []).length);
    if (missingProblem) return `样机 ${this.taskSampleDisplayName(missingProblem.sid)} 标记为故障时，必须填写本次失效/问题。`;
    return "";
  },

  clearTaskResultValidationMarks() {
    this.clearFieldValidationMarks();
    document.querySelectorAll(".task-result-modal .task-result-sample-row.has-error").forEach(el => el.classList.remove("has-error"));
  },

  markTaskResultInvalid(el, message) {
    this.markFieldInvalid(el, message);
    el?.closest(".task-result-sample-row")?.classList.add("has-error");
  },

  markTaskResultValidation(payload, finishTask = false) {
    this.clearTaskResultValidationMarks();
    if (!finishTask) return;
    if (!payload.result) this.markTaskResultInvalid(document.getElementById("taskResultValue"), "结束任务前必须选择 PASS / FAIL");
    if (!payload.user) this.markTaskResultInvalid(document.getElementById("taskResultUser"), "结束任务前必须选择操作人");
    document.querySelectorAll(".task-result-sample-row").forEach((row, idx) => {
      const item = payload.samples[idx];
      if (!item) return;
      if (!item.destLocation) {
        this.markTaskResultInvalid(row.querySelector(".task-result-sample-location"), "必须填写去向位置");
      }
      if (item.destination === "取走分析" && !item.receiver) {
        this.markTaskResultInvalid(row.querySelector("select[id^='taskResultTaker_']"), "必须选择取走人");
      }
      if (item.fault === "故障" && !item.problem && !(item.problemRecords || []).length) {
        this.markTaskResultInvalid(row.querySelector(".task-result-sample-problem"), "标记故障时必须填写或保留问题记录");
      }
    });
    document.querySelector(".task-result-modal .is-invalid")?.scrollIntoView({ block: "center", behavior: "smooth" });
  },

  /**
   * 任务结果摘要（仅用于任务日志和样机履历 reason 字段）
   * 只保留核心信息：测试结果 + 失效比例 + 新增失效（不再输出 OK 台数/去向/上传图片数等无用统计）。
   * 注意：本字符串不应再被作为 problemDescription 落入样机 problemRecords。
   */
  taskResultAutoReason(payload, finishTask = false, ctx = {}) {
    const samples = payload.samples || [];
    const removedCount = samples.filter(x => x.state === "removed").length;
    const activeCount = samples.length - removedCount;
    // 失效判定：只统计本次在「本次新增失效/问题」输入框中填写的内容
    const sampleFailureText = (x) => {
      const newProblem = String(x.problem || "").trim();
      if (newProblem && !Utils.isNoSampleIssueText(newProblem)) return newProblem;
      return "";
    };
    const failed = samples.map(x => ({ x, problem: sampleFailureText(x) })).filter(o => o.problem);
    const activeFail = failed.filter(o => o.x.state !== "removed").length;
    const removedFail = failed.filter(o => o.x.state === "removed").length;
    const ratio = `正式 ${activeFail}F/${activeCount}`
      + (removedCount ? `，变更 ${removedFail}F/${removedCount}` : "");
    const allProblems = failed.map(o => `${this.taskSampleDisplayName(o.x.sid)}：${o.problem}${o.x.state === "removed" ? "（变更）" : ""}`);
    const maxProblemItems = 5;
    const truncatedProblems = allProblems.length > maxProblemItems
      ? allProblems.slice(0, maxProblemItems).concat(`等 ${allProblems.length} 项`)
      : allProblems;
    const finishText = finishTask
      ? `；${payload.finishType === "异常完成" ? "未完成计划，异常结束" : "完成计划，正常结束"}`
      : "";
    const prefix = `测试结果：${payload.result}（${ratio}）`;
    const suffix = truncatedProblems.length ? `；新增失效：${truncatedProblems.join("；")}` : "";
    let reason = `${prefix}${suffix}${finishText}`;
    if (reason.length > 500) {
      reason = reason.slice(0, 497) + "...";
    }
    return reason;
  },


  syncTaskResultSampleProblems(sample, item, ctx = {}) {
    if (!sample) return [];
    const taskLabel = this.sampleTaskLabelFromCtx(ctx);
    const records = (item.problemRecords || []).map(record => ({
      id: record.id || Utils.id("problem_"),
      description: String(record.description || "").trim(),
      source: String(record.source || "手动补录").trim(),
      taskLabel: String(record.taskLabel || "").trim()
    })).filter(record => record.description && !Utils.isNoSampleIssueText(record.description));
    const newProblem = String(item.problem || "").trim();
    if (newProblem && !Utils.isNoSampleIssueText(newProblem)) {
      const newRecord = {
        id: Utils.id("problem_"),
        description: newProblem,
        source: "测试任务",
        taskLabel
      };
      const exists = records.some(record =>
        record.description === newRecord.description &&
        record.source === newRecord.source &&
        record.taskLabel === newRecord.taskLabel
      );
      if (!exists) records.push(newRecord);
    }
    sample.problemRecords = records;
    sample.initialResults = records.map(record => record.description);
    sample.initialResult = sample.initialResults.join("\n");
    return records;
  },

  saveTaskResultDraft(project, stage, task, payload) {
    const ctx = {
      projectId: project.id,
      stageId: stage.id,
      taskId: task.id,
      testItem: task.testItem
    };
    const samples = (payload.samples || []).map(item => {
      const found = this.findSample(item.sid);
      const problemRecords = this.syncTaskResultSampleProblems(found?.sample, item, ctx);
      return {
        ...item,
        problem: "",
        problemRecords: problemRecords.length ? problemRecords : (item.problemRecords || [])
      };
    });
    task.resultDraft = {
      ...payload,
      samples,
      savedAt: Utils.now()
    };
  },

  applyTaskResult(project, stage, task, payload, finishTask = false) {
    const from = task.status;
    const now = Utils.now();
    const result = finishTask && payload.finishType === "异常完成" ? "Fail" : payload.result;
    const reason = this.taskResultAutoReason({ ...payload, result }, finishTask, { projectId: project.id, stageId: stage.id, testItem: task.testItem });
    task.latestResult = result;
    task.resultDate = payload.resultDate;

    payload.samples.forEach(item => {
      const found = this.findSample(item.sid);
      item.problemRecords = this.syncTaskResultSampleProblems(found?.sample, item, {
        projectId: project.id,
        stageId: stage.id,
        taskId: task.id,
        testItem: task.testItem
      });
      const isFault = item.fault === "故障";
      const status = item.destination || "闲置";
      if (item.problem) {
        this.appendTaskSampleFault(task, item.sid, {
          fault: true,
          problem: item.problem,
          source: finishTask ? "任务结束" : "结果上传",
          time: now,
          result,
          sampleState: item.state || "active",
          removedFromTask: item.state === "removed",
          photos: item.photos || []
        });
      }
      const photoIds = (item.photos || []).map(photo => photo.id).filter(Boolean);
      this.changeSampleStatus(item.sid, status, {
        user: payload.user,
        receiver: item.receiver,
        accountOwner: item.accountOwner || "",
        destination: item.destination,
        destLocation: item.destLocation || "",
        receiverDate: payload.resultDate,
        source: finishTask ? "任务结束" : "结果上传",
        reason,
        projectId: project.id,
        stageId: stage.id,
        taskId: task.id,
        testItem: task.testItem,
        faultMarked: isFault,
        problemDescription: item.problem,
        photoIds,
        photos: item.photos || []
      });
    });

    if (!Array.isArray(task.resultUploads)) task.resultUploads = [];
    task.resultUploads.push({
      id: Utils.id("result_"),
      result,
      user: payload.user,
      resultDate: payload.resultDate,
      reason,
      time: now,
      finishTask,
      finishType: finishTask ? payload.finishType : "",
      samples: payload.samples.map(item => ({
        sampleId: item.sid,
        state: item.state || "active",
        fault: item.fault,
        destination: item.destination,
        destLocation: item.destLocation || "",
        receiver: item.receiver,
        accountOwner: item.accountOwner || "",
        problem: item.problem || "",
        problemRecords: item.problemRecords || [],
        photos: item.photos || []
      }))
    });

    if (finishTask) {
      const completionType = payload.finishType === "异常完成" ? "异常完成" : "正常完成";
      const completionLabel = completionType === "异常完成" ? "异常终止" : completionType;
      task.status = completionType;
      task.completed = true;
      task.completionType = completionType;
      task.completedAt = now;
      task.endDate = payload.resultDate || Utils.today();
      const progress = stage.progress.find(x => x.id === task.progressId);
      if (progress) {
        progress.status = result;
        progress.endDate = task.endDate;
        progress.issue = result === "Fail" ? reason : "";
      }
      this.addTaskLog(task, "结束任务", {
        user: payload.user,
        reason,
        fromStatus: from,
        toStatus: completionLabel,
        detail: `结果：${result}；结束方式：${completionLabel}`
      });
    } else {
      this.addTaskLog(task, "上传结果", {
        user: payload.user,
        reason,
        fromStatus: from,
        toStatus: task.status,
        detail: `结果：${result}`
      });
    }
  },

  isTaskResultSamplesEqual(a, b) {
    if (!a || !b) return false;
    const sa = a.samples || [], sb = b.samples || [];
    if (sa.length !== sb.length) return false;
    return sa.every((item, i) => {
      const o = sb[i];
      if (!o) return false;
      if (item.state !== o.state || item.fault !== o.fault || item.destination !== o.destination) return false;
      if (item.destLocation !== o.destLocation || item.accountOwner !== o.accountOwner || item.receiver !== o.receiver || item.problem !== o.problem) return false;
      const ra = (item.problemRecords || []).map(r => r.description || "").filter(Boolean).sort().join("|");
      const rb = (o.problemRecords || []).map(r => r.description || "").filter(Boolean).sort().join("|");
      return ra === rb;
    });
  },

  isTaskResultPayloadEqual(a, b) {
    if (!a || !b) return false;
    if ((a.result || "") !== (b.result || "")) return false;
    if ((a.user || "") !== (b.user || "")) return false;
    if ((a.resultDate || "") !== (b.resultDate || "")) return false;
    if ((a.finishType || "") !== (b.finishType || "")) return false;
    return this.isTaskResultSamplesEqual(a, b);
  },

  saveTaskResult(projectId, stageId, taskId, finishTask = false) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!p || !s || !t) return false;
    const payload = this.collectTaskResultForm();
    if (!finishTask) {
      const baselineUnchanged =
        this._taskResultBaselineTaskId === taskId &&
        this.isTaskResultPayloadEqual(this._taskResultBaseline, payload);

      if (baselineUnchanged) {
        Utils.toast("未检测到结果变更，未写入日志。");
        return false;
      }

      const samplesChanged = !t.resultDraft || !this.isTaskResultSamplesEqual(t.resultDraft, payload);
      this.saveTaskResultDraft(p, s, t, payload);
      if (samplesChanged) {
        this.applyTaskResult(p, s, t, payload, false);
      }
      this.save(); this.render();
      Utils.toast(samplesChanged ? "结果已保存，样机去向和人员已同步到样机档案。" : "结果已保存（样机无变化）。");
      return false;
    }
    const error = this.validateTaskResultPayload(payload, finishTask);
    if (error) {
      this.markTaskResultValidation(payload, finishTask);
      return true;
    }
    this.applyTaskResult(p, s, t, payload, finishTask);
    if (finishTask) delete t.resultDraft;
    this.save(); this.render();
    Utils.toast(finishTask ? "任务已结束，结果和样机档案已同步。" : "本次结果已保存，样机档案已同步。");
    return false;
  },

  tempChangeTask(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!p || !s || !t || this.isTaskCompleted(t)) return;
    const progress = s.progress.find(x => x.id === t.progressId);
    const sampleCards = this.buildTaskSamplePickerHtml(t.sampleIds || [], "tempSamplePick", "", "", t.id);
    this.showModal("临时变更", `
      <div class="temp-change-header-row">
        <div class="form-group"><label class="req danger-field-label">任务变更人</label>${this.projectMemberSelectHtml("tempUser", "", "请选择任务变更人")}</div>
        <div class="form-group"><label>变更原因</label><textarea id="tempReason" rows="1" class="temp-reason-one-line" placeholder="选填"></textarea></div>
      </div>
      <div class="temp-change-plan-row">
        <div class="form-group"><label class="req">执行人变更</label>${this.projectMemberSelectHtml("tempOwner", t.owner || "", "请选择执行人")}</div>
        <div class="form-group"><label>计划开始</label><input type="date" id="tempPlanStart" value="${Utils.esc(t.planStartDate || t.planDate || "")}"></div>
        <div class="form-group"><label>计划完成</label><input type="date" id="tempPlanEnd" value="${Utils.esc(t.planEndDate || t.endDate || "")}"></div>
      </div>
      <div class="temp-change-sample-section">
        <div class="form-group"><label>样机逐台变更</label><div class="dispatch-sample-select">${sampleCards}</div></div>
      </div>
    `, () => {
      const user = document.getElementById("tempUser").value.trim();
      const owner = document.getElementById("tempOwner").value.trim();
      const reason = document.getElementById("tempReason").value.trim();
      const planStart = document.getElementById("tempPlanStart").value;
      const planEnd = document.getElementById("tempPlanEnd").value;
      const newSampleIds = this.getSelectedTaskSampleIds("tempSamplePick");
      this.clearFieldValidationMarks();
      if (!user) { this.markFieldInvalid(document.getElementById("tempUser"), "请选择任务变更人。"); return true; }
      if (!owner) { this.markFieldInvalid(document.getElementById("tempOwner"), "请选择执行人。"); return true; }
      const changeReason = reason || "临时变更";
      if (progress) {
        const check = this.validateTaskSampleSelection(progress, newSampleIds, "临时变更");
        if (!check.ok) {
          const sampleArea = document.querySelector(".dispatch-sample-select");
          this.markFieldInvalid(sampleArea, check.msg);
          return true;
        }
      }

      // 保存旧值，供差异判断和日志使用
      const beforeOwner = String(t.owner || "").trim();
      const beforePlanStart = String(t.planStartDate || t.planDate || "").trim();
      const beforePlanEnd = String(t.planEndDate || t.endDate || "").trim();
      const beforeSampleIds = [...(t.sampleIds || [])];
      const beforeStatus = this.taskFlowStatus(t);

      const afterOwner = String(owner || "").trim();
      const afterPlanStart = String(planStart || "").trim();
      const afterPlanEnd = String(planEnd || "").trim();
      const afterSampleIds = newSampleIds;

      const ownerChanged = beforeOwner !== afterOwner;
      const planStartChanged = beforePlanStart !== afterPlanStart;
      const planEndChanged = beforePlanEnd !== afterPlanEnd;
      const removed = beforeSampleIds.filter(id => !afterSampleIds.includes(id));
      const added = afterSampleIds.filter(id => !beforeSampleIds.includes(id));
      const sampleChanged = removed.length > 0 || added.length > 0;

      if (!ownerChanged && !planStartChanged && !planEndChanged && !sampleChanged) {
        Utils.toast("未检测到变更");
        this.closeModal();
        return;
      }

      // 写入新值
      t.owner = afterOwner;
      t.planStartDate = afterPlanStart;
      t.planEndDate = afterPlanEnd;
      t.planDate = afterPlanStart || t.planDate || "";
      t.sampleIds = afterSampleIds;

      if (progress) {
        if (ownerChanged) progress.owner = afterOwner;
        if (sampleChanged) progress.sampleIds = [...new Set([...(progress.sampleIds || []), ...afterSampleIds])];
      }

      // 只有样机变了才记录退出/新增和更新样机状态
      if (sampleChanged) {
        this.recordTaskRemovedSamples(t, removed, { user, reason, receiver: owner });
        removed.forEach(id => {
          if (!this.isSampleUsedByAnotherOpenTask(id, t.id)) {
            const found = this.findSample(id);
            this.changeSampleStatus(id, "闲置", {
              user,
              receiver: found?.sample?.owner || owner,
              source: "任务临时变更",
              reason: "从当前任务移除；" + changeReason,
              projectId: p.id,
              stageId: s.id,
              taskId: t.id,
              testItem: t.testItem
            });
          }
        });
        added.forEach(id => this.changeSampleStatus(id, this.statusForOpenTaskUsage(t), {
          user,
          receiver: owner,
          source: "任务临时变更",
          reason: "加入当前任务；" + changeReason,
          projectId: p.id,
          stageId: s.id,
          taskId: t.id,
          testItem: t.testItem
        }));
      }

      // 生成差异日志（只记录真实变化项）
      const afterStatus = this.taskFlowStatus(t);
      const sampleName = (id) => this.sampleDisplayCode(this.findSample(id)?.sample) || id;
      const removedNames = removed.map(sampleName);
      const addedNames = added.map(sampleName);
      const detailParts = [];
      if (ownerChanged) {
        detailParts.push(`任务执行人：${beforeOwner || "-"} → ${afterOwner || "-"}`);
      }
      if (planStartChanged) {
        detailParts.push(`计划开始：${beforePlanStart || "待设置"} → ${afterPlanStart || "待设置"}`);
      }
      if (planEndChanged) {
        detailParts.push(`计划终止：${beforePlanEnd || "待设置"} → ${afterPlanEnd || "待设置"}`);
      }
      // 样机变更：按退出→新增逐对展示
      const maxPairs = Math.max(removedNames.length, addedNames.length);
      for (let i = 0; i < maxPairs; i++) {
        const out = removedNames[i] || "-";
        const inn = addedNames[i] || "-";
        detailParts.push(`样机变更：${out} → ${inn}`);
      }
      this.addTaskLog(t, "临时变更", {
        user,
        reason: changeReason,
        fromStatus: beforeStatus,
        toStatus: afterStatus,
        detail: detailParts.join("；"),
        detailLines: detailParts
      });

      this.save(); this.render();
    }, "确认", { className: "temp-change-modal", headerHint: `任务：${Utils.esc(t.testItem || "-")}` });
  },

  // 阻塞任务
  blockTask(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t || this.isTaskCompleted(t)) return;
    if (this.taskFlowStatus(t) === "阻塞中") { alert("任务已是阻塞状态。"); return; }

    this.showModal("阻塞暂停", `
      <div class="task-block-task-title">任务：${Utils.esc(t.testItem || "-")}</div>
      <div class="task-block-task-desc">阻塞只记录任务无法继续，样机失效请通过"上传结果"追加到档案。</div>
      <div class="form-group"><label class="req">状态变更人</label>${this.projectMemberSelectHtml("user", "", "请选择状态变更人")}</div>
      <div class="form-group"><label class="req">阻塞原因说明</label><textarea id="reason" rows="3" placeholder="必须填写，如：设备故障暂停"></textarea></div>
    `, () => {
      this.clearFieldValidationMarks();
      const user = document.getElementById("user").value.trim();
      const reason = document.getElementById("reason").value.trim();
      if (!user) { this.markFieldInvalid(document.getElementById("user"), "请选择状态变更人。请先在项目人员配置中新增人员。"); return true; }
      if (!reason) { this.markFieldInvalid(document.getElementById("reason"), "必须填写阻塞原因"); return true; }
      const from = t.status;
      t.status = "阻塞"; t.blockReason = reason;
      const prog = s.progress.find(x => x.id === t.progressId);
      if (prog) { prog.status = "阻塞"; prog.issue = reason; }
      (t.sampleIds || []).forEach(id => this.changeSampleStatus(id, "在位等待", { user, source: "任务阻塞", reason, projectId: p.id, stageId: s.id, taskId: t.id, testItem: t.testItem }));
      this.addTaskLog(t, "阻塞任务", { user, reason, fromStatus: from, toStatus: t.status });
      this.save(); this.render();
    });
  },

  // 上传结果（完成前后均可）
  uploadResult(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    if (this.taskFlowStatus(t) === "待下发") { alert("任务尚未启动。"); return; }
    const addOnly = this.isTaskCompleted(t);
    const draft = addOnly ? null : (t.resultDraft || {});
    const resultValue = draft?.result || "";
    const resultOptions = ["Pass", "Fail"].map(value => `<option value="${value}" ${resultValue === value ? "selected" : ""}>${value === "Pass" ? "PASS" : "FAIL"}</option>`).join("");
    const resultDate = draft?.resultDate || Utils.today();
    const finishType = draft?.finishType || "正常完成";
    this._taskResultUploadContext = {
      projectId,
      stageId,
      taskId,
      taskLabel: [p?.name, s?.name, t.testItem].filter(Boolean).join(" - ")
    };

    this.showModal(addOnly ? "添加结果" : "上传测试结果", `
      <div class="task-result-layout">
        <section class="task-result-fixed-panel">
          <div class="task-result-fixed-head">
            <div>
              <b>任务级结果</b>
              <span>保存可暂存阶段性结果；只有点击"结束任务"时才会检查全部必填项。</span>
            </div>
          </div>
          <div class="task-result-form-grid">
            <div class="form-group"><label class="req">结果</label><select id="taskResultValue"><option value="">请选择 PASS / FAIL</option>${resultOptions}</select></div>
            <div class="form-group"><label class="req">操作人</label>${this.projectMemberSelectHtml("taskResultUser", draft?.user || "", "请选择操作人")}</div>
            ${addOnly
              ? `<div class="form-group"><label>结果日期</label><input type="date" id="taskResultDate" value="${Utils.today()}"><input type="hidden" id="taskFinishType" value="正常完成"></div>`
              : `<div class="form-group"><label>结果日期</label><input type="date" id="taskResultDate" value="${Utils.esc(resultDate)}"></div>
                <div class="form-group"><label>结束任务方式</label><select id="taskFinishType" class="hint-select"><option value="正常完成" ${finishType === "正常完成" ? "selected" : ""}>完成计划，正常结束</option><option value="异常完成" ${finishType === "异常完成" ? "selected" : ""}>未完成计划，异常结束</option></select></div>`}
          </div>
        </section>
        <section class="task-result-scroll-panel">
          <div class="task-result-section-title">
            <div>
              <b>每台样机结果与去向</b>
              <span>先确认样机结果，再填写去向和接收人；问题表会和样机档案同步。</span>
            </div>
          </div>
          <div class="task-result-sample-list">${this.taskResultSampleRowsHtml(t, draft)}</div>
        </section>
      </div>
    `, () => this.saveTaskResult(projectId, stageId, taskId, false), "保存", {
      className: "task-result-modal",
      headerHint: addOnly
        ? `任务：${t.testItem || "-"}；任务已结束，仅追加新的样机结果、图片和失效记录，不改变任务结束状态。`
        : `任务：${t.testItem || "-"}；可多次上传。本次新增失效会追加到样机档案的问题表中，临时变更退出过的样机也会保留在这里录入。`
    });
    document.querySelectorAll(".task-result-sample-row").forEach(row => this.renderTaskResultPhotoList(row));

    // 记录弹窗打开时的基线快照，用于保存时判断是否有变更
    this._taskResultBaselineTaskId = taskId;
    this._taskResultBaseline = this.collectTaskResultForm();

    if (!addOnly) {
      const ok = document.getElementById("modalOk");
      const endBtn = document.createElement("button");
      endBtn.type = "button";
      endBtn.className = "btn btn-purple modal-extra-action";
      endBtn.innerText = "结束任务";
      endBtn.onclick = () => {
        const keepOpen = this.saveTaskResult(projectId, stageId, taskId, true);
        if (!keepOpen) this.closeModal();
      };
      ok?.insertAdjacentElement("afterend", endBtn);
    }
  },

  // 完成任务（正常完成/异常完成）
  completeTask(projectId, stageId, taskId) {
    this.uploadResult(projectId, stageId, taskId);
  },
});
