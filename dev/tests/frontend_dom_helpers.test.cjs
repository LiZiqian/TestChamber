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

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName || "").toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.className = "";
    this.type = "";
    this.title = "";
    this.value = "";
    this._textContent = "";
  }

  append(...items) {
    items.flat().forEach(item => {
      if (item === null || item === undefined) return;
      const node = typeof item === "string" ? new FakeText(item) : item;
      node.parentElement = this;
      this.children.push(node);
    });
  }

  addEventListener(event, handler) {
    if (!this._listeners) this._listeners = {};
    this._listeners[event] = handler;
  }

  replaceWith(node) {
    const siblings = this.parentElement?.children || [];
    const idx = siblings.indexOf(this);
    if (idx >= 0) {
      node.parentElement = this.parentElement;
      siblings.splice(idx, 1, node);
    }
  }

  set textContent(value) {
    this._textContent = String(value || "");
    this.children = [];
  }

  get textContent() {
    return this._textContent + this.children.map(child => child.textContent || "").join("");
  }

  set innerHTML(value) {
    this._innerHTML = String(value || "");
    const row = new FakeElement("div");
    row.className = "sample-initial-result-row";
    if (this.content) {
      this.content.children = [row];
      row.parentElement = this.content;
    } else {
      this.children = [row];
      row.parentElement = this;
    }
  }

  get innerHTML() {
    return this._innerHTML || "";
  }

  get firstElementChild() {
    return this.children.find(child => child instanceof FakeElement) || null;
  }
}

function collect(node, predicate, out = []) {
  if (predicate(node)) out.push(node);
  (node.children || []).forEach(child => collect(child, predicate, out));
  return out;
}

const context = {
  console,
  window: {},
  document: {
    createElement: tag => {
      const el = new FakeElement(tag);
      if (tag === "template") el.content = new FakeElement("fragment");
      return el;
    },
  },
  app: {
    version: "V7",
    _modules: {},
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
loadScript("js/app.logs.js");
loadScript("js/samples/03-detail-fields.js");
loadScript("js/samples/04-photos.js");
loadScript("js/samples/05-problems.js");
loadScript("js/workspace/06-sample-picker.js");
loadScript("js/workspace/04-stage.js");
loadScript("js/workspace/07-task-config.js");
loadScript("js/workspace/09-task-result.js");
loadScript("js/workspace/10-dropdown-issue.js");

const { app } = context;

const taskLogList = app.taskLogListNode([{
  time: "2026-06-04T01:02:03Z",
  action: "开始 <task>",
  user: "张三/001",
  fromStatus: "待下发",
  toStatus: "进行中",
}], null);
assert.equal(taskLogList.className, "task-log-list");
assert.equal(collect(taskLogList, node => node.className === "task-log-item").length, 1);
assert.equal(collect(taskLogList, node => node.className === "log-seq")[0].textContent, "#1");
assert.ok(taskLogList.textContent.includes("开始 <task>"));
assert.ok(taskLogList.textContent.includes("张三/001"));
const emptyTaskLogList = app.taskLogListNode([], null);
assert.equal(collect(emptyTaskLogList, node => node.className === "empty")[0].textContent, "暂无操作日志。");

const mask = app.samplePhotoPreviewNode({ name: "front <raw>.jpg" }, "/asset/front.jpg");
assert.equal(mask.className, "sample-photo-preview-mask");
assert.equal(mask.dataset.appAction, "sample-photo-preview-close");
assert.equal(mask.dataset.selfOnly, "1");
assert.ok(mask.textContent.includes("front <raw>.jpg"));
assert.equal(collect(mask, node => node.tagName === "IMG")[0].src, "/asset/front.jpg");
assert.equal(collect(mask, node => node.tagName === "IMG")[0].alt, "front <raw>.jpg");

const renameInput = app.samplePhotoRenameInputNode("front <raw>.jpg");
assert.equal(renameInput.className, "sample-photo-name-input");
assert.equal(renameInput.value, "front <raw>.jpg");

const [renameLabel, renameButton] = app.samplePhotoNameRowNodes("sample<1>", "photo&2", "front <raw>.jpg");
assert.equal(renameLabel.tagName, "B");
assert.equal(renameLabel.textContent, "front <raw>.jpg");
assert.equal(renameButton.className, "sample-photo-rename-icon");
assert.equal(renameButton.dataset.appAction, "sample-photo-rename");
assert.equal(renameButton.dataset.id, "sample<1>");
assert.equal(renameButton.dataset.photoId, "photo&2");
assert.equal(renameButton.dataset.stopPropagation, "1");

const row = app.sampleProblemRowNode("problems", { description: "黑点", source: "手动补录", taskLabel: "外观" }, { isLast: true });
assert.equal(row.className, "sample-initial-result-row");
const rowInputs = collect(row, node => node.tagName === "INPUT");
assert.equal(rowInputs.length, 3);
assert.equal(rowInputs[0].className, "sample-problem-desc");
assert.equal(rowInputs[0].value, "黑点");
assert.equal(rowInputs[1].value, "手动补录");
assert.equal(rowInputs[2].value, "外观");
const addProblemButton = collect(row, node => node.className === "sample-result-btn add")[0];
assert.equal(addProblemButton.dataset.appAction, "sample-problem-add");
assert.equal(addProblemButton.dataset.id, "problems");

const hint = new FakeElement("div");
app.setTaskSampleLimitHintContent(hint, "不足：需 2 台。", "1/2");
assert.equal(hint.textContent, "不足：需 2 台。1/2");
assert.equal(collect(hint, node => node.className === "sample-limit-count")[0].textContent, "1/2");

const emptyProblem = app.taskResultProblemEmptyNode();
assert.equal(emptyProblem.className, "task-result-problem-empty");
assert.equal(emptyProblem.textContent, "当前档案暂无问题记录。");

const chip = app.taskResultPhotoChipNode("sample<1>", { id: "photo&2", name: "证据 <1>", url: "/api/photo/2" });
assert.equal(chip.className, "task-result-photo-chip");
assert.equal(chip.dataset.appAction, "task-result-photo-preview");
assert.equal(chip.dataset.id, "sample<1>");
assert.equal(chip.dataset.photoId, "photo&2");
assert.equal(collect(chip, node => node.tagName === "IMG")[0].src, "/api/photo/2");
assert.equal(collect(chip, node => node.tagName === "IMG")[0].alt, "证据 <1>");
assert.ok(chip.textContent.includes("证据 <1>"));

const [dropdownHead, dropdownOptions] = app.caseDropdownShellNodes("搜索 <类别>");
assert.equal(dropdownHead.className, "case-dropdown-head");
assert.equal(collect(dropdownHead, node => node.tagName === "INPUT")[0].placeholder, "搜索 <类别>");
assert.equal(collect(dropdownHead, node => node.tagName === "INPUT")[0].dataset.appAction, "case-dropdown-search");
assert.equal(dropdownOptions.id, "caseDropdownOptions");
assert.equal(dropdownOptions.className, "case-dropdown-options");
const emptyCase = app.caseDropdownEmptyNode("无 <匹配>");
assert.equal(emptyCase.className, "case-empty");
assert.equal(emptyCase.textContent, "无 <匹配>");
const categoryOption = app.caseDropdownOptionNode({ category: "射频 <A>", count: 3 }, 2, "category");
assert.equal(categoryOption.className, "case-option");
assert.equal(categoryOption.dataset.caseOptionIndex, "2");
assert.ok(categoryOption.textContent.includes("射频 <A>"));
assert.ok(categoryOption.textContent.includes("3 条用例"));
const itemOption = app.caseDropdownOptionNode({ category: "射频 <A>", item: "通话 & 数据" }, 4, "item", "");
assert.equal(itemOption.className, "case-option item-mode");
assert.equal(itemOption.dataset.caseOptionIndex, "4");
assert.ok(itemOption.textContent.includes("通话 & 数据"));
assert.ok(itemOption.textContent.includes("射频 <A>"));

const inlineSkuRow = app.inlineSkuRowNode("A <1>", 2);
assert.equal(inlineSkuRow.className, "inline-sku-row");
assert.equal(collect(inlineSkuRow, node => node.className === "idx")[0].textContent, "#3");
assert.equal(collect(inlineSkuRow, node => node.className === "inline-sku-name-input")[0].value, "A <1>");
assert.equal(collect(inlineSkuRow, node => node.className === "inline-sku-name-input")[0].dataset.appAction, "inline-stage-skus");
assert.equal(collect(inlineSkuRow, node => node.className === "icon-btn")[0].dataset.appAction, "inline-sku-remove");
const skuRow = app.skuRowNode("B & 2", 5);
assert.equal(skuRow.className, "sku-row");
assert.equal(collect(skuRow, node => node.className === "idx")[0].textContent, "#5");
assert.equal(collect(skuRow, node => node.className === "sku-name-input")[0].value, "B & 2");
assert.equal(collect(skuRow, node => node.className === "icon-btn")[0].dataset.appAction, "sku-input-remove");
const titlebar = app.taskConfigTitlebarNode(null, { category: "可靠性 <A>", testItem: "跌落 & 振动" }, null);
assert.equal(titlebar.className, "task-config-titlebar");
assert.ok(titlebar.textContent.includes("任务配置"));
assert.ok(titlebar.textContent.includes("计划任务：可靠性 <A> -> 跌落 & 振动"));
assert.equal(collect(titlebar, node => node.className === "task-config-title-context")[0].textContent, "计划任务：可靠性 <A> -> 跌落 & 振动");

app.projectRecords = () => [
  { locations: ["实验室 <A>", "实验室 <A>", "仓库"] },
  { locations: [""] },
];
const locationHtml = app.sampleLocationInputHtml("loc", "实验室 <A>");
assert.ok(locationHtml.includes("value=\"实验室 &lt;A&gt;\""));
assert.equal((locationHtml.match(/<option value=/g) || []).length, 2);

app.sampleCategoryRecords = () => [
  { name: "Pool & A", samples: [{ id: "other", sampleNo: "NO-1", sn: "SN-1" }] },
];
app.sampleIsReassembled = () => true;
app.sampleDisplayCode = sample => sample.sampleNo || sample.id;
const reassemblyHtml = app.sampleReassemblySourcesHtml({ id: "current", sn: "SN-1", imei: "", boardSn: "" });
assert.ok(reassemblyHtml.includes("Pool &amp; A"));
assert.ok(reassemblyHtml.includes("匹配SN"));

console.log("frontend DOM helper tests passed");
