/* ========================================
   数字治理平台 V7 - workspace 共享工具模块
   ======================================== */

Object.assign(app, {

  // ==================== 任务下发与执行进度管理（合并原进展追踪）====================
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
    const status = String(t?.status || "").trim();
    if (["异常完成", "异常终止", "失败", "Fail"].includes(status)) return "异常终止";
    if (t?.completed || ["正常完成", "已完成", "通过", "Pass"].includes(status)) return "正常完成";
    if (["阻塞", "阻塞中"].includes(status)) return "阻塞中";
    if (["进行中", "Testing"].includes(status)) return "进行中";
    if (["待下发", "待执行", "待启动", ""].includes(status)) return "待下发";
    return "待下发";
  },

  taskStoredStatus(flowStatus) {
    const flow = String(flowStatus || "").trim();
    if (["异常完成", "异常终止", "失败", "Fail"].includes(flow)) return "异常终止";
    if (["正常完成", "已完成", "通过", "Pass"].includes(flow)) return "正常完成";
    if (["阻塞", "阻塞中"].includes(flow)) return "阻塞";
    if (["进行中", "Testing"].includes(flow)) return "进行中";
    return "待下发";
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

  setProgressStatus(progress, nextStatus, ctx = {}) {
    if (!progress) return null;
    const status = String(nextStatus || "").trim();
    if (status && progress.status !== status) {
      progress.status = status;
      if (ctx.markChanged) this._normalizedChanged = true;
    }
    return progress;
  },

  createProgressRecord(values = {}) {
    return {
      id: Utils.id("prog_"),
      ...values,
      status: values.status || "待启动",
      owner: values.owner || "",
      startDate: values.startDate || "",
      endDate: values.endDate || "",
      issue: values.issue || "",
      sampleIds: Array.isArray(values.sampleIds) ? values.sampleIds : []
    };
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

    this.syncProgressStatus(stage, task, toFlow, ctx);
    return { fromStatus, toStatus: task.status, fromFlow, toFlow };
  },

  syncProgressStatus(stage, task, flowStatus, ctx = {}) {
    const progress = ctx.progress || (stage?.progress || []).find(x => x.id === task?.progressId);
    if (!progress) return null;
    if (ctx.progressStatus) {
      this.setProgressStatus(progress, ctx.progressStatus);
    } else if (flowStatus === "进行中") {
      this.setProgressStatus(progress, "Testing");
    } else if (flowStatus === "阻塞中") {
      this.setProgressStatus(progress, "阻塞");
    } else if (flowStatus === "正常完成") {
      this.setProgressStatus(progress, ctx.result || "Pass");
    } else if (flowStatus === "异常终止") {
      this.setProgressStatus(progress, ctx.result || "Fail");
    }
    if (ctx.owner !== undefined) progress.owner = ctx.owner;
    if (ctx.startDate !== undefined) progress.startDate = ctx.startDate;
    if (ctx.endDate !== undefined) progress.endDate = ctx.endDate;
    if (ctx.issue !== undefined) progress.issue = ctx.issue;
    return progress;
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
