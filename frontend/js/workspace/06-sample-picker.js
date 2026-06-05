/* ========================================
   数字治理平台 V7 - 样机选择器模块
   ======================================== */

app.registerModule("workspace.samplePicker", {

  getSelectedTaskSampleIds(inputName) {
    const state = this._taskSamplePickerStates?.[inputName];
    if (state?.selectedIds instanceof Set) return [...state.selectedIds];
    const query = `input[name='${inputName}']:checked`;
    return [...(document.querySelectorAll?.(query) || [])].map(x => x.value);
  },

  async ensureTaskSamplePickerDataLoaded() {
    return true;
  },

  taskSamplePickerSafeKey(inputName) {
    return String(inputName || "samplePick").replace(/[^a-zA-Z0-9_]/g, "_");
  },

  taskSamplePickerDomId(inputName) {
    return `taskSamplePicker_${this.taskSamplePickerSafeKey(inputName)}`;
  },

  taskSamplePickerControlId(inputName, suffix) {
    return `${this.taskSamplePickerDomId(inputName)}_${suffix}`;
  },

  resetTaskSamplePickerState(inputName, { selectedIds = [], progressSelectId = "", hintId = "", excludeTaskId = "" } = {}) {
    if (!this._taskSamplePickerStates) this._taskSamplePickerStates = {};
    const uniqueSelected = [...new Set((selectedIds || []).map(id => String(id || "").trim()).filter(Boolean))];
    this._taskSamplePickerStates[inputName] = {
      inputName,
      progressSelectId,
      hintId,
      excludeTaskId,
      selectedIds: new Set(uniqueSelected),
      page: 1,
      pageSize: 50,
      categoryId: "",
      status: "",
      keyword: "",
      excludeKeyword: "",
      categories: [],
      lastResult: null,
      loading: true,
      error: "",
      initialized: false,
    };
    return this._taskSamplePickerStates[inputName];
  },

  taskSamplePickerState(inputName) {
    return this._taskSamplePickerStates?.[inputName] || null;
  },

  buildTaskSamplePickerHtml(selectedIds = [], inputName = "samplePick", progressSelectId = "", hintId = "", excludeTaskId = "") {
    const state = this.resetTaskSamplePickerState(inputName, { selectedIds, progressSelectId, hintId, excludeTaskId });
    return `<div id="${this.taskSamplePickerDomId(inputName)}" class="task-sample-picker" data-task-sample-picker="${Utils.esc(inputName)}">
      ${this.taskSamplePickerContentHtml(state)}
    </div>`;
  },

  initTaskSamplePicker(inputName) {
    const state = this.taskSamplePickerState(inputName);
    if (!state || state.initialized) return;
    state.initialized = true;
    this.loadTaskSamplePickerPage(inputName, { page: 1 });
  },

  taskSamplePickerFetchParams(state, overrides = {}) {
    return {
      taskId: state.excludeTaskId || "",
      selectedIds: [...state.selectedIds],
      page: overrides.page || state.page || 1,
      pageSize: state.pageSize || 50,
      categoryId: state.categoryId || "",
      status: state.status || "",
      keyword: state.keyword || "",
      excludeKeyword: state.excludeKeyword || "",
    };
  },

  async loadTaskSamplePickerPage(inputName, overrides = {}) {
    const state = this.taskSamplePickerState(inputName);
    if (!state) return false;
    if (overrides.page) state.page = Math.max(1, Number(overrides.page) || 1);
    state.loading = true;
    state.error = "";
    this.renderTaskSamplePicker(inputName);
    try {
      const result = await this.fetchTaskSampleCandidates(this.taskSamplePickerFetchParams(state, overrides));
      state.loading = false;
      state.error = "";
      state.page = result.page || state.page || 1;
      state.pageSize = result.pageSize || state.pageSize || 50;
      state.categories = result.categories || [];
      state.lastResult = result;
      this.mergeTaskSampleCandidateResult(result);
      this.renderTaskSamplePicker(inputName);
      return true;
    } catch (e) {
      console.error("任务样机候选加载失败：", e);
      state.loading = false;
      state.error = e.message || String(e);
      this.renderTaskSamplePicker(inputName);
      return false;
    }
  },

  mergeTaskSampleCandidateResult(result = {}) {
    const summaryById = new Map((result.categories || []).map(category => [String(category.id || ""), category]));
    const categories = this.sampleCategoryRecords();
    const existingById = new Map(categories.map(category => [String(category.id || ""), category]));
    (result.categories || []).forEach(summary => {
      const id = String(summary.id || "");
      if (!id) return;
      if (!existingById.has(id)) {
        const category = { ...summary, samples: [], samplesLoaded: false, _summaryOnly: true };
        categories.push(category);
        existingById.set(id, category);
      } else {
        const existing = existingById.get(id);
        Object.assign(existing, summary);
        if (!Array.isArray(existing.samples)) existing.samples = [];
      }
    });
    [...(result.items || []), ...(result.selectedItems || [])].forEach(sample => {
      const categoryId = String(sample.categoryId || "");
      if (!categoryId) return;
      let category = existingById.get(categoryId);
      if (!category) {
        const summary = summaryById.get(categoryId) || {};
        category = {
          id: categoryId,
          name: sample.categoryName || summary.name || "未分类",
          sampleCount: summary.sampleCount || 0,
          samples: [],
          samplesLoaded: false,
          _summaryOnly: true,
        };
        categories.push(category);
        existingById.set(categoryId, category);
      }
      if (!Array.isArray(category.samples)) category.samples = [];
      const idx = category.samples.findIndex(item => String(item.id || "") === String(sample.id || ""));
      const merged = idx >= 0 ? { ...category.samples[idx], ...sample } : sample;
      if (idx >= 0) category.samples[idx] = merged;
      else category.samples.push(merged);
    });
  },

  renderTaskSamplePicker(inputName) {
    const state = this.taskSamplePickerState(inputName);
    const el = document.getElementById?.(this.taskSamplePickerDomId(inputName));
    if (!state || !el) return;
    this.replaceHtml(el, this.taskSamplePickerContentHtml(state));
    if (state.progressSelectId && state.hintId) {
      this.updateTaskSampleLimitUI(state.progressSelectId, inputName, state.hintId);
    } else {
      this.updateDispatchSamplePoolCounts(inputName);
    }
  },

  taskSamplePickerContentHtml(state) {
    const result = state.lastResult || {};
    const page = result.page || state.page || 1;
    const totalPages = result.totalPages || 1;
    const total = Number(result.total || 0);
    const selectedCount = state.selectedIds.size;
    const categoryOptions = [`<option value="">全部样机池</option>`]
      .concat((state.categories || result.categories || []).map(category => {
        const id = String(category.id || "");
        const selected = id === String(state.categoryId || "") ? "selected" : "";
        const count = Number(category.sampleCount || 0);
        return `<option value="${Utils.esc(id)}" ${selected}>${Utils.esc(category.name || id)}${count ? ` (${count})` : ""}</option>`;
      })).join("");
    const statusOptions = ["", "闲置", "在位等待", "测试中", "已退库", "取走分析"].map(status => {
      const selected = status === String(state.status || "") ? "selected" : "";
      return `<option value="${Utils.esc(status)}" ${selected}>${status || "全部状态"}</option>`;
    }).join("");
    const keywordId = this.taskSamplePickerControlId(state.inputName, "keyword");
    const excludeId = this.taskSamplePickerControlId(state.inputName, "exclude");
    const categoryId = this.taskSamplePickerControlId(state.inputName, "category");
    const statusId = this.taskSamplePickerControlId(state.inputName, "status");
    const selectedItems = this.taskSamplePickerSelectedItems(state);
    const candidateHtml = state.loading
      ? `<div class="empty">正在加载候选样机...</div>`
      : state.error
        ? `<div class="empty">候选样机加载失败：${Utils.esc(state.error)} <button type="button" class="btn btn-sm btn-outline" data-app-action="task-sample-picker-page" data-id="${Utils.esc(state.inputName)}" data-value="${page}">重试</button></div>`
        : (result.items || []).map(sample => this.taskSamplePickerSampleRowHtml(sample, state)).join("") || `<div class="empty">没有匹配的候选样机。</div>`;
    return `
      <div class="task-sample-picker-toolbar">
        <select id="${categoryId}" data-app-action="task-sample-picker-filter" data-app-events="change" data-id="${Utils.esc(state.inputName)}" data-field="categoryId">${categoryOptions}</select>
        <select id="${statusId}" data-app-action="task-sample-picker-filter" data-app-events="change" data-id="${Utils.esc(state.inputName)}" data-field="status">${statusOptions}</select>
        <input id="${keywordId}" class="dispatch-search-input task-sample-picker-search" value="${Utils.esc(state.keyword || "")}" placeholder="包含搜索" data-app-action="task-sample-picker-search" data-app-events="keydown" data-id="${Utils.esc(state.inputName)}">
        <input id="${excludeId}" class="dispatch-search-input dispatch-search-exclude task-sample-picker-search" value="${Utils.esc(state.excludeKeyword || "")}" placeholder="排除搜索" data-app-action="task-sample-picker-search" data-app-events="keydown" data-id="${Utils.esc(state.inputName)}">
        <button type="button" class="dispatch-search-btn" data-app-action="task-sample-picker-search" data-id="${Utils.esc(state.inputName)}" title="搜索">🔍</button>
        <span class="dispatch-match-count">${state.loading ? "加载中" : `候选 ${total} 台`}</span>
      </div>
      <div class="dispatch-sample-group task-sample-selected-group" data-sample-input-name="${Utils.esc(state.inputName)}">
        <div class="dispatch-sample-head">
          <div class="dispatch-sample-title-wrap">
            <div class="dispatch-sample-title">已选样机</div>
            <span class="dispatch-selected-count ${selectedCount ? "has-selected" : ""}" data-total="${selectedCount}">${selectedCount}</span>
          </div>
        </div>
        <div class="dispatch-sample-body open task-sample-candidate-grid">
          ${selectedItems.length ? selectedItems.map(sample => this.taskSamplePickerSampleRowHtml(sample, state, { selected: true })).join("") : `<div class="empty">尚未选择样机。</div>`}
        </div>
      </div>
      <div class="dispatch-sample-group task-sample-candidate-group" data-sample-input-name="${Utils.esc(state.inputName)}">
        <div class="dispatch-sample-head">
          <div class="dispatch-sample-title-wrap">
            <div class="dispatch-sample-title">候选样机</div>
            <span class="dispatch-selected-count" data-total="${total}">${page}/${totalPages}</span>
          </div>
          <div class="dispatch-sample-tools">
            <button type="button" class="btn btn-sm btn-outline" ${page <= 1 || state.loading ? "disabled" : `data-app-action="task-sample-picker-page" data-id="${Utils.esc(state.inputName)}" data-value="${Math.max(1, page - 1)}"`}>上一页</button>
            <button type="button" class="btn btn-sm btn-outline" ${page >= totalPages || state.loading ? "disabled" : `data-app-action="task-sample-picker-page" data-id="${Utils.esc(state.inputName)}" data-value="${page + 1}"`}>下一页</button>
          </div>
        </div>
        <div class="dispatch-sample-body open task-sample-candidate-grid">
          ${candidateHtml}
        </div>
      </div>`;
  },

  taskSamplePickerSelectedItems(state) {
    const result = state.lastResult || {};
    const byId = new Map();
    [...(result.selectedItems || []), ...(result.items || [])].forEach(sample => {
      const id = String(sample?.id || "");
      if (id) byId.set(id, sample);
    });
    this.sampleCategoryRecords().forEach(category => {
      (category.samples || []).forEach(sample => {
        const id = String(sample?.id || "");
        if (id && !byId.has(id)) byId.set(id, { ...sample, categoryName: category.name || "" });
      });
    });
    return [...state.selectedIds].map(id => byId.get(id)).filter(Boolean);
  },

  taskSamplePickerSampleRowHtml(sample, state, { selected = false } = {}) {
    const sid = String(sample?.id || "");
    const isSelected = selected || state.selectedIds.has(sid) || sample?.alreadySelected === true;
    const status = this.normalizeSampleStatusValue(sample?.effectiveStatus || sample?.status);
    const selectable = isSelected || sample?.selectable !== false;
    const disabledReason = selectable ? "" : (sample?.disabledReason || "");
    const identity = this.taskSamplePickerIdentityText(sample);
    const stageName = String(sample?.sourceStageName || "").trim();
    const skuName = String(sample?.sourceSkuName || "").trim();
    const stageSku = stageName && skuName ? `${Utils.esc(stageName)} · ${Utils.esc(skuName)}`
      : stageName ? `${Utils.esc(stageName)} · 未配置`
      : skuName ? `未配置 · ${Utils.esc(skuName)}`
      : "未配置";
    const testedItems = typeof this.sampleTestedItemNames === "function" ? this.sampleTestedItemNames(sid) : [];
    const testedText = testedItems.length === 0
      ? "无"
      : testedItems.length <= 3
        ? Utils.esc(testedItems.join("、"))
        : `${Utils.esc(testedItems.slice(0, 3).join("、"))} 等 ${testedItems.length} 项`;
    return `
      <div class="dispatch-sample-row ${selectable ? "" : "is-disabled"}" data-app-action="task-sample-picker-row" data-id="${Utils.esc(state.inputName)}" data-progress-id="${Utils.esc(state.progressSelectId || "")}" data-hint-id="${Utils.esc(state.hintId || "")}" title="${Utils.esc(disabledReason)}">
        <div class="dispatch-sample-info">
          <div class="dispatch-sample-title-line">
            <span class="dispatch-sample-id" data-app-action="sample-readonly" data-id="${Utils.esc(sid)}" data-stop-propagation="1">${Utils.esc(identity)}</span>
            <label class="dispatch-sample-check"><input type="checkbox" name="${state.inputName}" value="${Utils.esc(sid)}" data-sample-pick="${state.inputName}" ${isSelected ? "checked" : ""} ${selectable ? "" : "disabled"} ${selectable ? `data-app-action="task-sample-picker-checkbox" data-app-events="change" data-id="${Utils.esc(state.inputName)}" data-progress-id="${Utils.esc(state.progressSelectId || "")}" data-hint-id="${Utils.esc(state.hintId || "")}"` : ""}></label>
          </div>
          <span class="dispatch-sample-stage">${Utils.esc(sample?.categoryName || "")}${sample?.categoryName ? " · " : ""}阶段/方案：${stageSku}</span>
          <span class="dispatch-sample-tested">已测：${testedText}</span>
          ${disabledReason ? `<span class="dispatch-sample-tested task-sample-disabled-reason">${Utils.esc(disabledReason)}</span>` : ""}
        </div>
        <div class="dispatch-sample-status"><span class="badge ${this.sampleHasProblem(sample) ? 's-有故障' : 's-无故障'}">${this.sampleHasProblem(sample) ? '有故障' : '无故障'}</span><span class="badge s-${Utils.esc(status)}">${Utils.esc(status)}</span></div>
      </div>`;
  },

  taskSamplePickerIdentityText(sample) {
    if (typeof this.sampleDisplayCode === "function") {
      const code = this.sampleDisplayCode(sample);
      if (code) return code;
    }
    if (sample?.sampleNo) return `档案号: ${sample.sampleNo}`;
    if (sample?.sn) return `SN: ${sample.sn}`;
    if (sample?.imei) return `IMEI: ${sample.imei}`;
    if (sample?.boardSn) return `主板SN: ${sample.boardSn}`;
    return sample?.id || "身份号未录入";
  },

  onTaskSamplePickerFilterChange(inputName, key, value) {
    const state = this.taskSamplePickerState(inputName);
    if (!state) return;
    state[key] = value || "";
    state.page = 1;
    this.loadTaskSamplePickerPage(inputName, { page: 1 });
  },

  applyTaskSamplePickerSearch(inputName) {
    const state = this.taskSamplePickerState(inputName);
    if (!state) return;
    state.keyword = document.getElementById?.(this.taskSamplePickerControlId(inputName, "keyword"))?.value.trim() || "";
    state.excludeKeyword = document.getElementById?.(this.taskSamplePickerControlId(inputName, "exclude"))?.value.trim() || "";
    state.page = 1;
    this.loadTaskSamplePickerPage(inputName, { page: 1 });
  },

  validateTaskSampleSelection(progress, sampleIds, contextLabel = "任务") {
    const s = this.currentStage();
    const required = this.getProgressRequiredSampleCount(s, progress);
    if (required === null) return { ok: false, required: null, count: sampleIds.length, msg: `${contextLabel}无法读取样机数配置。` };
    if (sampleIds.length !== required) return { ok: false, required, count: sampleIds.length, msg: `${contextLabel}需要 ${required} 台样机，当前选择 ${sampleIds.length} 台。` };
    return { ok: true, required, count: sampleIds.length, msg: "" };
  },

  setTaskSampleLimitHintContent(hint, text, countText) {
    if (!hint) return;
    hint.textContent = "";
    if (text) hint.append(text);
    const count = document.createElement("span");
    count.className = "sample-limit-count";
    count.textContent = countText || "";
    hint.append(count);
  },

  updateTaskSampleLimitUI(progressSelectId, inputName, hintId) {
    this.updateDispatchSamplePoolCounts(inputName);
    const s = this.currentStage();
    const select = document.getElementById?.(progressSelectId);
    const hint = document.getElementById?.(hintId);
    if (!s || !select || !hint) return;
    const progress = s.progress.find(x => x.id === select.value);
    const sampleIds = this.getSelectedTaskSampleIds(inputName);
    const required = this.getProgressRequiredSampleCount(s, progress);
    const isGlobalCompact = hint.classList.contains('sample-limit-global');
    hint.classList.remove('warn', 'bad', 'full');
    if (required === null) {
      hint.classList.add('bad');
      if (isGlobalCompact) {
        hint.title = `无法读取样机数配置。当前已选 ${sampleIds.length} 台。`;
        this.setTaskSampleLimitHintContent(hint, "", `${sampleIds.length}/?`);
      } else {
        this.setTaskSampleLimitHintContent(hint, "无法读取样机数配置。", `已选 ${sampleIds.length}`);
      }
      return;
    }
    const countText = `${sampleIds.length}/${required}`;
    if (sampleIds.length === required) {
      if (isGlobalCompact) {
        hint.classList.add('full');
        hint.title = `样机已选满：需 ${required} 台，已选 ${sampleIds.length} 台。未勾选的样机已禁用。`;
        this.setTaskSampleLimitHintContent(hint, "", `${countText} 已选满`);
      } else {
        this.setTaskSampleLimitHintContent(hint, `样机已满足：需 ${required} 台，已选 ${sampleIds.length} 台。`, "已满足");
      }
    } else if (sampleIds.length < required) {
      hint.classList.add('warn');
      if (isGlobalCompact) {
        hint.title = `不足：需 ${required} 台，已选 ${sampleIds.length} 台。`;
        this.setTaskSampleLimitHintContent(hint, "", countText);
      } else {
        this.setTaskSampleLimitHintContent(hint, `不足：需 ${required} 台，已选 ${sampleIds.length} 台。`, countText);
      }
    } else {
      hint.classList.add('bad');
      if (isGlobalCompact) {
        hint.title = `超出：需 ${required} 台，已选 ${sampleIds.length} 台。`;
        this.setTaskSampleLimitHintContent(hint, "", countText);
      } else {
        this.setTaskSampleLimitHintContent(hint, `超出：需 ${required} 台，已选 ${sampleIds.length} 台。`, countText);
      }
    }
  },

  onTaskSampleCheckboxChange(progressSelectId, inputName, hintId, checkboxEl) {
    const state = this.taskSamplePickerState(inputName);
    if (state && checkboxEl?.value) {
      if (checkboxEl.checked) state.selectedIds.add(String(checkboxEl.value));
      else state.selectedIds.delete(String(checkboxEl.value));
    }
    const s = this.currentStage();
    const progress = s?.progress?.find(x => x.id === document.getElementById?.(progressSelectId)?.value);
    const required = this.getProgressRequiredSampleCount(s, progress);
    let sampleIds = this.getSelectedTaskSampleIds(inputName);
    if (required !== null && sampleIds.length > required && checkboxEl?.checked) {
      checkboxEl.checked = false;
      if (state && checkboxEl.value) state.selectedIds.delete(String(checkboxEl.value));
      sampleIds = this.getSelectedTaskSampleIds(inputName);
    }
    if (state) {
      this.renderTaskSamplePicker(inputName);
      return;
    }
    const allCheckboxes = [...(document.querySelectorAll?.(`input[name='${inputName}']`) || [])];
    if (required !== null) {
      if (sampleIds.length >= required) {
        allCheckboxes.forEach(cb => { if (!cb.checked) cb.disabled = true; });
      } else {
        allCheckboxes.forEach(cb => {
          const row = cb.closest('.dispatch-sample-row');
          if (row && !row.classList.contains('is-disabled')) cb.disabled = false;
        });
      }
    }
    this.updateTaskSampleLimitUI(progressSelectId, inputName, hintId);
  },

  onTaskSampleRowClick(event, inputName, progressSelectId = "", hintId = "") {
    const target = event?.target;
    if (target?.closest?.("input, label, button, select, textarea, .dispatch-sample-id")) return;
    const row = event?.currentTarget || target?.closest?.(".dispatch-sample-row");
    const checkbox = row?.querySelector?.(`input[type="checkbox"][name="${inputName}"]`);
    if (!checkbox || checkbox.disabled) return;
    checkbox.checked = !checkbox.checked;
    this.onTaskSampleCheckboxChange(progressSelectId, inputName, hintId, checkbox);
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
      ...((typeof this.sampleTestedItemNames === "function" && this.sampleTestedItemNames(sample.id || "")) || []),
      ...(sample.problemRecords || []).map(r => r.description || "").filter(Boolean)
    ];
    return parts.map(v => String(v || "").trim()).filter(Boolean).join(" ").toLowerCase();
  },

  updateDispatchSamplePoolCounts(inputName) {
    document.querySelectorAll?.(`.dispatch-sample-group[data-sample-input-name="${inputName}"]`).forEach(group => {
      if (group.closest?.(".task-sample-picker")) return;
      const boxes = [...group.querySelectorAll(`input[type="checkbox"][name="${inputName}"]`)];
      const checked = boxes.filter(cb => cb.checked).length;
      const counter = group.querySelector(".dispatch-selected-count");
      if (counter) {
        const total = Number(counter.dataset.total || boxes.length);
        counter.textContent = total ? `${checked}/${total}` : `${checked}`;
        counter.classList.toggle("has-selected", checked > 0);
      }
    });
  },

  toggleDispatchGroup(groupId, btn) {
    const el = document.getElementById?.(groupId); if (!el) return;
    const isOpen = el.classList.toggle("open");
    if (btn) btn.innerText = isOpen ? "折叠" : "展开";
  },

  filterDispatchGroup(groupId, keyword, excludeKw, countId) {
    const body = document.getElementById?.(groupId); if (!body) return;
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
    const counter = document.getElementById?.(countId);
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

});
