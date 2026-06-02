/* ========================================
   数字治理平台 V7 - 筛选器模块
   ======================================== */

Object.assign(app, {

  // ---- 筛选 ----
  setProgressFilter(field, val) {
    if (!this.view.progressFilters) this.view.progressFilters = {};
    if (val === "" || val === null || val === undefined) delete this.view.progressFilters[field];
    else this.view.progressFilters[field] = val;
    this.renderPreserveScroll();
  },
  clearProgressFilters() {
    this.view.progressFilters = {};
    this.renderPreserveScroll();
  },
  setStageStrategyFilter(field, value) {
    if (!this.view.stageStrategyFilters) {
      this.view.stageStrategyFilters = { includeKeyword: "", excludeKeyword: "" };
    }
    this.view.stageStrategyFilters[field] = String(value || "");
    this.renderPreserveScroll();
  },
  clearStageStrategyFilters() {
    this.view.stageStrategyFilters = { includeKeyword: "", excludeKeyword: "" };
    this.renderPreserveScroll();
  },
  setTaskFlowFilter(field, value) {
    if (!this.view.taskFlowFilters) this.view.taskFlowFilters = {};
    this.view.taskFlowFilters[field] = value;
    this.view.taskFlowPage = 1;
    this.renderPreserveScroll();
  },
  setTaskFlowTextFilter(field, value) {
    if (!this.view.taskFlowFilters) this.view.taskFlowFilters = {};
    if (value === "" || value === null || value === undefined) {
      delete this.view.taskFlowFilters[field];
    } else {
      this.view.taskFlowFilters[field] = value;
    }
  },
  commitTaskFlowTextFilter(field, value) {
    if (!this.view.taskFlowFilters) this.view.taskFlowFilters = {};
    if (value === "" || value === null || value === undefined) {
      delete this.view.taskFlowFilters[field];
    } else {
      this.view.taskFlowFilters[field] = value;
    }
    clearTimeout(this._taskFlowTextFilterTimer);
    this._taskFlowTextFilterTimer = null;
    this.view.taskFlowPage = 1;
    this.renderPreserveScroll();
  },
  handleTaskFlowTextFilterKeydown(event, field, value) {
    if (event.key === "Enter") {
      event.preventDefault();
      this.commitTaskFlowTextFilter(field, value);
    }
  },
  clearTaskFlowFilters() {
    this.view.taskFlowFilters = {};
    this.view.taskFlowPage = 1;
    clearTimeout(this._taskFlowTextFilterTimer);
    this._taskFlowTextFilterTimer = null;
    this.renderPreserveScroll();
  }

});
