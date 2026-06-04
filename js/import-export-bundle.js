/* ========================================
   TestChamber V7 — 数据包导出/导入
   混入全局 app
   ======================================== */

app.registerModule("import-export-bundle", {

  // ── 导出 ──

  async exportBundle() {
    Utils.toast("正在生成数据包…");
    try {
      const resp = await fetch("/api/export-bundle");
      if (!resp.ok) {
        let serverMsg = "";
        try {
          const err = await resp.json();
          if (err && err.error) serverMsg = err.error;
        } catch (_) { /* response not JSON */ }
        const fullMsg = serverMsg ? `${serverMsg} (HTTP ${resp.status})` : `HTTP ${resp.status}`;
        console.error("[EXPORT] 导出失败:", fullMsg, "| Content-Type:", resp.headers.get("Content-Type"));
        if (resp.status === 403) {
          Utils.toast("导出失败：服务器拒绝访问，请尝试重启服务器后重试");
        } else {
          Utils.toast("导出失败：" + fullMsg);
        }
        return;
      }

      const contentType = resp.headers.get("Content-Type") || "";
      if (!contentType.includes("application/zip") && !contentType.includes("application/octet-stream")) {
        console.error("[EXPORT] 非预期的 Content-Type:", contentType);
        Utils.toast("导出失败：服务器返回了非 zip 内容 (HTTP " + resp.status + ")");
        return;
      }

      const blob = await resp.blob();
      if (!blob || blob.size === 0) {
        Utils.toast("导出失败：数据包为空");
        return;
      }

      // 从 Content-Disposition 解析文件名
      let filename = "testchamber_export.zip";
      const cd = resp.headers.get("Content-Disposition") || "";
      const fnMatch = cd.match(/filename\s*=\s*"?([^";\r\n]+)"?/i);
      if (fnMatch && fnMatch[1]) filename = fnMatch[1];

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);

      Utils.toast("数据包导出完成");
    } catch (e) {
      console.error("[EXPORT] 请求异常:", e);
      Utils.toast("导出失败：" + (e.message || "网络错误"));
    }
  },

  // ── 导入（入口） ──

  importBundle() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".zip";
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      Utils.toast("正在分析导入包…");
      try {
        const preview = await this.importBundlePreview(file);
        this._showImportPreviewModal(preview, file);
      } catch (e) {
        Utils.toast("导入分析失败: " + (e.message || e));
      }
    }, { once: true });
    input.click();
  },

  // ── 预览弹窗 ──

  _showImportPreviewModal(preview, file) {
    // 存储当前预览状态
    this._importState = {
      preview,
      file,
      decisions: {},        // {conflictId: decision}
      processedConflicts: new Set(),
    };

    const body = this._renderImportPreviewBody(preview);
    this.showModal("导入数据包", body, () => {
      void this._onImportCommit();
      return true;
    }, "确认导入已处理项目", {
      className: "import-bundle-modal",
      cancelText: "取消",
    });
    const cancelBtn = this.resetEventTarget(document.getElementById("modalCancel"));
    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        this._importState = null;
        this.closeModal();
      });
    }

    // 插入「仅导入无冲突数据」按钮
    this._injectQuickImportButton();
    // 初始化按钮状态
    this._updateImportCommitButton();
    // 绑定冲突处理事件
    this._bindConflictHandlers();
  },

  // ── 渲染预览主体 ──

  _renderImportPreviewBody(preview) {
    const src = preview.source || {};
    const summary = preview.summary || {};
    const conflicts = preview.conflicts || [];
    const blockers = preview.blockers || [];
    const autoApply = preview.autoApply || [];

    // 统计
    const newProjects = autoApply.filter(a => a.type === "new_project").length;
    const newStages = autoApply.filter(a => a.type === "new_stage").length;
    const newTasks = autoApply.filter(a => a.type === "new_task").length;
    const newSamples = autoApply.filter(a => a.type === "new_sample").length;
    const totalConflicts = conflicts.length;
    const unprocessedCount = totalConflicts - this._importState.processedConflicts.size;

    let html = "";

    // 1) 来源信息
    html += `<div class="import-section import-source">
      <div class="import-section-title">📦 数据包来源</div>
      <div class="import-source-grid">
        <span>部署ID：</span><code>${Utils.esc(src.deploymentId || "未知")}</code>
        <span>导出时间：</span><span>${Utils.esc(src.exportedAt || "")}</span>
        <span>数据版本：</span><span>${Utils.esc(src.appVersion || "")} / Rev ${src.revision || 0}</span>
      </div>
    </div>`;

    // 2) 可自动导入
    html += `<div class="import-section import-auto">
      <div class="import-section-title">✅ 可自动导入</div>
      <div class="import-stats">
        <span>新增项目：${newProjects}</span>
        <span>新增阶段：${newStages}</span>
        <span>新增任务：${newTasks}</span>
        <span>新增样机：${newSamples}</span>
      </div>
    </div>`;

    // 3) 冲突区
    html += `<div class="import-section import-conflicts">
      <div class="import-section-title">⚠️ 需要处理（<span id="importConflictCount">${totalConflicts}</span> 项，<span id="importUnprocessedCount">${unprocessedCount}</span> 项未处理）</div>`;

    if (blockers.length > 0) {
      html += `<div class="import-blockers">
        <strong>⛔ 阻断项：</strong>
        ${blockers.map(b => `缺失照片 ${b.count} 张`).join("；")}
        <br><small>存在阻断项时无法提交导入</small>
      </div>`;
    }

    if (conflicts.length === 0) {
      html += `<div class="import-no-conflicts">无冲突，可直接导入</div>`;
    } else {
      html += `<div class="import-conflict-list" id="importConflictList">`;
      conflicts.forEach((c, idx) => {
        html += this._renderConflictCard(c, idx);
      });
      html += `</div>`;
    }
    html += `</div>`;

    return html;
  },

  // ── 渲染单条冲突卡片 ──

  _renderConflictCard(c, idx) {
    const cid = c.conflictId;
    const ctype = c.type;
    const label = Utils.esc(c.label || cid);
    const isProcessed = this._importState.processedConflicts.has(cid);

    let cardClass = "conflict-card";
    if (isProcessed) cardClass += " conflict-processed";

    let typeLabel = "";
    switch (ctype) {
      case "project_name_conflict": typeLabel = "项目名称冲突"; break;
      case "stage_name_conflict": typeLabel = "阶段名称冲突"; break;
      case "task_name_conflict": typeLabel = "任务冲突"; break;
      case "sample_identity_conflict": typeLabel = "样机身份冲突"; break;
      case "field_conflict": typeLabel = "字段冲突"; break;
      case "task_occupancy_conflict": typeLabel = "任务占用冲突"; break;
      default: typeLabel = ctype;
    }

    let html = `<div class="${cardClass}" id="conflict_${cid}" data-conflict-id="${cid}">
      <div class="conflict-card-header">
        <span class="conflict-index">${idx + 1}/${this._importState.preview.conflicts.length}</span>
        <span class="conflict-type-badge">${typeLabel}</span>
        <span class="conflict-label">${label}</span>
        <span class="conflict-status" id="conflict_status_${cid}">${isProcessed ? "✅ 已处理" : "⏳ 待处理"}</span>
      </div>`;

    // 主体：根据类型渲染
    html += `<div class="conflict-card-body" id="conflict_body_${cid}">`;
    html += this._renderConflictBody(c);
    html += `</div>`;

    html += `</div>`;
    return html;
  },

  // ── 冲突主体内容 ──

  _renderConflictBody(c) {
    switch (c.type) {
      case "project_name_conflict":
      case "stage_name_conflict":
        return this._renderNameConflictBody(c);
      case "task_name_conflict":
        return this._renderTaskNameConflictBody(c);
      case "sample_identity_conflict":
        return this._renderSampleIdentityConflictBody(c);
      case "field_conflict":
        return this._renderFieldConflictBody(c);
      case "task_occupancy_conflict":
        return this._renderOccupancyConflictBody(c);
      default:
        return `<p>未知冲突类型: ${Utils.esc(c.type)}</p>`;
    }
  },

  // 项目/阶段名称冲突
  _renderNameConflictBody(c) {
    const cid = c.conflictId;
    const curr = c.current || {};
    const inc = c.incoming || {};
    let html = `<div class="conflict-compare">
      <div class="conflict-col"><strong>主库：</strong>${Utils.esc(curr.name || "")}</div>
      <div class="conflict-col"><strong>导入：</strong>${Utils.esc(inc.name || "")}</div>
    </div>`;
    html += `<div class="conflict-actions" data-cid="${cid}">
      <label><input type="radio" name="action_${cid}" value="merge_into_existing"> 合并到主库现有项目</label>
      <label><input type="radio" name="action_${cid}" value="rename_import"> 改名后作为新项目导入</label>
      <div class="conflict-rename-row" id="rename_row_${cid}" style="display:none">
        新名称：<input type="text" id="rename_input_${cid}" placeholder="[来源] 项目名称" style="width:260px">
      </div>
      <label><input type="radio" name="action_${cid}" value="skip"> 跳过不导入</label>
    </div>`;
    return html;
  },

  // 任务名称冲突
  _renderTaskNameConflictBody(c) {
    const cid = c.conflictId;
    const curr = c.current || {};
    const inc = c.incoming || {};
    let html = `<div class="conflict-compare">
      <div class="conflict-col"><strong>主库：</strong>${Utils.esc(curr.category || "")} - ${Utils.esc(curr.testItem || "")} (${Utils.esc(curr.status || "")})</div>
      <div class="conflict-col"><strong>导入：</strong>${Utils.esc(inc.category || "")} - ${Utils.esc(inc.testItem || "")} (${Utils.esc(inc.status || "")})</div>
    </div>`;
    html += `<div class="conflict-actions" data-cid="${cid}">
      <label><input type="radio" name="action_${cid}" value="merge_into_existing"> 合并日志/结果到现有任务</label>
      <label><input type="radio" name="action_${cid}" value="rename_import"> 改名后作为新任务导入</label>
      <div class="conflict-rename-row" id="rename_row_${cid}" style="display:none">
        新任务名称：<input type="text" id="rename_input_${cid}" placeholder="[来源] 任务名称" style="width:260px">
      </div>
      <label><input type="radio" name="action_${cid}" value="skip"> 跳过</label>
    </div>`;
    return html;
  },

  // 样机身份冲突
  _renderSampleIdentityConflictBody(c) {
    const cid = c.conflictId;
    const curr = c.current || {};
    const inc = c.incoming || {};
    const mergeableFields = c.mergeableFields || [];
    const matchBy = c.matchBy || "sn";

    let html = `<div class="conflict-compare">
      <div class="conflict-col"><strong>主库：</strong>`;
    for (const [k, v] of Object.entries(curr)) {
      html += `${Utils.esc(k)}: ${Utils.esc(String(v))}<br>`;
    }
    html += `</div><div class="conflict-col"><strong>导入：</strong>`;
    for (const [k, v] of Object.entries(inc)) {
      html += `${Utils.esc(k)}: ${Utils.esc(String(v))}<br>`;
    }
    html += `</div></div>`;

    html += `<div class="conflict-actions" data-cid="${cid}">
      <label><input type="radio" name="action_${cid}" value="merge_into_existing"> 视为同一台样机，合并日志/照片/问题记录</label>`;

    if (mergeableFields.length > 0) {
      html += `<div class="conflict-field-choices" id="field_choices_${cid}" style="display:none; margin-left:24px">`;
      for (const f of mergeableFields) {
        html += `<div class="field-choice-row">
          <span>${Utils.esc(f)}：</span>
          <label><input type="radio" name="field_${cid}_${f}" value="current"> 保留主库：${Utils.esc(String(curr[f] || ""))}</label>
          <label><input type="radio" name="field_${cid}_${f}" value="incoming"> 使用导入：${Utils.esc(String(inc[f] || ""))}</label>
        </div>`;
      }
      html += `</div>`;
    }

    html += `<label><input type="radio" name="action_${cid}" value="import_as_new_with_identity_edit"> 作为新样机导入，修改标识：</label>
      <div class="conflict-rename-row" id="rename_row_${cid}" style="display:none; margin-left:24px">
        SN：<input type="text" id="rename_sn_${cid}" placeholder="修改 SN" style="width:160px">
        IMEI：<input type="text" id="rename_imei_${cid}" placeholder="修改 IMEI" style="width:160px">
        主板SN：<input type="text" id="rename_board_sn_${cid}" placeholder="修改主板SN" style="width:160px">
        编号：<input type="text" id="rename_sno_${cid}" placeholder="修改编号" style="width:160px">
      </div>
      <label><input type="radio" name="action_${cid}" value="skip"> 跳过</label>
    </div>`;
    return html;
  },

  // 字段冲突
  _renderFieldConflictBody(c) {
    const cid = c.conflictId;
    const entityLabel = c.entity === "sample" ? "样机" : c.entity === "project" ? "项目" : c.entity;
    const diffFields = c.diffFields || [];
    const curr = c.current || {};
    const inc = c.incoming || {};

    let html = `<p>${Utils.esc(entityLabel)} ID 相同，以下字段不同：</p>`;
    html += `<div class="conflict-actions" data-cid="${cid}">
      <button class="btn btn-sm" data-action="all_current" data-cid="${cid}">全部保留主库</button>
      <button class="btn btn-sm" data-action="all_incoming" data-cid="${cid}">全部使用导入</button>`;

    for (const f of diffFields) {
      html += `<div class="field-choice-row">
        <span><strong>${Utils.esc(f)}：</strong></span>
        <label><input type="radio" name="field_${cid}_${f}" value="current"> 保留主库：${Utils.esc(String(curr[f] || ""))}</label>
        <label><input type="radio" name="field_${cid}_${f}" value="incoming"> 使用导入：${Utils.esc(String(inc[f] || ""))}</label>
      </div>`;
    }

    html += `<label style="margin-top:8px"><input type="radio" name="action_${cid}" value="apply_field_choices"> 应用以上字段选择到主库</label>
      <label><input type="radio" name="action_${cid}" value="skip"> 跳过此项</label>
    </div>`;
    return html;
  },

  // 任务占用冲突
  _renderOccupancyConflictBody(c) {
    const cid = c.conflictId;
    let html = `<p>样机 <strong>${Utils.esc(c.label || "")}</strong> 在两边都被占用：</p>`;
    html += `<div class="conflict-compare">
      <div class="conflict-col">主库任务：${Utils.esc(c.currentTaskId || "")} ${Utils.esc(c.incomingTaskLabel || "")}</div>
      <div class="conflict-col">导入任务：${Utils.esc(c.incomingTaskId || "")}</div>
    </div>`;
    html += `<div class="conflict-actions" data-cid="${cid}">
      <label><input type="radio" name="action_${cid}" value="skip_occupancy"> 跳过导入占用关系</label>
      <label><input type="radio" name="action_${cid}" value="import_no_occupy"> 导入记录但不改变样机占用</label>
    </div>`;
    return html;
  },

  // ── 绑定冲突处理事件 ──

  _importModalRoot() {
    return document.getElementById("modalBody") || document.querySelector(".modal");
  },

  _bindConflictHandlers() {
    // Radio 切换显示/隐藏子选项
    const modal = this._importModalRoot();
    if (!modal) return;

    modal.querySelectorAll(".conflict-actions").forEach(actionsDiv => {
      const cid = actionsDiv.dataset.cid;
      const refreshDecisions = () => this._collectImportDecisions();
      actionsDiv.querySelectorAll(`input[name="action_${cid}"]`).forEach(radio => {
        radio.addEventListener("change", () => {
          // 显示/隐藏 rename row
          const renameRow = document.getElementById(`rename_row_${cid}`);
          if (renameRow) {
            renameRow.style.display =
              (radio.value === "rename_import" || radio.value === "import_as_new_with_identity_edit")
                ? "block"
                : "none";
          }
          // 显示/隐藏 field choices（merge_into_existing 时）
          const fieldChoices = document.getElementById(`field_choices_${cid}`);
          if (fieldChoices) {
            fieldChoices.style.display = radio.value === "merge_into_existing" ? "block" : "none";
          }
          refreshDecisions();
        });
      });
      actionsDiv.querySelectorAll("input[type=radio]").forEach(radio => {
        if (radio.name !== `action_${cid}`) {
          radio.addEventListener("change", refreshDecisions);
        }
      });

      actionsDiv.querySelectorAll("input[type=text]").forEach(input => {
        input.addEventListener("input", refreshDecisions);
      });

      // "全部保留/使用" 按钮
      actionsDiv.querySelectorAll("[data-action]").forEach(btn => {
        btn.addEventListener("click", () => {
          const action = btn.dataset.action;
          const targetCid = btn.dataset.cid;
          const desired = action === "all_current" ? "current" : "incoming";
          actionsDiv.querySelectorAll(`input[name^="field_${targetCid}_"][value="${desired}"]`).forEach(r => {
            r.checked = true;
          });
          const applyAction = actionsDiv.querySelector(`input[name="action_${targetCid}"][value="apply_field_choices"]`);
          if (applyAction) applyAction.checked = true;
          refreshDecisions();
        });
      });
    });
  },

  // ── 收集决策 → 更新状态 ──

  _collectImportDecisions() {
    if (!this._importState) return;
    const modal = this._importModalRoot();
    if (!modal) return;

    const conflicts = this._importState.preview.conflicts || [];
    this._importState.processedConflicts = new Set();
    const nextDecisions = {};

    for (const c of conflicts) {
      const cid = c.conflictId;
      const statusEl = document.getElementById(`conflict_status_${cid}`);
      if (statusEl) statusEl.textContent = "⏳ 待处理";
      const cardEl = document.getElementById(`conflict_${cid}`);
      if (cardEl) cardEl.classList.remove("conflict-processed");

      // 查找选中的 action radio
      const actionRadio = modal.querySelector(`input[name="action_${cid}"]:checked`);
      if (!actionRadio) continue;

      const action = actionRadio.value;
      const decision = { action };

      if (action === "rename_import") {
        // 项目/阶段/任务改名导入
        decision.newName = (document.getElementById(`rename_input_${cid}`) || {}).value || "";
        if (!decision.newName) continue;
      }

      if (action === "import_as_new_with_identity_edit") {
        // 样机标识编辑导入
        decision.newSN = (document.getElementById(`rename_sn_${cid}`) || {}).value || "";
        decision.newIMEI = (document.getElementById(`rename_imei_${cid}`) || {}).value || "";
        decision.newBoardSn = (document.getElementById(`rename_board_sn_${cid}`) || {}).value || "";
        decision.newSampleNo = (document.getElementById(`rename_sno_${cid}`) || {}).value || "";
        if (!decision.newSN && !decision.newIMEI && !decision.newBoardSn && !decision.newSampleNo) continue;
      }

      if (action === "merge_into_existing") {
        decision.targetId = c.preferredMergeTarget || c.currentId;
        // 收集逐字段选择
        const mergeableFields = c.mergeableFields || c.diffFields || [];
        const fieldChoices = {};
        for (const f of mergeableFields) {
          const fr = modal.querySelector(`input[name="field_${cid}_${f}"]:checked`);
          if (fr) fieldChoices[f] = fr.value;
        }
        decision.fieldChoices = fieldChoices;
      }

      if (action === "apply_field_choices") {
        // field_conflict：逐字段选择写入
        const diffFields = c.diffFields || c.mergeableFields || [];
        const fieldChoices = {};
        for (const f of diffFields) {
          const fr = modal.querySelector(`input[name="field_${cid}_${f}"]:checked`);
          if (fr) fieldChoices[f] = fr.value;
        }
        decision.fieldChoices = fieldChoices;
        if (diffFields.length > 0 && Object.keys(fieldChoices).length < diffFields.length) {
          continue;
        }
      }

      nextDecisions[cid] = decision;
      this._importState.processedConflicts.add(cid);

      // 更新状态标记
      if (statusEl) statusEl.textContent = "✅ 已处理";
      if (cardEl) cardEl.classList.add("conflict-processed");
    }

    this._importState.decisions = nextDecisions;
    this._updateImportCommitButton();
  },

  // ── 更新确认按钮状态 ──

  _updateImportCommitButton() {
    if (!this._importState) return;
    const totalConflicts = (this._importState.preview.conflicts || []).length;
    const processed = this._importState.processedConflicts.size;
    const unprocessedEl = document.getElementById("importUnprocessedCount");
    if (unprocessedEl) unprocessedEl.textContent = String(Math.max(0, totalConflicts - processed));
    const okBtn = document.getElementById("modalOk");
    if (!okBtn) return;

    if (totalConflicts === 0) {
      okBtn.disabled = false;
      okBtn.textContent = "确认导入";
      okBtn.title = "";
      return;
    }

    if (processed < totalConflicts) {
      okBtn.disabled = true;
      okBtn.textContent = `确认导入（${processed}/${totalConflicts}）`;
      okBtn.title = "还有未处理的冲突项";
    } else {
      okBtn.disabled = false;
      okBtn.textContent = "确认导入已处理项目";
      okBtn.title = "";
    }
  },

  // ── 仅导入无冲突数据 ──

  _injectQuickImportButton() {
    // 在弹窗 footer 插入第三个按钮
    setTimeout(() => {
      const footer = document.querySelector(".modal-footer");
      if (!footer) return;
      document.getElementById("quickImportBtn")?.remove();
      const btn = document.createElement("button");
      btn.className = "btn btn-outline";
      btn.textContent = "仅导入无冲突数据";
      btn.id = "quickImportBtn";
      btn.addEventListener("click", () => this._onQuickImport());
      // 插入到 cancel 和 ok 之间
      const okBtn = document.getElementById("modalOk");
      if (okBtn) {
        footer.insertBefore(btn, okBtn);
      } else {
        footer.appendChild(btn);
      }
    }, 50);
  },

  async _onQuickImport() {
    // 跳过所有冲突项，只提交 autoApply
    if (!this._importState) return;
    const conflicts = this._importState.preview.conflicts || [];
    this._importState.decisions = {};
    this._importState.processedConflicts = new Set();
    for (const c of conflicts) {
      this._importState.decisions[c.conflictId] = { action: "skip" };
      this._importState.processedConflicts.add(c.conflictId);
    }
    // 直接提交，跳过 DOM 重新收集
    const shouldClose = await this._onImportCommit({ skipCollect: true });
    if (shouldClose === false || shouldClose === undefined) {
      // 弹窗已关闭
    }
  },

  // ── 提交导入 ──

  async _onImportCommit({ skipCollect = false } = {}) {
    if (!this._importState) return true;
    // 先收集决策（quick import 可跳过）
    if (!skipCollect) this._collectImportDecisions();

    const totalConflicts = (this._importState.preview.conflicts || []).length;
    const processed = this._importState.processedConflicts.size;
    if (totalConflicts > 0 && processed < totalConflicts) {
      Utils.toast(`还有 ${totalConflicts - processed} 项冲突未处理`);
      return true; // 保持弹窗打开
    }

    const blockers = this._importState.preview.blockers || [];
    if (blockers.length > 0) {
      Utils.toast("存在阻断项，无法提交导入");
      return true;
    }

    try {
      Utils.toast("正在导入数据…");
      const result = await this.importBundleCommit(
        this._importState.preview.previewId,
        this._importState.decisions
      );
      Utils.toast(
        `导入完成：新增 ${result.stats?.projectsAdded || 0} 项目、` +
        `${result.stats?.samplesAdded || 0} 样机，` +
        `合并 ${result.stats?.samplesMerged || 0} 样机，` +
        `事件 ${result.stats?.sampleEventsAdded || 0} 条，` +
        `跳过 ${result.stats?.skipped || 0} 项`
      );
      await this.applyImportBundleMutationResult(result, { render: true });
    } catch (e) {
      const msg = e.message || e;
      if (msg.includes("修改") || msg.includes("revision")) {
        Utils.toast("导入失败：服务器数据已被修改，请重新选择文件导入");
      } else {
        Utils.toast("导入失败: " + msg);
      }
      return true; // 保持弹窗打开
    }

    this._importState = null;
    this.closeModal();
    return false;
  },

});
