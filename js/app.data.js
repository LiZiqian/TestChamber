/* ========================================
   数字治理平台 V7 - 数据工具模块
   ======================================== */

Object.assign(app, {

  emptyData() {
    return {
      version: this.version,
      currentProjectId: null,
      currentStageId: null,
      users: [],
      projects: [],
      sampleLibrary: { categories: [], logs: [] }
    };
  },

  cloneData(data) {
    return JSON.parse(JSON.stringify(data || this.emptyData()));
  },

  normalizePersonText(text) {
    const raw = String(text || "").trim();
    if (!raw) return "";
    const p = Utils.personIdentityFromText(raw);
    return p.name && p.employeeNo ? Utils.personText(p.name, p.employeeNo) : raw;
  },

  projectActiveMembers(project) {
    return (project?.members || []).filter(m => m.active !== false && String(m.name || "").trim() && String(m.employeeNo || "").trim());
  },

  normalize() {
    this.data.version = this.version;
    if (!this.data.sampleLibrary) this.data.sampleLibrary = { categories: [], logs: [] };
    if (!Array.isArray(this.data.sampleLibrary.categories)) this.data.sampleLibrary.categories = [];
    if (!Array.isArray(this.data.sampleLibrary.logs)) this.data.sampleLibrary.logs = [];
    if (!Array.isArray(this.data.users)) this.data.users = [];
    if (!Array.isArray(this.data.projects)) this.data.projects = [];
    if ("peoplePool" in this.data) { delete this.data.peoplePool; this._normalizedChanged = true; }
    if ("locationPool" in this.data) { delete this.data.locationPool; this._normalizedChanged = true; }
    this.data.projects.forEach(p => {
      if (!Array.isArray(p.stages)) p.stages = [];
      if (!Array.isArray(p.members)) p.members = [];
      if (!Array.isArray(p.locations)) { p.locations = []; this._normalizedChanged = true; }
      if (!Array.isArray(p.testCaseMaster)) p.testCaseMaster = [];
      const cleanLocations = [];
      p.locations.forEach(loc => {
        const clean = String(loc || "").trim();
        if (clean && !cleanLocations.includes(clean)) cleanLocations.push(clean);
      });
      if (cleanLocations.length !== p.locations.length || cleanLocations.some((v, i) => v !== p.locations[i])) {
        p.locations = cleanLocations;
        this._normalizedChanged = true;
      }
      const memberKeys = new Set();
      p.members = p.members.map(m => {
        if (typeof m !== "string") return m || {};
        const identity = Utils.personIdentityFromText(m);
        this._normalizedChanged = true;
        return { id: Utils.id("member_"), name: identity.name, employeeNo: identity.employeeNo, active: !!(identity.name && identity.employeeNo) };
      });
      p.members.forEach(m => {
        if (!m.id) { m.id = Utils.id("member_"); this._normalizedChanged = true; }
        if (typeof m.active === "undefined") { m.active = true; this._normalizedChanged = true; }
        const legacyIdentity = Utils.personIdentityFromText(m.name);
        if ((!m.employeeNo || !String(m.employeeNo).trim()) && legacyIdentity.name && legacyIdentity.employeeNo) {
          m.name = legacyIdentity.name;
          m.employeeNo = legacyIdentity.employeeNo;
          this._normalizedChanged = true;
        }
        m.name = String(m.name || "").trim();
        m.employeeNo = Utils.normalizeDigits(m.employeeNo || "");
        const key = Utils.memberIdentityKey(m.name, m.employeeNo);
        if (m.active !== false && (!m.name || !m.employeeNo)) {
          m.active = false;
          this._normalizedChanged = true;
        }
        if (m.active !== false && key !== "||") {
          if (memberKeys.has(key)) {
            m.active = false;
            this._normalizedChanged = true;
          } else {
            memberKeys.add(key);
          }
        }
      });
      const memberCountBefore = p.members.length;
      p.members = p.members.filter(m => !(m.active === false && memberKeys.has(Utils.memberIdentityKey(m.name, m.employeeNo))));
      if (p.members.length !== memberCountBefore) this._normalizedChanged = true;
      p.stages.forEach(s => {
        if (!Array.isArray(s.skuNames)) s.skuNames = ["SKU1"];
        if (!Array.isArray(s.bom)) s.bom = [];
        if (!Array.isArray(s.strategy)) s.strategy = [];
        if (!Array.isArray(s.progress)) s.progress = [];
        if (!Array.isArray(s.tasks)) s.tasks = [];
        s.tasks.forEach(t => {
          if (!t.id) t.id = Utils.id("task_");
          if (!Array.isArray(t.sampleIds)) t.sampleIds = [];
          if (!Array.isArray(t.removedSampleRecords)) {
            const legacyIds = Array.isArray(t.removedSampleIds) ? t.removedSampleIds : [];
            t.removedSampleRecords = legacyIds.map(sampleId => ({
              id: Utils.id("removed_"),
              sampleId,
              sampleNo: sampleId,
              removedAt: "",
              user: "",
              reason: "历史退出记录"
            }));
            this._normalizedChanged = true;
          } else {
            t.removedSampleRecords = t.removedSampleRecords.map(item => {
              if (typeof item === "string") {
                this._normalizedChanged = true;
                return { id: Utils.id("removed_"), sampleId: item, sampleNo: item, removedAt: "", user: "", reason: "历史退出记录" };
              }
              if (!item || typeof item !== "object") { this._normalizedChanged = true; return null; }
              if (!item.id) { item.id = Utils.id("removed_"); this._normalizedChanged = true; }
              return item;
            }).filter(item => item && item.sampleId);
          }
          if (!Array.isArray(t.sampleFaultRecords)) t.sampleFaultRecords = [];
          if (!Array.isArray(t.resultUploads)) t.resultUploads = [];
          if (!Array.isArray(t.logs)) t.logs = [];
          t.owner = this.normalizePersonText(t.owner);
          if (typeof t.archived === "undefined") t.archived = false;
          if (t.status === "完成") t.status = "正常完成";
          if (t.status === "已完成") { t.status = t.completionType || "正常完成"; t.completed = true; }
          const progress = t.progressId ? s.progress.find(x => x.id === t.progressId) : null;
          if (progress) {
            if (!t.strategyId && progress.strategyId) t.strategyId = progress.strategyId;
            if (!t.category && progress.category) t.category = progress.category;
            if (!t.testItem && progress.testItem) t.testItem = progress.testItem;
            if (!t.skuIndex && progress.skuIndex) t.skuIndex = progress.skuIndex;
            if (!t.requiredSampleCount) t.requiredSampleCount = Utils.parsePositiveInt(progress.sampleSize) || t.requiredSampleCount;
          }
          if (typeof t.remark === "undefined") t.remark = "";
          if (!t.issueRecord) t.issueRecord = { dtsNo: "", isIssue: "", issueNote: "" };
        });
      });
    });
    this.data.sampleLibrary.categories.forEach(c => (c.samples || []).forEach(s => {
      if (typeof s.boardSn === "undefined") {
        s.boardSn = "";
        this._normalizedChanged = true;
      }
    }));
    this.eachSample(s => {
      if (!Array.isArray(s.logs)) s.logs = [];
      if (!s.status) s.status = "闲置";
      const statusMap = {
        "已分配": "在位等待",
        "进入测试任务": "测试中",
        "已归还": "闲置",
        "借出": "取走分析",
        "已借出": "取走分析",
        "待维修": "闲置",
        "报废": "闲置"
      };
      if (statusMap[s.status]) s.status = statusMap[s.status];
      if (!this.constants.sampleStatuses.includes(s.status)) s.status = "闲置";
      if (typeof s.imei === "undefined") s.imei = "";
      if (typeof s.boardSn === "undefined") s.boardSn = "";
      if (typeof s.schemeNo === "undefined") s.schemeNo = "";
      if (typeof s.initialResult === "undefined") s.initialResult = "";
      if (!Array.isArray(s.initialResults)) {
        s.initialResults = Utils.parseSampleIssueText(s.initialResult || "");
        if (s.initialResults.length) this._normalizedChanged = true;
      }
      if (!Array.isArray(s.problemRecords)) {
        s.problemRecords = (s.initialResults || []).map(desc => ({
          id: Utils.id("problem_"),
          description: String(desc || "").trim(),
          source: "初检",
          taskLabel: ""
        })).filter(x => x.description && !Utils.isNoSampleIssueText(x.description));
        if (s.problemRecords.length) this._normalizedChanged = true;
      } else {
        const beforeProblemCount = s.problemRecords.length;
        s.problemRecords = s.problemRecords.map(item => {
          if (typeof item === "string") {
            return { id: Utils.id("problem_"), description: item.trim(), source: "初检", taskLabel: "" };
          }
          return {
            id: item.id || Utils.id("problem_"),
            description: String(item.description || item.problem || "").trim(),
            source: String(item.source || "手动补录").trim(),
            taskLabel: String(item.taskLabel || item.task || "").trim()
          };
        }).filter(x => x.description && !Utils.isNoSampleIssueText(x.description));
        if (s.problemRecords.length !== beforeProblemCount) this._normalizedChanged = true;
      }
      (s.logs || []).forEach(log => {
        if (!(log.faultMarked || log.flowStatus === "故障")) return;
        const description = String(log.problemDescription || log.reason || "历史任务标记故障").trim();
        const taskLabel = [log.projectName || this.projectName(log.projectId), log.stageName || this.stageName(log.projectId, log.stageId), log.testItem]
          .filter(v => v && v !== "-").join(" - ");
        const exists = s.problemRecords.some(item =>
          item.description === description && item.source === "测试任务" && item.taskLabel === taskLabel
        );
        if (!exists) {
          s.problemRecords.push({ id: Utils.id("problem_"), description, source: "测试任务", taskLabel });
          this._normalizedChanged = true;
        }
      });
      s.initialResults = s.problemRecords.map(item => item.description);
      s.initialResult = s.initialResults.join("\n");
      if (typeof s.borrower === "undefined") s.borrower = "";
      if (typeof s.borrowDate === "undefined") s.borrowDate = "";
      if (typeof s.importDate === "undefined") s.importDate = "";
      if (typeof s.location === "undefined") s.location = "";
      if (!Array.isArray(s.photos)) s.photos = [];
    });
    this.reconcileSampleTaskOccupancy();
  },

  // ---- 数据访问 ----
  currentProject() {
    return this.data.projects.find(p => p.id === this.view.selectedProjectId) || this.data.projects[0] || null;
  },
  currentStage() {
    const p = this.currentProject();
    return p ? (p.stages.find(s => s.id === this.view.selectedStageId) || p.stages[0] || null) : null;
  },
  allSamples() {
    return this.data.sampleLibrary.categories.flatMap(c => (c.samples || []).map(s => ({ ...s, categoryName: c.name })));
  },
  /** 遍历所有样机的真实引用（可安全写入）。仅 normalize / reconcile 等修复逻辑使用。 */
  eachSample(fn) {
    this.data.sampleLibrary.categories.forEach(c => {
      (c.samples || []).forEach(s => fn(s, c));
    });
  },
  findSample(sampleId) {
    for (const c of this.data.sampleLibrary.categories) {
      const s = (c.samples || []).find(x => x.id === sampleId);
      if (s) return { category: c, sample: s };
    }
    return null;
  },
  projectName(id) { return this.data.projects.find(p => p.id === id)?.name || "-"; },
  stageName(projectId, stageId) {
    const p = this.data.projects.find(p => p.id === projectId);
    return p?.stages?.find(s => s.id === stageId)?.name || "-";
  },

  activeStageTasks(stage) {
    return (stage?.tasks || []).filter(t => !t.archived);
  },

  sampleProblemRecords(sample) {
    if (!sample) return [];
    if (!Array.isArray(sample.problemRecords)) sample.problemRecords = [];
    sample.problemRecords = sample.problemRecords.map(item => {
      if (typeof item === "string") {
        return { id: Utils.id("problem_"), description: item.trim(), source: "初检", taskLabel: "" };
      }
      return {
        id: item.id || Utils.id("problem_"),
        description: String(item.description || item.problem || "").trim(),
        source: String(item.source || "手动补录").trim(),
        taskLabel: String(item.taskLabel || item.task || "").trim()
      };
    }).filter(x => x.description && !Utils.isNoSampleIssueText(x.description));
    return sample.problemRecords;
  },

  sampleHasProblem(sample) {
    return this.sampleProblemRecords(sample).length > 0;
  },

  sampleEffectiveStatus(sample) {
    const status = String(sample?.status || "闲置").trim() || "闲置";
    if (["已退库", "取走分析", "已借出", "测试中", "在位等待"].includes(status)) return status === "已借出" ? "取走分析" : status;
    if (this.sampleHasProblem(sample)) return "故障";
    return status;
  },

  sampleTaskLabelFromCtx(ctx = {}) {
    const project = ctx.projectName || this.projectName(ctx.projectId);
    const stage = ctx.stageName || this.stageName(ctx.projectId, ctx.stageId);
    const item = ctx.testItem || "";
    return [project, stage, item].filter(v => v && v !== "-").join(" - ");
  },

  addSampleProblem(sample, description, ctx = {}) {
    const text = String(description || "").trim();
    if (!sample || !text) return null;
    const source = String(ctx.problemSource || ctx.source || "测试任务").trim();
    const taskLabel = String(ctx.taskLabel || this.sampleTaskLabelFromCtx(ctx)).trim();
    const records = this.sampleProblemRecords(sample);
    const exists = records.some(item =>
      item.description === text && item.source === source && item.taskLabel === taskLabel
    );
    if (exists) return null;
    const record = { id: Utils.id("problem_"), description: text, source, taskLabel };
    records.push(record);
    sample.initialResults = records.map(x => x.description);
    sample.initialResult = sample.initialResults.join("\n");
    return record;
  },

  // ---- 样机状态 ----
  changeSampleStatus(sampleId, newStatus, ctx = {}) {
    if (newStatus === "已借出") newStatus = "取走分析";
    if (newStatus === "故障") newStatus = "闲置";
    const found = this.findSample(sampleId);
    if (!found) return;
    const s = found.sample, old = this.sampleEffectiveStatus(s);
    if (old === newStatus && !ctx.forceLog && !ctx.taskId && !ctx.receiver) return;
    s.status = newStatus;
    s.updatedAt = Utils.now();
    const isFault = !!ctx.faultMarked;
    const problemDescription = String(ctx.problemDescription || "").trim();
    if (isFault && problemDescription) {
      this.addSampleProblem(s, problemDescription, { ...ctx, problemSource: ctx.problemSource || "测试任务" });
    }
    // 仅当传入了非空去向位置时才覆盖样机当前位置，避免保存草稿/释放等空值清空原位置
    if (ctx.destLocation !== undefined && String(ctx.destLocation).trim()) {
      s.location = String(ctx.destLocation).trim();
    }
    const dest = ctx.destination || newStatus;
    if (dest === "取走分析") {
      s.borrower = this.normalizePersonText(ctx.receiver || "");
      s.borrowDate = ctx.receiverDate || Utils.today();
    } else {
      // 闲置 / 已退库：统一清空 borrower，不动 owner
      s.borrower = "";
      s.borrowDate = "";
    }
    // accountOwner 最后写入 — 表单值永远胜出，不会被 destination 分支覆盖
    if (ctx.accountOwner !== undefined) {
      s.owner = this.normalizePersonText(ctx.accountOwner);
    }
    const freeStatus = ["闲置", "已退库", "取走分析", "已借出"].includes(newStatus);
    s.currentProjectId = freeStatus ? null : (ctx.projectId ?? s.currentProjectId);
    s.currentStageId = freeStatus ? null : (ctx.stageId ?? s.currentStageId);
    s.currentTaskId = freeStatus ? null : (ctx.taskId ?? s.currentTaskId);
    s.currentTestItem = freeStatus ? "" : (ctx.testItem ?? s.currentTestItem);
    const displayStatus = this.sampleEffectiveStatus(s);
    const log = {
      id: Utils.id("log_"), time: Utils.now(), sampleId: s.id, sampleNo: s.sampleNo,
      action: ctx.source || "未知入口",
      user: ctx.user || "未填写", source: ctx.source || "未知入口",
      from: old, to: displayStatus, flowStatus: newStatus, reason: ctx.reason || "",
      projectId: ctx.projectId || s.currentProjectId, stageId: ctx.stageId || s.currentStageId,
      projectName: ctx.projectName || this.projectName(ctx.projectId || s.currentProjectId),
      stageName: ctx.stageName || this.stageName(ctx.projectId || s.currentProjectId, ctx.stageId || s.currentStageId),
      taskId: ctx.taskId || s.currentTaskId, testItem: ctx.testItem || s.currentTestItem,
      faultMarked: isFault,
      problemDescription,
      photoIds: Array.isArray(ctx.photoIds) ? ctx.photoIds : [],
      photos: Array.isArray(ctx.photos) ? ctx.photos : []
    };
    s.logs = s.logs || [];
    s.logs.push(log);
    this.data.sampleLibrary.logs.push(log);
  },

  activeTaskUsagesForSample(sampleId, excludeTaskId = "") {
    const excluded = excludeTaskId instanceof Set
      ? excludeTaskId
      : new Set(Array.isArray(excludeTaskId) ? excludeTaskId : [excludeTaskId].filter(Boolean));
    const usages = [];
    (this.data.projects || []).forEach(project => (project.stages || []).forEach(stage => (stage.tasks || []).forEach(task => {
      if (!task || task.archived || excluded.has(task.id)) return;
      if (this.isTaskCompleted(task)) return;
      if ((task.sampleIds || []).includes(sampleId)) usages.push({ project, stage, task });
    })));
    return usages;
  },

  reconcileSampleTaskOccupancy() {
    if (!this.data?.sampleLibrary?.categories) return;
    this.eachSample(sample => {
      const activeUsages = this.activeTaskUsagesForSample(sample.id);
      if (activeUsages.length) return;
      if (sample.currentTaskId || ["测试中", "在位等待"].includes(sample.status)) {
        sample.currentProjectId = null;
        sample.currentStageId = null;
        sample.currentTaskId = null;
        sample.currentTestItem = "";
        if (["测试中", "在位等待"].includes(sample.status)) sample.status = "闲置";
        this._normalizedChanged = true;
      }
    });
  },

  // ---- 通用查找与判断 ----
  getProjectStageTask(projectId, stageId, taskId) {
    const p = this.data.projects.find(x => x.id === projectId);
    const s = p?.stages?.find(x => x.id === stageId);
    const t = s?.tasks?.find(x => x.id === taskId);
    return { p, s, t };
  },

  isTaskCompleted(task) {
    return !!(task?.completed || ["正常完成", "异常完成", "异常终止"].includes(task?.status));
  },

  isTaskExecuted(task) {
    if (!task) return false;
    if (task.completed || ["正常完成", "异常完成", "异常终止"].includes(task.status)) return true;
    return ["进行中", "阻塞", "阻塞中"].includes(task.status);
  },

  isSampleUsedByAnotherOpenTask(sampleId, excludeTaskId = "") {
    const usages = this.activeTaskUsagesForSample(sampleId, excludeTaskId);
    return usages.length > 0;
  }

});
