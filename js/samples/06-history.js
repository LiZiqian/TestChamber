/* ========================================
   TestChamber V7 - Sample test history
   Split from the previous monolithic module.
   ======================================== */

Object.assign(app, {

  switchSampleArchiveTab(tab) {
    document.querySelectorAll("[data-sample-archive-tab]").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.sampleArchiveTab === tab);
    });
    document.querySelectorAll("[data-sample-archive-panel]").forEach(panel => {
      panel.classList.toggle("active", panel.dataset.sampleArchivePanel === tab);
    });
    // 更新 footer 说明文字
    const hints = {
      info: "查看与编辑样机的基本档案，包括身份标识、当前状态、存放位置、人员归属及初检问题记录。",
      history: "该样机参与过的全部测试任务记录，含测试结果、故障标记与状态变更日志。",
      photos: "外观照片、失效分析图片、问题定位截图等。图片随样机档案一起保存，不随任务结束而清除。",
      ct: "归档 CT 扫描图像、扫描批次、三维结构分析结论等工业 CT 数据。",
      other: "预留扩展区。后续可在此定义更多样机维度的数据归档功能。"
    };
    const hint = document.getElementById("sampleArchiveFooterHint");
    if (hint) hint.textContent = hints[tab] || "";
    if ((tab === "photos" || tab === "history") && this._activeSampleDetailId) {
      const sample = this.findSample(this._activeSampleDetailId)?.sample;
      if (sample && ((tab === "photos" && sample.photosLoaded !== true) || (tab === "history" && sample.eventsLoaded !== true))) {
        this.ensureSampleDetailsLoaded(this._activeSampleDetailId, {
          photos: tab === "photos",
          events: tab === "history",
          renderPanels: true
        }).catch(e => {
          console.error("加载样机详情数据失败：", e);
          Utils.toast("样机详情数据加载失败：" + (e.message || e));
        });
      }
    }
  },

  sampleTaskResultPhotos(task, sampleId) {
    if (!task) return [];
    const sample = this.findSample(sampleId)?.sample || {};
    const photoById = new Map((sample.photos || []).filter(p => p?.id).map(p => [p.id, p]));
    const photos = [];
    (task.resultUploads || []).forEach(upload => {
      (upload.samples || [])
        .filter(item => item?.sampleId === sampleId)
        .forEach(item => {
          (item.photos || []).forEach(ref => {
            if (!ref?.id) return;
            const full = photoById.get(ref.id) || {};
            photos.push({
              id: ref.id,
              name: ref.name || full.name || "结果图片",
              url: ref.url || full.url || "",
              thumbUrl: ref.thumbUrl || ref.thumbnailUrl || full.thumbUrl || full.thumbnailUrl || "",
              uploadedAt: ref.uploadedAt || full.uploadedAt || upload.time || "",
              result: upload.result || "",
              user: upload.user || "",
              uploadTime: upload.time || ""
            });
          });
        });
    });
    const seen = new Set();
    return photos.filter(photo => {
      const key = `${photo.uploadTime || ""}_${photo.id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  },

  sampleHistoryPhotosHtml(sampleId, photos = []) {
    if (!photos.length) return "";
    return `<div class="sample-history-photos">
      <div class="sample-history-photos-title">结果图片</div>
      <div class="sample-history-photo-grid">
        ${photos.map(photo => `
          <button type="button" class="sample-history-photo" onclick="app.previewSamplePhoto('${Utils.esc(sampleId)}','${Utils.esc(photo.id)}')" title="${Utils.esc(photo.name || "结果图片")}">
            ${this.photoThumbUrl(photo) ? `<img src="${Utils.esc(this.photoThumbUrl(photo))}" alt="${Utils.esc(photo.name || "结果图片")}">` : ""}
            <span>${Utils.esc(photo.result || "-")} · ${Utils.esc(photo.user || "-")}</span>
          </button>
        `).join("")}
      </div>
    </div>`;
  },

  sampleEventLogsForSample(sampleId) {
    return (this.data?.sampleLibrary?.logs || []).filter(log => String(log?.sampleId || "") === String(sampleId));
  },

  sampleTestHistoryHtml(sampleId) {
    const sample = this.findSample(sampleId)?.sample;
    if (sample && sample.eventsLoaded !== true) {
      return this.sampleArchivePlaceholder("正在加载测试履历", "样机状态事件已按需外置，打开履历时从服务器读取。");
    }
    const sampleLogsAll = this.sampleEventLogsForSample(sampleId);
    const rows = new Map();
    sampleLogsAll.forEach(log => {
      const key = log.taskId || `log_${log.id}`;
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          task: null,
          projectName: log.projectName || this.projectName(log.projectId),
          stageName: log.stageName || this.stageName(log.projectId, log.stageId),
          testItem: log.testItem || "-",
          logs: []
        });
      }
      rows.get(key).logs.push(log);
    });
    (this.data.projects || []).forEach(project => (project.stages || []).forEach(stage => (stage.tasks || []).forEach(task => {
      const taskOwnsSample = (task.sampleIds || []).includes(sampleId)
        || (task.removedSampleRecords || []).some(item => item?.sampleId === sampleId);
      const taskTouchedSample = rows.has(task.id);
      if (!taskOwnsSample && !taskTouchedSample) return;
      const key = task.id;
      if (!rows.has(key)) {
        rows.set(key, { key, task, projectName: project.name, stageName: stage.name, testItem: task.testItem || "-", logs: [] });
      }
      const item = rows.get(key);
      item.task = task;
      item.projectName = project.name;
      item.stageName = stage.name;
      item.testItem = task.testItem || item.testItem || "-";
    })));
    const list = [...rows.values()].sort((a, b) => {
      const at = a.task?.completedAt || a.task?.resultDate || a.task?.startDate || a.logs[0]?.time || "";
      const bt = b.task?.completedAt || b.task?.resultDate || b.task?.startDate || b.logs[0]?.time || "";
      return String(bt).localeCompare(String(at));
    });
    if (!list.length) return this.sampleArchivePlaceholder("暂无测试履历", "该样机还没有被分配到任何测试任务。");

    return `<div class="sample-history-list">${list.map(({ task, projectName, stageName, testItem, logs }, idx) => {
      const historySeq = list.length - idx;
      const status = task ? this.taskFlowStatus(task) : "历史记录";
      const result = task?.latestResult || task?.result || "-";
      const date = task?.resultDate || task?.completedAt || task?.planDate || logs[logs.length - 1]?.time || "-";
      const taskSampleCount = task
        ? new Set([...(task.sampleIds || []), ...(task.removedSampleRecords || []).map(item => item?.sampleId).filter(Boolean)]).size
        : 0;
      const sampleFaultRecords = (task?.sampleFaultRecords || []).filter(x => x.sampleId === sampleId);
      const faultMarked = logs.some(log => log.faultMarked || log.flowStatus === "故障")
        || !!(task?.sampleFaults?.[sampleId]?.fault)
        || sampleFaultRecords.some(x => x.fault || x.problem);
      const problems = [...new Set([
        ...logs.map(log => log.problemDescription).filter(Boolean),
        task?.sampleFaults?.[sampleId]?.problem,
        ...sampleFaultRecords.map(x => x.problem).filter(Boolean)
      ].filter(Boolean))];
      const resultPhotos = this.sampleTaskResultPhotos(task, sampleId);
      const orderedLogs = logs.slice().reverse();
      return `<div class="sample-history-item">
        <button type="button" class="sample-history-summary" aria-expanded="false" onclick="app.toggleSampleHistoryItem(this)">
          <span class="history-seq">履历 #${historySeq}</span>
          <b>${Utils.esc(testItem || "-")}</b>
          <span class="badge s-${Utils.esc(status)}">${Utils.esc(status)}</span>
          <span class="badge ${faultMarked ? "status-bad" : "status-done"}">${faultMarked ? "已标记故障" : "未标记故障"}</span>
          <span class="sample-history-toggle"></span>
        </button>
        <div class="sample-history-detail">
          <div class="sample-history-grid">
            <span>任务ID：<b>${Utils.esc(task?.id || logs[0]?.taskId || "-")}</b></span>
            <span>项目：<b>${Utils.esc(projectName || "-")}</b></span>
            <span>阶段：<b>${Utils.esc(stageName || "-")}</b></span>
            <span>执行人：<b>${Utils.esc(task?.owner || logs[0]?.user || "-")}</b></span>
            <span>结果：<b>${Utils.esc(result)}</b></span>
            <span>日期：<b>${Utils.esc(date)}</b></span>
            <span>样机数：<b>${taskSampleCount || "-"} 台</b></span>
          </div>
          ${problems.length ? `<div class="sample-history-problems">问题：${problems.map(x => Utils.esc(x)).join("；")}</div>` : ""}
          ${this.sampleHistoryPhotosHtml(sampleId, resultPhotos)}
          ${orderedLogs.length ? `<div class="sample-history-logs">${orderedLogs.map((log, logIdx) => this.logHtml(log, orderedLogs.length - logIdx, "日志 #")).join("")}</div>` : `<div class="path">暂无该任务下的样机状态记录。</div>`}
        </div>
      </div>`;
    }).join("")}</div>`;
  },

  // ---- 样机数字档案（含 IMEI）----,

  findSampleSnapshot(sampleId) {
    for (const project of (this.data.projects || [])) {
      for (const stage of (project.stages || [])) {
        for (const task of (stage.tasks || [])) {
          const snap = task?.sampleSnapshots?.[sampleId];
          if (snap) return { snapshot: snap, project, stage, task };
        }
      }
    }
    return null;
  },

  openSampleReadonly(sampleId) {
    const found = this.findSample(sampleId);
    if (found) {
      this.openSampleDetail(sampleId, { readonly: true });
      return;
    }
    const hit = this.findSampleSnapshot(sampleId);
    if (!hit) { alert("该样机档案不存在，可能已被销毁且没有保留快照。"); return; }
    const snap = hit.snapshot;
    this.showModal("样机档案快照：" + (snap.code || sampleId), `
      <div class="sample-archive-summary">
        <div><span>档案编号</span><b>${Utils.esc(snap.code || sampleId)}</b></div>
        <div><span>所属样机池</span><b>${Utils.esc(snap.categoryName || "-")}</b></div>
        <div><span>快照时间</span><b>${Utils.esc(snap.destroyedAt || "-")}</b></div>
      </div>
      <div class="sample-archive-summary">
        <div><span>SN</span><b>${Utils.esc(snap.sn || "-")}</b></div>
        <div><span>IMEI</span><b>${Utils.esc(snap.imei || "-")}</b></div>
        <div><span>主板SN</span><b>${Utils.esc(snap.boardSn || "-")}</b></div>
      </div>
      <div class="empty">该样机档案已销毁，这里仅显示任务日志保留的只读快照。</div>
    `, () => false, "关闭", { hideCancel: true, className: "sample-archive-modal", headerHint: "只读快照，不能编辑" });
  },

});
