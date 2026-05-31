/* ========================================
   数字治理平台 V7 - 用例下拉与问题记录模块
   ======================================== */

Object.assign(app, {

  // ==================== 用例下拉 ====================
  openCaseDropdown(rowIdx, field, inputEl) {
    let dd = document.getElementById('caseDropdown');
    if (!dd) {
      dd = document.createElement('div'); dd.id = 'caseDropdown'; dd.className = 'case-dropdown';
      document.body.appendChild(dd);
    }
    this._caseDropdownState = { rowIdx, field, inputEl, search: '' };
    const placeholder = field === 'item' ? '搜索用例名称' : '搜索测量类别';
    dd.innerHTML = `<div class="case-dropdown-head"><input id="caseDropdownSearch" value="" placeholder="${placeholder}" oninput="app.filterCaseDropdown(this.value)"></div><div id="caseDropdownOptions" class="case-dropdown-options"></div>`;
    dd.classList.add('show');
    this.positionCaseDropdown();
    this.renderCaseDropdownOptions();
    requestAnimationFrame(() => this.positionCaseDropdown(true));
  },
  positionCaseDropdown(useActualHeight = false) {
    const state = this._caseDropdownState;
    const dd = document.getElementById('caseDropdown');
    const inputEl = state?.inputEl;
    if (!dd || !inputEl || !document.body.contains(inputEl)) return;
    const rect = inputEl.getBoundingClientRect();
    const margin = 12, gap = 6;
    const width = Math.min(Math.max(rect.width, 300), 420);
    let left = Math.min(rect.left, window.innerWidth - width - margin);
    if (left < margin) left = margin;

    const below = window.innerHeight - rect.bottom - gap - margin;
    const above = rect.top - gap - margin;
    const openAbove = below < 180 && above > below;
    const maxHeight = Math.max(120, Math.min(320, openAbove ? above : below));
    const actualHeight = useActualHeight && dd.offsetHeight ? Math.min(dd.offsetHeight, maxHeight) : maxHeight;
    const top = openAbove
      ? Math.max(margin, rect.top - gap - actualHeight)
      : Math.min(rect.bottom + gap, window.innerHeight - margin - 120);

    dd.style.left = left + 'px';
    dd.style.top = top + 'px';
    dd.style.width = width + 'px';
    dd.style.maxHeight = maxHeight + 'px';
    const options = dd.querySelector('.case-dropdown-options');
    if (options) options.style.maxHeight = Math.max(80, maxHeight - 50) + 'px';
  },
  repositionCaseDropdown() {
    if (!this._caseDropdownState) return;
    this.positionCaseDropdown();
  },
  filterCaseDropdown(val) {
    if (!this._caseDropdownState) return;
    this._caseDropdownState.search = val;
    this.renderCaseDropdownOptions();
    requestAnimationFrame(() => this.positionCaseDropdown(true));
  },
  renderCaseDropdownOptions() {
    const state = this._caseDropdownState;
    const box = document.getElementById('caseDropdownOptions');
    if (!state || !box) return;
    const p = this.currentProject();
    const master = p?.testCaseMaster || [];
    if (!master.length) { box.innerHTML = '<div class="case-empty">未导入用例库。可直接输入。</div>'; return; }
    const s = this.currentStage();
    const row = s?.strategy?.[state.rowIdx] || {};
    const selectedCategory = String(row.category || '').trim();
    const kw = String(state.search || '').toLowerCase().trim();
    let options = [];
    if (state.field === 'category') {
      const map = new Map();
      master.forEach(x => {
        const cat = String(x.category || '').trim(); if (!cat) return;
        if (kw && !cat.toLowerCase().includes(kw)) return;
        map.set(cat, (map.get(cat) || 0) + 1);
      });
      options = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0], 'zh-CN')).slice(0, 80)
        .map(([cat, count]) => ({ category: cat, item: '', count }));
    } else {
      let pool = master.filter(x => {
        const cat = String(x.category || '').trim();
        const item = String(x.item || '').trim();
        if (!item) return false;
        if (selectedCategory && cat !== selectedCategory) return false;
        if (!kw) return true;
        return item.toLowerCase().includes(kw) || cat.toLowerCase().includes(kw);
      });
      const seen = new Set();
      options = pool.filter(x => {
        const key = x.category + '||' + x.item;
        if (seen.has(key)) return false; seen.add(key); return true;
      }).sort((a, b) => String(a.item).localeCompare(String(b.item), 'zh-CN')).slice(0, 120);
    }
    if (!options.length) { box.innerHTML = '<div class="case-empty">无匹配项，可直接输入。</div>'; return; }
    this._caseDropdownOptions = options;
    if (state.field === 'category') {
      box.innerHTML = options.map((o, idx) => `<div class="case-option" data-case-option-index="${idx}"><div class="case-cat">${Utils.esc(o.category)}</div><div class="case-item">${o.count} 条用例</div></div>`).join('');
    } else {
      box.innerHTML = options.map((o, idx) => `<div class="case-option item-mode" data-case-option-index="${idx}"><div class="case-main">${Utils.esc(o.item)}</div>${selectedCategory ? '' : `<div class="case-sub">${Utils.esc(o.category)}</div>`}</div>`).join('');
    }
    box.querySelectorAll('.case-option').forEach(el => {
      el.addEventListener('mousedown', ev => {
        ev.preventDefault(); ev.stopPropagation();
        const idx = Number(el.dataset.caseOptionIndex);
        const opt = this._caseDropdownOptions?.[idx]; if (!opt) return;
        this.selectCaseSuggestion(state.rowIdx, state.field, opt.category, opt.item || '');
      });
    });
  },
  closeCaseDropdown() {
    const dd = document.getElementById('caseDropdown');
    if (dd) dd.classList.remove('show');
    this._caseDropdownState = null;
  },
  selectCaseSuggestion(rowIdx, field, category, item) {
    const s = this.currentStage();
    const r = s?.strategy?.[rowIdx]; if (!r) return;
    if (field === 'category') {
      r.category = category;
      if (this._caseDropdownState?.inputEl) this._caseDropdownState.inputEl.value = category;
    } else {
      r.category = category; r.item = item;
      const tr = document.querySelector(`tr[data-strategy-row="${rowIdx}"]`);
      const catInput = tr?.querySelector('input[data-field="category"]');
      const itemInput = tr?.querySelector('input[data-field="item"]');
      if (catInput) catInput.value = category;
      if (itemInput) itemInput.value = item;
    }
    this.save(); this.closeCaseDropdown();
    Utils.toast(field === 'category' ? `已选择：${category}` : `已选择：${item}`);
  },

  // ==================== 问题单 ====================
  updateIssueRecordRemark(projectId, stageId, taskId, value) {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages.find(x => x.id === stageId);
    const t = s?.tasks.find(x => x.id === taskId);
    if (!t) return;
    if (!t.issueRecord) t.issueRecord = { dtsNo: "", isIssue: "", issueNote: "" };
    t.issueRecord.issueNote = String(value || "").trim();
    this.save();
  },

  taskIssueRecordHtml(task, project = null, stage = null) {
    const r = task?.issueRecord || {};
    const hasDts = !!r.dtsNo;
    const hasIssue = r.isIssue === "是" || r.isIssue === "否";
    // 空态点击录入：优先使用调用方传入的 project/stage 上下文，回退到 task 自带字段，避免缺失 projectId/stageId 时弹窗静默失败
    const pid = project?.id || task?.projectId || "";
    const sid = stage?.id || task?.stageId || "";
    const tid = task?.id || "";
    if (!tid) {
      return `<span class="path">-</span>`;
    }
    if (!hasDts && !hasIssue) {
      return `<span class="path task-issue-record-empty" onclick="app.openTaskIssueRecordModal('${pid}','${sid}','${tid}')">点击录入</span>`;
    }
    const taskId = task?.id || "";
    const noteVal = Utils.esc(r.issueNote || "");
    return [
      hasDts ? `<div class="task-issue-record-line"><span class="task-issue-record-label">单号：</span> <b>${Utils.esc(r.dtsNo)}</b></div>` : "",
hasIssue ? `<div class="task-issue-record-line"><span class="task-issue-record-label">是否重复：</span> ${r.isIssue === "否" ? `<span class="task-issue-repeat-no">${Utils.esc(r.isIssue)}</span>` : Utils.esc(r.isIssue)}</div>` : "",
      `<div class="task-issue-record-line"><span class="task-issue-record-label">确认备注：</span> ${noteVal || "-"}</div>`
    ].join("");
  },

  openTaskIssueRecordModal(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    if (!t.issueRecord) t.issueRecord = { dtsNo: "", isIssue: "", issueNote: "" };
    const r = t.issueRecord;
    this.showModal("问题单录入", `
      <div class="form-group">
        <label>DTS单号</label>
        <input id="issueRecordDtsNo" value="${Utils.esc(r.dtsNo || "")}" placeholder="请输入DTS单号（如有）">
      </div>
      <div class="form-group">
        <label>是否重复</label>
        <select id="issueRecordIsIssue">
          <option value="">请选择</option>
          <option value="是" ${r.isIssue === "是" ? "selected" : ""}>是</option>
          <option value="否" ${r.isIssue === "否" ? "selected" : ""}>否</option>
        </select>
      </div>
      <div class="form-group">
        <label>问题确认说明</label>
        <textarea id="issueRecordNote" rows="4" placeholder="填写问题确认说明">${Utils.esc(r.issueNote || "")}</textarea>
      </div>
    `, () => {
      t.issueRecord = {
        dtsNo: document.getElementById("issueRecordDtsNo").value.trim(),
        isIssue: document.getElementById("issueRecordIsIssue").value,
        issueNote: document.getElementById("issueRecordNote").value.trim()
      };
      this.save(); this.render();
    }, "保存");
  }

});
