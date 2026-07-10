# Emby 媒体库整理

`EmbyLibraryOrganizer` 是一个面向 MoviePilot v2 的 Emby 媒体库巡检与整理插件，主要用于维护基于 115 STRM 方案建立的媒体库。

插件会扫描本地媒体库目录，识别无效 STRM、重复引用、疑似重复媒体、命名问题、孤儿伴随文件、垃圾文件和空目录，并生成可审查、可导出、可恢复的整理计划。默认使用演练模式，不会直接修改本地或云端文件。

## 适用场景

- Emby 通过本地 `.strm` 文件播放 115 网盘媒体。
- 同一媒体存在多个清晰度、版本或重复 STRM，需要人工选择保留项。
- 多个 STRM 意外指向同一个 115 文件，需要清理重复入口。
- 媒体库中长期积累了孤儿 NFO、缩略图、MediaInfo、临时文件或空目录。
- 希望在实际删除前获得清晰的风险分级、处理计划和执行报告。

## 核心能力

### 扫描与识别

- 支持混合、电影、剧集和动漫媒体库，可同时配置多个根目录。
- 支持 URL 与绝对媒体路径形式的 STRM，解析 `file_id`、`pickcode`、云端路径及自定义身份字段。
- 从路径中提取 TMDB、IMDb、TVDB 标识，优先用于媒体归组与去重。
- 支持 `SxxExx`、`Season 01/Episode 01`、动漫简单集号等常见剧集结构。
- 检查电影年份、剧集编号、年份冲突、缺失 NFO 和缺失图片等问题。
- 孤儿伴随文件按同目录 STRM 归属判断；电影检查 NFO、缩略图和 MediaInfo，电视剧仅检查季目录中的集级 NFO、缩略图和 MediaInfo，剧级文件与字幕不参与处理。
- 多余元数据和缺失元数据专项扫描会提前过滤无关文件，并使用轻量路径记录减少网络盘读取。
- 可使用 MoviePilot 已同步的媒体服务器缓存核对媒体是否已入库，不直接请求 Emby 外部接口。

### 重复分析与计划审查

- 区分“多个 STRM 指向同一文件”的引用重复和“不同文件对应同一媒体”的媒体重复。
- 支持质量与命名、优先路径、最新修改时间、文件体积四种保留策略。
- 为每个重复组记录评分明细、推荐保留项、候选清理项和风险等级。
- 可按动作、风险、重复组、问题代码和问题级别筛选或导出结果。
- 支持人工修改重复组保留项，并自动重建相关整理动作。

### 执行、审计与恢复

- 本地文件默认移动到插件隔离区，也可选择直接删除模式。
- 可选通过 MoviePilot 的 `115网盘Plus` 存储能力将重复云端文件移入回收站。
- 提供云端删除预检、计划专属确认 token、源文件快照和执行结果快照。
- 支持隔离文件单项恢复、按执行批次恢复和过期隔离文件清理。
- 支持 JSON、CSV、Markdown 计划及执行报告导出。
- 扫描、重复分析、计划生成和逐项执行均输出带插件前缀的进度日志。
- 详情页直接列出多余元数据的类型、原路径、处理状态及隔离位置，最多展示 200 条。
- 自动识别电影、电视剧和动漫目录下的二级分类，可多选分类查询缺少同名 NFO 或 `-mediainfo.json` 的 STRM。
- 详情概览只展示少量结果示例，可进入完整结果页按影视条目分页，并展开电视剧查看各季各集缺失项。
- 缺失详情只显示 NFO/JSON 类型，可逐个清理 STRM，或联动清理其现有同名 NFO、缩略图和 MediaInfo。
- 电视剧季目录支持按 `SxxExx` 或 `第X集/话` 识别同格式文件，一次清理仅集号不同的整组 STRM 及联动元数据。
- 提供插件详情页、首页仪表盘摘要、定时扫描和执行完成通知。

## 安全机制

插件将删除操作设计为失败即停止：

- 默认开启 `dry_run`，首次扫描只生成计划。
- 引用重复不会删除云端文件，因为保留 STRM 仍依赖同一 115 文件。
- 云端删除必须具备 `file_id` 和云端路径，并通过实时存在性与 ID 一致性校验。
- 云端删除仅在对应本地重复 STRM 已成功隔离或删除后执行。
- 本地动作被禁用、失败或计划快照过期时，关联云端动作自动跳过。
- 真实云端删除必须提交本次计划的确认 token；缺失或不匹配时不会执行。
- 本地动作只能处理已配置媒体库内部路径，越界符号链接不会进入扫描结果。
- 保护路径、单次最大处理数量和动作风险会在计划阶段提前标记。
- 隔离恢复不会递归覆盖同名目录，也不会接受隔离区外的备份路径。
- 空目录动作只删除执行时仍为空的目录，且不会删除媒体库根目录。

即使已经完成演练，也建议先导出计划并确认保留项、保护路径和云端文件身份，再执行真实清理。

## 环境要求

- MoviePilot `>= 2.12.0`
- 已挂载到 MoviePilot 容器或主机的 Emby STRM 媒体库目录
- 如需同步清理 115 文件，MoviePilot 中需配置并启用 `115网盘Plus`

插件不直接连接 Emby 或 115 HTTP API，媒体服务器核对使用 MoviePilot 本地缓存，云端操作通过 MoviePilot 已有存储链完成。

## 安装

### 插件市场

将以下仓库地址追加到 MoviePilot 的 `PLUGIN_MARKET` 配置，多个仓库使用英文逗号分隔：

```text
https://github.com/fxing263/MoviePilot-Plugins
```

刷新插件市场后，搜索并安装“Emby媒体库整理”。

### 本地仓库

克隆本仓库后，也可以将仓库根目录加入 `PLUGIN_LOCAL_REPO_PATHS`：

```text
/path/to/MoviePilot-Plugins
```

本地仓库必须保留 `package.v2.json` 与 `plugins.v2/embylibraryorganizer/` 的目录结构。

## 推荐使用流程

1. 配置电影媒体库路径和剧集媒体库路径。
2. 点击“扫描多余元数据”，查看候选文件和清理动作数量。
3. 保持 `dry_run` 开启进行首次演练，点击“确认执行”检查结果。
4. 确认候选正确后关闭演练模式，再次扫描并确认执行。
5. 默认删除方式为移入插件隔离区，可在执行后恢复。

“扫描多余元数据”只处理电影目录和电视剧季目录中没有同名 STRM 的 NFO、`-thumb` 图片和 `-mediainfo.json`；不会检查或删除字幕、电视剧剧级元数据、重复 STRM、空目录和 115 文件。

“查询缺失元数据”需要先在插件配置中选择一个或多个自动识别的二级分类。查询只生成缺失列表，不生成删除动作；电视剧仅检查季目录中的 STRM。

## 关键配置

| 配置项 | 说明 | 建议 |
| --- | --- | --- |
| `library_paths` | 混合媒体库路径 | 至少配置一项 |
| `movie_library_paths` | 电影媒体库路径 | 独立分库时配置 |
| `tv_library_paths` | 剧集媒体库路径 | 独立分库时配置 |
| `anime_library_paths` | 动漫媒体库路径 | 独立分库时配置 |
| `exclude_patterns` | 扫描排除正则 | 排除缓存和临时目录 |
| `protected_local_paths` | 禁止本地清理的路径 | 建议配置资源根目录和保种目录 |
| `protected_115_paths` | 禁止云端清理的路径 | 启用云端删除前必须审查 |
| `keep_strategy` | 重复项保留策略 | 默认 `quality_then_naming` |
| `delete_sidecar_files` | 清理重复 STRM 独占的 NFO、缩略图和 MediaInfo | 默认关闭 |
| `delete_orphan_sidecar_files` | 清理电影或季目录中无法归属 STRM 的伴随文件 | 默认关闭，字幕与剧级文件不处理 |
| `delete_empty_dirs` | 清理空目录 | 电视剧仅处理季目录 |
| `local_delete_mode` | `quarantine` 或 `delete` | 建议保持 `quarantine` |
| `max_delete_count` | 单次最大处理数量 | 初次使用设置较小值 |
| `sync_delete_115` | 同步清理 115 文件 | 完成本地演练后再开启 |
| `dry_run` | 仅生成执行结果，不实际清理 | 初次使用必须开启 |
| `require_confirm` | 执行前要求确认 | 建议始终开启 |
| `cron` | 定时扫描表达式 | 确认手动流程稳定后再配置 |

## 常用 API

插件 API 统一位于 `/api/v1/plugin/EmbyLibraryOrganizer`：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/scan` | 扫描媒体库并生成计划 |
| `POST` | `/scan_orphan_metadata` | 仅扫描多余元数据并生成清理计划 |
| `POST` | `/scan_missing_metadata` | 按所选二级分类查询缺失NFO或MediaInfo的STRM |
| `GET` | `/categories` | 获取自动识别的媒体库二级分类 |
| `POST` | `/delete_missing_strm` | 清理指定缺失项STRM及可选联动元数据 |
| `POST` | `/delete_episode_group` | 清理电视剧季目录中仅集号不同的同格式STRM及联动元数据 |
| `GET` | `/validate` | 校验当前配置 |
| `GET` | `/plan` | 查询最近计划 |
| `GET` | `/groups` | 查询重复组和关联动作 |
| `POST` | `/group/keep` | 修改重复组保留项 |
| `POST` | `/preflight` | 预检 115 删除动作 |
| `GET` | `/confirm_token` | 获取当前计划确认 token |
| `POST` | `/execute` | 执行最近计划 |
| `GET` | `/quarantine` | 查询隔离文件 |
| `POST` | `/restore` | 恢复单个隔离文件 |
| `POST` | `/restore_batch` | 恢复一个执行批次 |
| `POST` | `/export` | 导出整理计划 |
| `POST` | `/export_execution` | 导出执行报告 |

所有接口均使用 MoviePilot 插件 API 鉴权机制。

## 仓库结构

```text
MoviePilot-Plugins/
├── package.v2.json
├── plugins.v2/
│   └── embylibraryorganizer/
│       ├── __init__.py
│       └── core.py
└── tests/v2/embylibraryorganizer/
    └── test_plugin.py
```

## 开发验证

插件运行在 MoviePilot 后端环境中。修改后至少运行：

```bash
pytest tests/v2/embylibraryorganizer/test_plugin.py
```

同时确认 `package.v2.json` 中的版本与 `EmbyLibraryOrganizer.plugin_version` 一致。

MoviePilot 插件开发资料：

- [仓库指南](./docs/Repository_Guide.md)
- [V2 插件开发指南](./docs/V2_Plugin_Development.md)
- [常见问题](./docs/FAQ.md)

## 许可证

本仓库使用 [GNU General Public License v3.0](./LICENSE)。
