# 三插件统一运维工作台实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 EmbyLibraryOrganizer、MediaMetadataSync 和 DirectoryFileSearch 的主页面与配置页统一为已批准的 A 方案运维工作台，并保持现有接口和删除安全链不变。

**架构：** 三个插件继续独立构建和发布，不新增共享运行时依赖。每个 Vue 组件采用相同的 `plugin-workbench` / `plugin-config` 结构合同、Vuetify 语义 token、状态反馈和响应式规则；跨插件 pytest 源码合同测试负责防止后续视觉与可访问性规则漂移。

**技术栈：** Vue 3、Vuetify 3、Vite Module Federation、pytest、Playwright 浏览器验证。

---

## 文件结构

- 创建 `tests/v2/test_plugin_frontend_workbench.py`：验证三个插件共同的页面结构、可访问性、响应式和主题合同。
- 修改 `frontend/embylibraryorganizer/src/components/Page.vue`：把双扫描区整理为标签内工具栏，补充指标状态带和统一交互语义。
- 修改 `frontend/mediametadatasync/src/components/Page.vue`：统一工作台壳层、主次任务层级和语义状态反馈。
- 修改 `frontend/directoryfilesearch/src/components/Page.vue`：统一工作台壳层，增加结果/任务/记录视图并保留搜索与批量删除。
- 修改三个 `frontend/*/src/components/Config.vue`：统一配置页结构、辅助文字、字段错误、底部操作和移动端规则。
- 修改三个 `frontend/*/src/App.vue`：仅在本地预览需要时补齐新增视图的模拟数据，不改变联邦导出合同。
- 生成三个 `plugins.v2/<plugin>/dist/`：更新联邦构建产物。

### 任务 1：建立统一 UI 合同测试

**文件：**
- 创建：`tests/v2/test_plugin_frontend_workbench.py`

- [ ] **步骤 1：编写失败的主页面与配置页合同测试**

```python
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_IDS = (
    "embylibraryorganizer",
    "mediametadatasync",
    "directoryfilesearch",
)


def read_component(plugin_id: str, component: str) -> str:
    """读取指定插件的 Vue 组件源码。"""
    return (
        ROOT
        / "frontend"
        / plugin_id
        / "src"
        / "components"
        / component
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("plugin_id", PLUGIN_IDS)
def test_plugin_page_uses_shared_workbench_contract(plugin_id: str) -> None:
    """三个插件主页面应遵循统一工作台与可访问性合同。"""
    source = read_component(plugin_id, "Page.vue")

    assert 'class="plugin-workbench' in source
    assert 'class="metric-grid"' in source
    assert 'aria-label="刷新插件状态"' in source
    assert 'aria-label="打开插件设置"' in source
    assert 'aria-label="关闭插件页面"' in source
    assert 'aria-live="polite"' in source
    assert "min-height: 44px" in source
    assert "letter-spacing: 0" in source
    assert "@media (prefers-reduced-motion: reduce)" in source


@pytest.mark.parametrize("plugin_id", PLUGIN_IDS)
def test_plugin_config_uses_shared_form_contract(plugin_id: str) -> None:
    """三个插件配置页应遵循统一表单与辅助信息合同。"""
    source = read_component(plugin_id, "Config.vue")

    assert 'class="plugin-config' in source
    assert 'aria-label="关闭插件设置"' in source
    assert 'class="field-help"' in source
    assert "min-height: 44px" in source
    assert "letter-spacing: 0" in source
    assert "@media (prefers-reduced-motion: reduce)" in source
```

- [ ] **步骤 2：运行测试并确认因统一合同尚未实现而失败**

运行：`pytest tests/v2/test_plugin_frontend_workbench.py -v`

预期：3 个参数化主页面用例和 3 个配置页用例中至少一个断言失败，首个失败包含 `class="plugin-workbench` 或 `class="plugin-config`。

- [ ] **步骤 3：提交测试红灯**

```bash
git add tests/v2/test_plugin_frontend_workbench.py
git commit -m "test: 添加三插件工作台界面合同"
```

### 任务 2：改造 EmbyLibraryOrganizer 主页面

**文件：**
- 修改：`frontend/embylibraryorganizer/src/components/Page.vue`

- [ ] **步骤 1：实现统一页头、状态反馈和指标状态带**

将根节点改为 `class="plugin-workbench organizer-page"`。三个页头图标按钮分别加入：

```vue
aria-label="刷新插件状态"
aria-label="打开插件设置"
aria-label="关闭插件页面"
```

任务状态区使用稳定的实时区域：

```vue
<div
  class="task-strip"
  :class="statusTone"
  aria-live="polite"
  aria-atomic="true"
>
  <v-progress-circular v-if="scanRunning" indeterminate size="18" width="2" />
  <v-icon v-else :icon="state.status === 'failed' ? 'mdi-alert-circle-outline' : 'mdi-information-outline'" size="20" />
  <span>{{ state.last_error || state.task_message || statusText }}</span>
</div>
```

在标签前加入四项指标：

```vue
<section class="metric-grid" aria-label="媒体库整理概览">
  <div class="metric-cell"><strong>{{ state.missing.total }}</strong><span>缺失元数据</span></div>
  <div class="metric-cell"><strong>{{ state.orphan.total }}</strong><span>多余元数据</span></div>
  <div class="metric-cell"><strong>{{ state.categories.length }}</strong><span>可用分类</span></div>
  <div class="metric-cell"><strong>{{ formatShortTime(state.scan_finished_at) || '-' }}</strong><span>完成时间</span></div>
</section>
```

新增 `formatShortTime`，复用现有日期解析规则并只返回本地化时分值。

- [ ] **步骤 2：把扫描范围移入对应标签工具栏**

删除页面顶部同时展示的两条 `scan-row`。在 `missing` 标签内放置缺失分类选择和“查询缺失元数据”主按钮，在 `orphan` 标签内放置多余分类选择和“扫描多余元数据”主按钮；保留原有 `updateCategorySelection`、`startScan`、禁用条件和选择值，不修改 API 调用。

- [ ] **步骤 3：加入统一工作台 CSS 合同**

在局部样式中加入并应用以下规则：

```css
.plugin-workbench {
  display: flex;
  min-height: min(760px, 92vh);
  flex-direction: column;
  overflow: hidden;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
  letter-spacing: 0;
}

.header-actions :deep(.v-btn),
.episode-actions :deep(.v-btn),
.orphan-row :deep(.v-btn) {
  min-width: 44px;
  min-height: 44px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.metric-cell {
  min-width: 0;
  padding: 12px 18px;
  border-inline-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.metric-cell strong,
.metric-cell span { display: block; }
.metric-cell strong { font-variant-numeric: tabular-nums; }

@media (max-width: 760px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .scan-row { grid-template-columns: 1fr; }
  .scan-row :deep(.v-btn) { width: 100%; min-height: 44px; }
}

@media (prefers-reduced-motion: reduce) {
  .plugin-workbench *,
  .plugin-workbench *::before,
  .plugin-workbench *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
```

- [ ] **步骤 4：运行合同测试并确认 Emby 用例转绿**

运行：`pytest tests/v2/test_plugin_frontend_workbench.py -v`

预期：`embylibraryorganizer-Page.vue` 对应主页面用例通过，其余未实现用例继续失败。

### 任务 3：改造 MediaMetadataSync 主页面

**文件：**
- 修改：`frontend/mediametadatasync/src/components/Page.vue`

- [ ] **步骤 1：统一壳层和可访问名称**

根节点改为 `class="plugin-workbench sync-console"`。页头三个图标按钮使用与任务 2 相同的 aria-label；任务横幅加入 `aria-live="polite" aria-atomic="true"`。保留现有 `v-tabs`、状态派生值、轮询和 API 调用。

- [ ] **步骤 2：收敛同步操作层级**

保持“双向全量”为唯一填充色主按钮；“正向全量”和“JSON 回写”统一为 `variant="outlined"`；监控启停统一为 `variant="text"`，只用图标和状态文字表达启停，不改变原有提交动作。

- [ ] **步骤 3：用宿主语义 token 替换组件内强制主题**

移除 `.sync-console` 中覆盖 `--v-theme-*` 和 `color-scheme` 的硬编码亮暗色块。局部变量改为：

```css
.plugin-workbench {
  --workbench-surface: rgb(var(--v-theme-surface));
  --workbench-text: rgb(var(--v-theme-on-surface));
  --workbench-muted: rgba(var(--v-theme-on-surface), 0.72);
  --workbench-border: rgba(var(--v-border-color), var(--v-border-opacity));
  background: var(--workbench-surface);
  color: var(--workbench-text);
  letter-spacing: 0;
}
```

补齐 44px 页头/任务按钮触控目标和与任务 2 相同的 reduced-motion 规则。保留现有移动端表格转信息行布局。

- [ ] **步骤 4：运行合同测试并确认 MediaMetadataSync 用例转绿**

运行：`pytest tests/v2/test_plugin_frontend_workbench.py -v`

预期：两个已改主页面用例通过，仅 DirectoryFileSearch 主页面及三个配置页用例失败。

### 任务 4：改造 DirectoryFileSearch 主页面

**文件：**
- 修改：`frontend/directoryfilesearch/src/components/Page.vue`

- [ ] **步骤 1：统一壳层、页头、实时状态和指标区**

根节点改为 `class="plugin-workbench file-search-page"`，加入三个统一 aria-label 和 `aria-live="polite"`。保留现有搜索、指标、选择和删除逻辑。

- [ ] **步骤 2：增加结果、任务状态和执行记录视图**

在脚本中新增：

```javascript
const activeView = ref('results')
```

在指标区之后加入：

```vue
<v-tabs v-model="activeView" class="view-tabs" color="primary" show-arrows>
  <v-tab value="results">搜索结果 <span class="tab-count">{{ totalResults }}</span></v-tab>
  <v-tab value="status">任务状态</v-tab>
  <v-tab value="activity">执行记录</v-tab>
</v-tabs>
<v-divider />
```

用 `v-window` 包住现有结果区；`status` 视图展示 `state.task_message`、开始/完成时间和错误；`activity` 视图展示 `state.logs` 与 `state.last_report`，空数据时显示明确空状态。只消费现有状态，不新增 API。

- [ ] **步骤 3：替换强制主题并补齐响应式合同**

按任务 3 的宿主语义 token 方案移除 `--dfs-*` 对 `--v-theme-*` 的覆盖。保留桌面结果表和当前移动端三列信息行，补齐 44px 触控目标、`letter-spacing: 0` 和 reduced-motion 规则。

- [ ] **步骤 4：运行合同测试并确认三个主页面全部转绿**

运行：`pytest tests/v2/test_plugin_frontend_workbench.py -v`

预期：三个主页面参数化用例全部通过，配置页参数化用例仍失败。

### 任务 5：统一三个配置页

**文件：**
- 修改：`frontend/embylibraryorganizer/src/components/Config.vue`
- 修改：`frontend/mediametadatasync/src/components/Config.vue`
- 修改：`frontend/directoryfilesearch/src/components/Config.vue`

- [ ] **步骤 1：统一结构与可访问名称**

三个根节点分别改为 `class="plugin-config ..."`，关闭按钮统一加入 `aria-label="关闭插件设置"`。每个复杂字段组后加入持续可见辅助文字：

```vue
<p class="field-help">每行填写一个绝对路径；保存前会去除空行。</p>
```

辅助文字按字段语义调整：Emby 说明混合库/蓝光库分类差异，MediaMetadataSync 说明源目录/目标目录和删除挂载边界，DirectoryFileSearch 说明搜索目录限制。

- [ ] **步骤 2：统一字段校验和保存层级**

保留 DirectoryFileSearch 的现有 `rootError`。为 Emby 启用状态下的媒体库路径、MediaMetadataSync 启用状态下的源/目标目录增加 computed 错误数组，并把错误传给对应 `v-text-field` / `v-textarea`；三个保存按钮在字段无效时禁用。取消保持文本按钮，保存保持唯一填充色主按钮。

- [ ] **步骤 3：统一配置页 CSS 合同**

三个配置页都加入：

```css
.plugin-config {
  display: flex;
  min-height: min(560px, 88vh);
  max-height: 92vh;
  flex-direction: column;
  overflow: hidden;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
  letter-spacing: 0;
}

.config-header :deep(.v-btn),
.config-actions :deep(.v-btn) {
  min-height: 44px;
}

.field-help {
  margin: 8px 0 0;
  color: rgba(var(--v-theme-on-surface), 0.72);
  font-size: 0.8125rem;
  line-height: 1.5;
}

@media (prefers-reduced-motion: reduce) {
  .plugin-config *,
  .plugin-config *::before,
  .plugin-config *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
```

760px 以下字段网格改为单列，配置操作栏允许换行但不覆盖滚动内容。

- [ ] **步骤 4：运行合同测试并确认全绿**

运行：`pytest tests/v2/test_plugin_frontend_workbench.py -v`

预期：6 个参数化用例全部通过。

- [ ] **步骤 5：提交 Vue 源码改造**

```bash
git add frontend/embylibraryorganizer/src/components/Page.vue frontend/embylibraryorganizer/src/components/Config.vue frontend/mediametadatasync/src/components/Page.vue frontend/mediametadatasync/src/components/Config.vue frontend/directoryfilesearch/src/components/Page.vue frontend/directoryfilesearch/src/components/Config.vue
git commit -m "feat: 统一三插件运维工作台界面"
```

### 任务 6：构建、回归、运行时同步和视觉验收

**文件：**
- 生成：`plugins.v2/embylibraryorganizer/dist/`
- 生成：`plugins.v2/mediametadatasync/dist/`
- 生成：`plugins.v2/directoryfilesearch/dist/`
- 同步：`/home/zhaojg/MoviePilot/app/plugins/<plugin>/dist/`

- [ ] **步骤 1：构建三个前端**

分别在三个前端目录运行：`npm run build`

预期：三个命令退出码均为 0，各自生成 `dist/assets/remoteEntry.js` 并复制到对应 `plugins.v2/<plugin>/dist`。

- [ ] **步骤 2：运行 UI 合同与三个插件回归测试**

运行：

```bash
pytest tests/v2/test_plugin_frontend_workbench.py tests/v2/embylibraryorganizer/test_plugin.py tests/v2/mediametadatasync/test_plugin.py tests/v2/directoryfilesearch/test_plugin.py -v
```

预期：所有用例通过，测试过程无真实网络请求。

- [ ] **步骤 3：启动本地预览并完成视觉检查**

分别启动三个现有 Vite 预览入口，使用 Playwright 在 1440x900、768x1024 和 375x812 截图。检查主页面与 `?view=config`：无横向滚动、无重叠、亮暗主题文本和边框清晰、按钮触控区域不小于 44px、状态区非空白、结果内容可见。

- [ ] **步骤 4：同步运行时副本**

将三个插件的 `__init__.py`、`core.py`、README 和新 `dist/` 同步到 `/home/zhaojg/MoviePilot/app/plugins/<plugin>/`。使用文件比较确认源插件目录与运行时副本一致，不依赖 Git 状态判断 `app/plugins`。

- [ ] **步骤 5：重启并检查运行时加载**

运行：`moviepilot restart`，随后运行 `moviepilot logs --lines 100`。

预期：日志出现三个插件的加载记录，版本与 `package.v2.json` 一致，且没有联邦资源或插件 API 404。

- [ ] **步骤 6：提交构建产物与验证后的最终改动**

```bash
git add plugins.v2/embylibraryorganizer/dist plugins.v2/mediametadatasync/dist plugins.v2/directoryfilesearch/dist
git commit -m "build: 更新三插件工作台前端产物"
```
