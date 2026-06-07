/* ========================================
   数字治理平台 V7 - workspace 共享工具模块
   ======================================== */

app.registerModule("workspace.shared", {

  // ==================== 任务下发与执行管理 ====================
  taskOwnerName(owner) {
    const text = String(owner || "").trim();
    if (!text) return "";
    const idx = text.indexOf("/");
    if (idx >= 0) return text.slice(0, idx).replace(/（[^）]*）|\([^)]*\)/g, "").trim() || text.slice(0, idx).trim();
    return text.replace(/（[^）]*）|\([^)]*\)/g, "").trim();
  },

  taskOwnerId(owner) {
    const text = String(owner || "").trim();
    if (!text) return "";
    const idx = text.indexOf("/");
    if (idx >= 0) {
      const after = text.slice(idx + 1).trim();
      const parenClean = after.replace(/（[^）]*）|\([^)]*\)/g, "").trim();
      return parenClean;
    }
    return "";
  },

  taskDateText(value) {
    const text = String(value || "").trim();
    if (!text) return "-";
    const datePart = text.includes("T") ? text.split("T")[0] : text.slice(0, 10);
    return datePart.replace(/-/g, "/");
  },

  taskCategoryItemText(category, testItem) {
    const cat = String(category || "").trim();
    const item = String(testItem || "").trim();
    if (cat && item) return `${cat} - ${item}`;
    return cat || item || "-";
  },

  taskFlowStatus(t) {
    return this.normalizeTaskFlowStatus(t);
  },

  taskStoredStatus(flowStatus) {
    return this.normalizeTaskStoredStatus(flowStatus);
  },

  repairTaskStatus(task, nextStatus, ctx = {}) {
    if (!task) return { status: "", flow: "" };
    const storedStatus = this.taskStoredStatus(nextStatus);
    const flowStatus = this.taskFlowStatus({ ...task, status: storedStatus, completed: ["正常完成", "异常终止"].includes(storedStatus) });
    const changed = task.status !== storedStatus;
    task.status = storedStatus;

    if (flowStatus === "进行中") {
      task.completed = false;
      if (ctx.startDate !== undefined && (!task.startDate || ctx.resetStartDate)) task.startDate = ctx.startDate;
    } else if (flowStatus === "阻塞中") {
      task.completed = false;
      if (ctx.reason !== undefined) task.blockReason = ctx.reason || "";
    } else if (["正常完成", "异常终止"].includes(flowStatus)) {
      task.completed = true;
      task.completionType = flowStatus;
      if (ctx.completedAt !== undefined) task.completedAt = ctx.completedAt;
      if (ctx.endDate !== undefined) task.endDate = ctx.endDate;
    } else {
      task.completed = false;
      if (ctx.clearCompletion) {
        task.completionType = "";
        task.completedAt = "";
      }
    }
    if (changed && ctx.markChanged) this._normalizedChanged = true;
    return { status: task.status, flow: flowStatus };
  },

  createProgressRecord(values = {}) {
    return {
      id: values.id || Utils.id("prog_"),
      strategyId: values.strategyId || "",
      category: values.category || "",
      testItem: values.testItem || "",
      skuIndex: values.skuIndex || 1,
      sampleSize: values.sampleSize || ""
    };
  },

  taskResultStatus(task) {
    if (!task) return "";
    const direct = this.normalizeTaskResultValue(task.latestResult || task.result || "");
    if (direct) return direct;
    const uploads = Array.isArray(task.resultUploads) ? task.resultUploads : [];
    for (let i = uploads.length - 1; i >= 0; i--) {
      const result = this.normalizeTaskResultValue(uploads[i]?.result || "");
      if (result) return result;
    }
    return "";
  },

  progressDisplayStatus(stage, progress) {
    if (!stage || !progress?.id) return "待下发";
    const tasks = (stage.tasks || []).filter(task => !task?.archived && task.progressId === progress.id);
    if (!tasks.length) return "待下发";
    const statuses = new Set();
    tasks.forEach(task => {
      const flow = this.taskFlowStatus(task);
      if (flow === "进行中" || flow === "阻塞中" || flow === "待下发") {
        statuses.add(flow);
        return;
      }
      const result = this.taskResultStatus(task);
      if (flow === "异常终止") statuses.add("不通过");
      else statuses.add(result || "通过");
    });
    const priority = ["进行中", "阻塞中", "不通过", "待下发", "通过"];
    return priority.find(status => statuses.has(status)) || "待下发";
  },

  transitionTaskStatus(stage, task, nextStatus, ctx = {}) {
    if (!task) return { fromStatus: "", toStatus: "", fromFlow: "", toFlow: "" };
    const fromStatus = task.status || "";
    const fromFlow = this.taskFlowStatus(task);
    const repaired = this.repairTaskStatus(task, nextStatus, {
      ...ctx,
      startDate: ctx.startDate || Utils.today(),
      completedAt: ctx.completedAt || Utils.now(),
      endDate: ctx.endDate || task.endDate || Utils.today()
    });
    const toFlow = repaired.flow;

    return { fromStatus, toStatus: task.status, fromFlow, toFlow };
  },

  taskStatusBadgeClass(status) {
    if (status === "进行中") return "status-running";
    if (status === "阻塞中") return "status-blocked";
    if (status === "正常完成") return "status-done";
    if (status === "异常终止") return "status-bad";
    return "status-pending";
  },

  getProgressRequiredSampleCount(stage, progress) {
    if (!stage || !progress) return null;
    let n = Utils.parsePositiveInt(progress.sampleSize);
    if (n !== null) return n;
    const strategy = (stage.strategy || []).find(r => r.id === progress.strategyId || r.item === progress.testItem);
    return Utils.parsePositiveInt(strategy?.sampleSize);
  },

  getProgressDisplayName(stage, progress) {
    if (!stage || !progress) return "未知测试项";
    const sku = stage.skuNames?.[progress.skuIndex - 1] || `SKU${progress.skuIndex}`;
    return `${sku} · ${progress.category || ""} · ${progress.testItem || ""}`;
  },

  projectMemberSelectHtml(id, selected = "", placeholder = "请选择人员", disabled = false) {
    const p = this.currentProject();
    const members = this.projectActiveMembers(p);
    const selectedText = String(selected || "");
    const selectedIdentity = Utils.personIdentityFromText(selectedText);
    const selectedKey = selectedIdentity.name && selectedIdentity.employeeNo
      ? Utils.memberIdentityKey(selectedIdentity.name, selectedIdentity.employeeNo)
      : "";
    const disabledAttr = disabled ? " disabled" : "";
    if (!members.length) {
      return `<select id="${id}" disabled><option value="">请先在项目人员配置中新增人员</option></select>`;
    }
    const options = members.map(m => {
      const value = Utils.personText(m.name, m.employeeNo);
      const isSelected = selectedText === value || selectedKey === Utils.memberIdentityKey(m.name, m.employeeNo);
      return `<option value="${Utils.esc(value)}" ${isSelected ? "selected" : ""}>${Utils.esc(value)}</option>`;
    }).join("");
    return `<select id="${id}"${disabledAttr}><option value="">${Utils.esc(placeholder)}</option>${options}</select>`;
  },

  statusForOpenTaskUsage(task) {
    const flow = this.taskFlowStatus(task);
    if (flow === "进行中") return "测试中";
    if (flow === "阻塞中") return "在位等待";
    return "在位等待";
  },

  releaseTaskSamples(task, ctx = {}, excludeTaskIds = []) {
    const excluded = new Set([task?.id, ...(Array.isArray(excludeTaskIds) ? excludeTaskIds : [excludeTaskIds])].filter(Boolean));
    (task?.sampleIds || []).forEach(id => {
      const otherUsages = this.activeTaskUsagesForSample(id, excluded);
      if (otherUsages.length) {
        const usage = otherUsages[0];
        this.changeSampleStatus(id, this.statusForOpenTaskUsage(usage.task), {
          user: ctx.user || "管理员",
          source: ctx.source || "任务释放",
          reason: ctx.reason || "任务释放后仍被其他任务占用",
          projectId: usage.project.id,
          stageId: usage.stage.id,
          taskId: usage.task.id,
          testItem: usage.task.testItem
        });
      } else {
        this.changeSampleStatus(id, "闲置", {
          user: ctx.user || "管理员",
          source: ctx.source || "任务释放",
          reason: ctx.reason || "任务释放样机",
          projectId: ctx.projectId,
          stageId: ctx.stageId,
          forceLog: !!ctx.forceLog
        });
      }
    });
  },

  taskSampleDisplayName(sampleId) {
    const found = this.findSample(sampleId);
    const sample = found?.sample;
    return sample?.sampleNo || sample?.imei || sample?.sn || sample?.boardSn || sampleId;
  },

  sampleSnapshotForTask(sampleId, seed = {}) {
    const sid = String(sampleId || seed.sampleId || seed.id || "").trim();
    if (!sid) return null;
    const found = this.findSample(sid);
    const sample = found?.sample || {};
    const code = found?.sample
      ? this.sampleDisplayCode(sample)
      : (seed.code || seed.sampleNo || seed.sample_no || seed.sn || seed.imei || seed.boardSn || sid);
    return {
      id: sid,
      categoryId: found?.category?.id || sample.categoryId || seed.categoryId || "",
      categoryName: found?.category?.name || seed.categoryName || "",
      code,
      sampleNo: sample.sampleNo || seed.sampleNo || seed.code || code || sid,
      sn: sample.sn || seed.sn || "",
      imei: sample.imei || seed.imei || "",
      boardSn: sample.boardSn || seed.boardSn || "",
      capturedAt: seed.capturedAt || Utils.now(),
      destroyedAt: seed.destroyedAt || ""
    };
  },

  ensureTaskSampleSnapshots(task, sampleIds = null, options = {}) {
    if (!task) return {};
    if (!task.sampleSnapshots || typeof task.sampleSnapshots !== "object" || Array.isArray(task.sampleSnapshots)) {
      task.sampleSnapshots = {};
    }
    const ids = [];
    const seen = new Set();
    const add = value => {
      const sid = String(value || "").trim();
      if (sid && !seen.has(sid)) {
        seen.add(sid);
        ids.push(sid);
      }
    };
    const seedById = new Map();
    const rememberSeed = item => {
      if (!item || typeof item !== "object") return;
      const sid = String(item.sampleId || item.sid || item.id || "").trim();
      if (!sid) return;
      seedById.set(sid, { ...(seedById.get(sid) || {}), ...item });
      add(sid);
    };
    if (Array.isArray(sampleIds)) sampleIds.forEach(add);
    (task.sampleIds || []).forEach(add);
    (task.removedSampleRecords || []).forEach(rememberSeed);
    (task.sampleFaultRecords || []).forEach(rememberSeed);
    (task.resultDraft?.samples || []).forEach(rememberSeed);
    (task.resultUploads || []).forEach(upload => (upload?.samples || []).forEach(rememberSeed));

    ids.forEach(sid => {
      const existing = task.sampleSnapshots[sid] || {};
      const snapshot = this.sampleSnapshotForTask(sid, {
        ...seedById.get(sid),
        capturedAt: options.capturedAt || existing.capturedAt,
        destroyedAt: options.destroyedAt || existing.destroyedAt
      });
      if (!snapshot && !existing) return;
      task.sampleSnapshots[sid] = { ...existing, ...(snapshot || {}) };
      if (existing.destroyedAt && !options.destroyedAt) task.sampleSnapshots[sid].destroyedAt = existing.destroyedAt;
    });
    return task.sampleSnapshots;
  },

  attachSampleSnapshotToTasks(tasks = [], sampleIds = null, options = {}) {
    const list = Array.isArray(tasks) ? tasks : [tasks];
    list.forEach(task => this.ensureTaskSampleSnapshots(task, sampleIds, options));
  },

  taskSampleArchiveName(sampleId, snapshot = null) {
    const found = this.findSample(sampleId);
    const sample = found?.sample || null;
    const pool = found?.category?.name || snapshot?.categoryName || "未知样机池";
    const code = sample ? this.sampleDisplayCode(sample) : (snapshot?.code || snapshot?.sampleNo || sampleId);
    return `${pool}-${code}`;
  },

  taskSampleIdentityInfo(sampleId, snapshot = null) {
    const found = this.findSample(sampleId);
    const sample = found?.sample || {};
    return {
      pool: found?.category?.name || snapshot?.categoryName || "未知样机池",
      code: found ? this.sampleDisplayCode(sample) : (snapshot?.code || snapshot?.sampleNo || sampleId),
      sn: sample.sn || snapshot?.sn || "-",
      imei: sample.imei || snapshot?.imei || "-",
      boardSn: sample.boardSn || snapshot?.boardSn || "-"
    };
  },

});
