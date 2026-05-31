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