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
  }

};