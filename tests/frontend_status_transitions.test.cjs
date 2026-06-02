const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");

const root = path.resolve(__dirname, "..");
const context = {
  console,
  window: {},
  document: {},
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
loadScript("js/workspace/01-shared.js");

const { app } = context;
const { Utils } = context;

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

console.log("frontend status transition tests passed");
