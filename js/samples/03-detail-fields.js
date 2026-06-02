/* ========================================
   TestChamber V7 - Sample detail field helpers
   Split from the previous monolithic module.
   ======================================== */

Object.assign(app, {

  sampleArchivePlaceholder(title, text) {
    return `<div class="sample-archive-empty">
      <b>${Utils.esc(title)}</b>
      <span>${Utils.esc(text)}</span>
    </div>`;
  },

  samplePersonInputHtml(id, value = "", placeholder = "任意填写") {
    // 失焦时严格按 "姓名/工号" 校验，不合法直接清空（不再保留残留串）。
    // 允许整字段为空，但只要填了就必须合法。
    return `<input id="${id}" value="${Utils.esc(value || "")}" placeholder="${Utils.esc(placeholder)}" autocomplete="off"
      onblur="app.validateSamplePersonInput(this)">`;
  },

  validateSamplePersonInput(input) {
    if (!input) return;
    // 先清除该字段之前的错误标记
    input.classList.remove("is-invalid");
    const group = input.closest(".form-group") || input.parentElement;
    if (group) {
      const err = group.querySelector(".field-error");
      if (err) err.remove();
    }
    const raw = String(input.value || "").trim();
    if (!raw) { input.value = ""; return; }
    const parsed = Utils.parsePersonField(raw);
    if (!parsed.ok) {
      // 保留用户输入不清空，在输入框下方直接标红提示
      input.classList.add("is-invalid");
      if (group && !group.querySelector(".field-error")) {
        group.insertAdjacentHTML("beforeend", `<div class="field-error">${Utils.esc(parsed.msg)}</div>`);
      }
    } else {
      // 合法时规范化为 姓名/工号
      input.value = Utils.personText(parsed.name, parsed.employeeNo);
    }
  },

  sampleLocationInputHtml(id, value = "") {
    const seen = new Set();
    const locations = [];
    (this.data.projects || []).forEach(p => (p.locations || []).forEach(loc => {
      const name = String(loc || "").trim();
      if (!name || seen.has(name)) return;
      seen.add(name);
      locations.push(name);
    }));
    const listId = `${id}List`;
    const options = locations.map(loc => `<option value="${Utils.esc(loc)}"></option>`).join("");
    return `<input id="${id}" list="${listId}" value="${Utils.esc(value || "")}" placeholder="请选择或输入位置">
      <datalist id="${listId}">${options}</datalist>`;
  },

  sampleInitialResultsValue(sample) {
    const rows = this.sampleProblemRecords(sample).length
      ? this.sampleProblemRecords(sample).map(x => x.description)
      : Array.isArray(sample?.initialResults) && sample.initialResults.length
        ? sample.initialResults
      : String(sample?.initialResult || "").split(/\r?\n|；|;/);
    return rows.map(x => String(x || "").trim()).filter(Boolean);
  },

  sampleIdentityFields(sample = {}) {
    return [
      { key: "sn", label: "SN", value: String(sample.sn || "").trim() },
      { key: "imei", label: "IMEI", value: String(sample.imei || "").trim() },
      { key: "boardSn", label: "主板SN", value: String(sample.boardSn || "").trim() },
    ];
  },

  sampleReassemblySources(sample = {}) {
    const sampleId = String(sample.id || "");
    const fields = this.sampleIdentityFields(sample).filter(item => item.value);
    return fields.map(field => {
      const valueKey = field.value.toLowerCase();
      const matches = [];
      for (const category of (this.data.sampleLibrary.categories || [])) {
        for (const candidate of (category.samples || [])) {
          if (!candidate || String(candidate.id || "") === sampleId) continue;
          const matchedFields = this.sampleIdentityFields(candidate)
            .filter(item => item.value && item.value.toLowerCase() === valueKey)
            .map(item => item.label);
          if (!matchedFields.length) continue;
          matches.push({ category, sample: candidate, matchedFields });
        }
      }
      return { ...field, matches };
    });
  },

  sampleReassemblySourcesHtml(sample = {}) {
    if (!this.sampleIsReassembled(sample)) return "";
    const groups = this.sampleReassemblySources(sample);
    const hasMatches = groups.some(group => group.matches.length);
    const body = hasMatches
      ? groups.map(group => `
          <div class="sample-reassembly-group">
            <div class="sample-reassembly-group-title">${Utils.esc(group.label)}来源</div>
            <div class="sample-reassembly-group-body">
              ${group.matches.length ? group.matches.map(item => `
                <button type="button" class="sample-reassembly-link" onclick="app.openSampleReadonly('${Utils.esc(item.sample.id)}')">
                  <b>${Utils.esc(this.sampleDisplayCode(item.sample))}</b>
                  <span>${Utils.esc(item.category.name || "-")} · 匹配${Utils.esc(item.matchedFields.join("/"))}</span>
                </button>
              `).join("") : `<span class="sample-reassembly-empty">暂无匹配样机</span>`}
            </div>
          </div>`).join("")
      : `<div class="sample-reassembly-none">暂无已建档前身样机</div>`;
    return `<div class="sample-reassembly-panel">
      <div class="sample-reassembly-head">
        <b>重组来源</b>
        <span>按 SN / IMEI / 主板SN 自动匹配全局样机池</span>
      </div>
      ${body}
    </div>`;
  },

  showSamplePersonOptions(id) {
    document.querySelectorAll(".sample-person-options.show").forEach(el => {
      if (el.dataset.pickerFor !== id) el.classList.remove("show");
    });
    document.querySelector(`[data-picker-for="${id}"]`)?.classList.add("show");
    this.filterSamplePersonOptions(id);
  },

  hideSamplePersonOptions(id) {
    document.querySelector(`[data-picker-for="${id}"]`)?.classList.remove("show");
  },

  filterSamplePersonOptions(id) {
    const input = document.getElementById(id);
    const panel = document.querySelector(`[data-picker-for="${id}"]`);
    if (!input || !panel) return;
    const kw = input.value.trim().toLowerCase();
    panel.querySelectorAll(".sample-person-option").forEach(btn => {
      btn.style.display = !kw || btn.dataset.person.toLowerCase().includes(kw) ? "" : "none";
    });
  },

  pickSamplePerson(id, value) {
    const input = document.getElementById(id);
    if (input) input.value = value || "";
    this.hideSamplePersonOptions(id);
  },

});
