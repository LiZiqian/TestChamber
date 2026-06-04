const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");

const root = path.resolve(__dirname, "..");
const context = {
  console,
  URLSearchParams,
  alert: () => {},
  window: {},
  document: {},
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
    constants: {
      sampleStatuses: ["测试中", "闲置", "在位等待", "已退库", "取走分析"],
      taskStatuses: ["待下发", "进行中", "阻塞中", "正常完成", "异常终止"],
    },
    data: {
      projects: [],
      sampleLibrary: { categories: [], logs: [] },
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
loadScript("js/app.server.js");
loadScript("js/workspace/01-shared.js");
loadScript("js/workspace/06-sample-picker.js");
loadScript("js/samples/04-photos.js");
loadScript("js/workspace/09-task-result.js");

const { app } = context;
const { Utils } = context;

app.sampleTestedItemNames = () => [];

{
  app.data.sampleLibrary.categories = [{
    id: "cat_photo",
    name: "照片池",
    samples: [{ id: "sample_photo", sampleNo: "S001", photos: [], photoCount: 0, photosLoaded: true }],
  }];
  app.serverRevision = 1;
  vm.runInContext(`
    app._samplePageCaches = new Map([
      ["same", { categoryId: "cat_photo" }],
      ["other", { categoryId: "cat_other" }],
    ]);
    app._samplePageMetaCaches = new Map([
      ["same_meta", { categoryId: "cat_photo" }],
      ["other_meta", { categoryId: "cat_other" }],
    ]);
  `, context);
  let reloads = 0;
  const statuses = [];
  const originalReloadFromServer = app.reloadFromServer;
  const originalUpdateServerStatus = app.updateServerStatus;
  try {
    app.reloadFromServer = async () => { reloads++; };
    app.updateServerStatus = text => statuses.push(text);

    const sample = app.applySamplePhotosMutationResult("sample_photo", {
      revision: 2,
      updated_at: "2026-06-02T12:00:00",
      photos: [{ id: "photo_1", name: "front.jpg", url: "/api/samples/sample_photo/photos/photo_1" }],
    });

    assert.equal(reloads, 0);
    assert.equal(app.serverRevision, 2);
    assert.equal(sample.photoCount, 1);
    assert.equal(sample.photosLoaded, true);
    assert.equal(sample.photos[0].name, "front.jpg");
    assert.equal(app._samplePageCaches.has("same"), false);
    assert.equal(app._samplePageCaches.has("other"), true);
    assert.equal(app._samplePageMetaCaches.has("same_meta"), false);
    assert.equal(app._samplePageMetaCaches.has("other_meta"), true);
    assert.equal(statuses[statuses.length - 1], "已保存");
  } finally {
    app.reloadFromServer = originalReloadFromServer;
    app.updateServerStatus = originalUpdateServerStatus;
  }
}

function pickerInputHtml(html, sampleId) {
  const match = html.match(new RegExp(`<input[^>]+value="${sampleId}"[^>]*>`));
  assert.ok(match, `sample picker input not found: ${sampleId}`);
  return match[0];
}

{
  const text = "xlsx fallback deflate smoke test\n".repeat(300);
  const compressed = zlib.deflateRawSync(Buffer.from(text, "utf8"));
  const inflated = Utils.inflateRawBytesFallback(new Uint8Array(compressed));
  assert.equal(Buffer.from(inflated).toString("utf8"), text);
}

{
  const stage = { progress: [{ id: "prog_1" }] };
  const task = { id: "task_1", progressId: "prog_1", status: "待下发", owner: "张三/001" };

  const started = app.transitionTaskStatus(stage, task, "进行中", {
    owner: task.owner,
    startDate: "2026-06-02",
  });

  assert.equal(started.fromStatus, "待下发");
  assert.equal(started.toStatus, "进行中");
  assert.equal(task.completed, false);
  assert.equal(task.startDate, "2026-06-02");
  assert.equal(stage.progress[0].status, "Testing");
  assert.equal(stage.progress[0].owner, "张三/001");
  assert.equal(stage.progress[0].startDate, "2026-06-02");

  const blocked = app.transitionTaskStatus(stage, task, "阻塞中", {
    reason: "设备故障",
    issue: "设备故障",
  });

  assert.equal(blocked.fromStatus, "进行中");
  assert.equal(blocked.toStatus, "阻塞");
  assert.equal(task.blockReason, "设备故障");
  assert.equal(stage.progress[0].status, "阻塞");
  assert.equal(stage.progress[0].issue, "设备故障");

  app.transitionTaskStatus(stage, task, "正常完成", {
    completedAt: "2026-06-02T10:00:00.000Z",
    endDate: "2026-06-02",
    progressStatus: "Pass",
    issue: "",
  });

  assert.equal(task.status, "正常完成");
  assert.equal(task.completed, true);
  assert.equal(task.completionType, "正常完成");
  assert.equal(task.endDate, "2026-06-02");
  assert.equal(stage.progress[0].status, "Pass");
}

{
  const sample = { id: "sample_1", sampleNo: "SN001", status: "闲置" };
  app.data = {
    projects: [],
    sampleLibrary: { categories: [{ id: "cat_1", samples: [sample] }], logs: [] },
  };

  app.changeSampleStatus("sample_1", "取走分析", {
    user: "管理员",
    source: "测试",
    reason: "取走分析",
    receiver: "李四/002",
    accountOwner: "张三/001",
    destLocation: "实验室",
  });

  assert.equal(sample.status, "取走分析");
  assert.equal(sample.borrower, "李四/002");
  assert.equal(sample.owner, "张三/001");
  assert.equal(sample.location, "实验室");
  assert.equal(sample.logs, undefined);
  assert.equal(app.data.sampleLibrary.logs.length, 1);
}

{
  const task = { id: "task_legacy", status: "已完成", completionType: "正常完成", sampleIds: [] };
  const sample = { id: "sample_legacy", sampleNo: "SN002", status: "已借出" };
  app.data = {
    version: "V7",
    eventSchema: "sample_events_v2",
    users: [],
    projects: [{
      id: "project_1",
      stages: [{ id: "stage_1", skuNames: ["SKU1"], bom: [], strategy: [], progress: [], tasks: [task] }],
      members: [],
      locations: []
    }],
    sampleLibrary: { categories: [{ id: "cat_1", samples: [sample] }], logs: [] },
  };

  app.normalize();

  assert.equal(task.status, "正常完成");
  assert.equal(task.completed, true);
  assert.equal(sample.status, "取走分析");
}

{
  app.data = {
    projects: [],
    sampleLibrary: {
      categories: [{
        id: "cat_picker",
        name: "池A",
        sampleCount: 70000,
        samples: [
          { id: "idle", sampleNo: "S001", status: "闲置" },
          { id: "testing", sampleNo: "S002", status: "测试中" },
          { id: "waiting", sampleNo: "S003", status: "在位等待" },
          { id: "retired", sampleNo: "S004", status: "已退库" },
          { id: "analysis", sampleNo: "S005", status: "取走分析" },
          { id: "borrowed", sampleNo: "S006", status: "已借出" },
        ],
      }],
      logs: [],
    },
  };

  app.allSamples = () => {
    throw new Error("sample picker should not enumerate all samples");
  };
  const html = app.buildTaskSamplePickerHtml([], "pick", "", "", "");
  assert.ok(html.includes("data-task-sample-picker=\"pick\""));
  assert.ok(html.includes("正在加载候选样机"));

  const state = app.resetTaskSamplePickerState("pick", { selectedIds: ["testing", "waiting"], excludeTaskId: "task_current" });
  const idleHtml = app.taskSamplePickerSampleRowHtml({ id: "idle", sampleNo: "S001", status: "闲置", selectable: true }, state);
  assert.ok(!pickerInputHtml(idleHtml, "idle").includes("disabled"));
  const blockedHtml = app.taskSamplePickerSampleRowHtml({
    id: "borrowed",
    sampleNo: "S006",
    status: "取走分析",
    selectable: false,
    disabledReason: "当前状态为「取走分析」，不能加入测试任务",
  }, state);
  assert.ok(pickerInputHtml(blockedHtml, "borrowed").includes("disabled"));
  assert.ok(blockedHtml.includes("取走分析"));
  ["testing", "waiting"].forEach(sampleId => {
    const selectedRow = app.taskSamplePickerSampleRowHtml({
      id: sampleId,
      sampleNo: sampleId,
      status: sampleId === "testing" ? "测试中" : "在位等待",
      selectable: false,
      disabledReason: "当前任务已选",
    }, state, { selected: true });
    const input = pickerInputHtml(selectedRow, sampleId);
    assert.ok(input.includes("checked"), `${sampleId} should remain checked`);
    assert.ok(!input.includes("disabled"), `${sampleId} should remain editable for current task`);
  });
  assert.deepEqual(app.getSelectedTaskSampleIds("pick"), ["testing", "waiting"]);

  const enabledCheckbox = { value: "idle", checked: false, disabled: false };
  const enabledRow = { querySelector: () => enabledCheckbox };
  app.onTaskSampleRowClick({
    target: { closest: () => null },
    currentTarget: enabledRow,
  }, "pick");
  assert.equal(enabledCheckbox.checked, true);
  assert.deepEqual(app.getSelectedTaskSampleIds("pick"), ["testing", "waiting", "idle"]);

  const disabledCheckbox = { value: "retired", checked: false, disabled: true };
  const disabledRow = { querySelector: () => disabledCheckbox };
  app.onTaskSampleRowClick({
    target: { closest: () => null },
    currentTarget: disabledRow,
  }, "pick");
  assert.equal(disabledCheckbox.checked, false);
  assert.deepEqual(app.getSelectedTaskSampleIds("pick"), ["testing", "waiting", "idle"]);

  app.onTaskSampleRowClick({
    target: { closest: (selector) => selector.includes(".dispatch-sample-id") ? {} : null },
    currentTarget: enabledRow,
  }, "pick");
  assert.equal(enabledCheckbox.checked, true);
  assert.deepEqual(app.getSelectedTaskSampleIds("pick"), ["testing", "waiting", "idle"]);
}

function taskResultBaseData(status = "进行中") {
  return {
    projects: [{
      id: "p1",
      name: "项目1",
      stages: [{
        id: "st1",
        name: "阶段1",
        progress: [],
        tasks: [{
          id: "task1",
          status,
          completed: status === "正常完成",
          testItem: "test1",
          sampleIds: [],
          logs: [],
        }]
      }]
    }],
    sampleLibrary: { categories: [], logs: [] }
  };
}

function validTaskResultPayload() {
  return {
    result: "Pass",
    user: "LZQ/00609513",
    resultDate: "2026-06-02",
    finishType: "正常完成",
    samples: []
  };
}

async function runFinishTaskGuardTests() {
  const originalDocument = context.document;
  const originalSaveTaskResult = app.saveTaskResult;
  const originalApplyTaskResult = app.applyTaskResult;
  const originalCommitTaskMutation = app.commitTaskMutation;
  const originalCollectTaskResultForm = app.collectTaskResultForm;
  const originalValidateTaskResultPayload = app.validateTaskResultPayload;
  const originalShowModal = app.showModal;
  const originalCloseModal = app.closeModal;
  const originalProjectMemberSelectHtml = app.projectMemberSelectHtml;
  const originalTaskResultSampleRowsHtml = app.taskResultSampleRowsHtml;
  const originalRenderTaskResultPhotoList = app.renderTaskResultPhotoList;
  const originalRefreshTaskAfterAlreadyFinished = app.refreshTaskAfterAlreadyFinished;

  try {
    app.data = taskResultBaseData();
    let insertedButton = null;
    const modalOk = { disabled: false, insertAdjacentElement: (_pos, el) => { insertedButton = el; } };
    context.document = {
      getElementById: id => id === "modalOk" ? modalOk : null,
      createElement: () => ({
        disabled: false,
        addEventListener(event, handler) {
          if (event === "click") this.onclick = handler;
        },
      }),
      querySelectorAll: () => [],
    };
    app.showModal = () => {};
    app.projectMemberSelectHtml = () => "<select></select>";
    app.taskResultSampleRowsHtml = () => "";
    app.renderTaskResultPhotoList = () => {};
    app.collectTaskResultForm = validTaskResultPayload;
    let closes = 0;
    let saves = 0;
    let resolveSave;
    app.closeModal = () => { closes++; };
    app.saveTaskResult = async (_projectId, _stageId, _taskId, finishTask) => {
      saves++;
      assert.equal(finishTask, true);
      await new Promise(resolve => { resolveSave = resolve; });
      return false;
    };

    app.uploadResult("p1", "st1", "task1");
    assert.ok(insertedButton, "finish button should be inserted");
    const pending = insertedButton.onclick();
    assert.equal(insertedButton.disabled, true);
    assert.equal(modalOk.disabled, true);
    assert.equal(insertedButton.innerText, "结束中...");
    insertedButton.onclick();
    assert.equal(saves, 1);
    resolveSave();
    await pending;
    assert.equal(closes, 1);
    assert.equal(insertedButton.disabled, true);

    app.data = taskResultBaseData();
    insertedButton = null;
    modalOk.disabled = false;
    closes = 0;
    app.saveTaskResult = async () => true;
    app.uploadResult("p1", "st1", "task1");
    await insertedButton.onclick();
    assert.equal(closes, 0);
    assert.equal(insertedButton.disabled, false);
    assert.equal(modalOk.disabled, false);
    assert.equal(insertedButton.innerText, "结束任务");

    app.saveTaskResult = originalSaveTaskResult;
    app.data = taskResultBaseData("正常完成");
    app.collectTaskResultForm = validTaskResultPayload;
    let applied = 0;
    let committed = 0;
    app.applyTaskResult = () => { applied++; };
    app.commitTaskMutation = async () => { committed++; return true; };
    const alreadyDoneKeepOpen = await app.saveTaskResult("p1", "st1", "task1", true);
    assert.equal(alreadyDoneKeepOpen, false);
    assert.equal(applied, 0);
    assert.equal(committed, 0);

    app.data = taskResultBaseData();
    app._baseData = app.cloneData(app.data);
    app.collectTaskResultForm = validTaskResultPayload;
    app.validateTaskResultPayload = () => "";
    applied = 0;
    committed = 0;
    let resolveCommit;
    app.applyTaskResult = (_p, _s, task) => {
      applied++;
      task.logs.push({ id: "local_duplicate" });
    };
    app.commitTaskMutation = async () => {
      committed++;
      await new Promise(resolve => { resolveCommit = resolve; });
      return true;
    };
    const first = app.saveTaskResult("p1", "st1", "task1", true);
    await Promise.resolve();
    const second = await app.saveTaskResult("p1", "st1", "task1", true);
    assert.equal(second, true);
    assert.equal(applied, 1);
    assert.equal(committed, 1);
    resolveCommit();
    assert.equal(await first, false);

    app.data = taskResultBaseData();
    app._baseData = app.cloneData(app.data);
    app.applyTaskResult = (_p, _s, task) => {
      task.logs.push({ id: "local_should_rollback" });
    };
    app.commitTaskMutation = async () => false;
    const failedKeepOpen = await app.saveTaskResult("p1", "st1", "task1", true);
    assert.equal(failedKeepOpen, true);
    assert.deepEqual(app.getProjectStageTask("p1", "st1", "task1").t.logs, []);

    app.data = taskResultBaseData();
    app._baseData = app.cloneData(app.data);
    app.applyTaskResult = (_p, _s, task) => {
      task.logs.push({ id: "local_should_refresh" });
    };
    app.commitTaskMutation = async () => {
      app._lastTaskMutationError = { error_code: "TASK_ALREADY_FINISHED" };
      return false;
    };
    let refreshed = 0;
    app.refreshTaskAfterAlreadyFinished = async () => { refreshed++; };
    const conflictKeepOpen = await app.saveTaskResult("p1", "st1", "task1", true);
    assert.equal(conflictKeepOpen, false);
    assert.equal(refreshed, 1);
    assert.deepEqual(app.getProjectStageTask("p1", "st1", "task1").t.logs, []);
  } finally {
    context.document = originalDocument;
    app.saveTaskResult = originalSaveTaskResult;
    app.applyTaskResult = originalApplyTaskResult;
    app.commitTaskMutation = originalCommitTaskMutation;
    app.collectTaskResultForm = originalCollectTaskResultForm;
    app.validateTaskResultPayload = originalValidateTaskResultPayload;
    app.showModal = originalShowModal;
    app.closeModal = originalCloseModal;
    app.projectMemberSelectHtml = originalProjectMemberSelectHtml;
    app.taskResultSampleRowsHtml = originalTaskResultSampleRowsHtml;
    app.renderTaskResultPhotoList = originalRenderTaskResultPhotoList;
    app.refreshTaskAfterAlreadyFinished = originalRefreshTaskAfterAlreadyFinished;
  }
}

runFinishTaskGuardTests()
  .then(() => {
    console.log("frontend status transition tests passed");
  })
  .catch(err => {
    console.error(err);
    process.exit(1);
  });
