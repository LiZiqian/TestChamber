/* ========================================
   数字治理平台 V7 - 核心框架
   ======================================== */

const app = {
  version: "V7",
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
        <h1 class="home-title">终端硬件测试数字治理平台 <span>V7</span></h1>
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