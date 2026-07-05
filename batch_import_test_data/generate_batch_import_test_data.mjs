import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const dependencyRequire = createRequire("C:/Users/ROG/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/");
const { FileBlob, SpreadsheetFile } = await import(pathToFileURL(dependencyRequire.resolve("@oai/artifact-tool")).href);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const templatesDir = path.join(repoRoot, "frontend", "templates");
const seed = 20260606;

function mulberry32(initial) {
  let t = initial >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let x = t;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

const random = mulberry32(seed);
const pick = (items) => items[Math.floor(random() * items.length)];
const pad = (value, length) => String(value).padStart(length, "0");

const surnames = ["赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", "刘", "杨", "黄", "何", "高", "林", "罗", "宋", "唐", "许"];
const givenNames = ["明", "华", "杰", "敏", "静", "强", "磊", "娜", "伟", "芳", "洋", "佳", "鑫", "宁", "晨", "航", "悦", "彬", "琪", "楠"];
const englishNames = ["Alex Chen", "Nina Li", "Grace Wang", "Kevin Zhou", "Mia Huang", "Victor Lin"];
const stages = ["EVT1", "EVT2", "DVT1", "DVT2", "PVT", "MP试产", "专项返测", "V3-1"];
const schemes = ["QCOM-SM8650-5G", "MTK-D9300-WiFi", "UNISOC-T820", "Exynos-X1", "Intel-XMM-5G", "RK3588S-工业版"];
const locations = ["溪村-DB-B1F-A08", "溪村-DB-2F-B16", "成都实验室-3F-屏蔽房", "上海可靠性室-A12", "深圳仓-样机柜-07", "北京办公室-测试架-02"];
const issueTexts = [
  "/",
  "无",
  "屏幕轻微划伤",
  "开机键回弹偏弱；后盖缝隙偏大",
  "摄像头保护膜残胶；SIM 卡托轻微松动",
  "外观掉漆\nUSB-C 口插拔阻尼偏大",
  "低温启动偶发慢 3s；扬声器底噪待复测",
];
const statuses = ["闲置", "测试中", "在位等待", "已退库", "取走分析"];
const categories = ["可靠性", "结构耐久", "射频性能", "音频", "显示触控", "充电电池", "温湿度环境", "系统稳定性", "软件兼容", "包装运输", "传感器", "数据安全"];
const testItems = [
  "六面四角跌落",
  "-20℃低温标准弯折",
  "45℃高温老化 8h",
  "USB-C 插拔寿命 500 次",
  "整机静电接触放电",
  "弱网切换 4G/5G/WiFi",
  "摄像头连续拍照 100 张",
  "扬声器最大音量失真检查",
  "触控湿手场景滑动",
  "满电待机 24h",
  "OTA 升级后基础冒烟",
  "蓝牙耳机连接稳定性",
  "NFC 刷卡兼容性",
  "包装箱短边跌落",
  "整机条码扫描一致性",
];

function personName(index) {
  if (index % 17 === 0) return pick(englishNames);
  return `${pick(surnames)}${pick(givenNames)}${pick(givenNames)}`;
}

function employeeNo(index) {
  if (index % 9 === 0) return `wx${pad(520000 + index * 17, 6)}`;
  if (index % 13 === 0) return `RD${pad(1000 + index, 4)}`;
  return pad(62000000 + index * 37, 8);
}

function personText(index) {
  return `${personName(index)}/${employeeNo(index)}`;
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

async function writeCsv(fileName, rows) {
  const text = `\ufeff${rows.map((row) => row.map(csvEscape).join(",")).join("\r\n")}\r\n`;
  await fs.writeFile(path.join(__dirname, fileName), text, "utf8");
}

function rangeAddress(startCol, startRow, rowCount, colCount) {
  const colName = (num) => {
    let n = num;
    let out = "";
    while (n > 0) {
      const rem = (n - 1) % 26;
      out = String.fromCharCode(65 + rem) + out;
      n = Math.floor((n - 1) / 26);
    }
    return out;
  };
  const endCol = startCol + colCount - 1;
  const endRow = startRow + rowCount - 1;
  return `${colName(startCol)}${startRow}:${colName(endCol)}${endRow}`;
}

function imei(index) {
  return `86${pad(2600000000000 + index * 7919, 13)}`.slice(0, 15);
}

function stageCode(stage) {
  return ({
    "MP试产": "MP",
    "专项返测": "RET",
    "V3-1": "V31",
  })[stage] || String(stage).replace(/[^\w]/g, "") || "STAGE";
}

function sampleRows(count, { edge = false, extended = false } = {}) {
  return Array.from({ length: count }, (_, offset) => {
    const index = offset + 1;
    const serial = pad(index, 5);
    const stage = pick(stages);
    const sn = edge && index % 5 === 0 ? "" : `TCV7-${stageCode(stage)}-${serial}`;
    const idImei = edge && index % 7 === 0 ? "" : imei(index);
    const boardSn = edge && index % 6 === 0 ? "" : `MB20260606${pad(index * 19, 6)}`;
    const row = [
      sn,
      idImei,
      boardSn || `MBFALLBACK${serial}`,
      edge && index % 11 === 0 ? "是" : "否",
      stage,
      pick(schemes),
      `SCH-${stage}-${pad(100 + index, 3)}`,
      pick(issueTexts),
      personText(index),
      pick(locations),
      edge
        ? `边界样例 ${serial}：字段组合=${sn ? "SN" : ""}/${idImei ? "IMEI" : ""}/${boardSn ? "主板SN" : ""}，用于人工导入鲁棒性测试`
        : `随机有效样例 ${serial}`,
    ];
    if (extended) {
      row.push(pick(statuses));
      row.push(edge ? `边界;${stage};${index % 3 === 0 ? "长备注" : "常规"}` : `批量导入-${stage}`);
    }
    return row;
  });
}

function testCaseRows(count, { edge = false } = {}) {
  return Array.from({ length: count }, (_, offset) => {
    const index = offset + 1;
    const category = pick(categories);
    const item = edge
      ? `${pick(testItems)} - 边界批次 ${pad(index, 3)} / ${pick(["中文标点，逗号", "斜杠 A/B", "括号（复测）", "温度±5℃", "长名称回归验证"]) }`
      : `${pick(testItems)} - 随机批次 ${pad(index, 3)}`;
    return [category, item];
  });
}

async function exportWorkbookFromTemplate(templateName, sheetName, writes, fileName) {
  const input = await FileBlob.load(path.join(templatesDir, templateName));
  const workbook = await SpreadsheetFile.importXlsx(input);
  const sheet = workbook.worksheets.getItem(sheetName);
  for (const write of writes) {
    sheet.getRange(write.range).values = write.values;
  }
  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 20 },
    summary: `${fileName} formula error scan`,
  });
  const preview = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!A1:M8`,
    include: "values,formulas",
    tableMaxRows: 8,
    tableMaxCols: 13,
  });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(__dirname, fileName));
  return { fileName, formulaErrors: formulaErrors.ndjson, preview: preview.ndjson };
}

async function main() {
  const generated = [];

  const members = [["姓名/工号"]];
  for (let i = 1; i <= 80; i += 1) members.push([personText(i)]);
  await writeCsv("01_project_members_random_valid.csv", members);
  generated.push({ fileName: "01_project_members_random_valid.csv", rows: members.length - 1, note: "当前解析器可导入的单列姓名/工号格式" });

  const sampleBase = sampleRows(150);
  generated.push({
    ...(await exportWorkbookFromTemplate("sample_import_template.xlsx", "样机批量导入模板", [
    { range: rangeAddress(1, 2, sampleBase.length, 11), values: sampleBase },
    ], "02_sample_import_random_valid.xlsx")),
    rows: sampleBase.length,
    note: "常规有效样机导入数据",
  });

  const sampleEdge = sampleRows(90, { edge: true, extended: true });
  generated.push({
    ...(await exportWorkbookFromTemplate("sample_import_template.xlsx", "样机批量导入模板", [
    { range: "L1:M1", values: [["样机状态", "标签"]] },
    { range: rangeAddress(1, 2, sampleEdge.length, 13), values: sampleEdge },
    ], "02b_sample_import_extended_edge_valid.xlsx")),
    rows: sampleEdge.length,
    note: "扩展列和边界但有效样机导入数据",
  });

  const testCases = testCaseRows(180);
  generated.push({
    ...(await exportWorkbookFromTemplate("用例集导入模板.xlsx", "Sheet1", [
    { range: rangeAddress(1, 2, testCases.length, 2), values: testCases },
    ], "03_test_cases_random_valid.xlsx")),
    rows: testCases.length,
    note: "常规有效用例集导入数据",
  });

  const testCasesEdge = testCaseRows(90, { edge: true });
  generated.push({
    ...(await exportWorkbookFromTemplate("用例集导入模板.xlsx", "Sheet1", [
    { range: rangeAddress(1, 2, testCasesEdge.length, 2), values: testCasesEdge },
    ], "03b_test_cases_edge_valid.xlsx")),
    rows: testCasesEdge.length,
    note: "边界但有效用例集导入数据",
  });

  const readme = [
    "# TestChamber V7 批量导入人工测试数据",
    "",
    `生成时间：2026-06-06；随机种子：${seed}`,
    "",
    "## 文件",
    "",
    "- `01_project_members_random_valid.csv`：项目人员导入。当前前端解析器要求单列 `姓名/工号`，不是仓库静态模板里的两列 `姓名,工号`。",
    "- `02_sample_import_random_valid.xlsx`：基于 `frontend/templates/sample_import_template.xlsx` 的常规有效样机批量导入数据。",
    "- `02b_sample_import_extended_edge_valid.xlsx`：基于同一模板，额外加入当前解析器支持的 `样机状态`、`标签` 扩展列，并覆盖只填 SN/IMEI/主板 SN、长备注、多问题项等边界但有效场景。",
    "- `03_test_cases_random_valid.xlsx`：基于 `frontend/templates/用例集导入模板.xlsx` 的常规有效用例集。",
    "- `03b_test_cases_edge_valid.xlsx`：基于同一模板，覆盖较长用例名、符号、温度单位、括号和斜杠等边界但有效场景。",
    "",
    "## 使用提醒",
    "",
    "- 样机导入会在目标样机池内和跨池查重；如果你的真实库里已有相同 SN/IMEI/主板 SN，导入时会被跳过，这是预期行为。",
    "- 这些文件刻意保持为有效数据，不包含明显非法人员格式或完全空标识样机；如需测试非法输入，可在副本里手工删改几行。",
    "",
  ].join("\n");
  await fs.writeFile(path.join(__dirname, "README.md"), readme, "utf8");

  await fs.writeFile(path.join(__dirname, "manifest.json"), JSON.stringify({
    generatedAt: "2026-06-06",
    seed,
    generated: generated.map((item) => ({
      fileName: item.fileName,
      rows: item.rows,
      note: item.note,
    })),
  }, null, 2), "utf8");

  console.log(JSON.stringify({
    outputDir: __dirname,
    generated: generated.map((item) => item.fileName),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
