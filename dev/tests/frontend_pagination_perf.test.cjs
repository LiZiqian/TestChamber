const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..");
const frontendRoot = path.join(root, "frontend");

function fakeNodeText(item) {
  if (item === null || item === undefined) return "";
  if (typeof item === "string") return item;
  return [
    item.textContent || "",
    item.innerText || "",
    item.innerHTML || "",
    ...(item.children || []).map(fakeNodeText),
  ].join("");
}

function createFakeElement(tag = "div") {
  return {
    tagName: String(tag).toUpperCase(),
    className: "",
    dataset: {},
    style: {},
    attributes: {},
    children: [],
    innerHTML: "",
    innerText: "",
    textContent: "",
    append(...items) {
      this.children.push(...items);
    },
    replaceChildren(...items) {
      this.children = [...items];
      this.innerHTML = items.map(fakeNodeText).join("");
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
  };
}

function attachSamplePageNodes(nodes, categoryId) {
  nodes.samplePageShell = createFakeElement("div");
  nodes.samplePageShell.dataset.categoryId = categoryId;
  nodes.samplePagerTop = createFakeElement("div");
  nodes.samplePagerBottom = createFakeElement("div");
  nodes.samplePoolCount = createFakeElement("div");
  nodes.samplePoolGrid = createFakeElement("div");
}

function createContext() {
  const nodes = {
    content: createFakeElement("div"),
    pageFooter: createFakeElement("div"),
  };
  const context = {
    console,
    URLSearchParams,
    alert: () => {},
    window: {},
    document: {
      getElementById(id) {
        return nodes[id] || null;
      },
      createElement: createFakeElement,
      createDocumentFragment() {
        return createFakeElement("#fragment");
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
      htmlFragment(html) {
        const fragment = createFakeElement("#fragment");
        fragment.innerHTML = String(html || "");
        return fragment;
      },
      constants: {
        sampleStatuses: ["测试中", "闲置", "在位等待", "已退库", "取走分析"],
        taskStatuses: ["待下发", "进行中", "阻塞中", "正常完成", "异常终止"],
      },
      data: {
        projects: [],
        sampleLibrary: { categories: [], logs: [] },
      },
      view: {
        module: "samples",
        selectedCategoryId: "",
        sampleKeyword: "",
        sampleStatusFilter: "",
        sampleProblemFilter: "",
        sampleReassemblyFilter: "",
        sampleOwnerFilter: "",
        sampleBorrowerFilter: "",
        samplePage: 1,
        samplePageSize: 100,
        taskFlowFilters: {},
        taskFlowPage: 1,
        taskFlowPageSize: 100,
      },
    },
    nodes,
  };
  context.globalThis = context;
  vm.createContext(context);
  return context;
}

function loadScript(context, relativePath, trailer = "") {
  const code = fs.readFileSync(path.join(frontendRoot, relativePath), "utf8");
  vm.runInContext(`${code}\n${trailer}`, context, { filename: relativePath });
}

function loadFrontend() {
  const context = createContext();
  loadScript(context, "js/utils.js", "globalThis.Utils = Utils;");
  loadScript(context, "js/app.data.js");
  loadScript(context, "js/app.server.js");
  loadScript(context, "js/import-export-bundle.js");
  loadScript(context, "js/workspace/01-shared.js");
  loadScript(context, "js/workspace/05-task-table.js");
  loadScript(context, "js/samples/01-pool.js");
  loadScript(context, "js/samples/02-import-export.js");
  loadScript(context, "js/samples/03-detail-fields.js");
  loadScript(context, "js/samples/04-photos.js");
  loadScript(context, "js/samples/06-history.js");
  return context;
}

function flushPromises() {
  return Promise.resolve().then(() => Promise.resolve());
}

(async () => {
  {
    const context = loadFrontend();
    const { app } = context;
    const sample = {
      id: "sample_fault_idle",
      sn: "TPC000101",
      imei: "861000030001011",
      boardSn: "MBTPC000101",
      status: "闲置",
      sourceStageName: "EVT",
      sourceSkuName: "12+512-BOE",
      problemRecords: [{ id: "problem_1", description: "不开机" }],
    };

    assert.equal(app.sampleEffectiveStatus(sample), "闲置");
    assert.equal(app.sampleHasProblem(sample), true);
    const html = app.sampleCardHtml(sample);
    assert.ok(html.includes("data-usage-status=\"闲置\""));
    assert.ok(html.includes("data-quality-status=\"fault\""));
    assert.ok(html.includes("data-reassembly-status=\"normal\""));
    assert.ok(html.includes("非重组"));
    assert.ok(html.includes("有故障"));
    assert.ok(html.includes("不开机"));

    const reassembledHtml = app.sampleCardHtml({ ...sample, id: "sample_reassembled", isReassembled: true });
    assert.ok(reassembledHtml.includes("data-reassembly-status=\"reassembled\""));
    assert.ok(reassembledHtml.includes("重组"));
  }

  {
    const context = loadFrontend();
    const { app, Utils } = context;
    const parsed = Utils.parseSampleImportCsv([
      "SN,IMEI,主板SN,是否重组样机,阶段",
      "SN-R,IMEI-R,MB-R,是,EVT",
      "SN-N,IMEI-N,MB-N,否,DVT",
    ].join("\n"));
    assert.equal(parsed.error, null);
    assert.equal(parsed.rows[0].isReassembled, true);
    assert.equal(parsed.rows[1].isReassembled, false);

    const predecessor = { id: "sample_a", sn: "SN-A", imei: "IMEI-A", boardSn: "MB-A", status: "闲置" };
    const reassembled = { id: "sample_r", sn: "SN-A", imei: "IMEI-R", boardSn: "MB-R", isReassembled: true, status: "闲置" };
    const cat = { id: "cat_a", name: "池A", samples: [predecessor, reassembled] };
    app.data.sampleLibrary.categories = [cat];

    assert.equal(app.findDuplicateSampleInCategory(cat, { sn: "SN-A", isReassembled: true }), null);
    assert.equal(app.findDuplicateSampleInCategory(cat, { sn: "SN-A", isReassembled: false })?.id, "sample_a");

    app.data.sampleLibrary.categories = [{
      id: "cat_r",
      name: "重组池",
      samples: [{ id: "sample_r_only", sn: "SN-LATE", isReassembled: true, status: "闲置" }],
    }];
    assert.equal(app.findDuplicateSampleGlobally({ sn: "SN-LATE", isReassembled: false }), null);
  }

  {
    const context = loadFrontend();
    const { app } = context;
    const r = { id: "sample_r", sn: "SN-A", imei: "IMEI-B", boardSn: "MB-C", isReassembled: true };
    app.data.sampleLibrary.categories = [{
      id: "cat_src",
      name: "前身池",
      samples: [
        { id: "sample_a", sn: "SN-A" },
        { id: "sample_b", imei: "IMEI-B" },
        { id: "sample_c", boardSn: "MB-C" },
      ],
    }, {
      id: "cat_r",
      name: "重组池",
      samples: [r],
    }];

    const groups = app.sampleReassemblySources(r);
    assert.equal(groups.find(g => g.key === "sn").matches[0].sample.id, "sample_a");
    assert.equal(groups.find(g => g.key === "imei").matches[0].sample.id, "sample_b");
    assert.equal(groups.find(g => g.key === "boardSn").matches[0].sample.id, "sample_c");
    const html = app.sampleReassemblySourcesHtml(r);
    assert.ok(html.includes("SN来源"));
    assert.ok(html.includes("IMEI来源"));
    assert.ok(html.includes("主板SN来源"));
    assert.ok(html.includes("前身池"));
  }

  {
    const context = loadFrontend();
    const { app } = context;
    app.updateServerStatus = () => {};
    app.ensureFullStateLoaded = async () => { throw new Error("/api/state should not be loaded for sample destroy impact"); };
    const loadedCategories = [];
    const loadedProjects = [];
    app.ensureSampleCategoryLoaded = async (id) => {
      loadedCategories.push(id);
      return { id };
    };
    app.ensureProjectLoaded = async (id, options) => {
      loadedProjects.push([id, options.includeTasks]);
      return { id };
    };
    let impactRequests = 0;
    context.fetch = async (url) => {
      impactRequests++;
      assert.equal(String(url), "/api/sample-destroy-impact?sampleId=sample_destroy");
      return { ok: true, status: 200, json: async () => ({
        ok: true,
        sampleId: "sample_destroy",
        sampleCategoryIds: ["cat_destroy", "cat_keep"],
        projectIds: ["project_destroy"],
      }) };
    };

    const scope = await app.ensureSampleDestroyImpactScope({ sampleId: "sample_destroy" });

    assert.equal(scope.sampleId, "sample_destroy");
    assert.equal(impactRequests, 1);
    assert.deepEqual(loadedCategories, ["cat_destroy", "cat_keep"]);
    assert.deepEqual(loadedProjects, [["project_destroy", true]]);
  }

  {
    const context = loadFrontend();
    const { app } = context;
    let fetches = 0;
    context.fetch = async (url, options = {}) => {
      fetches++;
      assert.equal(String(url), "/api/sample-identity-check");
      assert.equal(options.method, "POST");
      const payload = JSON.parse(options.body);
      assert.equal(payload.categoryId, "cat_a");
      assert.equal(payload.samples[0].sn, "SN-A");
      assert.ok(!String(options.body).includes("/api/state"));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          results: [{
            index: 0,
            hasConflict: true,
            conflict: {
              index: 0,
              scope: "global",
              categoryName: "池B",
              conflictId: "SN-A",
              incomingField: "sn",
              existingLabel: "SN",
              sample: { id: "sample_b", code: "SN#SN-A", sn: "SN-A" },
            },
          }],
          conflicts: [],
          count: 1,
        }),
      };
    };

    const result = await app.checkSampleIdentityConflicts([{ index: 0, sn: "SN-A" }], { categoryId: "cat_a" });
    const validation = app.sampleIdentityConflictValidation(result.results[0].conflict, "SN-A", "", "", "sample");
    assert.equal(fetches, 1);
    assert.equal(validation.fieldId, "sampleSn");
    assert.ok(validation.msg.includes("池B"));
  }

  {
    const context = loadFrontend();
    const { app } = context;
    app.data.sampleLibrary.categories = [{ id: "cat_import", name: "导入池", samples: [] }];
    app.ensureFullStateLoaded = async () => { throw new Error("/api/state should not be loaded before sample import duplicate check"); };
    let identityChecks = 0;
    app.checkSampleIdentityConflicts = async (samples, { categoryId }) => {
      identityChecks++;
      assert.equal(categoryId, "cat_import");
      assert.equal(samples.length, 3);
      return {
        results: [
          { index: 0, hasConflict: false, conflict: null },
          { index: 1, hasConflict: true, conflict: { index: 1, scope: "category" } },
          { index: 2, hasConflict: true, conflict: { index: 2, scope: "global" } },
        ],
      };
    };
    let committedSamples = [];
    app.commitSampleCategoryMutation = async (category, options) => {
      assert.equal(category.id, "cat_import");
      committedSamples = options.samples;
      return true;
    };
    const csv = [
      "SN,IMEI,主板SN,是否重组样机,阶段",
      "SN-OK,IMEI-OK,MB-OK,否,EVT",
      "SN-DUP,,MB-DUP,否,EVT",
      "SN-GLOBAL,,MB-GLOBAL,否,EVT",
    ].join("\n");
    context.FileReader = class {
      addEventListener(event, handler) {
        if (event === "load") this._loadHandler = handler;
      }
      readAsText() {
        this.result = csv;
        return Promise.resolve().then(() => this._loadHandler && this._loadHandler());
      }
    };
    context.document.createElement = tag => {
      assert.equal(tag, "input");
      return {
        files: [{ name: "samples.csv" }],
        addEventListener(event, handler) {
          if (event === "change") this._changeHandler = handler;
        },
        click() {
          this._changeHandler({ target: this });
        },
      };
    };

    await app.importSampleBatch("cat_import");
    await flushPromises();
    await flushPromises();

    assert.equal(identityChecks, 1);
    assert.equal(committedSamples.length, 1);
    assert.equal(committedSamples[0].sn, "SN-OK");
  }

  {
    const context = loadFrontend();
    const { app } = context;
    let fetches = 0;
    context.fetch = async url => {
      fetches++;
      const text = String(url);
      assert.ok(text.startsWith("/api/samples/sample_1/history?"));
      assert.ok(text.includes("page=2"));
      assert.ok(text.includes("pageSize=20"));
      assert.ok(!text.includes("/api/state"));
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, sampleId: "sample_1", page: 2, pageSize: 20, total: 21, totalPages: 2, items: [] }),
      };
    };
    const result = await app.fetchSampleHistory("sample_1", { page: 2, pageSize: 20 });
    assert.equal(fetches, 1);
    assert.equal(result.page, 2);
  }

  {
    const context = loadFrontend();
    const { app } = context;
    app.data.projects = new Proxy([], {
      get() {
        throw new Error("sample history render must not scan local projects");
      },
    });
    app._sampleHistoryCache = {
      sample_1: {
        page: 1,
        pageSize: 20,
        total: 1,
        totalPages: 1,
        items: [{
          task: { id: "task_1", owner: "张三/001" },
          projectName: "项目A",
          stageName: "EVT",
          testItem: "跌落测试",
          logs: [],
          status: "正常完成",
          result: "不通过",
          date: "2026-06-03",
          taskSampleCount: 1,
          faultMarked: true,
          problems: ["不开机"],
          resultPhotos: [],
        }],
      },
    };
    app.logHtml = () => "<div>log</div>";
    const html = app.sampleTestHistoryHtml("sample_1");
    assert.ok(html.includes("跌落测试"));
    assert.ok(html.includes("项目A"));
    assert.ok(html.includes("不开机"));
  }

  {
    const context = loadFrontend();
    const { app } = context;
    let fetches = 0;
    context.fetch = async (url) => {
      fetches++;
      const text = String(url);
      assert.ok(text.startsWith("/api/task-sample-candidates?"));
      assert.ok(text.includes("taskId=task_1"));
      assert.ok(text.includes("selectedIds=sample_a%2Csample_b"));
      assert.ok(text.includes("page=2"));
      assert.ok(!text.includes("/api/state"));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          page: 2,
          pageSize: 50,
          total: 70,
          totalPages: 2,
          items: [{ id: "sample_c", status: "闲置", selectable: true }],
          selectedItems: [{ id: "sample_a", status: "在位等待", selectable: true }],
          categories: [],
        }),
      };
    };

    const result = await app.fetchTaskSampleCandidates({
      taskId: "task_1",
      selectedIds: ["sample_a", "sample_b"],
      page: 2,
      pageSize: 50,
    });

    assert.equal(fetches, 1);
    assert.equal(result.page, 2);
    assert.equal(result.items[0].id, "sample_c");
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    app._samplePagePrefetchDisabled = true;
    app.data.sampleLibrary.categories = [{
      id: "cat_perf",
      name: "池C",
      sampleCount: 1000,
      samples: Array.from({ length: 1000 }, (_, idx) => ({
        id: `sample_${idx + 1}`,
        sn: `TPC${String(idx + 1).padStart(6, "0")}`,
        status: "闲置",
      })),
    }];
    app.view.selectedCategoryId = "cat_perf";
    app.view.samplePage = 8;
    let fetchCalls = 0;
    app.fetchSamplePage = () => {
      fetchCalls++;
      return new Promise(() => {});
    };
    app.sampleEventLogsForSample = () => {
      throw new Error("sample event logs should not be scanned on a sample page cache miss");
    };

    app.renderSamples();

    assert.equal(fetchCalls, 1);
    assert.ok(nodes.content.innerHTML.includes("正在加载第 8 页样机"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    app._samplePagePrefetchDisabled = true;
    const cat = { id: "cat_cached", name: "池C", sampleCount: 1000, samples: [] };
    app.data.sampleLibrary.categories = [cat];
    app.view.selectedCategoryId = "cat_cached";
    app.view.samplePage = 2;
    app.view.samplePageSize = 100;
    app.view.sampleReassemblyFilter = "reassembled";
    const params = app.samplePageQueryParams(cat);
    assert.equal(params.reassembled, "reassembled");
    const toolbarText = fakeNodeText(app.samplePageToolbarNode(cat, { stats: {}, total: 0 }, app.samplePoolPageState(100).filters));
    assert.ok(toolbarText.includes("全部重组状态"));
    assert.ok(toolbarText.includes("非重组"));
    const key = app.samplePageCacheKey(cat, params);
    app.setSamplePageCache({
      key,
      filterKey: app.samplePageFilterKey(cat, params),
      categoryId: cat.id,
      page: 2,
      pageSize: 100,
      total: 1000,
      totalPages: 10,
      stats: { totalInCategory: 1000 },
      items: [{ id: "sample_cached", sn: "TPC000200", status: "闲置" }],
    });
    let fetchCalls = 0;
    app.fetchSamplePage = () => {
      fetchCalls++;
      return Promise.resolve({ ok: true, items: [] });
    };

    app.renderSamples();

    assert.equal(fetchCalls, 0);
    assert.ok(nodes.content.innerHTML.includes("SN #PC000200"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    app._samplePagePrefetchDisabled = true;
    const cat = { id: "cat_resolve", name: "池C", sampleCount: 1000, samples: [] };
    app.data.sampleLibrary.categories = [cat];
    app.view.selectedCategoryId = "cat_resolve";
    app.view.samplePage = 3;
    app.fetchSamplePage = () => Promise.resolve({
      page: 3,
      pageSize: 100,
      total: 1000,
      totalPages: 10,
      stats: { totalInCategory: 1000, statusCounts: { "闲置": 1000 } },
      category: { id: cat.id, name: cat.name },
      items: [{ id: "sample_loaded", sn: "TPC000300", status: "闲置" }],
    });

    app.renderSamples();
    assert.ok(nodes.content.innerHTML.includes("正在加载第 3 页样机"));
    await flushPromises();
    assert.ok(nodes.content.innerHTML.includes("SN #PC000300"));
  }

  {
    const context = loadFrontend();
    const { app } = context;
    app.view.module = "projectWorkspace";
    app.view.taskFlowFilters = { resultKeyword: "fail" };
    app.view.taskFlowPage = 2;
    app.fetchStageTasksPage = () => new Promise(() => {});
    app.sectionToggleTriangle = () => "";
    app.taskResultSearchText = () => {
      throw new Error("task result search should not run on a task page cache miss");
    };
    const stage = {
      id: "stage_perf",
      skuNames: ["A"],
      progress: [],
      tasks: Array.from({ length: 200 }, (_, idx) => ({
        id: `task_${idx + 1}`,
        progressId: `progress_${idx + 1}`,
        status: "待下发",
        skuIndex: 1,
        category: "drop",
        testItem: `test_${idx + 1}`,
        sampleIds: [],
      })),
    };
    const html = app.workspaceTaskFlowHtml({ id: "project_perf", name: "项目" }, stage);
    assert.ok(html.includes("正在加载服务器分页数据"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    nodes.taskFlowShell = { dataset: { stageId: "stage_local" }, innerHTML: "" };
    app.view.module = "projectWorkspace";
    app.view.selectedStageId = "stage_local";
    app.view.taskFlowPage = 1;
    app.view.taskFlowPageSize = 50;
    app.sectionToggleTriangle = () => "";
    app.taskIssueSummaryHtml = () => "<span>-</span>";
    app.taskIssueRecordHtml = () => "<span>-</span>";
    app.taskFlowActionsHtml = () => "";
    app.ensureTaskLogs = () => [];
    app.updateSelectPlaceholderState = () => {};
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderPreserveScroll = () => { fullRenders++; };
    const project = { id: "project_local", name: "项目", stages: [] };
    const stage = {
      id: "stage_local",
      name: "阶段",
      skuNames: ["SKU1"],
      progress: [],
      tasks: [{ id: "task_local", status: "待下发", skuIndex: 1, category: "老类别", testItem: "旧任务", sampleIds: [] }],
    };
    project.stages.push(stage);
    app.data.projects = [project];
    let pageFetches = 0;
    app.fetchStageTasksPage = async (stageId, params) => {
      pageFetches++;
      assert.equal(stageId, "stage_local");
      assert.equal(params.pageSize, 50);
      return {
        page: 1,
        pageSize: 50,
        total: 1,
        totalPages: 1,
        stats: { totalInStage: 1, statusCounts: { "进行中": 1 }, ownerNames: ["张三"] },
        rows: [{ progress: null, task: { id: "task_local", status: "进行中", skuIndex: 1, category: "射频", testItem: "吞吐测试", owner: "张三/001", sampleIds: [] } }],
      };
    };

    const refreshed = await app.refreshTaskListAfterMutation(project, stage, { render: true });

    assert.equal(refreshed, true);
    assert.equal(pageFetches, 1);
    assert.equal(fullRenders, 0);
    assert.ok(nodes.taskFlowShell.innerHTML.includes("吞吐测试"));
    assert.ok(nodes.taskFlowShell.innerHTML.includes("进行中"));
    assert.equal(stage.tasks[0].testItem, "吞吐测试");
    assert.equal(stage.statusCounts["进行中"], 1);
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    attachSamplePageNodes(nodes, "cat_local");
    app._samplePagePrefetchDisabled = true;
    app.view.module = "samples";
    app.view.selectedCategoryId = "cat_local";
    app.view.samplePage = 1;
    app.view.samplePageSize = 50;
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderSamples = () => { fullRenders++; };
    app.data.sampleLibrary.categories = [{
      id: "cat_local",
      name: "池A",
      sampleCount: 1,
      samples: [{ id: "sample_local", sn: "OLD000001", status: "闲置" }],
    }];
    let pageFetches = 0;
    app.fetchSamplePage = async (categoryId, params) => {
      pageFetches++;
      assert.equal(categoryId, "cat_local");
      assert.equal(params.pageSize, 50);
      return {
        page: 1,
        pageSize: 50,
        total: 1,
        totalPages: 1,
        stats: { totalInCategory: 1, statusCounts: { "测试中": 1 }, problemCounts: { ok: 1, fault: 0 } },
        category: { id: "cat_local", name: "池A" },
        items: [{ id: "sample_local", sn: "NEW000123", status: "测试中" }],
      };
    };

    const refreshed = await app.refreshSampleListAfterMutation({ categoryId: "cat_local" }, { render: true });

    assert.equal(refreshed, true);
    assert.equal(pageFetches, 1);
    assert.equal(fullRenders, 0);
    assert.ok(nodes.samplePoolGrid.innerHTML.includes("SN #EW000123"));
    assert.ok(nodes.samplePoolGrid.innerHTML.includes("测试中"));
    assert.equal(nodes.samplePoolCount.innerText, "显示 1 / 1 台");
    assert.equal(app.data.sampleLibrary.categories[0].samples[0].status, "测试中");
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    nodes.taskFlowShell = { dataset: { stageId: "stage_commit" }, innerHTML: "" };
    app.view.module = "projectWorkspace";
    app.view.selectedStageId = "stage_commit";
    app.sectionToggleTriangle = () => "";
    app.taskIssueSummaryHtml = () => "<span>-</span>";
    app.taskIssueRecordHtml = () => "<span>-</span>";
    app.taskFlowActionsHtml = () => "";
    app.ensureTaskLogs = () => [];
    app.updateSelectPlaceholderState = () => {};
    app.updateServerStatus = () => {};
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderPreserveScroll = () => { fullRenders++; };
    app.reloadFromServer = async () => { throw new Error("/api/state should not be used after task mutation"); };
    const task = { id: "task_commit", status: "进行中", skuIndex: 1, category: "可靠性", testItem: "跌落", owner: "张三/001", sampleIds: [] };
    const stage = { id: "stage_commit", name: "阶段", skuNames: ["SKU1"], progress: [], tasks: [task] };
    const project = { id: "project_commit", name: "项目", stages: [stage] };
    app.data.projects = [project];
    app.serverRevision = 1;
    const taskParams = app.taskFlowQueryParams(stage);
    const taskKey = app.taskFlowCacheKey(stage, taskParams);
    app._taskFlowPageCache = {
      key: taskKey,
      stageId: stage.id,
      page: 1,
      pageSize: 100,
      total: 1,
      totalPages: 1,
      stats: { totalInStage: 1, statusCounts: { "进行中": 1 }, ownerNames: ["张三"] },
      rows: [{ progress: null, task }],
    };
    let mutationFetches = 0;
    let pageFetches = 0;
    context.fetch = async (url) => {
      mutationFetches++;
      assert.ok(String(url).startsWith("/api/tasks/task_commit/mutation"));
      return { ok: true, status: 200, json: async () => ({
        ok: true,
        revision: 2,
        updated_at: "2026-06-03T10:00:00",
        affected: {
          summaryVersion: 1,
          taskIds: ["task_commit"],
          tasks: [{ ...task, projectId: project.id, stageId: stage.id }],
          tasksTruncated: false,
        },
      }) };
    };
    app.fetchStageTasksPage = async () => {
      pageFetches++;
      throw new Error("current task page should be patched from affected payload");
    };

    const saved = await app.commitTaskMutation(project, stage, task, { action: "start_task", remark: "开始测试", user: "张三/001" });

    assert.equal(saved, true);
    assert.equal(mutationFetches, 1);
    assert.equal(pageFetches, 0);
    assert.equal(fullRenders, 0);
    assert.equal(app.serverRevision, 2);
    assert.ok(nodes.taskFlowShell.innerHTML.includes("跌落"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    nodes.taskFlowShell = { dataset: { stageId: "stage_batch" }, innerHTML: "" };
    app.view.module = "projectWorkspace";
    app.view.selectedStageId = "stage_batch";
    app.sectionToggleTriangle = () => "";
    app.taskIssueSummaryHtml = () => "<span>-</span>";
    app.taskIssueRecordHtml = () => "<span>-</span>";
    app.taskFlowActionsHtml = () => "";
    app.ensureTaskLogs = () => [];
    app.updateSelectPlaceholderState = () => {};
    app.updateServerStatus = () => {};
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderPreserveScroll = () => { fullRenders++; };
    const tasks = [{ id: "task_batch", status: "待下发", skuIndex: 1, category: "射频", testItem: "批量新增", sampleIds: [] }];
    const stage = { id: "stage_batch", name: "阶段", skuNames: ["SKU1"], progress: [], tasks };
    const project = { id: "project_batch", name: "项目", stages: [stage] };
    app.data.projects = [project];
    app.serverRevision = 1;
    let mutationFetches = 0;
    let pageFetches = 0;
    context.fetch = async (url) => {
      mutationFetches++;
      assert.ok(String(url).startsWith("/api/stages/stage_batch/tasks/batch"));
      return { ok: true, status: 200, json: async () => ({ ok: true, revision: 2, updated_at: "2026-06-03T10:00:00" }) };
    };
    app.fetchStageTasksPage = async () => {
      pageFetches++;
      return {
        page: 1,
        pageSize: 100,
        total: 1,
        totalPages: 1,
        stats: { totalInStage: 1, statusCounts: { "待下发": 1 }, ownerNames: [] },
        rows: [{ progress: null, task: tasks[0] }],
      };
    };

    const saved = await app.commitTaskBatchMutation(project, stage, tasks, { action: "create_tasks", remark: "批量新增", user: "管理员" });

    assert.equal(saved, true);
    assert.equal(mutationFetches, 1);
    assert.equal(pageFetches, 1);
    assert.equal(fullRenders, 0);
    assert.ok(nodes.taskFlowShell.innerHTML.includes("批量新增"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    attachSamplePageNodes(nodes, "cat_commit");
    app._samplePagePrefetchDisabled = true;
    app.view.module = "samples";
    app.view.selectedCategoryId = "cat_commit";
    app.updateServerStatus = () => {};
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderSamples = () => { fullRenders++; };
    app.reloadFromServer = async () => { throw new Error("/api/state should not be used after sample mutation"); };
    const sample = { id: "sample_commit", categoryId: "cat_commit", sn: "SN123456", status: "测试中" };
    app.data.sampleLibrary.categories = [{ id: "cat_commit", name: "池A", sampleCount: 1, samples: [sample] }];
    app.serverRevision = 1;
    const sampleCategory = app.data.sampleLibrary.categories[0];
    const sampleParams = app.samplePageQueryParams(sampleCategory);
    const sampleKey = app.samplePageCacheKey(sampleCategory, sampleParams);
    app.setSamplePageCache({
      key: sampleKey,
      filterKey: app.samplePageFilterKey(sampleCategory, sampleParams),
      categoryId: sampleCategory.id,
      page: 1,
      pageSize: 100,
      total: 1,
      totalPages: 1,
      stats: { totalInCategory: 1, statusCounts: { "测试中": 1 }, problemCounts: { ok: 1, fault: 0 } },
      category: { id: "cat_commit", name: "池A" },
      items: [sample],
    });
    let mutationFetches = 0;
    let pageFetches = 0;
    context.fetch = async (url) => {
      mutationFetches++;
      assert.ok(String(url).startsWith("/api/samples/sample_commit/mutation"));
      return { ok: true, status: 200, json: async () => ({
        ok: true,
        revision: 2,
        updated_at: "2026-06-03T10:00:00",
        affected: {
          summaryVersion: 1,
          sampleCategoryIds: ["cat_commit"],
          sampleIds: ["sample_commit"],
          sampleCategorySummaries: [{
            id: "cat_commit",
            name: "池A",
            sampleCount: 1,
            statusCounts: { "测试中": 1 },
            problemCounts: { ok: 1, fault: 0 },
          }],
          samples: [sample],
          samplesTruncated: false,
        },
      }) };
    };
    app.fetchSamplePage = async () => {
      pageFetches++;
      throw new Error("current sample page should be patched from affected payload");
    };

    const saved = await app.commitSampleMutation(sample, { action: "sample_detail_update", remark: "样机详情编辑", user: "管理员" });

    assert.equal(saved, true);
    assert.equal(mutationFetches, 1);
    assert.equal(pageFetches, 0);
    assert.equal(fullRenders, 0);
    assert.equal(app.serverRevision, 2);
    assert.ok(nodes.samplePoolGrid.innerHTML.includes("SN #SN123456"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    attachSamplePageNodes(nodes, "cat_batch");
    app._samplePagePrefetchDisabled = true;
    app.view.module = "samples";
    app.view.selectedCategoryId = "cat_batch";
    app.updateServerStatus = () => {};
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderSamples = () => { fullRenders++; };
    const sample = { id: "sample_batch", categoryId: "cat_batch", sn: "SN654321", status: "闲置" };
    const category = { id: "cat_batch", name: "池B", sampleCount: 1, samples: [sample] };
    app.data.sampleLibrary.categories = [category];
    app.serverRevision = 1;
    let mutationFetches = 0;
    let pageFetches = 0;
    context.fetch = async (url) => {
      mutationFetches++;
      assert.ok(String(url).startsWith("/api/sample-categories/cat_batch/mutation"));
      return { ok: true, status: 200, json: async () => ({ ok: true, revision: 2, updated_at: "2026-06-03T10:00:00" }) };
    };
    app.fetchSamplePage = async () => {
      pageFetches++;
      return {
        page: 1,
        pageSize: 100,
        total: 1,
        totalPages: 1,
        stats: { totalInCategory: 1, statusCounts: { "闲置": 1 }, problemCounts: { ok: 1, fault: 0 } },
        category: { id: "cat_batch", name: "池B" },
        items: [sample],
      };
    };

    const saved = await app.commitSampleCategoryMutation(category, {
      action: "create_sample",
      remark: "新增样机",
      user: "管理员",
      createSamples: true,
      samples: [sample],
    });

    assert.equal(saved, true);
    assert.equal(mutationFetches, 1);
    assert.equal(pageFetches, 1);
    assert.equal(fullRenders, 0);
    assert.ok(nodes.samplePoolGrid.innerHTML.includes("SN #SN654321"));
  }

  {
    const context = loadFrontend();
    const { app } = context;
    app.view.module = "samples";
    app.view.selectedCategoryId = "cat_clean";
    app.updateServerStatus = () => {};
    const sample = { id: "sample_clean", categoryId: "cat_clean", sn: "SN777777", status: "闲置" };
    const category = { id: "cat_clean", name: "池C", sampleCount: 1, samples: [sample] };
    app.data.sampleLibrary.categories = [category];
    app._baseData = app.cloneData(app.data);
    app.serverRevision = 1;
    context.fetch = async (url) => {
      assert.ok(String(url).startsWith("/api/sample-categories/cat_clean/mutation"));
      return { ok: true, status: 200, json: async () => ({
        ok: true,
        revision: 2,
        updated_at: "2026-06-03T10:00:00",
      }) };
    };
    app.refreshCurrentSamplePage = async (refreshedCategory) => {
      Object.assign(refreshedCategory.samples[0], {
        photoCount: 0,
        photosLoaded: false,
        hasProblem: false,
        effectiveStatus: "闲置",
      });
      return true;
    };

    const saved = await app.commitSampleCategoryMutation(category, {
      action: "create_sample",
      remark: "新增样机",
      user: "管理员",
      createSamples: true,
      samples: [sample],
    });

    assert.equal(saved, true);
    assert.equal(app.hasLocalUnsavedChanges(), false);
    assert.equal(await app.prepareBeforeDirectMutation("上传样机外观照片前同步"), true);
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    nodes.taskFlowShell = { dataset: { stageId: "stage_import" }, innerHTML: "" };
    app.view.module = "projectWorkspace";
    app.view.selectedProjectId = "project_import";
    app.view.selectedStageId = "stage_import";
    app.view.taskFlowPage = 1;
    app.view.taskFlowPageSize = 50;
    app.sectionToggleTriangle = () => "";
    app.taskIssueSummaryHtml = () => "<span>-</span>";
    app.taskIssueRecordHtml = () => "<span>-</span>";
    app.taskFlowActionsHtml = () => "";
    app.ensureTaskLogs = () => [];
    app.updateSelectPlaceholderState = () => {};
    app.closeModal = () => { app._closed = (app._closed || 0) + 1; };
    app.updateServerStatus = () => {};
    app.renderNav = () => { app._navRenders = (app._navRenders || 0) + 1; };
    app.renderHeader = () => { app._headerRenders = (app._headerRenders || 0) + 1; };
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderContent = () => { fullRenders++; };
    app.reloadFromServer = async () => { throw new Error("/api/state should not be used after bundle import"); };
    app.data.projects = [{
      id: "project_import",
      name: "旧项目",
      stages: [{ id: "stage_import", name: "EVT", skuNames: ["SKU1"], progress: [], tasks: [] }],
      _detailLoaded: true,
    }];
    app.data.sampleLibrary.categories = [{ id: "cat_import", name: "旧样机池", sampleCount: 0, samples: [] }];
    app.serverRevision = 1;
    app._importState = { preview: { previewId: "preview_import", conflicts: [], blockers: [] }, decisions: {}, processedConflicts: new Set() };
    let projectSummaryFetches = 0;
    let categorySummaryFetches = 0;
    let projectDetailFetches = 0;
    let taskPageFetches = 0;
    app.importBundleCommit = async (previewId, decisions) => {
      assert.equal(previewId, "preview_import");
      assert.deepEqual(decisions, {});
      return {
        ok: true,
        revision: 2,
        updated_at: "2026-06-03T11:00:00",
        stats: { projectsAdded: 1, samplesAdded: 1, samplesMerged: 0, sampleEventsAdded: 0, skipped: 0 },
        mutationSummary: {
          projectIds: ["project_import"],
          stageIds: ["stage_import"],
          taskIds: ["task_import"],
          sampleCategoryIds: ["cat_import"],
          sampleIds: ["sample_import"],
          requiresFullState: false,
        },
      };
    };
    app.fetchProjectSummary = async () => {
      projectSummaryFetches++;
      return [{ id: "project_import", name: "导入项目", code: "IMP", owner: "张三/001", stageCount: 1, taskCount: 1 }];
    };
    app.fetchSampleCategoriesSummary = async () => {
      categorySummaryFetches++;
      return [{ id: "cat_import", name: "导入池", sampleCount: 1, statusCounts: { "闲置": 1 }, problemCounts: { ok: 1 } }];
    };
    app.fetchProjectDetail = async projectId => {
      projectDetailFetches++;
      assert.equal(projectId, "project_import");
      return {
        id: "project_import",
        name: "导入项目",
        code: "IMP",
        owner: "张三/001",
        stages: [{ id: "stage_import", name: "EVT", skuNames: ["SKU1"], progress: [], tasks: [], taskCount: 1, statusCounts: { "待下发": 1 }, ownerNames: [] }],
      };
    };
    app.fetchStageTasksPage = async (stageId, params) => {
      taskPageFetches++;
      assert.equal(stageId, "stage_import");
      assert.equal(params.pageSize, 50);
      return {
        page: 1,
        pageSize: 50,
        total: 1,
        totalPages: 1,
        stats: { totalInStage: 1, statusCounts: { "待下发": 1 }, ownerNames: [] },
        rows: [{ progress: null, task: { id: "task_import", status: "待下发", skuIndex: 1, category: "可靠性", testItem: "导入任务", sampleIds: [] } }],
      };
    };

    const shouldClose = await app._onImportCommit({ skipCollect: true });

    assert.equal(shouldClose, false);
    assert.equal(app._importState, null);
    assert.equal(app._closed, 1);
    assert.equal(projectSummaryFetches, 1);
    assert.equal(categorySummaryFetches, 1);
    assert.equal(projectDetailFetches, 1);
    assert.equal(taskPageFetches, 1);
    assert.equal(fullRenders, 0);
    assert.equal(app.serverRevision, 2);
    assert.equal(app.data.projects[0].name, "导入项目");
    assert.ok(nodes.taskFlowShell.innerHTML.includes("导入任务"));
  }

  {
    const context = loadFrontend();
    const { app, nodes } = context;
    attachSamplePageNodes(nodes, "cat_import");
    app._samplePagePrefetchDisabled = true;
    app.view.module = "samples";
    app.view.selectedCategoryId = "cat_import";
    app.view.samplePage = 1;
    app.view.samplePageSize = 50;
    app.updateServerStatus = () => {};
    app.renderNav = () => {};
    app.renderHeader = () => {};
    let fullRenders = 0;
    app.render = () => { fullRenders++; };
    app.renderContent = () => { fullRenders++; };
    app.renderSamples = () => { fullRenders++; };
    app.reloadFromServer = async () => { throw new Error("/api/state should not be used after bundle import"); };
    app.data.projects = [];
    app.data.sampleLibrary.categories = [{ id: "cat_import", name: "旧样机池", sampleCount: 0, samples: [] }];
    app.serverRevision = 1;
    let categorySummaryFetches = 0;
    let samplePageFetches = 0;
    app.fetchProjectSummary = async () => [];
    app.fetchSampleCategoriesSummary = async () => {
      categorySummaryFetches++;
      return [{ id: "cat_import", name: "导入池", sampleCount: 1, statusCounts: { "闲置": 1 }, problemCounts: { ok: 1 } }];
    };
    app.fetchProjectDetail = async () => {
      throw new Error("project detail should not be fetched when import only affects samples");
    };
    app.fetchSamplePage = async (categoryId, params) => {
      samplePageFetches++;
      assert.equal(categoryId, "cat_import");
      assert.equal(params.pageSize, 50);
      return {
        page: 1,
        pageSize: 50,
        total: 1,
        totalPages: 1,
        stats: { totalInCategory: 1, statusCounts: { "闲置": 1 }, problemCounts: { ok: 1 } },
        category: { id: "cat_import", name: "导入池" },
        items: [{ id: "sample_import", sn: "SN-IMPORT-001", status: "闲置" }],
      };
    };

    const synced = await app.applyImportBundleMutationResult({
      ok: true,
      revision: 2,
      updated_at: "2026-06-03T11:10:00",
      mutationSummary: {
        projectIds: [],
        stageIds: [],
        taskIds: [],
        sampleCategoryIds: ["cat_import"],
        sampleIds: ["sample_import"],
        requiresFullState: false,
      },
    });

    assert.equal(synced, true);
    assert.equal(categorySummaryFetches, 1);
    assert.equal(samplePageFetches, 1);
    assert.equal(fullRenders, 0);
    assert.equal(app.serverRevision, 2);
    assert.equal(app.data.sampleLibrary.categories[0].name, "导入池");
    assert.equal(app.data.sampleLibrary.categories[0].samples[0].id, "sample_import");
    assert.equal(nodes.samplePoolCount.innerText, "显示 1 / 1 台");
    assert.ok(nodes.samplePoolGrid.innerHTML.includes("sample_import"));
  }

  console.log("frontend pagination performance tests passed");
})();
