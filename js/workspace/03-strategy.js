/* ========================================
   数字治理平台 V7 - 阶段策略配置模块
   含策略页导航·BOM·测试策略·用例导入
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

});
