/* ========================================
   数字治理平台 V7 - 筛选器模块
   ======================================== */

app.registerModule("app.filters", {

  // ---- 筛选 ----
  setProgressFilter(field, val) {
    this.setViewMapValue("progressFilters", field, val);
    this.renderPreserveScroll();
  },
  clearProgressFilters() {
    this.resetViewMap("progressFilters");
    this.renderPreserveScroll();
  },
  setStageStrategyFilter(field, value) {
    this.setViewMapValue("stageStrategyFilters", field, String(value || ""), {
      removeEmpty: false,
      fallback: { includeKeyword: "", excludeKeyword: "" },
    });
    this.renderPreserveScroll();
  },
  clearStageStrategyFilters() {
    this.resetViewMap("stageStrategyFilters", { includeKeyword: "", excludeKeyword: "" });
    this.renderPreserveScroll();
  },
  setTaskFlowFilter(field, value) {
    this.setViewMapValue("taskFlowFilters", field, value, { removeEmpty: false });
    this.resetTaskFlowPage();
    this.renderPreserveScroll();
  },
  setTaskFlowTextFilter(field, value) {
    this.setViewMapValue("taskFlowFilterDrafts", field, value, { removeEmpty: false });
  },
  commitTaskFlowTextFilter(field, value) {
    this.setViewMapValue("taskFlowFilterDrafts", field, value, { removeEmpty: false });
    this.setViewMapValue("taskFlowFilters", field, value);
    clearTimeout(this._taskFlowTextFilterTimer);
    this._taskFlowTextFilterTimer = null;
    this.resetTaskFlowPage();
    this.renderPreserveScroll();
  },
  handleTaskFlowTextFilterKeydown(event, field, value) {
    if (event.key === "Enter" && !this.isImeCompositionEvent(event)) {
      event.preventDefault();
      this.commitTaskFlowTextFilter(field, value);
    }
  },
  clearTaskFlowFilters() {
    this.resetTaskFlowContextState();
    this.renderPreserveScroll();
  }

});
