# TestChamberV7 前端模块化重构 — 安全清单

> 状态：规划中 | 版本：1.0 | 日期：2026-05-31

---

## 1. 拆分前检查

### 1.1 环境检查
- [ ] 确认 `python server.py` 可正常启动，端口 9398
- [ ] 确认 `GET http://localhost:9398/api/health` 返回 `{"ok": true}`
- [ ] 确认 `GET http://localhost:9398/api/state` 返回完整数据
- [ ] 确认浏览器访问 `http://localhost:9398/` 首页正常加载
- [ ] 确认浏览器 Console 无报错
- [ ] 确认所有 JS 文件（5个）和 CSS 文件（1个）均可正常加载（Network 标签无 404）

### 1.2 版本控制检查
- [ ] 项目已 `git init` 并完成首次提交
- [ ] `git status` 显示 clean working tree
- [ ] 已知当前 commit hash：`________`
- [ ] 备份：已将整个项目目录复制到安全位置（推荐）

### 1.3 文档检查
- [ ] 已通读 `docs/refactor-target-architecture.md`
- [ ] 已通读 `docs/refactor-execution-plan.md`
- [ ] 已确认当前轮次的目标文件和移动清单

---

## 2. 每轮拆分前检查

- [ ] `git status` clean（无未提交修改）
- [ ] 确认本轮要拆分的源文件路径
- [ ] 确认本轮要创建的目标文件路径
- [ ] 确认本轮要移动的函数/规则清单
- [ ] 确认目标文件不与其他文件重名
- [ ] 确认本轮不需要修改 server.py
- [ ] 确认本轮不需要修改数据库

---

## 3. 每轮拆分后检查

### 3.1 文件层面
- [ ] `git diff --stat` 变动范围符合预期
- [ ] 旧文件中的对应代码已删除（CSS/JS 拆分后）
- [ ] 新文件中的代码与移动前一致（逐行对比）
- [ ] index.html 的 `<script>` 或 `<link>` 已更新
- [ ] 新文件路径可被 HTTP 服务器正常访问（在 ROOT_DIR 范围内）

### 3.2 语法检查

**CSS 文件：**
```bash
# 检查所有 CSS 文件是否存在明显的语法错误
# 方法：在浏览器 DevTools Sources 面板中打开每个 CSS 文件，确认无红色波浪线
# 或使用在线 CSS validator
```

**JS 文件：**
```bash
# 使用 Node.js 进行语法检查（如果可用）
node -c js/utils.js
node -c js/app.core.js
node -c js/app.data.js
# ... 对所有新创建的 JS 文件执行

# 替代方案：在浏览器 Console 中检查是否有 SyntaxError
# 任何 JS 语法错误都会阻止该文件及后续文件加载
```

**Windows 下无 Node.js 时的替代检查命令：**
```bash
# 确认文件以正确的 JS 语法结尾（无截断）
# 每个 JS 文件必须以完整的表达式或函数声明结束
tail -5 <file>.js   # 检查文件末尾
head -5 <file>.js   # 检查文件开头
```

### 3.3 运行时检查
- [ ] `python server.py` 启动无报错
- [ ] 浏览器 Hard Refresh（Ctrl+Shift+R）首页正常加载
- [ ] 浏览器 Console 无 `SyntaxError`
- [ ] 浏览器 Console 无 `Uncaught ReferenceError`（特别注意 `app.xxx is not a function`）
- [ ] 浏览器 Console 无 `Uncaught TypeError`
- [ ] 浏览器 Network 标签无 404（CSS/JS 文件全部加载成功）
- [ ] `app.init()` 正常执行完毕（sidebar 状态栏显示"已连接 · rev xxx"）

---

## 4. 页面人工验收清单

### 4.1 首页
- [ ] 首页正常显示，3 张入口卡片渲染正确
- [ ] 侧栏导航正常，点击可切换模块
- [ ] 侧栏折叠/展开正常
- [ ] 保存状态栏显示"已连接"

### 4.2 项目管理
- [ ] 项目列表正常显示
- [ ] 新建项目 → 弹窗正常 → 填写后保存成功
- [ ] 编辑项目 → 弹窗正常 → 修改后保存成功
- [ ] 删除项目 → 影响确认弹窗 → 输入 DELETE → 删除成功
- [ ] "进入项目"按钮跳转到工作台

### 4.3 项目工作台 — 主页
- [ ] 项目配置工作台正常显示
- [ ] 阶段卡片正常显示（进度条/指标）
- [ ] 人员配置区域正常，新增/移出人员
- [ ] 位置配置区域正常，新增/删除位置
- [ ] 折叠/展开各区域正常
- [ ] 阶段拖拽排序功能正常

### 4.4 项目工作台 — 阶段配置
- [ ] "配置测试用例集"打开阶段配置页
- [ ] 阶段名称编辑实时保存
- [ ] SKU 方案增删正常
- [ ] BOM 上料清单表格正常
- [ ] 测试策略表格正常，用例下拉搜索
- [ ] SKU 勾选触发自动同步

### 4.5 项目工作台 — 任务管理
- [ ] 任务列表正常显示
- [ ] 状态统计数字正确
- [ ] 筛选栏各维度筛选正常
- [ ] "新增任务"弹窗正常，批量创建
- [ ] 任务配置面板（计划+样机两Tab）正常
- [ ] 样机选择器搜索/折叠/勾选正常
- [ ] 样机数量提示正确显示

### 4.6 项目工作台 — 任务操作
- [ ] 分配样机 → 启动任务
- [ ] 进行中 → 上传结果（可不结束）
- [ ] 进行中 → 阻塞
- [ ] 阻塞中 → 重启
- [ ] 临时变更（执行人/时间/样机）
- [ ] 结束任务（正常完成/异常完成）
- [ ] 任务日志查看
- [ ] 问题单录入
- [ ] 删除任务

### 4.7 样机档案池
- [ ] 样机池列表正常
- [ ] 统计数字正确
- [ ] 进入样机池查看样机列表
- [ ] 筛选（关键词/状态/挂账人/持有人）
- [ ] 新增样机
- [ ] 编辑样机（详情弹窗 5 标签页）
- [ ] 样机照片上传/预览/重命名/删除
- [ ] 样机问题表编辑
- [ ] 测试履历查看
- [ ] 样机档案销毁（单台/整池）

### 4.8 数据持久化
- [ ] 创建/修改数据后刷新页面，数据仍在
- [ ] 多标签页同时打开，修改后冲突处理正常

---

## 5. 回滚策略

### 5.1 单轮回滚
```bash
git checkout -- .          # 丢弃本轮所有修改
git clean -fd              # 删除新建的文件
```

### 5.2 阶段回滚
```bash
git reset --hard <phase-n-done-commit>
```

### 5.3 完全回滚
```bash
git reset --hard <initial-snapshot-commit>
```

### 5.4 紧急回滚（无 git）
从备份目录恢复整个项目文件夹。

---

## 6. 语法检查命令

```bash
# === 检查所有 JS 文件语法（需 Node.js） ===
for f in js/utils.js js/app.js js/projects.js js/workspace.js js/samples.js; do
  echo "Checking $f..."
  node -c "$f" || echo "FAILED: $f"
done

# === 检查新创建的 JS 文件 ===
for f in js/app.*.js js/workspace/*.js js/samples/*.js; do
  [ -f "$f" ] && node -c "$f" || true
done

# === 检查 CSS 文件是否以完整的块结束 ===
# 每个 CSS 文件必须以 } 结束
for f in css/*.css; do
  echo "=== $f ==="
  tail -3 "$f"
done

# === 检查 index.html 中的引用完整性 ===
# 确保所有 <script src="..."> 指向的文件都存在
grep -oP 'src="([^"]+)"' index.html | while read -r line; do
  file=$(echo "$line" | grep -oP '"[^"]+"' | tr -d '"')
  [ -f "$file" ] && echo "OK: $file" || echo "MISSING: $file"
done
```

---

## 7. 高风险区域列表

以下区域修改时需要格外谨慎：

### 7.1 加载顺序敏感
| 区域 | 风险 | 原因 |
|------|------|------|
| `app.core.js` → `app.data.js` | **极高** | `init()` 中调用 `normalize()`，`normalize()` 中调用 `allSamples()` 等 data 函数 |
| `app.core.js` → `app.render.js` | **高** | `init()` 中调用 `render()` |
| `app.data.js` → `workspace.task-table.js` | **高** | `taskFlowStatus()` 被广泛调用 |
| 所有模块 → `utils.js` | **极高** | 所有模块都依赖 `Utils`，必须最先加载 |

### 7.2 函数名冲突
| 区域 | 风险 | 说明 |
|------|------|------|
| `app.js` vs `samples.js` | **高** | `openSampleReadonly` 和 `sampleDisplayCode` 在两个文件中各定义了一份，逻辑不同。拆分时必须确认以哪个版本为准（实际使用 samples.js 的版本） |
| `app.js` vs `workspace.js` | **中** | `taskFlowStatus` 在 app.js 中未定义但可能被调用 |

### 7.3 CSS 优先级
| 区域 | 风险 | 说明 |
|------|------|------|
| `!important` patch 块 | **高** | 行 4101-4285（任务配置滚动修复）依赖 `!important` 覆盖早期规则。拆分时这些块必须放在对应目标文件的末尾 |
| 响应式 `@media` | **中** | 必须全部集中在 `90-responsive.css` 中，且在最后加载 |
| 组件默认样式 vs 页面覆盖 | **中** | `02-components.css` 中的 button/input 默认样式会被页面 CSS 中的特定选择器覆盖。必须保持加载顺序 |

### 7.4 全局事件监听
| 区域 | 风险 | 说明 |
|------|------|------|
| `app.init()` 中的事件绑定 | **高** | `click`（任务操作菜单关闭）、`keydown`（Escape）、`pointerdown`（用例下拉关闭）在 init 中绑定。拆分 `app.core.js` 后需确认这些绑定仍正常 |
| `previewSamplePhoto` 中的滚轮/拖动 | **中** | 使用 `addEventListener` 绑定到 `window`，注意内存泄漏 |

### 7.5 闭包/状态共享
| 区域 | 风险 | 说明 |
|------|------|------|
| `_modalStack` / `_restoringModal` | **高** | 模态框堆栈依赖这些模块级变量，拆分 `app.modal.js` 后需保持 |
| `_saveInFlight` / `_saveQueued` / `_saveTimer` | **高** | 保存队列化状态，拆分后不能丢失 |
| `_caseDropdownState` | **中** | 用例下拉状态，拆分后保持引用 |
| `_taskResultBaseline` / `_taskResultUploadContext` | **中** | 结果录入上下文，跨函数共享 |

---

## 8. 常见拆分错误及预防

| 错误 | 表现 | 预防 |
|------|------|------|
| JS 文件截断 | `SyntaxError: Unexpected end of input` | 移动前确认函数的花括号配对 |
| 函数遗漏 | `Uncaught TypeError: app.xxx is not a function` | 使用 grep 确认函数在所有文件中的引用 |
| 加载顺序错误 | `Uncaught ReferenceError: Cannot access 'app' before initialization` | 严格按执行计划中的加载顺序 |
| CSS 规则遗漏 | 某元素样式丢失 | 逐条对比原始 style.css 和目标文件 |
| CSS 优先级变化 | 某规则不再生效 | 保持原始文件中的规则顺序 |
| 文件路径错误 | 404 Not Found | index.html 中的路径相对于 ROOT_DIR |
| Object.assign 缺失 | 函数未挂到 app 上 | 每个 JS 文件必须以 `Object.assign(app, { ... })` 包裹 |

---

## 9. 拆分操作伪代码模板

### CSS 拆分模板
```
1. Read source: css/style.css
2. 定位本轮目标规则块（行号范围 L1-L2）
3. 复制规则块到目标文件（如 css/00-vars.css）
4. 从 css/style.css 中删除对应规则块
5. 验证目标文件语法正确
6. 如本轮是 Phase 1 最后一轮，将 style.css 替换为 @import 语句
7. 如非最后一轮，更新 index.html 添加新的 <link>（或保持用 style.css @import）
8. 浏览器验证
```

### JS 拆分模板
```
1. Read source: js/workspace.js
2. 定位本轮目标函数（函数名清单）
3. 创建目标文件（如 js/workspace/workspace.home.js）
4. 将 "Object.assign(app, {" 写入目标文件开头
5. 复制目标函数到目标文件
6. 将 "});" 写入目标文件末尾
7. 从源文件中删除对应函数
8. 更新 index.html：在源文件 <script> 之前插入目标文件 <script>
9. 当源文件所有函数都移动完毕后，从 index.html 删除源文件 <script>
10. 删除源文件
11. 浏览器验证
```
