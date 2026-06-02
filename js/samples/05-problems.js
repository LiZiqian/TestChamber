/* ========================================
   TestChamber V7 - Sample problem table helpers
   Split from the previous monolithic module.
   ======================================== */

Object.assign(app, {

  sampleProblemsHtml(containerId, records = []) {
    const rows = records.length ? records : [{ description: "", source: "初检", taskLabel: "" }];
    return `<div id="${containerId}" class="sample-initial-results sample-problem-table">
      ${rows.map((v, i) => this.sampleProblemRowHtml(containerId, v, { isLast: i === rows.length - 1 })).join("")}
    </div>`;
  },

  sampleProblemRowHtml(containerId, record = {}, opts = {}) {
    const item = typeof record === "string" ? { description: record, source: "初检", taskLabel: "" } : record;
    const addBtn = opts.isLast ? `<button type="button" class="sample-result-btn add" title="追加一行" onclick="app.addSampleProblemRow('${containerId}')">+</button>` : `<span class="sample-result-btn-spacer"></span>`;
    return `<div class="sample-initial-result-row">
      <input class="sample-problem-desc" value="${Utils.esc(item.description || "")}" placeholder="问题描述，如 有碎亮点">
      <input class="sample-problem-source" value="${Utils.esc(item.source || "初检")}" placeholder="来源">
      <input class="sample-problem-task" value="${Utils.esc(item.taskLabel || "")}" placeholder="关联任务项">
      <button type="button" class="sample-result-btn remove" title="删除此行" onclick="app.removeSampleProblemRow(this)">🗑</button>
      ${addBtn}
    </div>`;
  },

  addSampleProblemRow(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    // 移除旧尾行的 + 按钮，换为占位
    const prevLast = container.querySelector(".sample-result-btn.add");
    if (prevLast) {
      const spacer = document.createElement("span");
      spacer.className = "sample-result-btn-spacer";
      prevLast.replaceWith(spacer);
    }
    // 追加新行（带 + 按钮）
    const total = container.querySelectorAll(".sample-initial-result-row").length;
    container.insertAdjacentHTML("beforeend", this.sampleProblemRowHtml(containerId, { description: "", source: "手动补录", taskLabel: "" }, { isLast: true }));
  },

  removeSampleProblemRow(btn) {
    const row = btn.closest(".sample-initial-result-row");
    const wrap = btn.closest(".sample-initial-results");
    if (!row || !wrap) return;
    const allRows = wrap.querySelectorAll(".sample-initial-result-row");
    if (allRows.length <= 1) {
      row.querySelectorAll("input").forEach(input => input.value = "");
      return;
    }
    // 如果删除的是尾行，先把 + 移到上一行
    if (row.querySelector(".sample-result-btn.add")) {
      const prevRow = row.previousElementSibling;
      if (prevRow) {
        const spacer = prevRow.querySelector(".sample-result-btn-spacer");
        if (spacer) {
          const addBtn = row.querySelector(".sample-result-btn.add");
          spacer.replaceWith(addBtn.cloneNode(true));
        }
      }
    }
    row.remove();
  },

  collectSampleProblems(containerId) {
    return [...(document.getElementById(containerId)?.querySelectorAll(".sample-initial-result-row") || [])]
      .map(row => ({
        id: Utils.id("problem_"),
        description: row.querySelector(".sample-problem-desc")?.value.trim() || "",
        source: row.querySelector(".sample-problem-source")?.value.trim() || "手动补录",
        taskLabel: row.querySelector(".sample-problem-task")?.value.trim() || ""
      }))
      .filter(item => item.description && !Utils.isNoSampleIssueText(item.description));
  },

  sampleInitialResultsHtml(containerId, values = []) {
    return this.sampleProblemsHtml(containerId, values.map(v => ({ description: v, source: "初检", taskLabel: "" })));
  },

  addSampleInitialResultRow(containerId) {
    this.addSampleProblemRow(containerId);
  },

  removeSampleInitialResultRow(btn) {
    this.removeSampleProblemRow(btn);
  },

  collectSampleInitialResults(containerId) {
    return this.collectSampleProblems(containerId).map(x => x.description);
  },

});
