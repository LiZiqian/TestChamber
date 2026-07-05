# TestChamber V7 批量导入人工测试数据

生成时间：2026-06-06；随机种子：20260606

## 文件

- `01_project_members_random_valid.csv`：项目人员导入。新版两列为 `姓名/工号,人员类型`，旧单列 `姓名/工号` 仍可导入并默认测试人员。
- `02_sample_import_random_valid.xlsx`：基于 `frontend/templates/sample_import_template.xlsx` 的常规有效样机批量导入数据。
- `02b_sample_import_extended_edge_valid.xlsx`：基于同一模板，额外加入当前解析器支持的 `样机状态`、`标签` 扩展列；2026-06-07 已刷新为 1500 行新样机，每行都有随机缺失字段但至少保留一个 SN/IMEI/主板 SN 标识。
- `03_test_cases_random_valid.xlsx`：基于 `frontend/templates/用例集导入模板.xlsx` 的常规有效用例集。
- `03b_test_cases_edge_valid.xlsx`：基于同一模板，覆盖较长用例名、符号、温度单位、括号和斜杠等边界但有效场景。

## 使用提醒

- 样机导入会在目标样机池内和跨池查重；如果你的真实库里已有相同 SN/IMEI/主板 SN，导入时会被跳过，这是预期行为。
- 这些文件刻意保持为有效数据，不包含明显非法人员格式或完全空标识样机；如需测试非法输入，可在副本里手工删改几行。
