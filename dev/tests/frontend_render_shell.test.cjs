const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..");
const frontendRoot = path.join(root, "frontend");

class FakeText {
  constructor(text) {
    this.textContent = String(text || "");
    this.children = [];
  }
}

class FakeClassList {
  constructor(owner) {
    this.owner = owner;
    this.values = new Set();
  }

  toggle(name, enabled) {
    if (enabled) this.values.add(name);
    else this.values.delete(name);
    this.owner.className = [...this.values].join(" ");
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName || "").toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.type = "";
    this.title = "";
    this.innerText = "";
    this._textContent = "";
  }

  append(...items) {
    items.flat().forEach(item => {
      if (item === null || item === undefined) return;
      this.children.push(typeof item === "string" ? new FakeText(item) : item);
    });
  }

  replaceChildren(...items) {
    this.children = [];
    this._textContent = "";
    this.innerText = "";
    this.append(...items);
  }

  set textContent(value) {
    this._textContent = String(value || "");
    this.children = [];
  }

  get textContent() {
    return this._textContent + this.innerText + (this.innerHTML || "") + this.children.map(child => child.textContent || "").join("");
  }
}

function collect(node, predicate, out = []) {
  if (predicate(node)) out.push(node);
  (node.children || []).forEach(child => collect(child, predicate, out));
  return out;
}

const nodes = {};
["content", "nav", "navTools", "pageTitle", "contextText", "actionArea", "sidebar", "sidebarToggle", "pageFooter"].forEach(id => {
  nodes[id] = new FakeElement("div");
});

const storage = new Map();
const context = {
  console,
  requestAnimationFrame: fn => fn(),
  localStorage: {
    getItem: key => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
  },
  document: {
    createElement: tag => new FakeElement(tag),
    createTextNode: text => new FakeText(text),
    getElementById: id => nodes[id] || null,
    querySelectorAll: () => [],
  },
  app: {
    version: "V7",
    _modules: {},
    data: {
      projects: [],
      sampleLibrary: { categories: [], logs: [] },
    },
    view: {
      module: "home",
      selectedProjectId: null,
      selectedCategoryId: null,
      collapsed: {},
    },
    registerModule(name, members) {
      this._modules[name] = Object.keys(members || {});
      Object.keys(members || {}).forEach(key => { this[key] = members[key]; });
      return this;
    },
    replaceHtml(target, html) {
      if (target) target.innerHTML = String(html || "");
      return target;
    },
  },
};
context.globalThis = context;
vm.createContext(context);

function loadScript(relativePath, trailer = "") {
  const code = fs.readFileSync(path.join(frontendRoot, relativePath), "utf8");
  vm.runInContext(`${code}\n${trailer}`, context, { filename: relativePath });
}

loadScript("js/utils.js", "globalThis.Utils = Utils;");
loadScript("js/app.data.js");
loadScript("js/app.render.js");
loadScript("js/workspace/02-home.js");

const { app } = context;

app.data.projects = [
  { id: "p1", name: "项目 <A>", stages: [{ id: "st1", name: "阶段1" }] },
];
app.data.sampleLibrary.categories = [
  { id: "cat1", name: "样机池 <B>", sampleCount: 12, samples: [] },
];
app.patchViewState({ module: "home", selectedProjectId: "p1", selectedCategoryId: "cat1" });

app.renderHome();
assert.equal(nodes.content.children[0].className, "home-shell");
assert.ok(nodes.content.textContent.includes("1 个项目"));
assert.ok(nodes.content.textContent.includes("1 个样机池 · 12 台样机"));
assert.deepEqual(
  collect(nodes.content, node => !!node.dataset?.appAction).map(node => node.dataset.module).sort(),
  ["devices", "projects", "samples"]
);

app.renderNav();
assert.ok(nodes.nav.textContent.includes("项目 <A>"));
assert.ok(nodes.nav.textContent.includes("样机池 <B>"));
assert.deepEqual(
  collect(nodes.navTools, node => !!node.dataset?.appAction).map(node => node.dataset.appAction).sort(),
  ["bundle-export", "bundle-import"]
);

app.patchViewState({ module: "samples", selectedCategoryId: "cat1" });
app.renderHeader();
assert.ok(nodes.pageTitle.textContent.includes("首页"));
assert.ok(nodes.pageTitle.textContent.includes("样机档案池"));
assert.ok(nodes.pageTitle.textContent.includes("样机池 <B>"));

app.toggleSidebar();
assert.equal(storage.get("digital_governance_sidebar_collapsed"), "1");
assert.equal(nodes.sidebar.classList.contains("collapsed"), true);
assert.equal(nodes.sidebarToggle.innerText, "▶");

app.renderEmpty("空数据 <safe>");
assert.equal(nodes.content.children[0].className, "card empty");
assert.ok(nodes.content.textContent.includes("空数据 <safe>"));

app.workspaceMembersHtml = () => '<div class="project-members-section">成员 <safe></div>';
app.workspaceLocationsHtml = () => '<div class="project-locations-section">位置 <safe></div>';
app.workspaceTaskFlowHtml = () => '<div class="task-flow-shell">任务 <safe></div>';
app.sectionToggleTriangle = id => `<button data-app-action="toggle-section" data-id="${id}"></button>`;
app.isCollapsed = () => false;
const workspaceNodes = app.projectWorkspacePageNodes(
  { id: "p1", name: "项目 <A>", members: [], locations: [] },
  { id: "st1", name: "阶段 <B>" },
  {
    stageCards: '<div class="stage-summary-card">阶段 <B></div>',
    addStageCard: '<div class="card add-card">新增阶段</div>',
    sampleOwnerCounts: new Map(),
    sortMode: false,
  }
);
assert.equal(workspaceNodes.length, 2);
assert.equal(workspaceNodes[0].className, "card project-config-card");
assert.equal(workspaceNodes[1].className, "card workspace-section section-green");
assert.ok(workspaceNodes[0].textContent.includes("项目配置工作台"));
assert.ok(workspaceNodes[0].textContent.includes("阶段 <B>"));
assert.ok(workspaceNodes[0].textContent.includes("成员 <safe>"));
assert.ok(workspaceNodes[0].textContent.includes("位置 <safe>"));
assert.ok(workspaceNodes[1].textContent.includes("任务 <safe>"));
assert.ok(collect(workspaceNodes[0], node => node.dataset?.appAction === "stage-sort-toggle").length === 1);

console.log("frontend render shell tests passed");
