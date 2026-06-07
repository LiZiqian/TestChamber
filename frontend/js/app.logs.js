/* ========================================
   数字治理平台 V7 - 日志模块
   ======================================== */

app.registerModule("app.logs", {

  // ---- 日志展示 ----
  toggleSampleHistoryItem(button) {
    const item = button.closest(".sample-history-item");
    if (!item) return;
    const expanded = item.classList.toggle("is-expanded");
    button.setAttribute("aria-expanded", String(expanded));
  },

  logHtml(l, seq = "", seqPrefix = "", task = null) {
    const seqHtml = seq ? `<span class="log-seq">${Utils.esc(seqPrefix)}${Utils.esc(seq)}</span>` : "";
    const rawContent = this.normalizeStatusText(String(l.reason || l.problemDescription || "").trim());
    const content = rawContent ? `<div class="task-log-text" title="${Utils.esc(rawContent)}">${this.linkSampleRefsInLogText(this.compactTaskLogText(rawContent), task, l)}</div>` : "";
    const actionTitle = this.normalizeStatusText(l.action || l.source || "-");
    return `<div class="log-line">${seqHtml}<b>${Utils.esc(actionTitle)}</b>
      <div class="task-log-meta">${Utils.esc(new Date(l.time).toLocaleString("zh-CN"))} | 操作人：${Utils.esc(l.user || "-")} | 状态：${Utils.esc(l.from || "-")} → ${Utils.esc(l.to || "-")} | 测试项：${Utils.esc(l.testItem || "-")}</div>
      ${content}</div>`;
  },

  // ---- 任务日志 ----
  ensureTaskLogs(t) {
    if (t && !Array.isArray(t.logs)) t.logs = [];
    return t?.logs || [];
  },
  taskLogSemanticKey(log = {}) {
    const lines = Array.isArray(log.detailLines) ? log.detailLines.map(x => String(x || "").trim()).filter(Boolean) : [];
    return [
      log.action,
      log.user,
      log.reason,
      log.detail,
      lines.join("\n"),
      log.fromStatus,
      log.toStatus,
    ].map(v => String(v || "").trim()).join("\u0001");
  },
  addTaskLog(t, action, ctx = {}) {
    if (!t) return;
    const logs = this.ensureTaskLogs(t);
    if (typeof this.ensureTaskSampleSnapshots === "function") this.ensureTaskSampleSnapshots(t);
    const next = {
      id: Utils.id("tasklog_"),
      time: Utils.now(),
      action,
      user: ctx.user || t.owner || "未填写",
      reason: ctx.reason || "",
      detail: ctx.detail || "",
      detailLines: Array.isArray(ctx.detailLines) ? ctx.detailLines : [],
      fromStatus: ctx.fromStatus || "",
      toStatus: ctx.toStatus || t.status || ""
    };
    const nextKey = this.taskLogSemanticKey(next);
    const nextTime = Date.parse(next.time) || Date.now();
    const duplicate = logs.find(log => {
      if (this.taskLogSemanticKey(log) !== nextKey) return false;
      const logTime = Date.parse(log.time) || 0;
      return logTime && Math.abs(nextTime - logTime) <= 5000;
    });
    if (duplicate) {
      this.ensureTaskLogSampleRefs(duplicate, t);
      return duplicate;
    }
    this.ensureTaskLogSampleRefs(next, t);
    logs.push(next);
    return next;
  },
  logSampleRefToken(token) {
    const clean = this.normalizeLogSampleRefCode(token);
    if (/^(SN|IMEI|主板SN)#/i.test(clean)) return clean;
    if (/^\d{12,18}$/.test(clean)) return `IMEI#${clean.slice(-4)}`;
    if (/^[A-Za-z0-9]{10,}$/.test(clean)) return `SN#${clean.slice(-4)}`;
    return clean;
  },
  logSampleRefPattern() {
    return /(?:SN|IMEI|主板SN)\s*#\s*[A-Za-z0-9-]+|\b\d{12,18}\b|\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}\b/g;
  },
  normalizeLogSampleRefCode(ref) {
    return String(ref || "")
      .trim()
      .replace(/[，,、;；。]+$/, "")
      .replace(/^(SN|IMEI|主板SN)\s*#\s*/i, (_m, label) => `${label.toUpperCase() === "SN" ? "SN" : label.toUpperCase() === "IMEI" ? "IMEI" : "主板SN"}#`);
  },
  isLabeledLogSampleRef(ref) {
    return /^(SN|IMEI|主板SN)\s*#/i.test(String(ref || "").trim());
  },
  compactTaskLogText(text) {
    const raw = String(text || "").trim();
    if (!raw) return "-";
    const converted = raw.replace(this.logSampleRefPattern(), token => this.logSampleRefToken(token));
    const refs = [...converted.matchAll(this.logSampleRefPattern())].map(x => this.normalizeLogSampleRefCode(x[0]));
    const uniqueRefs = [...new Set(refs)];
    const hasLabeledSections = /(退出样机|新增样机|新加样机|移除样机|加入样机)/.test(converted);
    if (uniqueRefs.length >= 4 && !hasLabeledSections) {
      const label = converted.includes("清空") ? "已清空任务样机"
        : converted.includes("移除") ? "已移除样机"
        : converted.includes("销毁") ? "涉及销毁样机"
        : converted.includes("样机") ? "涉及样机"
        : "样机";
      const shown = uniqueRefs.slice(0, 6).join("、");
      return `${label}：${shown}${uniqueRefs.length > 6 ? ` 等 ${uniqueRefs.length} 台` : ""}`;
    }
    return converted.length > 96 ? `${converted.slice(0, 96)}...` : converted;
  },
  taskLogContentText(log) {
    const action = String(log?.action || "").trim();
    const reason = String(log?.reason || "").trim();
    const detail = String(log?.detail || "").trim();
    let text = detail && (
      detail.includes("样机") ||
      ["分配样机", "重新分配样机", "临时变更", "样机池档案销毁"].some(x => action.includes(x))
    ) ? detail : (reason || detail);
    if (action.includes("阻塞") && text && !text.startsWith("阻塞")) text = `阻塞：${text}`;
    return this.normalizeStatusText(text);
  },
  taskLogDetailLines(log) {
    const action = String(log?.action || "").trim();
    if (Array.isArray(log?.detailLines) && log.detailLines.length) {
      return log.detailLines.map(x => String(x || "").trim()).filter(Boolean);
    }
    const text = this.taskLogContentText(log);
    if (action.includes("临时变更")) {
      return String(text || "")
        .split(/[；;\n]+/)
        .map(x => x.trim())
        .filter(Boolean);
    }
    return [String(text || "").trim()].filter(Boolean);
  },
  taskLogSampleRefMatches(value, code, suffix = "") {
    const ref = this.normalizeLogSampleRefCode(value);
    if (!ref) return false;
    if (ref === code) return true;
    return !!suffix && ref.endsWith(suffix);
  },
  taskLogSourceTexts(log = {}) {
    const texts = [];
    if (Array.isArray(log.detailLines)) texts.push(...log.detailLines);
    ["detail", "reason", "problemDescription"].forEach(key => {
      const value = String(log?.[key] || "").trim();
      if (value) texts.push(value);
    });
    return texts.map(text => String(text || "").trim()).filter(Boolean);
  },
  taskLogSampleRefs(log = {}, task = null) {
    if (!task) return [];
    const refs = [];
    const seen = new Set();
    this.taskLogSourceTexts(log).forEach(text => {
      for (const match of String(text || "").matchAll(this.logSampleRefPattern())) {
        const ref = this.normalizeLogSampleRefCode(match[0]);
        const sampleId = this.findLogSampleRefId(ref, task, null);
        if (!ref || !sampleId) continue;
        const key = `${ref}\u0001${sampleId}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const snap = task?.sampleSnapshots?.[sampleId] || {};
        refs.push({
          ref,
          sampleId,
          code: snap.code || snap.sampleNo || ref,
          sampleNo: snap.sampleNo || "",
          sn: snap.sn || "",
          imei: snap.imei || "",
          boardSn: snap.boardSn || ""
        });
      }
    });
    return refs;
  },
  ensureTaskLogSampleRefs(log, task = null) {
    if (!log || !task) return [];
    const refs = this.taskLogSampleRefs(log, task);
    if (refs.length) log.sampleRefs = refs;
    return refs;
  },
  appendTaskLogRichText(target, text, task = null, log = null) {
    const raw = this.normalizeStatusText(String(text || ""));
    const pattern = /(?:SN|IMEI|主板SN)\s*#\s*[A-Za-z0-9-]+|\b\d{12,18}\b|\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}\b|(?:通过|不通过)(\s*[（(][^)）]*[)）])?/g;
    let last = 0;
    for (const match of raw.matchAll(pattern)) {
      if (match.index > last) target.append(document.createTextNode(raw.slice(last, match.index)));
      const token = match[0];
      const sampleId = this.findLogSampleRefId(token, task, log);
      if (sampleId || this.isLabeledLogSampleRef(token)) {
        if (sampleId) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "sample-log-link";
          button.dataset.appAction = "sample-readonly";
          button.dataset.stopPropagation = "1";
          button.dataset.id = sampleId;
          button.textContent = this.normalizeLogSampleRefCode(token);
          target.append(button);
        } else {
          const missing = document.createElement("span");
          missing.className = "sample-log-ref-missing";
          missing.title = "样机档案不存在或已销毁";
          missing.textContent = this.normalizeLogSampleRefCode(token);
          target.append(missing);
        }
      } else if (/^(?:通过|不通过)/.test(token)) {
        const result = document.createElement("b");
        result.className = token.startsWith("通过") ? "log-result-pass" : "log-result-fail";
        result.textContent = token;
        target.append(result);
      } else {
        target.append(document.createTextNode(token));
      }
      last = match.index + token.length;
    }
    if (last < raw.length) target.append(document.createTextNode(raw.slice(last)));
  },
  taskLogTextNode(raw, task = null, log = null) {
    const node = document.createElement("div");
    node.className = "task-log-text";
    node.title = String(raw || "");
    this.appendTaskLogRichText(node, this.compactTaskLogText(raw), task, log);
    return node;
  },
  taskLogContentNode(log) {
    const lines = this.taskLogDetailLines(log);
    if (!lines.length) return null;
    const action = String(log?.action || "").trim();
    const isTempChange = action.includes("临时变更");
    const task = log.taskContext || null;

    if (lines.length === 1 && !isTempChange) {
      return this.taskLogTextNode(lines[0], task, log);
    }

    const node = document.createElement("div");
    node.className = "task-log-text task-log-text-multiline";
    lines.forEach(line => {
      const row = document.createElement("div");
      row.className = "task-log-detail-line";
      const idx = line.indexOf("：");
      if (idx > 0) {
        const label = document.createElement("span");
        label.className = "task-log-detail-label";
        label.textContent = line.slice(0, idx + 1);
        const value = document.createElement("span");
        value.className = "task-log-detail-value";
        this.appendTaskLogRichText(value, line.slice(idx + 1), task, log);
        row.append(label, value);
      } else {
        this.appendTaskLogRichText(row, line, task, log);
      }
      node.append(row);
    });
    return node;
  },
  findLogSampleRefId(ref, task = null, log = null) {
    const code = this.normalizeLogSampleRefCode(ref);
    if (!code) return "";
    const suffix = code.includes("#") ? code.split("#").pop() : "";
    const logRefHit = (log?.sampleRefs || []).find(item => {
      if (!item || !item.sampleId) return false;
      return [
        item.ref,
        item.code,
        item.sampleNo,
        item.sn,
        item.imei,
        item.boardSn,
      ].some(value => this.taskLogSampleRefMatches(value, code, suffix));
    });
    if (logRefHit) return String(logRefHit.sampleId || "");
    const snapshots = task?.sampleSnapshots || {};
    const snapHit = Object.entries(snapshots).find(([, snap]) => [
      snap?.code,
      snap?.sampleNo,
      snap?.sn,
      snap?.imei,
      snap?.boardSn,
    ].some(v => this.taskLogSampleRefMatches(v, code, suffix)));
    if (snapHit) return snapHit[0];
    const samples = typeof this.allSamples === "function" ? this.allSamples() : [];
    const candidates = samples.filter(s => {
      const refs = [
        typeof this.sampleDisplayCode === "function" ? this.sampleDisplayCode(s) : "",
        s.sampleNo,
        s.sn,
        s.imei,
        s.boardSn,
      ].map(v => this.normalizeLogSampleRefCode(v)).filter(Boolean);
      return refs.includes(code) || (suffix && refs.some(v => v.endsWith(suffix)));
    });
    if (!candidates.length) return "";
    const taskIds = new Set([
      ...(task?.sampleIds || []),
      ...(task?.removedSampleRecords || []).map(item => item?.sampleId).filter(Boolean)
    ]);
    if (taskIds.size) return candidates.find(s => taskIds.has(s.id))?.id || "";
    return candidates.length === 1 ? candidates[0].id || "" : "";
  },
  linkSampleRefsInLogText(text, task = null, log = null) {
    const str = this.normalizeStatusText(String(text || ""));
    const re = this.logSampleRefPattern();
    let html = "";
    let last = 0;
    for (const match of str.matchAll(re)) {
      const ref = match[0];
      html += Utils.esc(str.slice(last, match.index));
      const sampleId = this.findLogSampleRefId(ref, task, log);
      if (sampleId) {
        html += `<button type="button" class="sample-log-link" data-app-action="sample-readonly" data-stop-propagation="1" data-id="${Utils.esc(sampleId)}">${Utils.esc(this.normalizeLogSampleRefCode(ref))}</button>`;
      } else if (this.isLabeledLogSampleRef(ref)) {
        html += `<span class="sample-log-ref-missing" title="样机档案不存在或已销毁">${Utils.esc(this.normalizeLogSampleRefCode(ref))}</span>`;
      } else {
        html += Utils.esc(ref);
      }
      last = match.index + ref.length;
    }
    html += Utils.esc(str.slice(last));
    return this.highlightTestResult(html);
  },

  highlightTestResult(html) {
    return String(html || "").replace(
      /(通过|不通过)(\s*[（(][^)）]*[)）])?/g,
      (match, result) => {
        const isPass = result === "通过";
        return `<b class="${isPass ? 'log-result-pass' : 'log-result-fail'}">${match}</b>`;
      }
    );
  },
  taskLogNode(log, seq = "", task = null) {
    const logWithContext = { ...log, taskContext: task };
    const item = document.createElement("div");
    item.className = "task-log-item";
    if (seq) {
      const seqNode = document.createElement("span");
      seqNode.className = "log-seq";
      seqNode.textContent = `#${seq}`;
      item.append(seqNode);
    }
    const action = document.createElement("b");
    action.textContent = log.action || "-";
    item.append(action);

    const meta = document.createElement("div");
    meta.className = "task-log-meta";
    meta.textContent = `${new Date(log.time).toLocaleString("zh-CN")} | 操作人：${log.user || "-"} | 状态：${log.fromStatus || "-"} → ${log.toStatus || "-"}`;
    item.append(meta);

    const contentNode = this.taskLogContentNode(logWithContext);
    if (contentNode) {
      const content = document.createElement("div");
      content.className = "task-log-content";
      content.append(contentNode);
      item.append(content);
    }
    return item;
  },
  taskLogListNode(logs, task = null) {
    const list = document.createElement("div");
    list.className = "task-log-list";
    const ordered = (logs || []).slice().reverse();
    if (!ordered.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "暂无操作日志。";
      list.append(empty);
      return list;
    }
    ordered.forEach((log, idx) => {
      list.append(this.taskLogNode(log, String(ordered.length - idx), task));
    });
    return list;
  },
  async showTaskLogs(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    const loadingSamples = this.ensureTaskReferenceSamplesLoaded?.(t);
    if (loadingSamples?.then) await loadingSamples;
    const logs = this.ensureTaskLogs(t);
    const taskLabel = [p?.name, s?.name, t.testItem].filter(Boolean).join(" - ");
    this.showModal(`任务日志 · ${taskLabel}`, "", () => false, "关闭", {
      bodyNodes: [this.taskLogListNode(logs, t)]
    });
  }

});
