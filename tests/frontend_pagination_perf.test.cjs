const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function createContext() {
  const nodes = {
    content: { innerHTML: "", innerText: "", style: {}, dataset: {} },
    pageFooter: { innerHTML: "", innerText: "", style: {}, dataset: {} },
  };
  const context = {
    console,
    window: {},
    document: {
      getElementById(id) {
        return nodes[id] || null;
      },
    },
    app: {
      version: "V7",
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
  const code = fs.readFileSync(path.join(root, relativePath), "utf8");
  vm.runInContext(`${code}\n${trailer}`, context, { filename: relativePath });
}

function loadFrontend() {
  const context = createContext();
  loadScript(context, "js/utils.js", "globalThis.Utils = Utils;");
  loadScript(context, "js/app.data.js");
  loadScript(context, "js/workspace/01-shared.js");
  loadScript(context, "js/workspace/05-task-table.js");
  loadScript(context, "js/samples/01-pool.js");
  loadScript(context, "js/samples/02-import-export.js");
  loadScript(context, "js/samples/03-detail-fields.js");
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
    assert.ok(html.includes("有故障"));
    assert.ok(html.includes("不开机"));
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
    const params = app.samplePageQueryParams(cat);
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
    assert.ok(nodes.content.innerHTML.includes("SN#000200"));
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
    assert.ok(nodes.content.innerHTML.includes("SN#000300"));
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

  console.log("frontend pagination performance tests passed");
})();
