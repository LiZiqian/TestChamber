/* ========================================
   数字治理平台 V7 - 服务器通信模块
   ======================================== */

Object.assign(app, {

  // ---- 服务器通信 ----
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
