/* ========================================
   数字治理平台 V7 - 数据工具模块
   ======================================== */

app.registerModule("app.data", {

  emptyData() {
    return {
      version: this.version,
      currentProjectId: null,
      currentStageId: null,
      eventSchema: "sample_events_v2",
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
    if (this.data.eventSchema !== "sample_events_v2") {
      this.data.eventSchema = "sample_events_v2";
      if (this.data.sampleLibrary) this.data.sampleLibrary.logs = [];
      this._normalizedChanged = true;
    }
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
          let normalizedTaskStatus = t.status;
          if (normalizedTaskStatus === "完成") normalizedTaskStatus = "正常完成";
          if (normalizedTaskStatus === "已完成") {
            normalizedTaskStatus = t.completionType || "正常完成";
            t.completed = true;
          }
          if (normalizedTaskStatus !== t.status) this._normalizedChanged = true;
          this.repairTaskStatus(t, this.taskFlowStatus({ ...t, status: normalizedTaskStatus }), { markChanged: true });
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
      if (Array.isArray(s.logs)) {
        delete s.logs;
        this._normalizedChanged = true;
      }
      this.repairSampleStatus(s, s.status || "闲置", { markChanged: true });
      if (typeof s.imei === "undefined") s.imei = "";
      if (typeof s.boardSn === "undefined") s.boardSn = "";
      const normalizedReassembled = Utils.parseSampleReassembledFlag(s.isReassembled);
      if (s.isReassembled !== normalizedReassembled) {
        s.isReassembled = normalizedReassembled;
        this._normalizedChanged = true;
      }
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
  dataSnapshot() {
    return this.cloneData(this.data);
  },

  restoreDataSnapshot(snapshot) {
    this.data = this.cloneData(snapshot);
    return this.data;
  },

  patchViewState(values = {}) {
    this.view = { ...(this.view || {}), ...(values || {}) };
    return this.view;
  },

  viewModule() {
    return this.view?.module || "home";
  },

  selectedProjectId() {
    return this.view?.selectedProjectId || null;
  },

  selectedStageId() {
    return this.view?.selectedStageId || null;
  },

  selectedCategoryId() {
    return this.view?.selectedCategoryId || null;
  },

  stageStrategyId() {
    return this.view?.stageStrategyId || null;
  },

  sampleCategoryRecords() {
    if (!this.data) this.data = this.emptyData();
    if (!this.data.sampleLibrary) this.data.sampleLibrary = { categories: [], logs: [] };
    if (!Array.isArray(this.data.sampleLibrary.categories)) this.data.sampleLibrary.categories = [];
    return this.data.sampleLibrary.categories;
  },

  currentSampleCategory() {
    const id = String(this.selectedCategoryId() || "");
    return this.sampleCategoryRecords().find(category => String(category.id || "") === id) || null;
  },

  samplePoolPageState(fallbackPageSize = 100) {
    return {
      page: Math.max(1, Number.parseInt(this.view?.samplePage, 10) || 1),
      pageSize: this.boundedViewPageSize(this.view?.samplePageSize, fallbackPageSize),
      filters: {
        keyword: this.view?.sampleKeyword || "",
        status: this.view?.sampleStatusFilter || "",
        problemState: this.view?.sampleProblemFilter || "",
        owner: this.view?.sampleOwnerFilter || "",
        borrower: this.view?.sampleBorrowerFilter || ""
      }
    };
  },

  setSamplePoolPageState(page) {
    return this.patchViewState({ samplePage: Math.max(1, Number.parseInt(page, 10) || 1) });
  },

  setSamplePoolPageSizeState(size, fallback = 100) {
    return this.patchViewState({
      samplePageSize: this.boundedViewPageSize(size, fallback),
      samplePage: 1
    });
  },

  setSamplePoolFilterState(name, value, { resetPage = true } = {}) {
    const map = {
      keyword: "sampleKeyword",
      status: "sampleStatusFilter",
      problemState: "sampleProblemFilter",
      owner: "sampleOwnerFilter",
      borrower: "sampleBorrowerFilter"
    };
    const key = map[name];
    if (!key) return null;
    return this.patchViewState({
      [key]: value || "",
      ...(resetPage ? { samplePage: 1 } : {})
    });
  },

  resetSamplePoolFiltersState() {
    return this.patchViewState({
      sampleKeyword: "",
      sampleStatusFilter: "",
      sampleProblemFilter: "",
      sampleOwnerFilter: "",
      sampleBorrowerFilter: "",
      samplePage: 1
    });
  },

  isCurrentSampleCategoryPage(categoryId) {
    return this.viewModule() === "samples"
      && String(this.selectedCategoryId() || "") === String(categoryId || "");
  },

  homeMetrics() {
    const projects = this.projectRecords();
    const categories = this.sampleCategoryRecords();
    return {
      projectCount: projects.length,
      samplePoolCount: categories.length,
      sampleCount: categories.reduce((sum, category) => (
        sum + (Number(category.sampleCount) || (category.samples || []).length || 0)
      ), 0),
    };
  },

  navExpandedState() {
    if (!this.view) this.view = {};
    if (!this.view._navExpanded) this.view._navExpanded = { projects: true, samples: true };
    return this.view._navExpanded;
  },

  toggleNavExpanded(id) {
    const expanded = this.navExpandedState();
    expanded[id] = !expanded[id];
    return expanded;
  },

  isNavItemActive(id) {
    const module = this.viewModule();
    if (id === "projects" && module === "projectWorkspace") return true;
    return module === id;
  },

  isProjectNavActive(projectId) {
    return this.viewModule() === "projectWorkspace"
      && String(this.selectedProjectId() || "") === String(projectId || "");
  },

  isSampleCategoryNavActive(categoryId) {
    return this.viewModule() === "samples"
      && String(this.selectedCategoryId() || "") === String(categoryId || "");
  },

  navFingerprintData() {
    const expanded = this.navExpandedState();
    return [
      this.viewModule(),
      this.selectedProjectId(),
      this.selectedCategoryId(),
      !!expanded.projects,
      !!expanded.samples,
      this.projectRecords().map(project => [project.id, project.name]),
      this.sampleCategoryRecords().map(category => [category.id, category.name]),
    ];
  },

  projectRecords() {
    if (!this.data) this.data = this.emptyData();
    if (!Array.isArray(this.data.projects)) this.data.projects = [];
    return this.data.projects;
  },

  findProjectRecord(projectId) {
    const id = String(projectId || "");
    return this.projectRecords().find(project => String(project.id || "") === id) || null;
  },

  projectInitialStageId(project) {
    return project?.stages?.[0]?.id || null;
  },

  isProjectSelected(projectId) {
    return String(projectId || "") === String(this.view?.selectedProjectId || "");
  },

  projectStateNameExists(name, excludeId = "") {
    const normalized = String(name || "").trim().toLowerCase();
    if (!normalized) return false;
    return this.projectRecords().some(project =>
      String(project.id || "") !== String(excludeId || "")
      && String(project.name || "").trim().toLowerCase() === normalized
    );
  },

  appendProjectRecord(project) {
    if (!project?.id) return null;
    this.projectRecords().push(project);
    return project;
  },

  removeProjectRecord(projectId) {
    const id = String(projectId || "");
    this.data.projects = this.projectRecords().filter(project => String(project.id || "") !== id);
    return this.data.projects;
  },

  selectFirstProjectState(overrides = {}) {
    const project = this.projectRecords()[0] || null;
    return this.patchViewState({
      selectedProjectId: project?.id || null,
      selectedStageId: this.projectInitialStageId(project),
      ...overrides,
    });
  },

  selectProjectState(projectId, overrides = {}) {
    return this.patchViewState({
      selectedProjectId: projectId || null,
      selectedStageId: Object.prototype.hasOwnProperty.call(overrides, "selectedStageId") ? overrides.selectedStageId : this.view?.selectedStageId,
      ...overrides,
    });
  },

  selectProjectWorkspaceState(projectId, { selectedStageId = null } = {}) {
    return this.patchViewState({
      selectedProjectId: projectId || null,
      selectedStageId,
      stageStrategyId: null,
      module: "projectWorkspace",
    });
  },

  selectSampleCategoryState(categoryId) {
    return this.patchViewState({
      selectedCategoryId: categoryId || null,
      samplePage: 1,
      module: "samples",
    });
  },

  navigateModuleState(module) {
    const next = { module: module || "home" };
    if (next.module !== "projectWorkspace") next.stageStrategyId = null;
    if (next.module === "samples") {
      next.selectedCategoryId = null;
      next.samplePage = 1;
    }
    if (next.module === "home") next.selectedCategoryId = null;
    return this.patchViewState(next);
  },

  clearStageStrategyState() {
    return this.patchViewState({ stageStrategyId: null });
  },

  sidebarCollapsed() {
    return !!this.view?.sidebarCollapsed;
  },

  setSidebarCollapsed(collapsed) {
    return this.patchViewState({ sidebarCollapsed: !!collapsed });
  },

  toggleSidebarCollapsed() {
    return this.setSidebarCollapsed(!this.sidebarCollapsed());
  },

  isSectionCollapsed(sectionId) {
    return !!(this.view?.collapsed && this.view.collapsed[sectionId]);
  },

  toggleSectionState(sectionId) {
    if (!this.view) this.view = {};
    if (!this.view.collapsed) this.view.collapsed = {};
    this.view.collapsed[sectionId] = !this.view.collapsed[sectionId];
    return this.view.collapsed[sectionId];
  },

  ensureViewMap(key, fallback = {}) {
    if (!this.view) this.view = {};
    if (!this.view[key] || typeof this.view[key] !== "object") this.view[key] = { ...fallback };
    return this.view[key];
  },

  setViewMapValue(key, field, value, { removeEmpty = true, fallback = {} } = {}) {
    const target = this.ensureViewMap(key, fallback);
    if (removeEmpty && (value === "" || value === null || value === undefined)) {
      delete target[field];
    } else {
      target[field] = value;
    }
    return target;
  },

  resetViewMap(key, value = {}) {
    if (!this.view) this.view = {};
    this.view[key] = { ...value };
    return this.view[key];
  },

  resetTaskFlowPage() {
    return this.patchViewState({ taskFlowPage: 1 });
  },

  boundedViewPageSize(value, fallback = 100) {
    const n = Number.parseInt(value, 10);
    if (!Number.isFinite(n) || n <= 0) return fallback;
    return Math.min(500, Math.max(20, n));
  },

  taskFlowPageState(fallbackPageSize = 100) {
    return {
      page: Math.max(1, Number.parseInt(this.view?.taskFlowPage, 10) || 1),
      pageSize: this.boundedViewPageSize(this.view?.taskFlowPageSize, fallbackPageSize),
      filters: this.ensureViewMap("taskFlowFilters")
    };
  },

  setTaskFlowPageState(page) {
    return this.patchViewState({ taskFlowPage: Math.max(1, Number.parseInt(page, 10) || 1) });
  },

  setTaskFlowPageSizeState(size, fallback = 100) {
    return this.patchViewState({
      taskFlowPageSize: this.boundedViewPageSize(size, fallback),
      taskFlowPage: 1
    });
  },

  isCurrentProjectWorkspaceStage(stageId) {
    return this.viewModule() === "projectWorkspace"
      && String(this.selectedStageId() || "") === String(stageId || "");
  },

  ensureWorkspaceStageSelection(project) {
    if (!project?.stages?.length) return null;
    const selectedId = this.selectedStageId();
    if (!selectedId || !project.stages.some(stage => String(stage.id || "") === String(selectedId))) {
      this.patchViewState({ selectedStageId: project.stages[0].id });
    }
    return this.selectedStageId();
  },

  stageSortMode() {
    return !!this.view?.stageSortMode;
  },

  setStageSortModeState(enabled) {
    return this.patchViewState({ stageSortMode: !!enabled });
  },

  sampleEventRecords() {
    if (!this.data) this.data = this.emptyData();
    if (!this.data.sampleLibrary) this.data.sampleLibrary = { categories: [], logs: [] };
    if (!Array.isArray(this.data.sampleLibrary.logs)) this.data.sampleLibrary.logs = [];
    return this.data.sampleLibrary.logs;
  },

  currentProject() {
    return this.findProjectRecord(this.view?.selectedProjectId) || this.projectRecords()[0] || null;
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
    if (!sample) return false;
    if (sample.hasProblem === true || sample.hasProblem === 1 || sample.hasProblem === "1") return true;
    return this.sampleProblemRecords(sample).length > 0;
  },

  sampleIsReassembled(sample) {
    return Utils.parseSampleReassembledFlag(sample?.isReassembled);
  },

  sampleEffectiveStatus(sample) {
    return this.normalizeSampleStatusValue(sample?.status);
  },

  normalizeSampleStatusValue(status) {
    const raw = String(status || "").trim();
    const statusMap = {
      "已分配": "在位等待",
      "进入测试任务": "测试中",
      "已归还": "闲置",
      "借出": "取走分析",
      "已借出": "取走分析",
      "待维修": "闲置",
      "报废": "闲置",
      "故障": "闲置"
    };
    const normalized = statusMap[raw] || raw || "闲置";
    return this.constants.sampleStatuses.includes(normalized) ? normalized : "闲置";
  },

  repairSampleStatus(sample, nextStatus, ctx = {}) {
    if (!sample) return "";
    const normalized = this.normalizeSampleStatusValue(nextStatus);
    if (sample.status !== normalized) {
      sample.status = normalized;
      if (ctx.markChanged !== false) this._normalizedChanged = true;
    }
    return normalized;
  },

  clearSampleOccupancy(sample, ctx = {}) {
    if (!sample) return false;
    const changed = !!(sample.currentProjectId || sample.currentStageId || sample.currentTaskId || sample.currentTestItem);
    sample.currentProjectId = null;
    sample.currentStageId = null;
    sample.currentTaskId = null;
    sample.currentTestItem = "";
    if (changed && ctx.markChanged !== false) this._normalizedChanged = true;
    return changed;
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
  createSampleEventLog(sample, fromStatus, toStatus, flowStatus, ctx = {}) {
    return {
      id: Utils.id("event_"),
      time: Utils.now(),
      eventType: "sample_status",
      sampleId: sample.id,
      sampleNo: sample.sampleNo,
      action: ctx.source || "未知入口",
      source: ctx.source || "未知入口",
      user: ctx.user || "未填写",
      from: fromStatus,
      to: toStatus,
      flowStatus,
      reason: ctx.reason || "",
      detail: ctx.detail || "",
      projectId: ctx.projectId || sample.currentProjectId,
      stageId: ctx.stageId || sample.currentStageId,
      projectName: ctx.projectName || this.projectName(ctx.projectId || sample.currentProjectId),
      stageName: ctx.stageName || this.stageName(ctx.projectId || sample.currentProjectId, ctx.stageId || sample.currentStageId),
      taskId: ctx.taskId || sample.currentTaskId,
      testItem: ctx.testItem || sample.currentTestItem,
      faultMarked: !!ctx.faultMarked,
      problemDescription: String(ctx.problemDescription || "").trim(),
      photoIds: Array.isArray(ctx.photoIds) ? ctx.photoIds : [],
      photos: Array.isArray(ctx.photos) ? ctx.photos : []
    };
  },

  changeSampleStatus(sampleId, newStatus, ctx = {}) {
    newStatus = this.normalizeSampleStatusValue(newStatus);
    const found = this.findSample(sampleId);
    if (!found) return;
    const s = found.sample, old = this.sampleEffectiveStatus(s);
    if (old === newStatus && !ctx.forceLog && !ctx.taskId && !ctx.receiver) return;
    this.repairSampleStatus(s, newStatus, { markChanged: false });
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
    const log = this.createSampleEventLog(s, old, displayStatus, newStatus, { ...ctx, faultMarked: isFault, problemDescription });
    if (!Array.isArray(this.data.sampleLibrary.logs)) this.data.sampleLibrary.logs = [];
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
        this.clearSampleOccupancy(sample, { markChanged: true });
        if (["测试中", "在位等待"].includes(sample.status)) {
          this.repairSampleStatus(sample, "闲置", { markChanged: true });
        }
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
    if (!task) return false;
    if (task.archived) return true;
    const flow = this.taskFlowStatus(task);
    return flow === "正常完成" || flow === "异常终止";
  },

  isTaskExecuted(task) {
    if (!task) return false;
    const flow = this.taskFlowStatus(task);
    if (flow === "正常完成" || flow === "异常终止") return true;
    return flow === "进行中" || flow === "阻塞中";
  },

  isSampleUsedByAnotherOpenTask(sampleId, excludeTaskId = "") {
    const usages = this.activeTaskUsagesForSample(sampleId, excludeTaskId);
    return usages.length > 0;
  }

});
