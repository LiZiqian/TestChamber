/* ========================================
   数字治理平台 V7 - 日志模块
   ======================================== */

Object.assign(app, {

  // ---- 日志展示 ----
  toggleSampleHistoryItem(button) {
    const item = button.closest(".sample-history-item");
    if (!item) return;
    const expanded = item.classList.toggle("is-expanded");
    button.setAttribute("aria-expanded", String(expanded));
  },

  logHtml(l, seq = "", seqPrefix = "") {
    const seqHtml = seq ? `<span class="log-seq">${Utils.esc(seqPrefix)}${Utils.esc(seq)}</span>` : "";
    const rawContent = String(l.reason || l.problemDescription || "").trim();
    const content = rawContent ? `<div class="task-log-text" title="${Utils.esc(rawContent)}">${this.linkSampleRefsInLogText(this.compactTaskLogText(rawContent), null)}</div>` : "";
    const actionTitle = l.action || l.source || "-";
    return `<div class="log-line">${seqHtml}<b>${Utils.esc(actionTitle)}</b>
      <div class="task-log-meta">${Utils.esc(new Date(l.time).toLocaleString("zh-CN"))} | 操作人：${Utils.esc(l.user || "-")} | 状态：${Utils.esc(l.from || "-")} → ${Utils.esc(l.to || "-")} | 测试项：${Utils.esc(l.testItem || "-")}</div>
      ${content}</div>`;
  },

  // ---- 任务日志 ----
  ensureTaskLogs(t) {
    if (t && !Array.isArray(t.logs)) t.logs = [];
    return t?.logs || [];
  },
  addTaskLog(t, action, ctx = {}) {
    if (!t) return;
    this.ensureTaskLogs(t);
    t.logs.push({
      id: Utils.id("tasklog_"),
      time: Utils.now(),
      action,
      user: ctx.user || t.owner || "未填写",
      reason: ctx.reason || "",
      detail: ctx.detail || "",
      detailLines: Array.isArray(ctx.detailLines) ? ctx.detailLines : [],
      fromStatus: ctx.fromStatus || "",
      toStatus: ctx.toStatus || t.status || ""
    });
  },
  logSampleRefToken(token) {
    const clean = String(token || "").trim().replace(/[，,、;；。]+$/, "");
    if (/^(SN|IMEI|主板SN)#/i.test(clean)) return clean;
    if (/^\d{12,18}$/.test(clean)) return `IMEI#${clean.slice(-4)}`;
    if (/^[A-Za-z0-9]{10,}$/.test(clean)) return `SN#${clean.slice(-4)}`;
    return clean;
  },
  compactTaskLogText(text) {
    const raw = String(text || "").trim();
    if (!raw) return "-";
    const converted = raw.replace(/(?:SN|IMEI|主板SN)#[A-Za-z0-9-]+|\b\d{12,18}\b|\b[A-Za-z0-9]{10,}\b/g, token => this.logSampleRefToken(token));
    const refs = [...converted.matchAll(/(?:SN|IMEI|主板SN)#[A-Za-z0-9-]+/g)].map(x => x[0]);
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
    return text;
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
  taskLogContentHtml(log) {
    const lines = this.taskLogDetailLines(log);
    if (!lines.length) return "";
    const action = String(log?.action || "").trim();
    const isTempChange = action.includes("临时变更");

    if (lines.length === 1 && !isTempChange) {
      const raw = lines[0];
      return `<div class="task-log-text" title="${Utils.esc(raw)}">${this.linkSampleRefsInLogText(this.compactTaskLogText(raw), log.taskContext || null)}</div>`;
    }

    return `<div class="task-log-text task-log-text-multiline">
      ${lines.map(line => {
        const idx = line.indexOf("：");
        if (idx > 0) {
          const label = line.slice(0, idx + 1);
          const value = line.slice(idx + 1);
          return `<div class="task-log-detail-line"><span class="task-log-detail-label">${Utils.esc(label)}</span><span class="task-log-detail-value">${this.linkSampleRefsInLogText(value, log.taskContext || null)}</span></div>`;
        }
        return `<div class="task-log-detail-line">${this.linkSampleRefsInLogText(line, log.taskContext || null)}</div>`;
      }).join("")}
    </div>`;
  },
  findLogSampleRefId(ref, task = null) {
    const code = String(ref || "").trim();
    if (!code) return "";
    const snapshots = task?.sampleSnapshots || {};
    const snapHit = Object.entries(snapshots).find(([, snap]) => String(snap?.code || "").trim() === code);
    if (snapHit) return snapHit[0];
    const suffix = code.includes("#") ? code.split("#").pop() : "";
    const candidates = this.allSamples().filter(s =>
      this.sampleDisplayCode(s) === code ||
      (suffix && [s.sn, s.imei, s.boardSn, s.sampleNo].some(v => String(v || "").trim().endsWith(suffix)))
    );
    if (!candidates.length) return "";
    const taskIds = new Set([
      ...(task?.sampleIds || []),
      ...(task?.removedSampleRecords || []).map(item => item?.sampleId).filter(Boolean)
    ]);
    return candidates.find(s => taskIds.has(s.id))?.id || "";
  },
  linkSampleRefsInLogText(text, task = null) {
    const str = String(text || "");
    const re = /(?:SN|IMEI|主板SN)#[A-Za-z0-9-]+/g;
    let html = "";
    let last = 0;
    for (const match of str.matchAll(re)) {
      const ref = match[0];
      html += Utils.esc(str.slice(last, match.index));
      const sampleId = this.findLogSampleRefId(ref, task);
      html += sampleId
        ? `<button type="button" class="sample-log-link" onclick="event.stopPropagation();app.openSampleReadonly('${Utils.esc(sampleId)}')">${Utils.esc(ref)}</button>`
        : `<span class="sample-log-ref-missing" title="样机档案不存在或已销毁">${Utils.esc(ref)}</span>`;
      last = match.index + ref.length;
    }
    html += Utils.esc(str.slice(last));
    return this.highlightTestResult(html);
  },

  highlightTestResult(html) {
    return String(html || "").replace(
      /\b(Pass|PASS|pass|Fail|FAIL|fail)\b(\s*[（(][^)）]*[)）])?/g,
      (match, result) => {
        const isPass = /^pass$/i.test(result);
        return `<b class="${isPass ? 'log-result-pass' : 'log-result-fail'}">${match}</b>`;
      }
    );
  },
  taskLogHtml(log, seq = "", task = null) {
    const logWithContext = { ...log, taskContext: task };
    const seqHtml = seq ? `<span class="log-seq">#${Utils.esc(seq)}</span>` : "";
    return `<div class="task-log-item">
      ${seqHtml}<b>${Utils.esc(log.action || "-")}</b>
      <div class="task-log-meta">${Utils.esc(new Date(log.time).toLocaleString("zh-CN"))} | 操作人：${Utils.esc(log.user || "-")} | 状态：${Utils.esc(log.fromStatus || "-")} → ${Utils.esc(log.toStatus || "-")}</div>
      ${this.taskLogContentHtml(logWithContext)}
    </div>`;
  },
  showTaskLogs(projectId, stageId, taskId) {
    const { p, s, t } = this.getProjectStageTask(projectId, stageId, taskId);
    if (!t) return;
    const logs = this.ensureTaskLogs(t);
    const taskLabel = [p?.name, s?.name, t.testItem].filter(Boolean).join(" - ");
    const items = logs.slice().reverse().map((log, idx) => this.taskLogHtml(log, String(logs.length - idx), t)).join("") || '<div class="empty">暂无操作日志。</div>';
    this.showModal(`任务日志 · ${Utils.esc(taskLabel)}`, `<div class="task-log-list">${items}</div>`, () => false, "关闭");
  }

});
