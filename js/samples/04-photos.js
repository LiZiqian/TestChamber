/* ========================================
   TestChamber V7 - Sample photos and thumbnails
   Split from the previous monolithic module.
   ======================================== */

Object.assign(app, {

  photoThumbUrl(photo) {
    return photo?.thumbUrl || photo?.thumbnailUrl || photo?.url || photo?.dataUrl || "";
  },

  async createPhotoThumbnail(file, { maxSize = 360, quality = 0.72 } = {}) {
    if (!file || !String(file.type || "").startsWith("image/")) return null;
    let bitmap = null;
    let objectUrl = "";
    try {
      if ("createImageBitmap" in window) {
        bitmap = await createImageBitmap(file);
      } else {
        objectUrl = URL.createObjectURL(file);
        bitmap = await new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = objectUrl;
        });
      }
      const scale = Math.min(1, maxSize / Math.max(bitmap.width || 1, bitmap.height || 1));
      const width = Math.max(1, Math.round((bitmap.width || 1) * scale));
      const height = Math.max(1, Math.round((bitmap.height || 1) * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(bitmap, 0, 0, width, height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", quality));
      if (!blob) return null;
      const base = String(file.name || "photo").replace(/\.[^.]+$/, "") || "photo";
      return new File([blob], `${base}.thumb.jpg`, { type: "image/jpeg" });
    } catch (e) {
      console.warn("生成缩略图失败：", e);
      return null;
    } finally {
      if (bitmap?.close) bitmap.close();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    }
  },

  async appendPhotoUploadFiles(form, files) {
    for (let idx = 0; idx < files.length; idx++) {
      const file = files[idx];
      form.append("photos", file, file.name);
      const thumb = await this.createPhotoThumbnail(file);
      if (thumb) form.append(`thumb_${idx}`, thumb, thumb.name);
    }
  },

  samplePhotosHtml(sample) {
    const photos = Array.isArray(sample?.photos) ? sample.photos : [];
    return `<div class="sample-photo-grid">
      <div class="sample-photo-card sample-photo-add" onclick="app.uploadSamplePhotos('${sample.id}')">
        <div class="add-card-plus" style="font-size:28px;margin-bottom:6px">+</div>
        <div class="add-card-label">上传图片</div>
      </div>
      ${photos.length ? photos.map(photo => `
        <div class="sample-photo-card">
          <div class="sample-photo-thumb-wrap">
            <button type="button" class="sample-photo-thumb" onclick="app.previewSamplePhoto('${sample.id}','${photo.id}')" title="查看大图">
              <img src="${Utils.esc(this.photoThumbUrl(photo))}" alt="${Utils.esc(photo.name || "图片数据")}">
            </button>
            <button type="button" class="sample-photo-delete-btn" onclick="event.stopPropagation();app.deleteSamplePhoto('${sample.id}','${photo.id}')" title="删除照片">🗑</button>
          </div>
          <div class="sample-photo-meta">
            <div class="sample-photo-name-row">
              <b title="${Utils.esc(photo.name || "")}">${Utils.esc(photo.name || "图片数据")}</b>
              <button type="button" class="sample-photo-rename-icon" onclick="event.stopPropagation();app.startPhotoRename(this,'${sample.id}','${photo.id}')" title="重命名">✎</button>
            </div>
          </div>
        </div>`).join("") : ""}
    </div>`;
  },

  previewSamplePhoto(sampleId, photoId) {
    const sample = this.findSample(sampleId)?.sample;
    const photo = (sample?.photos || []).find(x => x.id === photoId);
    if (!photo) return;
    const src = photo.url || photo.dataUrl || "";
    if (!src) return;
    const existing = document.querySelector(".sample-photo-preview-mask");
    if (existing) existing.remove();
    document.body.insertAdjacentHTML("beforeend", `
      <div class="sample-photo-preview-mask" onclick="if(event.target===this)this.remove()">
        <div class="sample-photo-preview">
          <div class="sample-photo-preview-head">
            <b>${Utils.esc(photo.name || "外观照片")}</b>
            <span class="path" style="font-size:12px">滚轮缩放 · 点击背景关闭</span>
            <button type="button" class="btn btn-sm btn-outline" onclick="this.closest('.sample-photo-preview-mask').remove()">关闭</button>
          </div>
          <div class="sample-photo-preview-body">
            <img src="${Utils.esc(src)}" alt="${Utils.esc(photo.name || "外观照片")}" style="transform-origin:center center;transition:transform 0.15s">
          </div>
        </div>
      </div>
    `);
    // 鼠标滚轮缩放 + 左键拖动平移
    const mask = document.querySelector(".sample-photo-preview-mask");
    const img = mask?.querySelector(".sample-photo-preview-body img");
    if (img) {
      let scale = 1, tx = 0, ty = 0, dragging = false, startX = 0, startY = 0;
      const maxScale = 5;
      const updateTransform = () => {
        img.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
      };
      const clampTranslate = () => {
        if (scale <= 1) { tx = 0; ty = 0; return; }
        const rect = img.getBoundingClientRect();
        const cw = body.clientWidth, ch = body.clientHeight;
        const iw = rect.width / scale, ih = rect.height / scale;
        const vw = iw * scale, vh = ih * scale;
        const maxX = Math.max(0, (vw - cw) / 2);
        const maxY = Math.max(0, (vh - ch) / 2);
        tx = Math.max(-maxX, Math.min(maxX, tx));
        ty = Math.max(-maxY, Math.min(maxY, ty));
      };
      const body = mask.querySelector(".sample-photo-preview-body");
      body.addEventListener("wheel", (e) => {
        e.preventDefault();
        const rect = img.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const oldScale = scale;
        scale *= e.deltaY < 0 ? 1.02 : 1 / 1.02;
        if (scale < 1) { scale = 1; tx = 0; ty = 0; }
        else if (scale > maxScale) scale = maxScale;
        else { tx = mx - (mx - tx) * (scale / oldScale); ty = my - (my - ty) * (scale / oldScale); }
        clampTranslate();
        updateTransform();
        body.style.cursor = scale > 1 ? "grab" : "zoom-in";
      }, { passive: false });
      img.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        dragging = true; startX = e.clientX - tx; startY = e.clientY - ty;
        img.style.cursor = "grabbing";
        e.preventDefault();
      });
      window.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        tx = e.clientX - startX; ty = e.clientY - startY;
        clampTranslate();
        updateTransform();
      });
      window.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        img.style.cursor = scale > 1 ? "grab" : "zoom-in";
      });
      const observer = new MutationObserver(() => {
        if (!document.body.contains(mask)) observer.disconnect();
      });
      observer.observe(document.body, { childList: true });
    }
  },

  uploadSamplePhotos(sampleId) {
    const found = this.findSample(sampleId);
    if (!found) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = true;
    input.onchange = async () => {
      const files = [...(input.files || [])];
      if (!files.length) return;
      try {
        if (!(await this.prepareBeforeDirectMutation("上传样机外观照片前同步"))) return;
        const form = new FormData();
        await this.appendPhotoUploadFiles(form, files);
        form.append("revision", String(this.serverRevision || 0));
        form.append("remark", "上传样机外观照片");
        const res = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/photos`, {
          method: "POST",
          body: form
        });
        const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
        if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
        await this.syncAfterDirectMutation({ render: false, statusText: "已保存" });
        const latest = this.findSample(sampleId);
        const panel = document.querySelector('[data-sample-archive-panel="photos"]');
        if (panel && latest?.sample) panel.innerHTML = this.samplePhotosHtml(latest.sample);
        Utils.toast(`已上传 ${files.length} 张外观照片。`);
      } catch (e) {
        alert("照片上传失败：" + (e.message || e));
      }
    };
    input.click();
  },

  startPhotoRename(btn, sampleId, photoId) {
    const nameRow = btn.closest(".sample-photo-name-row");
    if (!nameRow) return;
    const nameB = nameRow.querySelector("b");
    if (!nameB) return;
    const originalName = nameB.textContent.trim();

    // Replace display with inline input
    nameRow.innerHTML = `<input class="sample-photo-name-input" value="${Utils.esc(originalName)}">`;
    const input = nameRow.querySelector(".sample-photo-name-input");
    if (!input) return;
    input.focus();
    input.select();

    let committed = false;

    const commit = () => {
      if (committed) return;
      committed = true;
      const newName = input.value.trim();
      // Empty or unchanged -> restore original, no save
      if (!newName || newName === originalName) {
        this.finishPhotoRename(nameRow, sampleId, photoId, originalName);
        return;
      }
      // Persist to data
      const found = this.findSample(sampleId);
      const photo = found?.sample?.photos?.find(x => x.id === photoId);
      if (found && photo) {
        photo.name = newName;
        found.sample.updatedAt = Utils.now();
        this.save();
      }
      this.finishPhotoRename(nameRow, sampleId, photoId, photo ? newName : originalName);
    };

    const cancel = () => {
      if (committed) return;
      committed = true;
      this.finishPhotoRename(nameRow, sampleId, photoId, originalName);
    };

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      if (e.key === "Escape") { e.preventDefault(); cancel(); }
    });
    input.addEventListener("blur", () => {
      setTimeout(() => commit(), 100);
    });
  },

  finishPhotoRename(nameRow, sampleId, photoId, name) {
    nameRow.innerHTML = `
      <b title="${Utils.esc(name)}">${Utils.esc(name)}</b>
      <button type="button" class="sample-photo-rename-icon" onclick="event.stopPropagation();app.startPhotoRename(this,'${Utils.esc(sampleId)}','${Utils.esc(photoId)}')" title="重命名">✎</button>
    `;
  },

  deleteSamplePhoto(sampleId, photoId) {
    const found = this.findSample(sampleId);
    if (!found || !Array.isArray(found.sample.photos)) return;
    this.showConfirm("确认删除这张外观照片？", async () => {
      try {
        if (!(await this.prepareBeforeDirectMutation("删除样机外观照片前同步"))) return;
        const res = await fetch(`/api/samples/${encodeURIComponent(sampleId)}/photos/${encodeURIComponent(photoId)}`, { method: "DELETE" });
        const obj = await res.json().catch(() => ({ ok: false, error: "服务器返回不是 JSON" }));
        if (!res.ok || !obj.ok) throw new Error(obj.error || ("HTTP " + res.status));
        await this.syncAfterDirectMutation({ render: false, statusText: "已保存" });
        const latest = this.findSample(sampleId);
        const panel = document.querySelector('[data-sample-archive-panel="photos"]');
        if (panel && latest?.sample) panel.innerHTML = this.samplePhotosHtml(latest.sample);
      } catch (e) {
        alert("删除照片失败：" + (e.message || e));
      }
    }, { title: "删除照片", okText: "删除", okClass: "btn btn-danger" });
  },

});
