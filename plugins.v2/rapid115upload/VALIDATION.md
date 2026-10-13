# 115仅秒传 1.0.0 验证记录

日期：2026-10-03。未安装到运行中的 MoviePilot，未使用真实115账号或媒体文件。

## 已执行

仓库根目录使用现有 `.venv`，未改变主程序依赖或锁文件：

```bash
uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py -q
```

最终 **53 passed**。覆盖秒传命中/未命中、二次校验区间、普通上传接口禁入、目录创建竞争、
错误与限流冷却、远端重名核对、队列原子保存、重启恢复、重复事件、并发登记、
源文件变化/丢失/符号链接、缓存哈希、停止、配置边界、管理员权限及前端保存门禁。
pytest 网络守卫启用，网络响应全部由替身提供。

```bash
uv run --locked --no-sync pylint \
  local-plugins/plugins.v2/rapid115upload/__init__.py \
  local-plugins/plugins.v2/rapid115upload/client.py \
  local-plugins/plugins.v2/rapid115upload/queue.py \
  local-plugins/plugins.v2/rapid115upload/rules.py \
  tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py --reports=n
```

通过，**10.00/10**。

在 `local-plugins/plugins.v2/rapid115upload/frontend/`：

```bash
npm ci --offline --no-audit --no-fund
npm run build
```

通过；复用延迟暂存插件的依赖锁与联邦构建方式，生成 Config/Page 和 `remoteEntry.js`。
离线安装报告 esbuild 的安装脚本被环境阻止，但已缓存的平台二进制可用，构建成功。
前端打包测试最初误把 Vite 提取到共享 chunk 的状态字典当成 Page 内联内容，
按实际依赖拆分修正断言后通过；保留对全部三行路径及“已上传”字典的产物检查。

```bash
git diff --check
```

通过；原有未提交文档内容保留，仅追加本插件契约。`app/` 没有代码差异。

## 扩展架构检查的工作区限制

```bash
uv run --locked --no-sync pytest \
  tests/test_architecture_dependencies.py \
  tests/test_architecture_adapter_imports.py \
  tests/test_architecture_egress.py -q
```

结果：**126 passed，1 failed**。唯一失败是
`test_legacy_source_directories_do_not_exist`：工作区存在 `app/core`、`app/helper`、`app/utils`。
目录时间为2026-09-15，含历史 `.pyc` 和 `app/helper/sites.cpython-314-aarch64-linux-gnu.so`，
不在 HEAD 中，本次未创建、修改或删除。这不是本插件增加的依赖或源码违规。

为核对归因，将 HEAD 用 `git archive HEAD` 导出到独立临时目录，在该目录执行：

```bash
/home/zhaojg/MoviePilot/.venv/bin/python -m pytest \
  tests/test_architecture_dependencies.py::test_legacy_source_directories_do_not_exist -q
```

结果：**1 passed**。没有修改测试、刷新基线或删除现有工作区残留文件。
原工作区的完整架构命令仍记为未全通过，不能将干净副本单项结果冒称为全套通过。

## 未验证与交付边界

- 未进行真实115协议联调、登录刷新或实际秒传；接口字段沿用当前宿主实现。
- 未在运行中宿主安装或进行浏览器端到端测试；前端已构建并验证保存/产物契约。
- 未运行全产品测试；此次交付仅新增独立本地插件、测试、插件索引与文档，无宿主代码/DB/SDK改动。
- 三行路径在插件自己的“115秒传记录”页；嵌入原整理历史页属于下一部分。
- 未提交 Git 或推送；当前授权范围内没有部署、账户操作、真实上传或文件清理。


## 实际安装验证（2026-10-03）

用户启动本机 MP 后，按明确安装授权通过运行实例的插件安装接口安装本地来源
`local://Rapid115Upload?path=/home/zhaojg/MoviePilot/local-plugins&version=v2`。
返回“插件安装成功”，`restart_required=false`。

- 已安装列表：`installed=true`、`runtime_status=active`、版本1.0.0。
- 配置表单与页面元数据接口正常，均为 Vue 渲染模式。
- 任务接口：`success=true`、`enabled=false`、`tasks=[]`、`error=""`。
- 关闭状态空映射配置通过在线只读校验，未保存映射或启用插件。
- 安装后的四个 Python 文件及 `remoteEntry.js` 与开发源逐字节一致。
- 静态资源接口仅接受登录资源 Cookie；单独使用 API Key 的探测返回预期401，
  本次未进行浏览器登录及页面端到端验证。
- 安装未重启宿主，未调用115、未入队实际文件、未执行秒传或清理。

上文“未安装”的边界描述对应代码验收阶段；安装状态以本节为准。

# 1.1.0 合并版验证（2026-10-11）

本次仅实现、构建与同步插件源码，不重启、不改运行配置，不发送真实115/qB请求。
独立 qB标签监控1.1.1原文件保留；合并版 `tag_hook.py` 与其 `hook.py` 逐字节一致。

## 最终通过

- `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py tests/test_qbittorrent_tag_monitor.py tests/test_builtin_skill_boundaries.py -q`：167 passed。
- `uv run --locked --no-sync pylint local-plugins/plugins.v2/rapid115upload/{__init__,client,queue,rules,normal,torrents,tag_hook}.py tests/test_rapid115upload.py --reports=n`：10.00/10。
- `uv run --locked --no-sync python scripts/architecture/baseline.py --check-host`：退出码0，未更新基线。
- `uv run --locked --no-sync pytest tests/test_chain_rate_limit.py tests/test_episode_group_recognition.py tests/test_system_notification_dispatch.py tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py -q`：88 passed，验证旧下载器模块替身与插件用例混跑。
- 插件前端：`npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend` 成功。
- 宿主前端目录 `artifacts/rapid115-frontend`：
  - `./node_modules/.bin/vitest run src/composables/__tests__/useRapid115History.spec.ts src/views/reorganize/__tests__/Rapid115HistoryStatus.spec.ts src/views/reorganize/__tests__/TransferHistoryView.spec.ts`：70 passed。
  - `./node_modules/.bin/vue-tsc --noEmit`：通过。
  - `./node_modules/.bin/eslint src/composables/useRapid115History.ts src/composables/__tests__/useRapid115History.spec.ts src/views/reorganize/Rapid115HistoryStatus.vue src/views/reorganize/__tests__/Rapid115HistoryStatus.spec.ts src/locales/zh-CN.ts src/locales/zh-TW.ts src/locales/en-US.ts`：通过。
  - `./node_modules/.bin/vite build`：成功。
- `git diff --check`：通过。

新增覆盖：目标路径入队和Hash关联、重复整理的多记录关联、并行工作且不重复认领、
秒传次数耗尽回退、网络异常不消耗次数、普通上传分片/远端校验/停止回收/凭据过期刷新、
整种子完整清单核对、映射缺口禁止回写、标签失败独立重试、测试模式零外部调用、挂钩冲突与停止恢复。

## 未通过的全工作区检查

- 架构策略五组测试（dependencies、adapter_imports、egress、event_facts、event_policy）：
  165 passed，1 failed。失败为 `test_legacy_source_directories_do_not_exist`，
  工作区存在9月15日留下的 `app/core`、`app/helper`、`app/utils` 目录。本次未删除现场或改动基线。
- `uv run --locked --no-sync python tests/run.py`：退出码2，未全绿。
  收集失败涉及既有 `MediaServerQuality` 缺失及 `mediaintake/constants.py` 缺失；
  其他失败包括既有Agent测试、RSS测试、插件清单不完整和 `test_ptdaily.py` 旧ChainBase导入。
  首轮还发现旧测试留下不完整 `qbittorrentapi` 替身影响新插件导入，已改为按需加载qB适配，
  并通过上述88项混跑测试；技能文档英文约束失败已修复，11项技能边界测试包含在最终167项中。
  修复后未重复运行整套已知仍受其他插件缺失影响的全量套件，不将局部成功表述为全量通过。

真实115秒传、OSS回调和真实qB标签回写尚未实测。安装包已构建；需重载插件，
按说明配置映射及标签，并部署配套宿主前端构建后，才能在运行页面使用全部新功能。

## 插件弹窗精简（2026-10-11）

插件管理弹窗自动转入配置，不渲染记录、不发起队列请求或轮询；侧栏 navKey 入口继续显示队列。移除配置页的记录切换按钮。
`npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend` 通过；
`uv run --locked --no-sync pytest tests/test_rapid115upload_frontend.py -q`：5 passed。
仅同步前端资源与说明文档，不变更运行配置。

## 配置分页与间距修复（2026-10-11）

配置拆为基本设置、目录映射、qB标签三页；独立字段标签消除浮动标签与提示重叠；固定高度、内部滚动、固定保存栏。多组映射一次编辑一组。
插件前端 Vite 构建成功，`uv run --locked --no-sync pytest tests/test_rapid115upload_frontend.py -q`：5 passed。
Playwright 在1000×840和390×844模拟界面检查分页保留输入、新增/删除映射、无横向溢出、保存按钮可见、模拟保存及无页面异常，全部通过；未连接真实115/qB或修改运行配置。截图位于 `artifacts/rapid115-ui-check/`。

## 复用MP目录及下载器选择（2026-10-11）

本地根由系统目录管理的library_path选取（仅local），不再自由输入；服务端保存验证和整理事件均核对有效系统根。系统目录失效不再登记新任务，历史队列保留。
开关改名“下载器监控增强”，通过宿主download/clients接口选择一个或多个已有qB，不读取凭据。沿用1.1.1挂钩，未改变查询作用域。

验证：
- `npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`：通过。
- `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py tests/test_qbittorrent_tag_monitor.py tests/test_builtin_skill_boundaries.py -q`：172 passed。
- `uv run --locked --no-sync pylint local-plugins/plugins.v2/rapid115upload/{__init__,directories}.py tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py --reports=n`：10.00/10。
- Playwright模拟界面：系统目录选择、两个已有qB多选、切页保留选择、模拟保存、无页面异常，均通过。
- `git diff --check`：通过。未改运行配置或连接真实115/qB。

## 隐藏未映射目录的115行（2026-10-11）

队列只读接口增加mappings根目录快照；前端按路径组件匹配，无映射且无任务时隐藏115行，保留已有任务历史。
`uv run --locked --no-sync pytest tests/test_rapid115upload.py -q`：78 passed。
`uv run --locked --no-sync pylint local-plugins/plugins.v2/rapid115upload/__init__.py tests/test_rapid115upload.py --reports=n`：10.00/10。
宿主前端执行 `./node_modules/.bin/vitest run src/views/reorganize/__tests__/Rapid115HistoryStatus.spec.ts src/composables/__tests__/useRapid115History.spec.ts src/views/reorganize/__tests__/TransferHistoryView.spec.ts`：73 passed。
`./node_modules/.bin/vue-tsc --noEmit`、`./node_modules/.bin/eslint src/views/reorganize/Rapid115HistoryStatus.vue src/views/reorganize/__tests__/Rapid115HistoryStatus.spec.ts src/composables/useRapid115History.ts`、`./node_modules/.bin/vite build` 均通过。
网页静态资源备份后部署到public，保留service.js及旧哈希资源。不变更运行配置或连接115。

## 2026-10-11 上传后处理

新增默认保留、成功后删除整理目标文件的配置；不增加删除来源/身份校验或删除结果字段。删除异常不回滚上传。
离线验证：上传、前端、qB监控相关测试174项通过；前端保存契约修改后7项复测通过。
修改的Python文件 pylint 10/10，插件 Vite 构建通过。未执行真实115上传或删除运行目录文件，未修改运行配置。

空父目录清理：增加第三个处理选项，默认不启用。临时目录测试覆盖逐级清理、根目录保留、NFO阻止清理及映射失效；相关测试178项通过，Vite构建通过。

目录独立次数：移除全局UI配置，每组映射独立保存max_attempts；缺省旧值继承历史全局配置，新目录默认3，队列已有快照不改写。相关测试186项通过，前端构建及修改Python的pylint通过。

首次等待：目录映射initial_delay_minutes默认0，仅在新任务入队时计算ready_at。验证重复事件、重新加载队列不重置时间，首次领取前不增加次数，第一次失败仍使用第一档重试间隔。193项相关测试通过，修改Python pylint 10/10，Vite构建通过。未修改运行配置。

实时进度：OSS分片字节回调提供进度，线程安全内存快照提供阶段及速率，不增加队列磁盘写入。离线回调、速度过期/回退、API不持久化验证通过；195项相关测试通过，构建后前端7项通过，修改Python pylint 10/10。未进行真实115网络上传验收。

移除入队测试模式：删除配置/响应字段、页面提示及运行拦截；旧test_mode值被忽略。原测试模式用例替换为旧配置不阻断执行、停用不访问外部服务的边界验证。196项相关测试通过，修改Python pylint 10/10，Vite构建通过。

主媒体标签核对：按MP RMT_MEDIAEXT筛选种子选中文件，仅成功上传记录覆盖清单；附件未入队或失败不阻挡，无主媒体不标记。新增大小写、附件、未选视频及手动补整理后回写验证。201项相关测试通过，修改Python pylint 10/10。

手动重整关联改为插件实现：撤回宿主transfer.py、transferhistory.py及宿主测试改动，宿主文件与HEAD一致。插件接收失败事件保存来源身份及唯一种子关联，成功事件恢复。覆盖跨队列重载、替换文件、歧义种子和宿主原行为；268项相关测试通过，修改Python pylint 10/10。

失败关联缓存收窄：仅失败事件新增缓存，成功入队不清理；确认整种子已上传标签后，与标签状态一起原子持久化清理唯一缓存。上传覆盖不足、标签失败及重新加载仍保留关联，上传任务links不删除。`uv run --locked --no-sync pytest tests/test_rapid115upload.py -q`：124 passed；`uv run --locked --no-sync pylint local-plugins/plugins.v2/rapid115upload/{__init__,queue}.py tests/test_rapid115upload.py --reports=n`：10/10；`git diff --check`通过。

媒体整理记录插件页面（2026-10-11）：仅复用宿主分页历史和插件队列GET接口，多入口联邦AppPageHistory，无宿主实现改动。记录ID优先，旧记录完整双路径关联；上传读取失败保留历史展示，取消/乱序响应防护。`npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`通过；`uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py -q`：134 passed；`uv run --locked --no-sync pylint local-plugins/plugins.v2/rapid115upload/__init__.py tests/test_rapid115upload_frontend.py --reports=n`：10/10。Playwright模拟接口检查桌面/390px手机、搜索、详情、进度速度及无横向溢出通过；未执行真实整理或上传。git diff --check通过。

界面修正：按原版VDataTableVirtual整理表格结构呈现，恢复路径内115行及底部分页，默认50条；没有复制宿主写操作。最终表格构建、前端10项pytest、模拟浏览器列显示/任务详情/搜索/手机无页面溢出检查通过。

原版源码移植（2026-10-11）：NativeHistory.vue直接摘取宿主TransferHistoryView的桌面工具栏、列插槽、分页及手机article；原版样式加插件根命名空间以免污染宿主。来源SHA256与必要适配记录于NATIVE-SOURCE.md。修正海报读取image字段。`npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`通过；`uv run --locked --no-sync pytest tests/test_rapid115upload_frontend.py tests/test_rapid115upload.py -q`：134 passed。Playwright本地模拟：桌面列、image海报、防抖搜索、上传详情、手机原版卡片及路径展开通过，零Vue警告/页面错误、手机页面无横向溢出。没有更改宿主代码或业务处理流程。

失败重整入口（2026-10-11）：使用MP原有manual历史请求契约，logids恢复来源，后台提交、预览、指定媒体ID/复用历史、目录配置继承；不自行写历史或上传。失败按钮/菜单入口，受理后等待实际历史，不重复提交。`npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`通过；`uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py -q`：135 passed；`uv run --locked --no-sync pylint tests/test_rapid115upload_frontend.py --reports=n`：10/10。Playwright模拟失败入口、预览、单次后台提交、回执与共享历史刷新通过；没有对真实媒体执行重整。

## 完整原版页面与浏览器构建修复（2026-10-11）

此前局部移植已被完整原版历史页与弹窗替代。显式编译生产环境常量，修复浏览器 process is not defined；运行目录旧产物被替换，入口与样式增加构建指纹。

- `npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`：通过；原版 native Vite 构建此前已通过。
- `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py -q`：134 passed。
- `uv run --locked --no-sync pylint tests/test_rapid115upload_frontend.py --reports=n`：10/10。
- `uv run --locked --no-sync python /tmp/test_full_interactions.py`：本地模拟 API 浏览器验证成功记录重新整理完整弹窗、原版控件、批量勾选，无页面异常。
- 已同步运行插件与镜像仓库；MP 插件 reload 接口返回 success=true。未操作真实媒体或修改运行配置。

本次没有执行完整产品测试，也没有将模拟界面检查表述为真实整理/删除验收。

## 预览编辑整理目标路径（2026-10-11）

仅插件新增历史页面改造 ReorganizeDialog，编辑完整目录/文件名后经管理员专用端点验证，MP 原准入 UoW 同事务持久化完整 checkpoint。无编辑上下文的宿主请求保持原行为。目标扩展名保留，编辑目标冻结为不覆盖；成功历史、上传入队及标签均继续来自实际宿主整理结果。

- native `npm run build` 与外层 `npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`：通过。
- `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py tests/test_rapid115upload_reorganize.py tests/test_rapid115upload_reorganize_persistence.py tests/test_qbittorrent_tag_monitor.py tests/test_transfer_planning_checkpoint.py tests/test_transfer_planning_persistence.py tests/test_builtin_skill_boundaries.py -q`：287 passed。
- changed-file pylint（插件 __init__.py、reorganize.py、三个本次变更测试文件）：10/10。
- `artifacts/rapid115-path-preview/check.py` 本地浏览器接口替身：编辑、恢复、非法路径阻断、表单变更失效、手机响应式及真实提交载荷断言通过，未连接真实媒体操作。
- 独立临时 SQLite 验证原子提交/回滚、无插件上下文的宿主恢复、重复准入不能改写先前目标。
- 架构策略5组：165 passed，1 failed；失败仍为工作区遗留 app/core、app/helper、app/utils 物理目录。
- 已执行 `uv run --locked --no-sync python tests/run.py`，退出码2，未全绿。存在旧插件缺文件/导入收集失败、技能目录历史 pycache 被扫描、其他插件包版本不一致及 RSS 用例失败；未修改或掩盖这些工作区问题。详细日志 `/tmp/rapid115-path-full-suite.log`。本功能与原整理计划的聚焦测试结果以上述287项为准，不声称全产品验证通过。

没有对真实文件执行重新整理、删除或上传验收，没有修改宿主源码或数据库schema。


## 2026-10-11 BDMV CD2 extension 1.2.0

- 边界：仅插件自有配置、bdmv.json、已有 qB 客户端及 CloudDrive2储存连接，无宿主业务源码或数据库表改动。
- 实际 MP v3.1.4 locked 环境执行 `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py tests/test_rapid115upload_reorganize.py tests/test_rapid115upload_reorganize_persistence.py tests/test_qbittorrent_tag_monitor.py tests/test_rapid115upload_bdmv.py tests/test_rapid115upload_bdmv_cd2.py -q`：278 passed。全部使用临时状态、qB/CD2替身。
- `npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`：成功。
- 本次修改 Python 文件与三个相关测试文件 pylint：10.00/10。
- 未执行实际 CD2/115 目录上传；没有修改用户配置或开启 BDMV。未重新运行宿主全套测试、架构基线；宿主源码与共享契约未变，采用插件相关回归范围。

## 2026-10-11 BDMV 1.2.1

按用户要求取消上传后115目录复查，只使用关联CD2任务终态及计数；保留上传前源清单与冲突检查。删除对应已退役目标验证测试，新增完成后禁止远端查询且正常切换标签的回归。原七文件pytest命令：276 passed；本次修改的三个生产Python文件与两个测试文件pylint 10/10。未执行真实种子上传。

## 2026-10-12 BDMV Cron 1.2.2

BDMV扫描改为五段Cron，旧HH:MM等价迁移，进度轮询仍一分钟。实际v3.1.4环境 `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py tests/test_rapid115upload_bdmv.py tests/test_rapid115upload_bdmv_cd2.py -q`：201 passed；修改Python与测试pylint10/10；前端npm run build成功。未执行真实上传。

## 2026-10-12 1.2.3 目标目录映射

用户明确允许115目标根重复/包含，仅本地根保持互斥。新增远端同根/父子及本地同根/父子双向校验回归。七文件完整相关pytest：292 passed；rules.py、__init__.py及test_rapid115upload.py pylint10/10。

## 2026-10-13 1.2.4 队列提示展示

按用户要求移除普通上传队列中的种子标签提示，不改变后台核对及重试。前端构建成功；test_rapid115upload_frontend.py：12 passed。

## 2026-10-13 1.2.5 同名复用策略

用户最新明确要求目标名称/路径和字节大小一致即可，不比较远端SHA1。size_byte依据宿主u115.py的__get_info_item；file_id补查依据p115client fs_info公开契约（https://github.com/ChenyangGao/p115client/blob/main/p115client/client.py，引用115文档https://www.yuque.com/115yun/open/rl8zrhe2nag21dfw），同接口支持POST。未猜新增大小字段。

七文件相关pytest：312 passed；client.py、queue.py、__init__.py及test_rapid115upload.py pylint10/10。涵盖无SHA1/不同SHA1同大小复用、整数/数字字符串/0字节、拒绝非法大小、file_id补查、限流等待、元数据三次暂停及重新排队恢复。不访问真实115进行测试。前端不变，继续使用1.2.4已验证产物。

## 2026-10-13 1.2.6 同名冲突处理

插件接口/队列/115客户端及队列详情页面内实现；不改MP宿主业务代码、数据库结构、依赖、BDMV或qB筛选合同。用户要求直接实施，不创建Trellis任务。删除协议沿用宿主U115Pan.delete：POST /open/ufile/delete，file_ids为文件ID。授权仅来自当前blocked大小冲突的确认快照；网络调用前持久化意图。测试全部使用临时文件和协议替身，没有对真实115文件进行删除/覆盖验证。

在 `/home/zhaojg/MoviePilot-upgrades/jxxghp-MoviePilot-09f62ff` 执行：

- `uv run --locked --no-sync pytest tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py tests/test_rapid115upload_reorganize.py tests/test_rapid115upload_reorganize_persistence.py tests/test_qbittorrent_tag_monitor.py tests/test_rapid115upload_bdmv.py tests/test_rapid115upload_bdmv_cd2.py -q`：340 passed。
- `uv run --locked --no-sync pylint --reports=n /home/zhaojg/MoviePilot/local-plugins/plugins.v2/rapid115upload/client.py /home/zhaojg/MoviePilot/local-plugins/plugins.v2/rapid115upload/queue.py /home/zhaojg/MoviePilot/local-plugins/plugins.v2/rapid115upload/__init__.py tests/test_rapid115upload.py tests/test_rapid115upload_frontend.py`：10/10。
- `npm run build --prefix local-plugins/plugins.v2/rapid115upload/frontend`：成功。

新增覆盖：另存为持久化及重复事件不丢关联、路径越界/过期确认/目录覆盖拒绝、重试取消撤销删除授权、远端变化及删除超时禁止重发、删除后重启恢复、本地身份变化、同目标并发保护、仅成功上传清理本地，以及前端确认快照/错误保留弹窗。宿主全量、架构快照及真实115覆盖操作未执行；原生媒体记录前端未修改。
