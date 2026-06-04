/* ========================================
   数字治理平台 V7 - 服务器通信模块
   ======================================== */

app.registerModule("app.server", {

  // ---- 服务器通信 ----
  async fetchBootstrapState() {
    const res = await fetch("/api/bootstrap", { cache: "no-store" });
    const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
    return obj;
  },

  updateServerStatus(extraText = "") {
    const el = document.getElementById("saveState");
    if (!el) return;
    if (this.serverOnline) {
      const t = this.serverUpdatedAt ? new Date(this.serverUpdatedAt).toLocaleString("zh-CN") : "-";
      const full = `已连接 · rev ${this.serverRevision} · ${t}${extraText ? " · " + extraText : ""}`;
      el.innerText = extraText || "同步正常";
      el.title = full;
    } else {
      el.innerText = extraText || "未连接服务器";
      el.title = `未连接 · 数据无法保存${extraText ? " · " + extraText : ""}`;
    }
  },

  fullStateUrl(reason = "manual-full-reload") {
    const query = new URLSearchParams();
    query.set("reason", String(reason || "unspecified"));
    return `/api/state?${query.toString()}`;
  },

  async reloadFromServer({ render = true, reason = "manual-full-reload" } = {}) {
    const res = await fetch(this.fullStateUrl(reason), { cache: "no-store" });
    const obj = await res.json();
    if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
    this.data = obj.data || this.emptyData();
    this.serverRevision = obj.revision || 0;
    this.serverUpdatedAt = obj.updated_at || null;
    this.serverOnline = true;
    this._statePartial = false;
    this.normalize();
    this._baseData = this.cloneData(this.data);
    this.view.selectedProjectId = this.data.currentProjectId || this.data.projects[0]?.id || null;
    this.view.selectedStageId = this.data.currentStageId || this.currentProject()?.stages?.[0]?.id || null;
    if (render) this.render();
    this.updateServerStatus("已刷新");
    if (this._normalizedChanged) {
      this._normalizedChanged = false;
      this.updateServerStatus("已刷新，需检查");
    }
  },

  scheduleSave({ delay = 450, remark = "" } = {}) {
    clearTimeout(this._saveTimer);
    this._queuedRemark = remark || this._queuedRemark || "";
    this.updateServerStatus("待同步");
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      const queuedRemark = this._queuedRemark;
      this._queuedRemark = "";
      this.save({ silent: true, remark: queuedRemark });
    }, delay);
  },

  async save({ silent = false, remark = "", retryOnConflict = true } = {}) {
    if (this._statePartial) {
      if (!silent) alert("当前仍处于摘要加载模式，此入口需要先加载完整数据。请稍后重试或刷新页面。");
      this.updateServerStatus("需完整加载");
      return false;
    }
    if (this._saveTimer) {
      clearTimeout(this._saveTimer);
      this._saveTimer = null;
    }
    if (this._saveInFlight) {
      this._saveQueued = true;
      this._queuedRemark = remark || this._queuedRemark || "";
      this.updateServerStatus("待同步");
      return true;
    }
    this.data.currentProjectId = this.view.selectedProjectId;
    this.data.currentStageId = this.view.selectedStageId;
    if (!this.serverOnline && !silent) {
      this.updateServerStatus("保存失败");
      return false;
    }
    this._saveInFlight = true;
    try {
      const res = await fetch("/api/state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision: this.serverRevision,
          baseData: this._baseData || this.data,
          appVersion: this.version,
          remark,
          data: this.data
        })
      });
      const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (res.status === 409 && obj.error_code === "SAMPLE_OCCUPANCY_CONFLICT") {
        // C1：样机占用冲突——服务器拒绝保存，不能静默 reload（会丢弃本地编辑）
        this.updateServerStatus("样机占用冲突");
        this._saveQueued = false;
        this._queuedRemark = "";
        const conflicts = Array.isArray(obj.conflicts) ? obj.conflicts : [];
        const detail = conflicts.slice(0, 5).map(c => {
          const sample = this.findSample?.(c.sampleId);
          const sampleName = sample?.sample?.sampleNo || sample?.sample?.sn || c.sampleId;
          const items = (c.tasks || []).map(t => t.testItem || "未命名任务").join("、");
          return `· 样机 ${sampleName}：被「${items}」同时占用`;
        }).join("\n");
        alert(`保存被拒绝：样机占用冲突。\n\n同一样机不能被多个未完成任务同时占用：\n${detail}\n\n请先释放或结束其中一个任务的样机后再保存。`);
        return false;
      }
      if (res.status === 409) {
        this.updateServerStatus("保存冲突");
        this._saveQueued = false;
        this._queuedRemark = "";
        if (!silent) alert("保存冲突：服务器上的数据已被其他人更新。\n\n请刷新页面后再继续操作。");
        return false;
      }
      if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
      this.serverRevision = obj.revision || this.serverRevision;
      this.serverUpdatedAt = obj.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已保存");
      return true;
    } catch (e) {
      console.error("保存到服务器失败：", e);
      this.serverOnline = false;
      this.updateServerStatus("保存失败");
      if (!silent) alert("保存失败：" + e.message);
      return false;
    } finally {
      this._saveInFlight = false;
      if (this._saveQueued && this.serverOnline) {
        this._saveQueued = false;
        const queuedRemark = this._queuedRemark;
        this._queuedRemark = "";
        setTimeout(() => this.save({ silent: true, remark: queuedRemark, retryOnConflict: false }), 0);
      }
    }
  },

  // ---- 直接变更辅助（照片上传/删除等绕过 save() 的接口） ----

  hasLocalUnsavedChanges() {
    return JSON.stringify(this.data || {}) !== JSON.stringify(this._baseData || {});
  },

  async prepareBeforeDirectMutation(remark = "直接变更前同步") {
    // 1. 清掉待执行的 debounce 保存
    if (this._saveTimer) {
      clearTimeout(this._saveTimer);
      this._saveTimer = null;
    }
    // 2. 等待当前正在进行的保存完成（最多等 3 秒）
    if (this._saveInFlight) {
      let waited = 0;
      while (this._saveInFlight && waited < 3000) {
        await new Promise(r => setTimeout(r, 100));
        waited += 100;
      }
      if (this._saveInFlight) {
        alert("正在保存中，请稍后重试。");
        return false;
      }
    }
    // 3. 如果本地有未保存编辑，先保存再继续
    if (this.hasLocalUnsavedChanges()) {
      alert(`${remark}失败：当前还有未保存的本地编辑。请先完成当前编辑，再重试。`);
      this.updateServerStatus("有未保存编辑");
      return false;
    }
    return true;
  },

  async syncAfterDirectMutation({ render = false, statusText = "已保存" } = {}) {
    if (render && typeof this.render === "function") this.render();
    this.updateServerStatus(statusText);
  },

  applySamplePhotosMutationResult(sampleId, json = {}, { renderPanel = false, statusText = "已保存" } = {}) {
    const found = this.findSample(sampleId);
    this.serverRevision = json.revision || json.newRevision || this.serverRevision;
    this.serverUpdatedAt = json.updated_at || json.updatedAt || new Date().toISOString();
    this.serverOnline = true;

    if (found?.sample && Array.isArray(json.photos)) {
      found.sample.photos = json.photos;
      found.sample.photoCount = json.photos.length;
      found.sample.photosLoaded = true;
      found.sample.updatedAt = json.updated_at || json.updatedAt || Utils.now();
    }

    if (found?.category?.id) this.invalidatePagedCaches({ categoryId: found.category.id });
    this.invalidateSampleHistoryCache(sampleId);
    this._baseData = this.cloneData(this.data);

    if (renderPanel) {
      const panel = document.querySelector('[data-sample-archive-panel="photos"]');
      if (panel && found?.sample) this.replaceHtml(panel, this.samplePhotosHtml(found.sample));
    }

    this.updateServerStatus(statusText);
    return found?.sample || null;
  },

  invalidateSampleHistoryCache(sampleIds = []) {
    const ids = Array.isArray(sampleIds) ? sampleIds : [sampleIds];
    if (!this._sampleHistoryCache) return;
    ids.map(id => String(id || "")).filter(Boolean).forEach(id => {
      delete this._sampleHistoryCache[id];
      const sample = this.findSample(id)?.sample;
      if (sample) sample.historyLoaded = false;
    });
  },

  taskFlowQueryHasFilters(params = {}) {
    return ["sku", "flowStatus", "ownerName", "categoryKeyword", "caseKeyword", "dtsKeyword", "resultKeyword"]
      .some(key => String(params?.[key] || "").trim());
  },

  samplePageQueryHasFilters(params = {}) {
    return ["keyword", "status", "problemState", "owner", "borrower"]
      .some(key => String(params?.[key] || "").trim());
  },

  applyTaskStatusCountDelta(target, changes = []) {
    if (!target || !changes.length) return;
    const counts = { ...(target.statusCounts || {}) };
    changes.forEach(change => {
      const before = String(change.beforeStatus || "").trim();
      const after = String(change.afterStatus || "").trim();
      if (!before || !after || before === after) return;
      counts[before] = Math.max(0, Number(counts[before] || 0) - 1);
      counts[after] = Number(counts[after] || 0) + 1;
    });
    target.statusCounts = counts;
  },

  tryPatchCurrentTaskFlowPage(project, stage, affected = {}) {
    if (!stage?.id || !affected || affected.tasksTruncated) return false;
    if (!this._taskFlowPageCache || typeof this.taskFlowQueryParams !== "function" || typeof this.taskFlowCacheKey !== "function") return false;
    const isCurrentTaskFlow = this.view?.module === "projectWorkspace"
      && String(this.view?.selectedStageId || "") === String(stage.id || "");
    if (!isCurrentTaskFlow) return false;
    const params = this.taskFlowQueryParams(stage);
    if (this.taskFlowQueryHasFilters(params)) return false;
    const key = this.taskFlowCacheKey(stage, params);
    const cache = this._taskFlowPageCache?.key === key ? this._taskFlowPageCache : null;
    if (!cache || !Array.isArray(cache.rows)) return false;

    const affectedTasks = (affected.tasks || []).filter(task => String(task?.stageId || "") === String(stage.id || ""));
    const affectedTaskIds = (affected.taskIds || []).filter(Boolean).map(id => String(id));
    if (!affectedTaskIds.length || affectedTasks.length !== affectedTaskIds.length) return false;

    const rowByTaskId = new Map(cache.rows.map(row => [String(row?.task?.id || ""), row]));
    if (!affectedTaskIds.every(id => rowByTaskId.has(id))) return false;

    const stageTasksById = new Map((stage.tasks || []).map(task => [String(task.id || ""), task]));
    affectedTasks.forEach(task => {
      const id = String(task.id || "");
      const row = rowByTaskId.get(id);
      const mergedTask = stageTasksById.get(id) || task;
      if (row) row.task = mergedTask;
    });

    const statusChanges = (this._lastMutationAffectedChanges?.taskStatus || [])
      .filter(change => String(change.stageId || "") === String(stage.id || "") && affectedTaskIds.includes(String(change.taskId || "")));
    if (cache.stats) this.applyTaskStatusCountDelta(cache.stats, statusChanges);
    this.applyTaskStatusCountDelta(stage, statusChanges);

    if (cache.stats) {
      const ownerNames = new Set(cache.stats.ownerNames || stage.ownerNames || []);
      affectedTasks.forEach(task => {
        const ownerName = this.taskOwnerName?.(task.owner || "") || "";
        if (ownerName) ownerNames.add(ownerName);
      });
      cache.stats.ownerNames = [...ownerNames].sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true }));
      stage.ownerNames = cache.stats.ownerNames;
    }

    this.refreshTaskFlowRegion(project, stage);
    return true;
  },

  async refreshTaskListAfterMutation(project, stage, { render = true, affected = null } = {}) {
    if (!stage?.id) return false;
    const isCurrentTaskFlow = this.view?.module === "projectWorkspace"
      && String(this.view?.selectedStageId || "") === String(stage.id || "");
    if (render && isCurrentTaskFlow && typeof this.refreshCurrentTaskFlowPage === "function") {
      if (this.tryPatchCurrentTaskFlowPage(project, stage, affected)) return true;
      this.invalidatePagedCaches({ stageId: stage.id });
      await this.refreshCurrentTaskFlowPage(project, stage);
      return true;
    }
    this.invalidatePagedCaches({ stageId: stage.id });
    if (render) this.render();
    return false;
  },

  tryPatchCurrentSamplePage(category, affected = {}) {
    if (!category?.id || !affected || affected.samplesTruncated) return false;
    if (typeof this.samplePageQueryParams !== "function" || typeof this.samplePageCacheKey !== "function") return false;
    const isCurrentSamplePage = this.view?.module === "samples"
      && String(this.view?.selectedCategoryId || "") === String(category.id || "");
    if (!isCurrentSamplePage) return false;
    const params = this.samplePageQueryParams(category);
    if (this.samplePageQueryHasFilters(params)) return false;
    const key = this.samplePageCacheKey(category, params);
    const cache = this.getSamplePageCache?.(key) || (this._samplePageCache?.key === key ? this._samplePageCache : null);
    if (!cache || !Array.isArray(cache.items)) return false;

    const affectedSamples = (affected.samples || []).filter(sample => String(sample?.categoryId || "") === String(category.id || ""));
    const affectedSampleIds = (affected.sampleIds || []).filter(Boolean).map(id => String(id));
    if (!affectedSampleIds.length || affectedSamples.length !== affectedSampleIds.length) return false;

    const itemById = new Map(cache.items.map(sample => [String(sample?.id || ""), sample]));
    if (!affectedSampleIds.every(id => itemById.has(id))) return false;

    const categorySamplesById = new Map((category.samples || []).map(sample => [String(sample.id || ""), sample]));
    cache.items = cache.items.map(sample => {
      const id = String(sample?.id || "");
      return affectedSampleIds.includes(id) ? (categorySamplesById.get(id) || sample) : sample;
    });
    if (cache.stats) {
      cache.stats.statusCounts = category.statusCounts || cache.stats.statusCounts || {};
      cache.stats.problemCounts = category.problemCounts || cache.stats.problemCounts || {};
      cache.stats.totalInCategory = category.sampleCount ?? cache.stats.totalInCategory;
    }
    this.setSamplePageCache?.(cache);
    this.refreshSamplePageRegion(category);
    return true;
  },

  async refreshSampleListAfterMutation(sampleOrCategory, { render = true, affected = null } = {}) {
    const categoryId = sampleOrCategory?.categoryId || sampleOrCategory?.id || "";
    if (!categoryId) return false;
    const category = this.data?.sampleLibrary?.categories?.find(c => String(c.id || "") === String(categoryId));
    const isCurrentSamplePage = category
      && this.view?.module === "samples"
      && String(this.view?.selectedCategoryId || "") === String(category.id || "");
    if (render && isCurrentSamplePage && typeof this.refreshCurrentSamplePage === "function") {
      if (this.tryPatchCurrentSamplePage(category, affected)) return true;
      this.invalidatePagedCaches({ categoryId });
      await this.refreshCurrentSamplePage(category);
      return true;
    }
    this.invalidatePagedCaches({ categoryId });
    if (render) this.render();
    return false;
  },

  async fetchSamplePhotos(sampleId) {
    const resp = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/photos`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json.photos || [];
  },

  async fetchSampleEvents(sampleId) {
    const resp = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/events`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json.logs || [];
  },

  async fetchSampleHistory(sampleId, { page = 1, pageSize = 20 } = {}) {
    const params = new URLSearchParams();
    params.set("page", String(page || 1));
    params.set("pageSize", String(pageSize || 20));
    const resp = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/history?${params.toString()}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json;
  },

  async checkSampleIdentityConflicts(samples = [], { categoryId = "" } = {}) {
    const list = Array.isArray(samples) ? samples : [samples];
    const resp = await fetch("/api/sample-identity-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ categoryId, samples: list }),
    });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json;
  },

  async fetchProjectSummary() {
    const resp = await fetch("/api/projects/summary", { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json.projects || [];
  },

  async fetchStageTasksPage(stageId, params = {}) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) query.set(key, value);
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const resp = await fetch(`/api/stages/${encodeURIComponent(stageId)}/tasks${suffix}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json;
  },

  async fetchSampleCategoriesSummary() {
    const resp = await fetch("/api/sample-categories", { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json.categories || [];
  },

  async fetchSamplePage(categoryId, params = {}) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) query.set(key, value);
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const resp = await fetch(`/api/sample-categories/${encodeURIComponent(categoryId)}/samples${suffix}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json;
  },

  async fetchTaskSampleCandidates(params = {}) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (Array.isArray(value)) {
        if (value.length) query.set(key, value.join(","));
      } else if (value !== "" && value !== null && value !== undefined) {
        query.set(key, value);
      }
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const resp = await fetch(`/api/task-sample-candidates${suffix}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json;
  },

  async fetchSampleDestroyImpactScope(params = {}) {
    const query = new URLSearchParams();
    ["sampleId", "categoryId"].forEach(key => {
      const value = String(params?.[key] || "").trim();
      if (value) query.set(key, value);
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const resp = await fetch(`/api/sample-destroy-impact${suffix}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json;
  },

  async fetchProjectDetail(projectId, { includeTasks = false } = {}) {
    const suffix = includeTasks ? "?includeTasks=1" : "";
    const resp = await fetch(`/api/projects/${encodeURIComponent(projectId)}${suffix}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json.project || null;
  },

  async fetchSampleCategoryDetail(categoryId, { includePhotos = false } = {}) {
    const suffix = includePhotos ? "?includePhotos=1" : "";
    const resp = await fetch(`/api/sample-categories/${encodeURIComponent(categoryId)}${suffix}`, { cache: "no-store" });
    const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
    if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
    return json.category || null;
  },

  mergeProjectDetail(project, { includeTasks = false } = {}) {
    if (!project?.id) return null;
    if (!Array.isArray(project.stages)) project.stages = [];
    const idx = (this.data.projects || []).findIndex(item => String(item.id || "") === String(project.id));
    const existing = idx >= 0 ? this.data.projects[idx] : null;
    if (existing && !includeTasks) {
      const existingStages = new Map((existing.stages || []).map(stage => [String(stage.id || ""), stage]));
      project.stages.forEach(stage => {
        const oldStage = existingStages.get(String(stage.id || ""));
        if (oldStage?.tasks?.length) stage.tasks = oldStage.tasks;
        else if (!Array.isArray(stage.tasks)) stage.tasks = [];
      });
    }
    project._summaryOnly = false;
    project._detailLoaded = true;
    project._tasksFullyLoaded = !!includeTasks;
    if (idx >= 0) this.data.projects[idx] = { ...existing, ...project };
    else this.data.projects.push(project);
    return this.data.projects.find(item => String(item.id || "") === String(project.id)) || project;
  },

  mergeSampleCategoryDetail(category) {
    if (!category?.id) return null;
    if (!Array.isArray(category.samples)) category.samples = [];
    const idx = (this.data.sampleLibrary.categories || []).findIndex(item => String(item.id || "") === String(category.id));
    const existing = idx >= 0 ? this.data.sampleLibrary.categories[idx] : null;
    if (existing) {
      const existingSamples = new Map((existing.samples || []).map(sample => [String(sample.id || ""), sample]));
      category.samples = category.samples.map(sample => {
        const oldSample = existingSamples.get(String(sample.id || ""));
        if (oldSample?.photosLoaded && !sample.photosLoaded) {
          sample.photos = oldSample.photos || [];
          sample.photoCount = sample.photos.length;
          sample.photosLoaded = true;
        }
        if (oldSample?.eventsLoaded) sample.eventsLoaded = true;
        return oldSample ? { ...oldSample, ...sample } : sample;
      });
    }
    category._summaryOnly = false;
    category.samplesLoaded = true;
    if (idx >= 0) this.data.sampleLibrary.categories[idx] = { ...existing, ...category };
    else this.data.sampleLibrary.categories.push(category);
    return this.data.sampleLibrary.categories.find(item => String(item.id || "") === String(category.id)) || category;
  },

  mergeProjectSummaries(projects = []) {
    const existingById = new Map((this.data.projects || []).map(project => [String(project.id || ""), project]));
    this.data.projects = (projects || []).map(summary => {
      const existing = existingById.get(String(summary.id || "")) || null;
      const detailLoaded = !!existing?._detailLoaded;
      return {
        ...(existing || {}),
        ...summary,
        stages: Array.isArray(existing?.stages) ? existing.stages : [],
        _summaryOnly: !detailLoaded,
        _detailLoaded: detailLoaded,
        _tasksFullyLoaded: !!existing?._tasksFullyLoaded,
      };
    });
    return this.data.projects;
  },

  mergeSampleCategorySummaries(categories = []) {
    if (!this.data.sampleLibrary) this.data.sampleLibrary = { categories: [], logs: [] };
    const existingById = new Map((this.data.sampleLibrary.categories || []).map(category => [String(category.id || ""), category]));
    this.data.sampleLibrary.categories = (categories || []).map(summary => {
      const existing = existingById.get(String(summary.id || "")) || null;
      const samplesLoaded = !!existing?.samplesLoaded;
      return {
        ...(existing || {}),
        ...summary,
        samples: Array.isArray(existing?.samples) ? existing.samples : [],
        _summaryOnly: !samplesLoaded,
        samplesLoaded,
      };
    });
    this._sampleCategorySummaryLoaded = true;
    return this.data.sampleLibrary.categories;
  },

  importMutationIdSets(mutationSummary = {}) {
    const toSet = values => new Set((values || []).map(value => String(value || "")).filter(Boolean));
    return {
      projectIds: toSet(mutationSummary.projectIds),
      stageIds: toSet(mutationSummary.stageIds),
      sampleCategoryIds: toSet(mutationSummary.sampleCategoryIds),
      sampleIds: toSet(mutationSummary.sampleIds),
    };
  },

  mergeProjectSummaryRows(projects = []) {
    if (!Array.isArray(this.data.projects)) this.data.projects = [];
    const byId = new Map(this.data.projects.map(project => [String(project.id || ""), project]));
    (projects || []).forEach(summary => {
      const id = String(summary?.id || "");
      if (!id) return;
      const existing = byId.get(id);
      if (existing) {
        Object.assign(existing, summary, {
          stages: Array.isArray(existing.stages) ? existing.stages : [],
          _summaryOnly: !existing._detailLoaded,
        });
      } else {
        const created = { ...summary, stages: [], _summaryOnly: true, _detailLoaded: false };
        this.data.projects.push(created);
        byId.set(id, created);
      }
    });
    return this.data.projects;
  },

  mergeSampleCategorySummaryRows(categories = []) {
    if (!this.data.sampleLibrary) this.data.sampleLibrary = { categories: [], logs: [] };
    if (!Array.isArray(this.data.sampleLibrary.categories)) this.data.sampleLibrary.categories = [];
    const byId = new Map(this.data.sampleLibrary.categories.map(category => [String(category.id || ""), category]));
    (categories || []).forEach(summary => {
      const id = String(summary?.id || "");
      if (!id) return;
      const existing = byId.get(id);
      if (existing) {
        Object.assign(existing, summary, {
          samples: Array.isArray(existing.samples) ? existing.samples : [],
          _summaryOnly: !existing.samplesLoaded,
        });
      } else {
        const created = { ...summary, samples: [], _summaryOnly: true, samplesLoaded: false };
        this.data.sampleLibrary.categories.push(created);
        byId.set(id, created);
      }
    });
    return this.data.sampleLibrary.categories;
  },

  applyMutationAffected(affected = {}) {
    if (!affected || typeof affected !== "object") return false;
    const changes = { taskStatus: [], sampleStatus: [] };
    this.mergeProjectSummaryRows(affected.projectSummaries || []);
    this.mergeSampleCategorySummaryRows(affected.sampleCategorySummaries || []);

    (affected.tasks || []).forEach(task => {
      const project = (this.data.projects || []).find(item => String(item.id || "") === String(task?.projectId || ""));
      const stage = (project?.stages || []).find(item => String(item.id || "") === String(task?.stageId || ""));
      if (!stage) return;
      if (!Array.isArray(stage.tasks)) stage.tasks = [];
      const existing = stage.tasks.find(item => String(item.id || "") === String(task.id || ""));
      const beforeStatus = existing && typeof this.taskFlowStatus === "function" ? this.taskFlowStatus(existing) : "";
      if (existing) Object.assign(existing, task);
      else stage.tasks.push(task);
      const merged = existing || task;
      const afterStatus = typeof this.taskFlowStatus === "function" ? this.taskFlowStatus(merged) : "";
      if (beforeStatus || afterStatus) {
        changes.taskStatus.push({
          projectId: task.projectId || project.id || "",
          stageId: task.stageId || stage.id || "",
          taskId: task.id || "",
          beforeStatus,
          afterStatus,
        });
      }
    });

    (affected.samples || []).forEach(sample => {
      const category = (this.data.sampleLibrary?.categories || []).find(item => String(item.id || "") === String(sample?.categoryId || ""));
      if (!category) return;
      if (!Array.isArray(category.samples)) category.samples = [];
      const existing = category.samples.find(item => String(item.id || "") === String(sample.id || ""));
      const beforeStatus = existing && typeof this.sampleEffectiveStatus === "function" ? this.sampleEffectiveStatus(existing) : "";
      if (existing) Object.assign(existing, sample);
      else category.samples.push(sample);
      const merged = existing || sample;
      const afterStatus = typeof this.sampleEffectiveStatus === "function" ? this.sampleEffectiveStatus(merged) : "";
      if (beforeStatus || afterStatus) {
        changes.sampleStatus.push({
          categoryId: sample.categoryId || category.id || "",
          sampleId: sample.id || "",
          beforeStatus,
          afterStatus,
        });
      }
    });
    this._lastMutationAffectedChanges = changes;
    return true;
  },

  async applyImportBundleMutationResult(result = {}, { render = true } = {}) {
    const mutationSummary = result.mutationSummary || null;
    this.serverRevision = result.revision || result.newRevision || this.serverRevision;
    this.serverUpdatedAt = result.updated_at || result.updatedAt || new Date().toISOString();
    this.serverOnline = true;

    if (!mutationSummary || mutationSummary.requiresFullState) {
      console.error("导入提交缺少局部同步摘要，拒绝自动拉取完整 state。");
      this.updateServerStatus("导入已写入，同步失败");
      return false;
    }

    this.updateServerStatus("同步导入");
    this.invalidatePagedCaches();
    const { projectIds, stageIds, sampleCategoryIds } = this.importMutationIdSets(mutationSummary);

    try {
      const [projectSummaries, categorySummaries] = await Promise.all([
        this.fetchProjectSummary(),
        this.fetchSampleCategoriesSummary(),
      ]);
      this.mergeProjectSummaries(projectSummaries);
      this.mergeSampleCategorySummaries(categorySummaries);

      await Promise.all([...projectIds].map(async projectId => {
        const detail = await this.fetchProjectDetail(projectId, { includeTasks: false });
        if (detail) this.mergeProjectDetail(detail, { includeTasks: false });
      }));

      if (!this.view.selectedProjectId || !(this.data.projects || []).some(project => String(project.id || "") === String(this.view.selectedProjectId))) {
        this.view.selectedProjectId = [...projectIds][0] || this.data.projects[0]?.id || null;
      }
      const currentProject = this.currentProject();
      if (currentProject && (!this.view.selectedStageId || !(currentProject.stages || []).some(stage => String(stage.id || "") === String(this.view.selectedStageId)))) {
        this.view.selectedStageId = currentProject.stages?.[0]?.id || null;
      }

      if (render) {
        this.renderNav?.();
        this.renderHeader?.();
        let contentRefreshed = false;
        if (this.view.module === "projectWorkspace") {
          const project = this.currentProject();
          const stage = this.currentStage();
          const selectedProjectAffected = projectIds.has(String(project?.id || ""));
          const selectedStageAffected = stageIds.has(String(stage?.id || "")) || selectedProjectAffected;
          if (project && stage && selectedStageAffected && typeof this.refreshCurrentTaskFlowPage === "function") {
            contentRefreshed = await this.refreshCurrentTaskFlowPage(project, stage);
          }
          if (!contentRefreshed && selectedProjectAffected && typeof this.renderContent === "function") {
            this.renderContent();
            contentRefreshed = true;
          }
        } else if (this.view.module === "samples") {
          const category = (this.data.sampleLibrary.categories || [])
            .find(cat => String(cat.id || "") === String(this.view.selectedCategoryId || ""));
          if (category && sampleCategoryIds.has(String(category.id || "")) && typeof this.refreshCurrentSamplePage === "function") {
            contentRefreshed = await this.refreshCurrentSamplePage(category);
          }
          if (!contentRefreshed && typeof this.renderContent === "function") {
            this.renderContent();
            contentRefreshed = true;
          }
        } else if ((this.view.module === "home" || this.view.module === "projects") && typeof this.renderContent === "function") {
          this.renderContent();
        }
      }

      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已导入");
      return true;
    } catch (e) {
      console.error("导入后局部同步失败：", e);
      this.updateServerStatus("导入同步失败");
      return false;
    }
  },

  async ensureProjectLoaded(projectId, { includeTasks = false, render = false } = {}) {
    const id = String(projectId || "");
    if (!id) return null;
    const current = (this.data.projects || []).find(project => String(project.id || "") === id);
    if (current?._detailLoaded && (!includeTasks || current._tasksFullyLoaded)) return current;
    const key = `${id}:${includeTasks ? "tasks" : "detail"}`;
    if (!this._projectDetailPromises) this._projectDetailPromises = {};
    if (!this._projectDetailPromises[key]) {
      this.updateServerStatus("加载项目");
      this._projectDetailPromises[key] = this.fetchProjectDetail(id, { includeTasks })
        .then(project => {
          const merged = this.mergeProjectDetail(project, { includeTasks });
          this._baseData = this.cloneData(this.data);
          this.updateServerStatus("已加载");
          if (render) this.render();
          return merged;
        })
        .catch(e => {
          this.updateServerStatus("加载失败");
          console.error("项目详情加载失败：", e);
          alert("项目详情加载失败：" + e.message);
          return null;
        })
        .finally(() => { delete this._projectDetailPromises[key]; });
    }
    return this._projectDetailPromises[key];
  },

  async ensureSampleCategoryLoaded(categoryId, { includePhotos = false, render = false } = {}) {
    const id = String(categoryId || "");
    if (!id) return null;
    const current = (this.data.sampleLibrary.categories || []).find(category => String(category.id || "") === id);
    const expectedCount = Number(current?.sampleCount || 0);
    const currentCount = Array.isArray(current?.samples) ? current.samples.length : 0;
    if (current?.samplesLoaded && !includePhotos && (!expectedCount || currentCount >= expectedCount)) return current;
    const key = `${id}:${includePhotos ? "photos" : "detail"}`;
    if (!this._sampleCategoryDetailPromises) this._sampleCategoryDetailPromises = {};
    if (!this._sampleCategoryDetailPromises[key]) {
      this.updateServerStatus("加载样机池");
      this._sampleCategoryDetailPromises[key] = this.fetchSampleCategoryDetail(id, { includePhotos })
        .then(category => {
          const merged = this.mergeSampleCategoryDetail(category);
          this._baseData = this.cloneData(this.data);
          this.updateServerStatus("已加载");
          if (render) this.render();
          return merged;
        })
        .catch(e => {
          this.updateServerStatus("加载失败");
          console.error("样机池详情加载失败：", e);
          alert("样机池详情加载失败：" + e.message);
          return null;
        })
        .finally(() => { delete this._sampleCategoryDetailPromises[key]; });
    }
    return this._sampleCategoryDetailPromises[key];
  },

  async ensureSampleDestroyImpactScope({ sampleId = "", categoryId = "" } = {}) {
    try {
      this.updateServerStatus("加载影响范围");
      const scope = await this.fetchSampleDestroyImpactScope({ sampleId, categoryId });
      const categoryIds = new Set((scope.sampleCategoryIds || []).map(id => String(id || "")).filter(Boolean));
      if (categoryId) categoryIds.add(String(categoryId));
      const projectIds = new Set((scope.projectIds || []).map(id => String(id || "")).filter(Boolean));
      const categoryList = [...categoryIds];
      const projectList = [...projectIds];

      const categories = await Promise.all(categoryList.map(id => this.ensureSampleCategoryLoaded(id, { render: false })));
      if (categories.some((item, idx) => !item && categoryList[idx])) return null;
      const projects = await Promise.all(projectList.map(id => this.ensureProjectLoaded(id, { includeTasks: true, render: false })));
      if (projects.some((item, idx) => !item && projectList[idx])) return null;

      this.updateServerStatus("已加载");
      return scope;
    } catch (e) {
      console.error("销毁影响范围加载失败：", e);
      this.updateServerStatus("加载失败");
      alert("销毁影响范围加载失败：" + e.message);
      return null;
    }
  },

  taskMutationSampleIds(task) {
    const ids = new Set();
    const add = value => {
      const id = String(value || "").trim();
      if (id) ids.add(id);
    };
    (task?.sampleIds || []).forEach(add);
    (task?.removedSampleRecords || []).forEach(item => add(item?.sampleId || item?.sid));
    (task?.sampleFaultRecords || []).forEach(item => add(item?.sampleId || item?.sid));
    (task?.resultDraft?.samples || []).forEach(item => add(item?.sampleId || item?.sid));
    (task?.resultUploads || []).forEach(upload => (upload?.samples || []).forEach(item => add(item?.sampleId || item?.sid)));
    return [...ids];
  },

  compactStageForMutation(stage) {
    if (!stage) return null;
    const copy = { ...stage };
    delete copy.tasks;
    return copy;
  },

  compactProjectForMutation(project) {
    if (!project) return null;
    const copy = { ...project };
    delete copy.stages;
    return copy;
  },

  compactSampleForMutation(sample) {
    if (!sample) return null;
    const copy = { ...sample };
    delete copy.photos;
    delete copy.logs;
    return copy;
  },

  compactSampleCategoryForMutation(category) {
    if (!category) return null;
    const copy = { ...category };
    delete copy.samples;
    return copy;
  },

  invalidatePagedCaches({ stageId = "", categoryId = "" } = {}) {
    if (stageId && this._taskFlowPageCache?.stageId === stageId) this._taskFlowPageCache = null;
    if (!stageId && this._taskFlowPageCache) this._taskFlowPageCache = null;
    const clearSampleCacheStore = (store) => {
      if (!(store instanceof Map)) return;
      if (!categoryId) {
        store.clear();
        return;
      }
      [...store.entries()].forEach(([key, value]) => {
        if (String(value?.categoryId || "") === String(categoryId)) store.delete(key);
      });
    };
    clearSampleCacheStore(this._samplePageCaches);
    clearSampleCacheStore(this._samplePageMetaCaches);
    if (categoryId && this._samplePageCache?.categoryId === categoryId) this._samplePageCache = null;
    if (!categoryId && this._samplePageCache) this._samplePageCache = null;
    if (this._samplePageLoadingKeys instanceof Set) this._samplePageLoadingKeys.clear();
    this._sampleCategorySummaryLoaded = false;
  },

  sampleEventsForTaskMutation(task, sampleIds = []) {
    const taskId = String(task?.id || "");
    const sampleSet = new Set((sampleIds || []).map(id => String(id || "")).filter(Boolean));
    return (this.data?.sampleLibrary?.logs || []).filter(log => {
      if (!log) return false;
      if (taskId && String(log.taskId || "") === taskId) return true;
      return sampleSet.has(String(log.sampleId || ""));
    });
  },

  taskSampleStatusBlockerMessage(json = {}) {
    return (json.samples || []).slice(0, 8).map(item => {
      const found = this.findSample?.(item.sampleId);
      const sampleName = found?.sample?.sampleNo || item.sampleNo || found?.sample?.sn || item.sn || item.imei || item.sampleId;
      const status = item.status || "未知状态";
      const taskNames = (item.tasks || []).map(t => t.testItem || t.taskId || "未命名任务").join("、");
      return `· 样机 ${sampleName}：当前状态「${status}」${taskNames ? `，目标任务「${taskNames}」` : ""}`;
    }).join("\n");
  },

  async commitTaskMutation(project, stage, task, { action = "task_mutation", remark = "任务增量变更", user = "", render = true, createIfMissing = false, deleteMode = "" } = {}) {
    if (!project || !stage || !task) return false;
    this._lastTaskMutationError = null;
    const sampleIds = this.taskMutationSampleIds(task);
    const samples = sampleIds
      .map(id => this.compactSampleForMutation(this.findSample(id)?.sample))
      .filter(Boolean);
    const payload = {
      revision: this.serverRevision,
      projectId: project.id,
      stageId: stage.id,
      taskId: task.id,
      action,
      remark,
      user,
      stage: this.compactStageForMutation(stage),
      task,
      samples,
      sampleEvents: this.sampleEventsForTaskMutation(task, sampleIds),
      createIfMissing,
      deleteMode,
    };
    this.updateServerStatus("同步中");
    try {
      const resp = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/mutation`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (resp.status === 409 && json.error_code === "SAMPLE_OCCUPANCY_CONFLICT") {
        const detail = (json.conflicts || []).slice(0, 5).map(c => {
          const sample = this.findSample?.(c.sampleId);
          const sampleName = sample?.sample?.sampleNo || sample?.sample?.sn || c.sampleId;
          const items = (c.tasks || []).map(t => t.testItem || "未命名任务").join("、");
          return `· 样机 ${sampleName}：被「${items}」同时占用`;
        }).join("\n");
        this.updateServerStatus("样机占用冲突");
        alert(`保存被拒绝：样机占用冲突。\n\n同一样机不能被多个未完成任务同时占用：\n${detail}`);
        return false;
      }
      if (resp.status === 409 && json.error_code === "SAMPLE_STATUS_NOT_SELECTABLE") {
        this._lastTaskMutationError = json;
        this.updateServerStatus("样机状态不可选");
        alert(`保存被拒绝：样机状态不可选。\n\n只有「闲置」样机可以加入测试任务：\n${this.taskSampleStatusBlockerMessage(json)}`);
        return false;
      }
      if (resp.status === 409 && json.error_code === "TASK_ALREADY_FINISHED") {
        this._lastTaskMutationError = json;
        this.updateServerStatus("任务已结束");
        Utils.toast("任务已经结束，已同步服务器状态。");
        return false;
      }
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this.applyMutationAffected(json.affected);
      this.invalidateSampleHistoryCache(sampleIds);
      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已保存");
      await this.refreshTaskListAfterMutation(project, stage, { render, affected: json.affected });
      return true;
    } catch (e) {
      console.error("任务增量保存失败：", e);
      this.updateServerStatus("保存失败");
      alert("任务增量保存失败：" + e.message);
      return false;
    }
  },

  async commitTaskBatchMutation(project, stage, tasks, { action = "task_batch_mutation", remark = "批量任务增量变更", user = "", render = true, createIfMissing = true } = {}) {
    if (!project || !stage || !Array.isArray(tasks) || !tasks.length) return false;
    const payload = {
      revision: this.serverRevision,
      projectId: project.id,
      stageId: stage.id,
      action,
      remark,
      user,
      stage: this.compactStageForMutation(stage),
      tasks,
      createIfMissing,
    };
    this.updateServerStatus("同步中");
    try {
      const resp = await fetch(`/api/stages/${encodeURIComponent(stage.id)}/tasks/batch`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (resp.status === 409 && json.error_code === "SAMPLE_STATUS_NOT_SELECTABLE") {
        this.updateServerStatus("样机状态不可选");
        alert(`保存被拒绝：样机状态不可选。\n\n只有「闲置」样机可以加入测试任务：\n${this.taskSampleStatusBlockerMessage(json)}`);
        return false;
      }
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this.applyMutationAffected(json.affected);
      this.invalidateSampleHistoryCache([...new Set(tasks.flatMap(task => this.taskMutationSampleIds(task)))]);
      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已保存");
      await this.refreshTaskListAfterMutation(project, stage, { render, affected: json.affected });
      return true;
    } catch (e) {
      console.error("批量任务增量保存失败：", e);
      this.updateServerStatus("保存失败");
      alert("批量任务增量保存失败：" + e.message);
      return false;
    }
  },

  taskMutationPayloadFor(project, stage, task, { createIfMissing = false } = {}) {
    return {
      projectId: project?.id,
      stageId: stage?.id,
      taskId: task?.id,
      stage: this.compactStageForMutation(stage),
      task,
      createIfMissing
    };
  },

  async commitProjectMutation(project, { action = "project_mutation", remark = "项目增量变更", user = "", createIfMissing = false, deleteProject = false, samples = [], sampleEvents = [], render = true } = {}) {
    if (!project?.id) return false;
    const payload = {
      revision: this.serverRevision,
      projectId: project.id,
      project: deleteProject ? null : this.compactProjectForMutation(project),
      samples: (samples || []).map(s => this.compactSampleForMutation(s)).filter(Boolean),
      sampleEvents: sampleEvents || [],
      action,
      remark,
      user,
      createIfMissing,
      deleteProject,
    };
    this.updateServerStatus("同步中");
    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(project.id)}/mutation`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this.applyMutationAffected(json.affected);
      this.invalidateSampleHistoryCache([...(samples || []).map(s => s?.id), ...(sampleEvents || []).map(log => log?.sampleId)]);
      this._baseData = this.cloneData(this.data);
      this.invalidatePagedCaches();
      this.updateServerStatus("已保存");
      if (render) this.render();
      return true;
    } catch (e) {
      console.error("项目增量保存失败：", e);
      this.updateServerStatus("保存失败");
      alert("项目增量保存失败：" + e.message);
      return false;
    }
  },

  async commitStageMutation(project, stage, { action = "stage_mutation", remark = "阶段增量变更", user = "", createIfMissing = false, deleteStage = false, samples = [], sampleEvents = [], render = true } = {}) {
    if (!project?.id || !stage?.id) return false;
    const payload = {
      revision: this.serverRevision,
      projectId: project.id,
      stageId: stage.id,
      project: this.compactProjectForMutation(project),
      stage: deleteStage ? null : this.compactStageForMutation(stage),
      stages: (project.stages || []).map(st => this.compactStageForMutation(st)).filter(Boolean),
      samples: (samples || []).map(s => this.compactSampleForMutation(s)).filter(Boolean),
      sampleEvents: sampleEvents || [],
      action,
      remark,
      user,
      createIfMissing,
      deleteStage,
    };
    this.updateServerStatus("同步中");
    try {
      const resp = await fetch(`/api/stages/${encodeURIComponent(stage.id)}/mutation`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this.applyMutationAffected(json.affected);
      this.invalidateSampleHistoryCache([...(samples || []).map(s => s?.id), ...(sampleEvents || []).map(log => log?.sampleId)]);
      this._baseData = this.cloneData(this.data);
      this.invalidatePagedCaches({ stageId: stage.id });
      this.updateServerStatus("已保存");
      if (render) this.render();
      return true;
    } catch (e) {
      console.error("阶段增量保存失败：", e);
      this.updateServerStatus("保存失败");
      alert("阶段增量保存失败：" + e.message);
      return false;
    }
  },

  async commitSampleMutation(sample, { action = "sample_mutation", remark = "样机增量变更", user = "", deleteSample = false, taskMutations = [], samples = [], sampleEvents = null, render = true } = {}) {
    if (!sample?.id) return false;
    const events = sampleEvents || (this.data?.sampleLibrary?.logs || []).filter(log => String(log?.sampleId || "") === String(sample.id));
    const payload = {
      revision: this.serverRevision,
      sampleId: sample.id,
      sample: deleteSample ? null : this.compactSampleForMutation(sample),
      samples: (samples || []).map(s => this.compactSampleForMutation(s)).filter(Boolean),
      sampleEvents: events,
      taskMutations,
      action,
      remark,
      user,
      deleteSample,
    };
    this.updateServerStatus("同步中");
    try {
      const resp = await fetch(`/api/samples/${encodeURIComponent(sample.id)}/mutation`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this.applyMutationAffected(json.affected);
      this.invalidateSampleHistoryCache([sample.id, ...(samples || []).map(s => s?.id), ...(events || []).map(log => log?.sampleId)]);
      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已保存");
      await this.refreshSampleListAfterMutation(sample, { render, affected: json.affected });
      return true;
    } catch (e) {
      console.error("样机增量保存失败：", e);
      this.updateServerStatus("保存失败");
      alert("样机增量保存失败：" + e.message);
      return false;
    }
  },

  async commitSampleCategoryMutation(category, { action = "sample_category_mutation", remark = "样机池增量变更", user = "", createIfMissing = false, createSamples = false, deleteCategory = false, taskMutations = [], samples = [], sampleEvents = [], render = true } = {}) {
    if (!category?.id) return false;
    const payload = {
      revision: this.serverRevision,
      categoryId: category.id,
      category: this.compactSampleCategoryForMutation(category),
      samples: (samples || []).map(s => this.compactSampleForMutation(s)).filter(Boolean),
      sampleEvents: sampleEvents || [],
      taskMutations,
      action,
      remark,
      user,
      createIfMissing,
      createSamples,
      deleteCategory,
    };
    this.updateServerStatus("同步中");
    try {
      const resp = await fetch(`/api/sample-categories/${encodeURIComponent(category.id)}/mutation`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await resp.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this.applyMutationAffected(json.affected);
      this.invalidateSampleHistoryCache([...(samples || []).map(s => s?.id), ...(sampleEvents || []).map(log => log?.sampleId)]);
      this._baseData = this.cloneData(this.data);
      this.updateServerStatus("已保存");
      if (createSamples && !deleteCategory) {
        await this.refreshSampleListAfterMutation(category, { render, affected: json.affected });
      } else {
        this.invalidatePagedCaches({ categoryId: category.id });
        if (render) this.render();
      }
      return true;
    } catch (e) {
      console.error("样机池增量保存失败：", e);
      this.updateServerStatus("保存失败");
      alert("样机池增量保存失败：" + e.message);
      return false;
    }
  },

  async ensureSampleDetailsLoaded(sampleId, { photos = true, events = true, renderPanels = true } = {}) {
    const found = this.findSample(sampleId);
    if (!found) return null;
    const sample = found.sample;
    const tasks = [];
    if (photos && sample.photosLoaded !== true) {
      tasks.push(this.fetchSamplePhotos(sampleId).then(list => {
        sample.photos = list;
        sample.photoCount = list.length;
        sample.photosLoaded = true;
      }));
    }
    if (events && sample.eventsLoaded !== true) {
      tasks.push(this.fetchSampleEvents(sampleId).then(list => {
        if (!Array.isArray(this.data.sampleLibrary.logs)) this.data.sampleLibrary.logs = [];
        const byId = new Map(this.data.sampleLibrary.logs.filter(log => log?.id).map(log => [log.id, log]));
        list.forEach(log => {
          if (log?.id && !byId.has(log.id)) {
            this.data.sampleLibrary.logs.push(log);
            byId.set(log.id, log);
          }
        });
        sample.eventsLoaded = true;
      }));
    }
    if (tasks.length) await Promise.all(tasks);
    if (renderPanels) this.refreshSampleArchivePanels(sampleId);
    return sample;
  },

  async ensureSampleHistoryLoaded(sampleId, { page = 1, pageSize = 20, renderPanels = true, force = false } = {}) {
    const found = this.findSample(sampleId);
    if (!found) return null;
    if (!this._sampleHistoryCache) this._sampleHistoryCache = {};
    const key = String(sampleId || "");
    const cached = this._sampleHistoryCache[key];
    if (!force && cached && cached.page === page && cached.pageSize === pageSize) return cached;
    this._sampleHistoryCache[key] = { loading: true, page, pageSize, items: [], total: 0, totalPages: 1 };
    if (renderPanels) this.refreshSampleArchivePanels(sampleId);
    try {
      const result = await this.fetchSampleHistory(sampleId, { page, pageSize });
      this._sampleHistoryCache[key] = result;
      found.sample.historyLoaded = true;
      if (renderPanels) this.refreshSampleArchivePanels(sampleId);
      return result;
    } catch (e) {
      this._sampleHistoryCache[key] = { error: e.message || String(e), page, pageSize, items: [], total: 0, totalPages: 1 };
      if (renderPanels) this.refreshSampleArchivePanels(sampleId);
      throw e;
    }
  },

  // ── 数据包导入导出 ──

  async importBundlePreview(file) {
    const form = new FormData();
    form.append("bundle", file);
    const resp = await fetch("/api/import-bundle/preview", { method: "POST", body: form });
    const json = await resp.json();
    if (!json.ok) throw new Error(json.error || "预览分析失败");
    return json;
  },

  async importBundleCommit(previewId, decisions) {
    const resp = await fetch("/api/import-bundle/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ previewId, decisions }),
    });
    const json = await resp.json();
    if (!json.ok) throw new Error(json.error || "导入失败");
    return json;
  },

});
