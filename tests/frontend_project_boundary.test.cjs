const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

class FakeText {
  constructor(text) {
    this.nodeType = 3;
    this.textContent = String(text || "");
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName || "").toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.className = "";
    this.type = "";
    this.title = "";
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
    this.append(...items);
  }

  set textContent(value) {
    this._textContent = String(value || "");
    this.children = [];
  }

  get textContent() {
    return this._textContent + this.children.map(child => child.textContent || "").join("");
  }
}

function collect(node, predicate, out = []) {
  if (predicate(node)) out.push(node);
  (node.children || []).forEach(child => collect(child, predicate, out));
  return out;
}

const content = new FakeElement("div");
const context = {
  console,
  document: {
    createElement: tag => new FakeElement(tag),
    createTextNode: text => new FakeText(text),
    getElementById: id => (id === "content" ? content : null),
  },
  app: {
    version: "V7",
    _modules: {},
    data: {
      projects: [],
      sampleLibrary: { categories: [], logs: [] },
    },
    view: {
      selectedProjectId: null,
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
  const code = fs.readFileSync(path.join(root, relativePath), "utf8");
  vm.runInContext(`${code}\n${trailer}`, context, { filename: relativePath });
}

loadScript("js/utils.js", "globalThis.Utils = Utils;");
loadScript("js/app.data.js");
loadScript("js/projects.js");

const { app } = context;

app.data.projects = [
  { id: "p1", name: "Alpha <script>", code: "A-001", owner: "张三/001", stages: [{ id: "s1" }] },
  { id: "p2", name: "Beta", code: "", owner: "", stageCount: 4, stages: [] },
];
app.patchViewState({ selectedProjectId: "p2" });

app.renderProjects();

const grid = content.children[0];
assert.equal(grid.className, "grid project-grid");
assert.equal(grid.children.length, 3);
assert.ok(grid.textContent.includes("项目：Alpha <script>"));
assert.ok(grid.textContent.includes("A-001"));
assert.ok(grid.textContent.includes("张三/001"));
assert.ok(grid.textContent.includes("新建项目"));

const actions = collect(grid, node => !!node.dataset?.appAction).map(node => node.dataset.appAction).sort();
assert.deepEqual(actions, [
  "project-add",
  "project-delete",
  "project-delete",
  "project-edit",
  "project-edit",
  "project-select",
  "project-select",
]);

const selected = grid.children[1];
assert.equal(selected.style.borderColor, "var(--primary)");
assert.equal(selected.style.borderWidth, "2px");

app.renderProjectLoading({ name: "大型项目" });
assert.equal(content.children[0].className, "card empty");
assert.ok(content.textContent.includes("正在加载 大型项目..."));

console.log("frontend project boundary tests passed");
