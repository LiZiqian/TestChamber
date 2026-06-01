/* ========================================
   数字治理平台 V7 - 样机选择器模块
   ======================================== */

Object.assign(app, {

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
    hint.classList.remove('warn', 'bad', 'full');
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
        hint.classList.add('full');
        hint.title = `样机已选满：需 ${required} 台，已选 ${sampleIds.length} 台。未勾选的样机已禁用。`;
        hint.innerHTML = `<span class="sample-limit-count">${countText} 已选满</span>`;
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
    // 超出时静默取消勾选（不再弹 alert）
    if (required !== null && sampleIds.length > required && checkboxEl?.checked) {
      checkboxEl.checked = false;
      sampleIds = this.getSelectedTaskSampleIds(inputName);
    }
    // 选满后禁用所有未勾选项；未满时恢复
    const allCheckboxes = [...document.querySelectorAll(`input[name='${inputName}']`)];
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

});
