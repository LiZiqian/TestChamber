/* ========================================
   数字治理平台 V7 - 核心框架
   ======================================== */

const app = {
  version: "7.1.0",
  data: null,
  serverRevision: 0,
  serverUpdatedAt: null,
  serverOnline: false,
  _saveInFlight: false,
  _saveQueued: false,
  _queuedRemark: "",
  _saveTimer: null,
  _baseData: null,
  _statePartial: false,
  _projectDetailPromises: {},
  _sampleCategoryDetailPromises: {},
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
    sampleProblemFilter: "",
    sampleOwnerFilter: "",
    sampleBorrowerFilter: "",
    samplePage: 1,
    samplePageSize: 100,
    collapsed: {},
    progressFilters: {},
    stageStrategyFilters: { includeKeyword: "", excludeKeyword: "" },
    taskFlowFilters: {},
    taskFlowPage: 1,
    taskFlowPageSize: 100,
    sidebarCollapsed: false
  },

  constants: {
    sampleStatuses: ["测试中", "闲置", "在位等待", "已退库", "取走分析"],
    taskStatuses: ["待下发", "进行中", "阻塞中", "正常完成", "异常终止"],
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
      const obj = await this.fetchBootstrapState();
      this.data = obj.data || this.emptyData();
      this.serverRevision = obj.revision || 0;
      this.serverUpdatedAt = obj.updated_at || null;
      this.serverOnline = true;
      this._statePartial = obj.partial !== false;
      this._baseData = this.cloneData(this.data);
    } catch (e) {
      console.error("服务器数据读取失败：", e);
      this.serverOnline = false;
      this.data = this.emptyData();
      this._statePartial = false;
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
    if (this._normalizedChanged && !this._statePartial) {
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

};
