/* ========================================
   数字治理平台 V7 - 主渲染模块
   ======================================== */

Object.assign(app, {

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

  openSampleReadonly(sampleId) {
    this.view.selectedSampleId = sampleId;
    this.view.module = "samples";
    this.render();
    setTimeout(() => {
      const el = document.querySelector(`.sample-card[data-sample-id="${sampleId}"]`);
      el?.click?.();
    }, 50);
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
  }

});
