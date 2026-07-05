/* ========================================
   数字治理平台 V7 - 弹窗模块
   ======================================== */

app.registerModule("app.modal", {

  // ---- 模态框 ----
  _syncModalInputsToAttributes() {
    const body = document.getElementById("modalBody");
    if (!body) return;
    body.querySelectorAll("input[type='checkbox'], input[type='radio']").forEach(el => {
      if (el.checked) el.setAttribute("checked", "");
      else el.removeAttribute("checked");
    });
    body.querySelectorAll("input:not([type='checkbox']):not([type='radio']), textarea").forEach(el => {
      el.setAttribute("value", el.value);
    });
    body.querySelectorAll("select").forEach(el => {
      Array.from(el.options).forEach(opt => {
        if (opt.selected) opt.setAttribute("selected", "");
        else opt.removeAttribute("selected");
      });
    });
  },

  showModal(title, bodyHtml, onOk, okText = "确认", options = {}) {
    // 模态框堆栈：当前已显示时，保存当前状态
    if (!this._restoringModal && document.getElementById("modalMask").style.display === "flex") {
      this._syncModalInputsToAttributes();
      const modalEl = document.querySelector(".modal");
      const modalBody = document.getElementById("modalBody");
      this._modalStack.push({
        title: document.getElementById("modalTitle").innerText,
        bodyNodes: this.cloneChildNodes(modalBody),
        footerExtraNodes: Array.from(document.querySelectorAll(".modal-footer > .modal-extra-action"))
          .map(node => node?.cloneNode ? node.cloneNode(true) : null)
          .filter(Boolean),
        onOk: this._currentModalOnOk,
        okText: document.getElementById("modalOk").innerText,
        okClass: document.getElementById("modalOk").className,
        hideCancel: document.getElementById("modalCancel").style.display === "none",
        cancelText: document.getElementById("modalCancel").innerText,
        headerHint: (document.getElementById("modalHeaderHint")?.innerText || ""),
        className: modalEl ? modalEl.className.replace(/^modal\s*/, "") : ""
      });
    }
    this._restoringModal = false;
    this._currentModalOnOk = onOk;

    const modal = document.querySelector(".modal");
    if (modal) modal.className = `modal${options.className ? " " + options.className : ""}`;
    document.getElementById("modalTitle").innerText = title;
    const hint = document.getElementById("modalHeaderHint");
    if (hint) {
      hint.innerText = options.headerHint || "";
      hint.style.display = options.headerHint ? "" : "none";
    }
    const modalBody = document.getElementById("modalBody");
    if (options.bodyNodes) this.replaceWithClonedNodes(modalBody, options.bodyNodes);
    else this.replaceHtml(modalBody, bodyHtml);
    document.querySelectorAll(".modal-extra-action").forEach(btn => btn.remove());
    document.querySelectorAll(".modal-footer > #sampleArchiveExportBtn").forEach(btn => btn.remove());
    const footer = document.querySelector(".modal-footer");
    if (footer && options.footerExtraNodes) {
      const footerExtraNodes = (options.footerExtraNodes || [])
        .map(node => node?.cloneNode ? node.cloneNode(true) : node)
        .filter(Boolean);
      footer.prepend(...footerExtraNodes);
    }
    const cancel = this.resetEventTarget(document.getElementById("modalCancel"));
    if (cancel) {
      cancel.disabled = false;
      cancel.style.display = options.hideCancel ? "none" : "";
      cancel.innerText = options.cancelText || "取消";
      cancel.className = "btn btn-outline";
      cancel.addEventListener("click", () => this.closeModal());
    }
    const ok = this.resetEventTarget(document.getElementById("modalOk"));
    if (!ok) { console.error("modalOk not found in DOM"); return; }
    ok.disabled = false;
    ok.className = options.okClass || "btn";
    ok.innerText = okText;
    ok.addEventListener("click", async () => {
      try {
        const keepOpen = onOk && onOk();
        if (keepOpen && typeof keepOpen.then === "function") {
          ok.disabled = true;
          const resolved = await keepOpen;
          ok.disabled = false;
          if (!resolved) this.closeModal();
          return;
        }
        if (!keepOpen) this.closeModal();
      } catch (e) {
        ok.disabled = false;
        console.error("[showModal] onOk 异常：", e);
        alert("操作失败：" + (e.message || e));
      }
    });
    document.getElementById("modalMask").style.display = "flex";
    this.updateSelectPlaceholderState(document.getElementById("modalBody"));
  },

  showConfirm(message, onOk, options = {}) {
    const mask = document.getElementById("confirmMask");
    const box = mask?.querySelector(".confirm-box");
    const title = document.getElementById("confirmTitle");
    const msg = document.getElementById("confirmMessage");
    const desc = document.getElementById("confirmDesc");
    const cancel = document.getElementById("confirmCancel");
    const ok = document.getElementById("confirmOk");
    if (!mask || !title || !msg || !cancel || !ok) {
      console.warn("Confirm dialog is not available:", message);
      return;
    }
    if (box) box.className = `confirm-box${options.className ? " " + options.className : ""}`;
    title.innerText = options.title || "确认操作";
    msg.innerText = message || "";
    if (desc) {
      desc.innerText = options.description || "";
      desc.style.display = options.description ? "" : "none";
    }
    cancel.style.display = options.hideCancel ? "none" : "";
    cancel.innerText = options.cancelText || "取消";
    ok.innerText = options.okText || "确认";
    ok.className = options.okClass || "btn";
    const boundCancel = this.resetEventTarget(cancel);
    const boundOk = this.resetEventTarget(ok);
    if (!boundCancel || !boundOk) return;
    boundCancel.disabled = false;
    boundOk.disabled = false;
    boundCancel.style.display = cancel.style.display;
    boundCancel.innerText = options.cancelText || "取消";
    boundCancel.addEventListener("click", () => this.closeConfirm());
    boundOk.innerText = options.okText || "确认";
    boundOk.className = options.okClass || "btn";
    boundOk.addEventListener("click", async () => {
      boundOk.disabled = true;
      try {
        const result = typeof onOk === "function" ? onOk() : null;
        if (result && typeof result.then === "function") await result;
        this.closeConfirm();
      } catch (e) {
        console.error("[showConfirm] onOk 异常：", e);
        alert("操作失败：" + (e.message || e));
      } finally {
        boundOk.disabled = false;
      }
    });
    mask.style.display = "flex";
  },

  showAlert(message, options = {}) {
    this.showConfirm(message, null, {
      title: options.title || "提示",
      okText: options.okText || "确定",
      okClass: options.okClass || "btn",
      hideCancel: true,
      className: "alert-box"
    });
  },

  closeConfirm() {
    const mask = document.getElementById("confirmMask");
    if (mask) mask.style.display = "none";
    const box = mask?.querySelector(".confirm-box");
    if (box) box.className = "confirm-box";
  },

  closeModal() {
    // 模态框堆栈：有上一级则恢复
    if (this._modalStack.length > 0) {
      const prev = this._modalStack.pop();
      this._restoringModal = true;
      this.showModal(prev.title, "", prev.onOk, prev.okText, {
        okClass: prev.okClass || "btn",
        hideCancel: prev.hideCancel,
        cancelText: prev.cancelText,
        headerHint: prev.headerHint || "",
        className: prev.className || "",
        bodyNodes: prev.bodyNodes || [],
        footerExtraNodes: prev.footerExtraNodes || []
      });
      return;
    }
    document.getElementById("modalMask").style.display = "none";
    const modal = document.querySelector(".modal");
    if (modal) modal.className = "modal";
    const hint = document.getElementById("modalHeaderHint");
    if (hint) {
      hint.innerText = "";
      hint.style.display = "none";
    }
  },

  // ---- 内联表单校验工具 ----
  // 清除当前模态框中所有校验标记
  clearFieldValidationMarks() {
    const modal = document.querySelector(".modal");
    if (!modal) return;
    modal.querySelectorAll(".is-invalid").forEach(el => el.classList.remove("is-invalid"));
    modal.querySelectorAll(".field-error").forEach(el => el.remove());
  },

  fieldErrorNode(message) {
    const node = document.createElement("div");
    node.className = "field-error";
    node.textContent = String(message || "");
    return node;
  },

  appendFieldError(container, message) {
    if (!container || !message || container.querySelector(".field-error")) return null;
    const node = this.fieldErrorNode(message);
    container.append(node);
    return node;
  },

  insertFieldErrorAfter(anchor, message) {
    const parent = anchor?.parentElement || null;
    if (!parent || !message || parent.querySelector(".field-error")) return null;
    const node = this.fieldErrorNode(message);
    if (typeof anchor.after === "function") anchor.after(node);
    else parent.insertBefore(node, anchor.nextSibling || null);
    return node;
  },

  // 将指定元素标记为校验失败，在其所属 .form-group 中显示错误信息
  markFieldInvalid(el, message) {
    if (!el) return;
    this.revealInvalidFieldPanel?.(el);
    el.classList.add("is-invalid");
    const group = el.closest(".form-group") || el.closest(".form-row") || el.parentElement;
    this.appendFieldError(group, message);
    const first = document.querySelector(".modal .is-invalid");
    first?.scrollIntoView({ block: "center", behavior: "smooth" });
  },

  revealInvalidFieldPanel(el) {
    const panel = el?.closest?.(".task-config-panel");
    if (!panel || panel.classList.contains("active")) return;
    document.querySelectorAll(".task-config-panel").forEach(item => item.classList.toggle("active", item === panel));
    const value = panel.id === "tcPanelSample" ? "sample" : panel.id === "tcPanelPlan" ? "plan" : "";
    if (!value) return;
    document.querySelectorAll(".task-config-nav-card").forEach(item => {
      item.classList.toggle("active", item.dataset.value === value);
    });
  },

  // ---- 危险确认弹窗（DELETE 关键词二次验证） ----
  showDangerConfirm(descHtml, onConfirm, options = {}) {
    const confirmCode = options.confirmCode || "DELETE";
    const actionLabel = options.actionLabel || "删除";
    const body = `
      <div class="delete-confirm">
        ${descHtml}
        <label>请输入 <strong>${Utils.esc(confirmCode)}</strong> 确认${Utils.esc(actionLabel)}：</label>
        <input id="deleteKeywordInput" autocomplete="off" autofocus>
        <div id="deleteKeywordError" class="delete-confirm-error" style="display:none">请输入 ${Utils.esc(confirmCode)} 后才能继续。</div>
      </div>
    `;
    this.showModal(options.title || "危险操作确认", body, () => {
      const input = document.getElementById("deleteKeywordInput");
      const error = document.getElementById("deleteKeywordError");
      if ((input?.value || "") !== confirmCode) {
        if (error) error.style.display = "block";
        input?.focus();
        return true;
      }
      return onConfirm?.();
    }, options.okText || "确认", {
      okClass: options.okClass || "btn btn-danger",
      hideCancel: false,
      cancelText: options.cancelText || "取消",
      className: options.className || ""
    });
    setTimeout(() => document.getElementById("deleteKeywordInput")?.focus(), 60);
  }

});
