/* ========================================
   数字治理平台 V7 - 服务器通信模块
   ======================================== */

Object.assign(app, {

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

  async reloadFromServer({ render = true } = {}) {
    const res = await fetch("/api/state", { cache: "no-store" });
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
      this.save({ silent: true, remark: "自动清理重复项目人员" });
    }
  },

  async ensureFullStateLoaded({ render = false } = {}) {
    if (!this._statePartial) return true;
    const viewSnapshot = this.cloneData(this.view);
    try {
      await this.reloadFromServer({ render: false });
      this.view = { ...this.view, ...viewSnapshot };
      if (render) this.render();
      return true;
    } catch (e) {
      console.error("完整数据加载失败：", e);
      this.updateServerStatus("完整加载失败");
      alert("完整数据加载失败：" + e.message);
      return false;
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
        if (silent && retryOnConflict && obj.server_revision) {
          await this.reloadFromServer({ render: false });
          this.updateServerStatus("已刷新");
          return false;
        }
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
      const saved = await this.save({ silent: false, remark });
      if (!saved) return false;
    }
    return true;
  },

  async syncAfterDirectMutation({ render = false, statusText = "已保存" } = {}) {
    try {
      await this.reloadFromServer({ render });
    } catch (e) {
      console.error("syncAfterDirectMutation 刷新失败：", e);
    }
    this.updateServerStatus(statusText);
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
    if (current?.samplesLoaded && !includePhotos) return current;
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
    if (categoryId && this._samplePageCache?.categoryId === categoryId) this._samplePageCache = null;
    if (!categoryId && this._samplePageCache) this._samplePageCache = null;
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

  async commitTaskMutation(project, stage, task, { action = "task_mutation", remark = "任务增量变更", user = "", render = true, createIfMissing = false, deleteMode = "" } = {}) {
    if (!project || !stage || !task) return false;
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
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this._baseData = this.cloneData(this.data);
      this.invalidatePagedCaches({ stageId: stage.id });
      this.updateServerStatus("已保存");
      if (render) this.render();
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
      if (!resp.ok || !json.ok) throw new Error(json.error || ("HTTP " + resp.status));
      this.serverRevision = json.revision || this.serverRevision;
      this.serverUpdatedAt = json.updated_at || new Date().toISOString();
      this.serverOnline = true;
      this._baseData = this.cloneData(this.data);
      this.invalidatePagedCaches({ stageId: stage.id });
      this.updateServerStatus("已保存");
      if (render) this.render();
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
      this._baseData = this.cloneData(this.data);
      this.invalidatePagedCaches({ categoryId: sample.categoryId || "" });
      this.updateServerStatus("已保存");
      if (render) this.render();
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
      this._baseData = this.cloneData(this.data);
      this.invalidatePagedCaches({ categoryId: category.id });
      this.updateServerStatus("已保存");
      if (render) this.render();
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
