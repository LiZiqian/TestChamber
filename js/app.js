/* ========================================
   数字治理平台 v6.1 - 核心框架
   ======================================== */

const app = {
  version: "6.1-intranet",
  data: null,
  serverRevision: 0,
  serverUpdatedAt: null,
  serverOnline: false,
  _saveInFlight: false,
  _saveQueued: false,
  _queuedRemark: "",
  _saveTimer: null,
  _baseData: null,
  _modalStack: [],
  _restoringModal: false,
  _currentModalOnOk: null,

  view: {
    module: "home",
    selectedProjectId: null,
    selectedStageId: null,
    stageStrategyId: null,
    selectedCategoryId: null,
    sampleKeyword: "",
    sampleStatusFilter: "",
    sampleOwnerFilter: "",
    sampleBorrowerFilter: "",
    collapsed: {},
    progressFilters: {},
    taskFlowFilters: {},
    sidebarCollapsed: false
  },

  constants: {
    sampleStatuses: ["测试中", "闲置", "在位等待", "已退库", "取走分析"],
    taskStatuses: ["待下发", "待执行", "进行中", "通过", "失败", "阻塞", "正常完成", "异常完成"],
    modules: {
      home: "首页",
      projects: "项目管理",
      projectWorkspace: "项目工作台",
      samples: "样机档案池",
      devices: "测试设备仓库"
    }
  },

  // ---- 初始化 ----
  async init() {
    try {
      const res = await fetch("/api/state", { cache: "no-store" });
      const obj = await res.json();
      if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
      this.data = obj.data || this.emptyData();
      this.serverRevision = obj.revision || 0;
      this.serverUpdatedAt = obj.updated_at || null;
      this.serverOnline = true;
      this._baseData = this.cloneData(this.data);
    } catch (e) {
      console.error("服务器数据读取失败：", e);
      this.serverOnline = false;
      this.data = this.emptyData();
      setTimeout(() => alert("无法连接内网服务器 API，页面将以空白只读状态打开。请确认 server.py 正在运行。\n\n" + e.message), 50);
    }
    this.normalize();
    this._baseData = this.cloneData(this.data);
    this.view.selectedProjectId = this.data.currentProjectId || this.data.projects[0]?.id || null;
    this.view.selectedStageId = this.data.currentStageId || this.currentProject()?.stages?.[0]?.id || null;
    this.view.stageStrategyId = null;
    this.render();
    this.applySidebarState();
    this.updateServerStatus();
    if (this._normalizedChanged) {
      this._normalizedChanged = false;
      this.save({ silent: true, remark: "自动清理重复项目人员" });
    }
    // 全局任务操作菜单关闭事件（只绑定一次）
    if (!this._taskOpMenuEventsBound) {
      this._taskOpMenuEventsBound = true;
      document.addEventListener("click", (event) => {
        if (!event.target.closest(".task-op-menu, .task-more-menu")) {
          this.closeTaskOpMenus();
        }
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          this.closeTaskOpMenus();
          this.closeCaseDropdown?.();
        }
      });
    }
    // 全局 pointerdown 关闭用例搜索下拉框（只绑定一次）
    if (!this._caseDropdownEventsBound) {
      this._caseDropdownEventsBound = true;
      document.addEventListener("pointerdown", (event) => {
        const state = this._caseDropdownState;
        if (!state) return;
        const dd = document.getElementById("caseDropdown");
        const target = event.target;
        if (dd && dd.contains(target)) return;
        if (state.inputEl && state.inputEl === target) return;
        this.closeCaseDropdown();
      });
    }
  },

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
    this.allSamples().forEach(s => {
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

  // ---- 任务操作菜单统一管理 ----
  closeTaskOpMenus(exceptEl = null) {
    document.querySelectorAll(".task-op-menu.open, .task-more-menu.open").forEach(menu => {
      if (exceptEl && menu === exceptEl) return;
      menu.classList.remove("open");
    });
  },

  handleTaskOpMenuClick(menu) {
    const wasOpen = menu.classList.contains("open");
    this.closeTaskOpMenus();
    if (!wasOpen) menu.classList.add("open");
  },

  // ---- 服务器通信 ----
  updateServerStatus(extraText = "") {
    const el = document.getElementById("saveState");
    if (!el) return;
    if (this.serverOnline) {
      const t = this.serverUpdatedAt ? new Date(this.serverUpdatedAt).toLocaleString("zh-CN") : "-";
      const full = `已连接 · rev ${this.serverRevision} · ${t}${extraText ? " · " + extraText : ""}`;
      el.innerText = extraText || "同步正常";
      el.title = full;
    } else {
      el.innerText = extraText || "未连接服务器";
      el.title = `未连接 · 数据无法保存${extraText ? " · " + extraText : ""}`;
    }
  },

  async reloadFromServer({ render = true } = {}) {
    const res = await fetch("/api/state", { cache: "no-store" });
    const obj = await res.json();
    if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
    this.data = obj.data || this.emptyData();
    this.serverRevision = obj.revision || 0;
    this.serverUpdatedAt = obj.updated_at || null;
    this.serverOnline = true;
    this.normalize();
    this._baseData = this.cloneData(this.data);
    this.view.selectedProjectId = this.data.currentProjectId || this.data.projects[0]?.id || null;
    this.view.selectedStageId = this.data.currentStageId || this.currentProject()?.stages?.[0]?.id || null;
    if (render) this.render();
    this.updateServerStatus("已刷新");
    if (this._normalizedChanged) {
      this._normalizedChanged = false;
      this.save({ silent: true, remark: "自动清理重复项目人员" });
    }
  },

  scheduleSave({ delay = 450, remark = "" } = {}) {
    clearTimeout(this._saveTimer);
    this._queuedRemark = remark || this._queuedRemark || "";
    this.updateServerStatus("待同步");
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      const queuedRemark = this._queuedRemark;
      this._queuedRemark = "";
      this.save({ silent: true, remark: queuedRemark });
    }, delay);
  },

  async save({ silent = false, remark = "", retryOnConflict = true } = {}) {
    if (this._saveTimer) {
      clearTimeout(this._saveTimer);
      this._saveTimer = null;
    }
    if (this._saveInFlight) {
      this._saveQueued = true;
      this._queuedRemark = remark || this._queuedRemark || "";
      this.updateServerStatus("待同步");
      return true;
    }
    this.data.currentProjectId = this.view.selectedProjectId;
    this.data.currentStageId = this.view.selectedStageId;
    if (!this.serverOnline && !silent) {
      this.updateServerStatus("保存失败");
      return false;
    }
    this._saveInFlight = true;
    try {
      const res = await fetch("/api/state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision: this.serverRevision,
          baseData: this._baseData || this.data,
          appVersion: this.version,
          remark,
          data: this.data
        })
      });
      const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (res.status === 409) {
        this.updateServerStatus("保存冲突");
        if (silent && retryOnConflict && obj.server_revision) {
          await this.reloadFromServer({ render: false });
          this.updateServerStatus("已刷新");
          return false;
        }
        this._saveQueued = false;
        this._queuedRemark = "";
        if (!silent) alert("保存冲突：服务器上的数据已被其他人更新。\n\n请刷新页面后再继续操作。");
        return false;
      }
      if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
      this.serverRevision = obj.revision || this.serverRevision;
      this.serverUpdatedAt = obj.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已保存");
      return true;
    } catch (e) {
      console.error("保存到服务器失败：", e);
      this.serverOnline = false;
      this.updateServerStatus("保存失败");
      if (!silent) alert("保存失败：" + e.message);
      return false;
    } finally {
      this._saveInFlight = false;
      if (this._saveQueued && this.serverOnline) {
        this._saveQueued = false;
        const queuedRemark = this._queuedRemark;
        this._queuedRemark = "";
        setTimeout(() => this.save({ silent: true, remark: queuedRemark, retryOnConflict: false }), 0);
      }
    }
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
    if (ctx.destLocation !== undefined) {
      s.location = String(ctx.destLocation || "").trim();
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
    this.allSamples().forEach(sample => {
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

  // ---- 渲染引擎 ----
  render() {
    this.renderNav();
    this.renderHeader();
    const fn = {
      home: this.renderHome,
      projects: this.renderProjects,
      projectWorkspace: this.renderProjectWorkspace,
      samples: this.renderSamples,
      devices: this.renderDevices
    }[this.view.module] || this.renderHome;
    fn.call(this);
    this.updateSelectPlaceholderState();
  },

  renderHome() {
    const projectCount = this.data.projects.length;
    const samplePoolCount = this.data.sampleLibrary.categories.length;
    const sampleCount = this.allSamples().length;
    document.getElementById("content").innerHTML = `
      <section class="home-shell">
        <h1 class="home-title">终端硬件测试数字治理平台 <span>V6.1</span></h1>
        <div class="home-entry-grid">
          <button type="button" class="home-entry-card project-entry" onclick="app.go('projects')">
            <span class="home-entry-icon">📁</span>
            <span class="home-entry-name">项目管理</span>
            <span class="home-entry-meta">${projectCount} 个项目</span>
          </button>
          <button type="button" class="home-entry-card sample-entry" onclick="app.go('samples')">
            <span class="home-entry-icon">📦</span>
            <span class="home-entry-name">样机档案池</span>
            <span class="home-entry-meta">${samplePoolCount} 个样机池 · ${sampleCount} 台样机</span>
          </button>
          <button type="button" class="home-entry-card" onclick="app.go('devices')" style="opacity:0.7">
            <span class="home-entry-icon">🔬</span>
            <span class="home-entry-name">测试设备仓库</span>
            <span class="home-entry-meta">敬请期待...</span>
          </button>
        </div>
        <p class="home-slogan">从执行走向治理</p>
      </section>`;
  },
  renderDevices() {
    document.getElementById("content").innerHTML = `
      <div class="sample-archive-empty" style="min-height:calc(100vh - 160px)">
        <b>测试设备仓库</b>
        <span>敬请期待...</span>
      </div>`;
  },

  renderPreserveScroll() {
    const el = document.getElementById("content");
    const y = el ? el.scrollTop : 0;
    this.render();
    requestAnimationFrame(() => {
      const el2 = document.getElementById("content");
      if (el2) el2.scrollTop = y;
    });
  },

  renderNav() {
    const groups = [
      {
        title: "", items: [
          { id: "home", icon: "🏠", label: "首页" },
          { id: "projects", icon: "📁", label: "项目管理" },
          { id: "samples", icon: "📦", label: "样机档案池" },
          { id: "devices", icon: "🔬", label: "测试设备仓库" }
        ]
      }
    ];
    const isActive = (id) => {
      if (id === "projects" && this.view.module === "projectWorkspace") return true;
      return this.view.module === id;
    };
    document.getElementById("nav").innerHTML = groups.map(g => `
      <div class="nav-title">${g.title}</div>
      ${g.items.map(item => `<div class="nav-item ${isActive(item.id) ? 'active' : ''}" title="${Utils.esc(item.label)}" onclick="app.go('${item.id}')"><span class="nav-icon">${item.icon}</span><span class="nav-label">${Utils.esc(item.label)}</span></div>`).join("")}
    `).join("");
    this.applySidebarState();
  },

  renderHeader() {
    document.getElementById("pageTitle").innerHTML = this.breadcrumbHtml();
    document.getElementById("contextText").innerText = "";
    document.getElementById("actionArea").innerHTML = '';
  },

  breadcrumbHtml() {
    const parts = [{ label: "首页", action: "app.go('home')" }];
    const p = this.currentProject();
    const cat = this.data.sampleLibrary.categories.find(c => c.id === this.view.selectedCategoryId);
    if (this.view.module === "projects") {
      parts.push({ label: "项目管理", action: "app.go('projects')" });
    } else if (this.view.module === "projectWorkspace") {
      parts.push({ label: "项目管理", action: "app.go('projects')" });
      if (p) parts.push({ label: p.name, action: this.view.stageStrategyId ? "app.go('projectWorkspace')" : null });
      if (this.view.stageStrategyId) parts.push({ label: "阶段配置", action: null });
    } else if (this.view.module === "samples") {
      parts.push({ label: "样机档案池", action: "app.go('samples')" });
      if (cat) parts.push({ label: cat.name, action: null });
    }
    return parts.map((part, idx) => {
      const isLast = idx === parts.length - 1;
      const label = Utils.esc(part.label);
      const node = part.action && !isLast
        ? `<button type="button" onclick="${part.action}">${label}</button>`
        : `<span>${label}</span>`;
      return `${idx ? '<em>></em>' : ''}${node}`;
    }).join("");
  },

  go(module) {
    if (this.view.stageStrategyId && typeof this.autoSyncProgress === "function") {
      this.autoSyncProgress();
      this.view.stageStrategyId = null;
      this.save();
    }
    this.view.module = module;
    if (module !== "projectWorkspace") this.view.stageStrategyId = null;
    if (module === "samples") this.view.selectedCategoryId = null;
    if (module === "home") this.view.selectedCategoryId = null;
    this.render();
  },

  // ---- 侧栏 ----
  toggleSidebar() {
    this.view.sidebarCollapsed = !this.view.sidebarCollapsed;
    localStorage.setItem("digital_governance_sidebar_collapsed", this.view.sidebarCollapsed ? "1" : "0");
    this.applySidebarState();
  },

  applySidebarState() {
    const persisted = localStorage.getItem("digital_governance_sidebar_collapsed");
    if (persisted !== null) this.view.sidebarCollapsed = persisted === "1";
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("sidebarToggle");
    if (!sidebar) return;
    sidebar.classList.toggle("collapsed", !!this.view.sidebarCollapsed);
    if (toggle) {
      toggle.innerText = this.view.sidebarCollapsed ? "▶" : "◀";
      toggle.title = this.view.sidebarCollapsed ? "展开左侧栏" : "收起左侧栏";
    }
  },

  // ---- 折叠 ----
  isCollapsed(sectionId) {
    return !!(this.view.collapsed && this.view.collapsed[sectionId]);
  },
  collapseButton(sectionId) {
    const collapsed = this.isCollapsed(sectionId);
    return `<button class="btn btn-sm collapse-btn" onclick="app.toggleSection('${sectionId}')">${collapsed ? '展开' : '折叠'} ${collapsed ? '▾' : '▴'}</button>`;
  },
  sectionToggleTriangle(sectionId) {
    const collapsed = this.isCollapsed(sectionId);
    return `<button type="button" class="section-toggle-triangle" title="${collapsed ? '展开' : '收起'}" data-collapsed="${collapsed ? '1' : '0'}" onclick="app.toggleSection('${sectionId}')"></button>`;
  },
  toggleSection(sectionId) {
    if (!this.view.collapsed) this.view.collapsed = {};
    this.view.collapsed[sectionId] = !this.view.collapsed[sectionId];
    this.render();
  },

  // ---- 模态框 ----
  _syncModalInputsToAttributes() {
    const body = document.getElementById("modalBody");
    if (!body) return;
    body.querySelectorAll("input[type='checkbox'], input[type='radio']").forEach(el => {
      if (el.checked) el.setAttribute("checked", "");
      else el.removeAttribute("checked");
    });
    body.querySelectorAll("input:not([type='checkbox']):not([type='radio']), textarea").forEach(el => {
      el.setAttribute("value", el.value);
    });
    body.querySelectorAll("select").forEach(el => {
      Array.from(el.options).forEach(opt => {
        if (opt.selected) opt.setAttribute("selected", "");
        else opt.removeAttribute("selected");
      });
    });
  },

  showModal(title, bodyHtml, onOk, okText = "确认", options = {}) {
    // 模态框堆栈：当前已显示时，保存当前状态
    if (!this._restoringModal && document.getElementById("modalMask").style.display === "flex") {
      this._syncModalInputsToAttributes();
      const modalEl = document.querySelector(".modal");
      this._modalStack.push({
        title: document.getElementById("modalTitle").innerText,
        bodyHtml: document.getElementById("modalBody").innerHTML,
        onOk: this._currentModalOnOk,
        okText: document.getElementById("modalOk").innerText,
        okClass: document.getElementById("modalOk").className,
        hideCancel: document.getElementById("modalCancel").style.display === "none",
        cancelText: document.getElementById("modalCancel").innerText,
        headerHint: (document.getElementById("modalHeaderHint")?.innerText || ""),
        className: modalEl ? modalEl.className.replace(/^modal\s*/, "") : ""
      });
    }
    this._restoringModal = false;
    this._currentModalOnOk = onOk;

    const modal = document.querySelector(".modal");
    if (modal) modal.className = `modal${options.className ? " " + options.className : ""}`;
    document.getElementById("modalTitle").innerText = title;
    const hint = document.getElementById("modalHeaderHint");
    if (hint) {
      hint.innerText = options.headerHint || "";
      hint.style.display = options.headerHint ? "" : "none";
    }
    document.getElementById("modalBody").innerHTML = bodyHtml;
    document.querySelectorAll(".modal-extra-action").forEach(btn => btn.remove());
    const cancel = document.getElementById("modalCancel");
    if (cancel) {
      cancel.style.display = options.hideCancel ? "none" : "";
      cancel.innerText = options.cancelText || "取消";
      cancel.className = "btn btn-outline";
      cancel.onclick = () => this.closeModal();
    }
    const ok = document.getElementById("modalOk");
    if (!ok) { console.error("modalOk not found in DOM"); return; }
    ok.className = options.okClass || "btn";
    ok.innerText = okText;
    ok.onclick = () => {
      try {
        const keepOpen = onOk && onOk();
        if (!keepOpen) this.closeModal();
      } catch (e) {
        console.error("[showModal] onOk 异常：", e);
        alert("操作失败：" + (e.message || e));
      }
    };
    document.getElementById("modalMask").style.display = "flex";
    this.updateSelectPlaceholderState(document.getElementById("modalBody"));
  },

  showConfirm(message, onOk, options = {}) {
    const mask = document.getElementById("confirmMask");
    const box = mask?.querySelector(".confirm-box");
    const title = document.getElementById("confirmTitle");
    const msg = document.getElementById("confirmMessage");
    const desc = document.getElementById("confirmDesc");
    const cancel = document.getElementById("confirmCancel");
    const ok = document.getElementById("confirmOk");
    if (!mask || !title || !msg || !cancel || !ok) {
      console.warn("Confirm dialog is not available:", message);
      return;
    }
    if (box) box.className = `confirm-box${options.className ? " " + options.className : ""}`;
    title.innerText = options.title || "确认操作";
    msg.innerText = message || "";
    if (desc) {
      desc.innerText = options.description || "";
      desc.style.display = options.description ? "" : "none";
    }
    cancel.style.display = options.hideCancel ? "none" : "";
    cancel.innerText = options.cancelText || "取消";
    cancel.onclick = () => this.closeConfirm();
    ok.innerText = options.okText || "确认";
    ok.className = options.okClass || "btn";
    ok.onclick = () => {
      this.closeConfirm();
      if (typeof onOk === "function") onOk();
    };
    mask.style.display = "flex";
  },

  showAlert(message, options = {}) {
    this.showConfirm(message, null, {
      title: options.title || "提示",
      okText: options.okText || "确定",
      okClass: options.okClass || "btn",
      hideCancel: true,
      className: "alert-box"
    });
  },

  closeConfirm() {
    const mask = document.getElementById("confirmMask");
    if (mask) mask.style.display = "none";
    const box = mask?.querySelector(".confirm-box");
    if (box) box.className = "confirm-box";
  },

  closeModal() {
    // 模态框堆栈：有上一级则恢复
    if (this._modalStack.length > 0) {
      const prev = this._modalStack.pop();
      this._restoringModal = true;
      this.showModal(prev.title, prev.bodyHtml, prev.onOk, prev.okText, {
        okClass: prev.okClass || "btn",
        hideCancel: prev.hideCancel,
        cancelText: prev.cancelText,
        headerHint: prev.headerHint || "",
        className: prev.className || ""
      });
      return;
    }
    document.getElementById("modalMask").style.display = "none";
    const modal = document.querySelector(".modal");
    if (modal) modal.className = "modal";
    const hint = document.getElementById("modalHeaderHint");
    if (hint) {
      hint.innerText = "";
      hint.style.display = "none";
    }
  },

  // ---- 内联表单校验工具 ----
  // 清除当前模态框中所有校验标记
  clearFieldValidationMarks() {
    const modal = document.querySelector(".modal");
    if (!modal) return;
    modal.querySelectorAll(".is-invalid").forEach(el => el.classList.remove("is-invalid"));
    modal.querySelectorAll(".field-error").forEach(el => el.remove());
  },

  // 将指定元素标记为校验失败，在其所属 .form-group 中显示错误信息
  markFieldInvalid(el, message) {
    if (!el) return;
    el.classList.add("is-invalid");
    const group = el.closest(".form-group") || el.closest(".form-row") || el.parentElement;
    if (group && message && !group.querySelector(".field-error")) {
      group.insertAdjacentHTML("beforeend", `<div class="field-error">${Utils.esc(message)}</div>`);
    }
    const first = document.querySelector(".modal .is-invalid");
    first?.scrollIntoView({ block: "center", behavior: "smooth" });
  },

  // ---- 危险确认弹窗（DELETE 关键词二次验证） ----
  showDangerConfirm(descHtml, onConfirm, options = {}) {
    const confirmCode = options.confirmCode || "DELETE";
    const actionLabel = options.actionLabel || "删除";
    const body = `
      <div class="delete-confirm">
        ${descHtml}
        <label>请输入 <strong>${Utils.esc(confirmCode)}</strong> 确认${Utils.esc(actionLabel)}：</label>
        <input id="deleteKeywordInput" autocomplete="off" autofocus>
        <div id="deleteKeywordError" class="delete-confirm-error" style="display:none">请输入 ${Utils.esc(confirmCode)} 后才能继续。</div>
      </div>
    `;
    this.showModal(options.title || "危险操作确认", body, () => {
      const input = document.getElementById("deleteKeywordInput");
      const error = document.getElementById("deleteKeywordError");
      if ((input?.value || "") !== confirmCode) {
        if (error) error.style.display = "block";
        input?.focus();
        return true;
      }
      onConfirm?.();
    }, options.okText || "确认", {
      okClass: options.okClass || "btn btn-danger",
      hideCancel: false,
      cancelText: options.cancelText || "取消",
      className: options.className || ""
    });
    setTimeout(() => document.getElementById("deleteKeywordInput")?.focus(), 60);
  },

  updateSelectPlaceholderState(root = document) {
    const scope = root || document;
    scope.querySelectorAll?.("select").forEach(select => {
      const selected = select.options[select.selectedIndex];
      const isPlaceholder = !select.value || selected?.value === "";
      select.classList.toggle("placeholder-select", !!isPlaceholder);
    });
  },

  renderEmpty(msg) {
    document.getElementById("content").innerHTML = `<div class="card empty">${Utils.esc(msg)}</div>`;
  },

  // ---- 筛选 ----
  setProgressFilter(field, val) {
    if (!this.view.progressFilters) this.view.progressFilters = {};
    if (val === "" || val === null || val === undefined) delete this.view.progressFilters[field];
    else this.view.progressFilters[field] = val;
    this.renderPreserveScroll();
  },
  clearProgressFilters() {
    this.view.progressFilters = {};
    this.renderPreserveScroll();
  },
  setTaskFlowFilter(field, value) {
    if (!this.view.taskFlowFilters) this.view.taskFlowFilters = {};
    this.view.taskFlowFilters[field] = value;
    this.renderPreserveScroll();
  },
  setTaskFlowTextFilter(field, value) {
    if (!this.view.taskFlowFilters) this.view.taskFlowFilters = {};
    if (value === "" || value === null || value === undefined) {
      delete this.view.taskFlowFilters[field];
    } else {
      this.view.taskFlowFilters[field] = value;
    }
  },
  commitTaskFlowTextFilter(field, value) {
    if (!this.view.taskFlowFilters) this.view.taskFlowFilters = {};
    if (value === "" || value === null || value === undefined) {
      delete this.view.taskFlowFilters[field];
    } else {
      this.view.taskFlowFilters[field] = value;
    }
    clearTimeout(this._taskFlowTextFilterTimer);
    this._taskFlowTextFilterTimer = null;
    this.renderPreserveScroll();
  },
  handleTaskFlowTextFilterKeydown(event, field, value) {
    if (event.key === "Enter") {
      event.preventDefault();
      this.commitTaskFlowTextFilter(field, value);
    }
  },
  clearTaskFlowFilters() {
    this.view.taskFlowFilters = {};
    clearTimeout(this._taskFlowTextFilterTimer);
    this._taskFlowTextFilterTimer = null;
    this.renderPreserveScroll();
  },

  // ---- 日志展示 ----
  toggleSampleHistoryItem(button) {
    const item = button.closest(".sample-history-item");
    if (!item) return;
    const expanded = item.classList.toggle("is-expanded");
    button.setAttribute("aria-expanded", String(expanded));
  },

  logHtml(l, seq = "", seqPrefix = "") {
    const seqHtml = seq ? `<span class="log-seq">${Utils.esc(seqPrefix)}${Utils.esc(seq)}</span>` : "";
    const rawContent = String(l.reason || l.problemDescription || "").trim();
    const content = rawContent ? `<div class="task-log-text" title="${Utils.esc(rawContent)}">${this.linkSampleRefsInLogText(this.compactTaskLogText(rawContent), null)}</div>` : "";
    const actionTitle = l.action || l.source || "-";
    return `<div class="log-line">${seqHtml}<b>${Utils.esc(actionTitle)}</b>
      <div class="task-log-meta">${Utils.esc(new Date(l.time).toLocaleString("zh-CN"))} | 操作人：${Utils.esc(l.user || "-")} | 状态：${Utils.esc(l.from || "-")} → ${Utils.esc(l.to || "-")} | 测试项：${Utils.esc(l.testItem || "-")}</div>
      ${content}</div>`;
  },

  // ---- 任务日志 ----
  ensureTaskLogs(t) {
    if (t && !Array.isArray(t.logs)) t.logs = [];
    return t?.logs || [];
  },
  addTaskLog(t, action, ctx = {}) {
    if (!t) return;
    this.ensureTaskLogs(t);
    t.logs.push({
      id: Utils.id("tasklog_"),
      time: Utils.now(),
      action,
      user: ctx.user || t.owner || "未填写",
      reason: ctx.reason || "",
      detail: ctx.detail || "",
      detailLines: Array.isArray(ctx.detailLines) ? ctx.detailLines : [],
      fromStatus: ctx.fromStatus || "",
      toStatus: ctx.toStatus || t.status || ""
    });
  },
  logSampleRefToken(token) {
    const clean = String(token || "").trim().replace(/[，,、;；。]+$/, "");
    if (/^(SN|IMEI|主板SN)#/i.test(clean)) return clean;
    if (/^\d{12,18}$/.test(clean)) return `IMEI#${clean.slice(-4)}`;
    if (/^[A-Za-z0-9]{10,}$/.test(clean)) return `SN#${clean.slice(-4)}`;
    return clean;
  },
  compactTaskLogText(text) {
    const raw = String(text || "").trim();
    if (!raw) return "-";
    const converted = raw.replace(/(?:SN|IMEI|主板SN)#[A-Za-z0-9-]+|\b\d{12,18}\b|\b[A-Za-z0-9]{10,}\b/g, token => this.logSampleRefToken(token));
    const refs = [...converted.matchAll(/(?:SN|IMEI|主板SN)#[A-Za-z0-9-]+/g)].map(x => x[0]);
    const uniqueRefs = [...new Set(refs)];
    const hasLabeledSections = /(退出样机|新增样机|新加样机|移除样机|加入样机)/.test(converted);
    if (uniqueRefs.length >= 4 && !hasLabeledSections) {
      const label = converted.includes("清空") ? "已清空任务样机"
        : converted.includes("移除") ? "已移除样机"
        : converted.includes("销毁") ? "涉及销毁样机"
        : converted.includes("样机") ? "涉及样机"
        : "样机";
      const shown = uniqueRefs.slice(0, 6).join("、");
      return `${label}：${shown}${uniqueRefs.length > 6 ? ` 等 ${uniqueRefs.length} 台` : ""}`;
    }
    return converted.length > 96 ? `${converted.slice(0, 96)}...` : converted;
  },
  taskLogContentText(log) {
    const action = String(log?.action || "").trim();
    const reason = String(log?.reason || "").trim();
    const detail = String(log?.detail || "").trim();
    let text = detail && (
      detail.includes("样机") ||
      ["分配样机", "重新分配样机", "临时变更", "样机池档案销毁"].some(x => action.includes(x))
    ) ? detail : (reason || detail);
    if (action.includes("阻塞") && text && !text.startsWith("阻塞")) text = `阻塞：${text}`;
    return text;
  },
  taskLogDetailLines(log) {
    const action = String(log?.action || "").trim();
    if (Array.isArray(log?.detailLines) && log.detailLines.length) {
      return log.detailLines.map(x => String(x || "").trim()).filter(Boolean);
    }
    const text = this.taskLogContentText(log);
    if (action.includes("临时变更")) {
      return String(text || "")
        .split(/[；;\n]+/)
        .map(x => x.trim())
        .filter(Boolean);
    }
    return [String(text || "").trim()].filter(Boolean);
  },
  taskLogContentHtml(log) {
    const lines = this.taskLogDetailLines(log);
    if (!lines.length) return "";
    const action = String(log?.action || "").trim();
    const isTempChange = action.includes("临时变更");

    if (lines.length === 1 && !isTempChange) {
      const raw = lines[0];
      return `<div class="task-log-text" title="${Utils.esc(raw)}">${this.linkSampleRefsInLogText(this.compactTaskLogText(raw), log.taskContext || null)}</div>`;
    }

    return `<div class="task-log-text task-log-text-multiline">
      ${lines.map(line => {
        const idx = line.indexOf("：");
        if (idx > 0) {
          const label = line.slice(0, idx + 1);
          const value = line.slice(idx + 1);
          return `<div class="task-log-detail-line"><span class="task-log-detail-label">${Utils.esc(label)}</span><span class="task-log-detail-value">${this.linkSampleRefsInLogText(value, log.taskContext || null)}</span></div>`;
        }
        return `<div class="task-log-detail-line">${this.linkSampleRefsInLogText(line, log.taskContext || null)}</div>`;
      }).join("")}
    </div>`;
  },
  findLogSampleRefId(ref, task = null) {
    const code = String(ref || "").trim();
    if (!code) return "";
    const snapshots = task?.sampleSnapshots || {};
    const snapHit = Object.entries(snapshots).find(([, snap]) => String(snap?.code || "").trim() === code);
    if (snapHit) return snapHit[0];
    const suffix = code.includes("#") ? code.split("#").pop() : "";
    const candidates = this.allSamples().filter(s =>
      this.sampleDisplayCode(s) === code ||
      (suffix && [s.sn, s.imei, s.boardSn, s.sampleNo].some(v => String(v || "").trim().endsWith(suffix)))
    );
    if (!candidates.length) return "";
    const taskIds = new Set([
      ...(task?.sampleIds || []),
      ...(task?.removedSampleRecords || []).map(item => item?.sampleId).filter(Boolean)
    ]);
    return candidates.find(s => taskIds.has(s.id))?.id || "";
  },
  linkSampleRefsInLogText(text, task = null) {
    const str = String(text || "");
    const re = /(?:SN|IMEI|主板SN)#[A-Za-z0-9-]+/g;
    let html = "";
    let last = 0;
    for (const match of str.matchAll(re)) {
      const ref = match[0];
      html += Utils.esc(str.slice(last, match.index));
      const sampleId = this.findLogSampleRefId(ref, task);
      html += sampleId
        ? `<button type="button" class="sample-log-link" onclick="event.stopPropagation();app.openSampleReadonly('${Utils.esc(sampleId)}')">${Utils.esc(ref)}</button>`
        : `<span class="sample-log-ref-missing" title="样机档案不存在或已销毁">${Utils.esc(ref)}</span>`;
      last = match.index + ref.length;
    }
    html += Utils.esc(str.slice(last));
    return this.highlightTestResult(html);
  },

  highlightTestResult(html) {
    return String(html || "").replace(
      /\b(Pass|PASS|pass|Fail|FAIL|fail)\b(\s*[（(][^)）]*[)）])?/g,
      (match, result) => {
        const isPass = /^pass$/i.test(result);
        return `<b class="${isPass ? 'log-result-pass' : 'log-result-fail'}">${match}</b>`;
      }
    );
  },
  taskLogHtml(log, seq = "", task = null) {
    const logWithContext = { ...log, taskContext: task };
    const seqHtml = seq ? `<span class="log-seq">#${Utils.esc(seq)}</span>` : "";
    return `<div class="task-log-item">
      ${seqHtml}<b>${Utils.esc(log.action || "-")}</b>
      <div class="task-log-meta">${Utils.esc(new Date(log.time).toLocaleString("zh-CN"))} | 操作人：${Utils.esc(log.user || "-")} | 状态：${Utils.esc(log.fromStatus || "-")} → ${Utils.esc(log.toStatus || "-")}</div>
      ${this.taskLogContentHtml(logWithContext)}
    </div>`;
  },
  showTaskLogs(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    const logs = this.ensureTaskLogs(t);
    const taskLabel = [p?.name, s?.name, t.testItem].filter(Boolean).join(" - ");
    const items = logs.slice().reverse().map((log, idx) => this.taskLogHtml(log, String(logs.length - idx), t)).join("") || '<div class="empty">暂无操作日志。</div>';
    this.showModal(`任务日志 · ${Utils.esc(taskLabel)}`, `<div class="task-log-list">${items}</div>`, () => false, "关闭");
  },

  // ---- 通用 ----
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
  },

  sampleDisplayCode(sample) {
    if (!sample) return "-";
    const parts = [sample.sampleNo, sample.sn, sample.imei, sample.boardSn].filter(Boolean);
    return parts[0] || "-";
  },

  openSampleReadonly(sampleId) {
    this.view.selectedSampleId = sampleId;
    this.view.module = "samples";
    this.render();
    setTimeout(() => {
      const el = document.querySelector(`.sample-card[data-sample-id="${sampleId}"]`);
      el?.click?.();
    }, 50);
  }

};