/* ========================================
   数字治理平台 V7 - 任务结果录入模块
   含结果上传·样机去向·问题记录·图片·完成
   ======================================== */

Object.assign(app, {

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
          <div class="form-group task-result-account-group">
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
    // 任务已结束（追加结果模式）：只补录问题表/故障/图片，不再改写样机当前状态/去向/持有人/位置
    const lockSampleStatus = !finishTask && this.isTaskCompleted(task);

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
      if (lockSampleStatus) return;
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
