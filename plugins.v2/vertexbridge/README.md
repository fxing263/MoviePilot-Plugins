# Vertex 桥接 1.2.1

MP 提供原生媒体识别、统一接收用户指令和发送通知，VT 继续负责 RSS、优选、下载、删种及权限校验。识别通过插件接口集成，不修改 MP 核心文件。
插件源码位于 MoviePilot 的 `local-plugins/plugins.v2/vertexbridge/`，对应测试为 `tests/test_vertexbridge.py`。VT 仓库只维护桥接接口和通知适配，不重复保存 MP 插件源码。

## 安装

本目录包含插件源码和独立索引 `manifest.json`；MP 的 `local-plugins/package.v2.json` 已注册该插件。导出的独立安装包包含 `package.v2.json` 和 `plugins.v2/vertexbridge/`。
适配 MP v2 插件契约，并兼容本机 MP v3 的 SDK 入口。测试使用隔离的宿主接口，尚未向真实聊天渠道发送消息。

对于支持本地插件仓库的 MP（本机这一版支持）：

1. 解压 `vertexbridge-1.2.1.tar.gz` 到持久化目录，例如宿主机 `/volume1/docker/moviepilot/vertex-bridge`。
2. 在 MP 容器挂载此目录：`/volume1/docker/moviepilot/vertex-bridge:/plugins/vertex-bridge:ro`。
3. 在 MP Compose 的 `environment` 中添加 `PLUGIN_LOCAL_REPO_PATHS: /plugins/vertex-bridge`。已有其它本地仓库时，将此路径追加到原值，用英文逗号分隔。
4. 重建 MP 容器后，在插件市场查找并安装「Vertex 桥接」。不要覆盖已有插件仓库的 `package.v2.json`。

没有本地插件仓库功能的 MP，需要把本目录发布为独立的 GitHub 插件仓库，再将仓库地址添加到 MP 插件市场。本次提供离线包，未发布远端仓库，也未修改运行中的 MP。

VT 使用 1.3.32 或更新版本；此前的 1.3.31 镜像没有 `/api/openapi/moviepilot/command` 接口。插件包不包含 VT Docker 镜像。

## 媒体识别（独立于通知与指令）

1. 安装或更新插件到 1.2.1，开启「启用插件」和「为 VT 提供媒体识别」。无需填写 VT 地址、通知工具 ID 或桥接密钥，指令开关可以保持关闭。
2. VT 需使用含插件识别接入的版本（当前 `feature/moviepilot-recognition` 分支；旧的 1.3.32 发布镜像只有通知桥接）。在候选设置填写 MP 后端根地址和系统 `API_TOKEN`，保存后测试识别。
3. 识别词、平台、小组、自定义占位符在 MP 配置。插件只调用 MP 原生 `MetaInfo` 与 `MediaChain.recognize_by_meta`，复用该流程的缓存，不自建 TMDB 缓存或发起下载、文件整理。后续 MP 文件整理能否命中缓存取决于原生缓存键和有效期，不保证所有文件名命中。

接口：`POST /api/v1/plugin/VertexBridge/recognize`，请求头 `X-API-KEY` 为 MP 系统令牌。
JSON 正文含 `title`、可选 `subtitle`、可选临时 `custom_words`（换行分隔；空值使用 MP 全局识别词）。
响应包含 `recognition_version:2`、`meta_info`、`source_meta_info`、`media_info`；未匹配时 `media_info:null`，仍保留质量、帧率和位深。需要与支持协议 v2 的 VT 分支配套升级，旧 VT 不接受该响应。
两个元数据对象增加 `customization_items`：由 MP 原生占位符匹配器及当前分隔符生成独立列表，避免宿主加速器固定分隔符导致合并评分；不修改全局规则，不把 CHS 等自动翻译成中文。版本、字幕等占位符由 VT 统一作为附加逐项计分。
原生 `total_episode` 保留：副标题“全24集”可能只有数量而没有 `begin_episode` 或 `episode_list`。插件不据此补造 1–24 文件坐标；VT 结合季度信息判断合集，无明确证据时待确认。
`source_meta_info` 不应用识别词，用于原文件选集；`meta_info` 为应用识别词、媒体链修正后的坐标。VT 负责验证两者是否可一一映射。

识别默认关闭。关闭时返回 503，同一插件实例只允许一个识别请求执行，繁忙返回 429，由 VT 退避重试；原生识别异常返回脱敏的 502。通知和命令使用独立限流。同步识别在宿主线程池执行，不阻塞异步事件循环。HTTP 超时不代表 MP 已停止工作，插件也不接管其它 MP 任务的队列。
兼容测试覆盖本机 v3 的真实解析器以及旧版链方法签名；尚未对官方 v2 镜像做运行验收。

### TMDB 故障与未匹配

1.2.1 在 `MediaChain.recognize_by_meta` 返回空媒体时再判断 TMDB 是否可用。当前宿主只在内部保留请求级 `connection_error`，没有插件可用的最近失败状态／熔断器接口，因此经宿主 `RequestUtils`、TMDB 域名、API Key 和代理请求 `/3/configuration`，超时 5 秒。成功与失败结果均在插件实例内缓存 60 秒，不启动额外后台任务；成功识别不会触发探测。

- 探测成功：HTTP 200，`media_info=null`，保留原生解析结果。
- 不可达、非 200、无效响应或探测异常：HTTP 503，`detail` 为「TMDB 暂不可用，请稍后重试」。配套 Vertex 保持传输错误与退避重试，不记终止的 unmatched。
- 探测异常不打印 URL、Token 或原始异常，响应会关闭。探测只代表配置接口的短期可用性，不能还原此前搜索请求；缓存可能让故障恢复的观测延迟最多 60 秒。

协议仍为 recognition_version=2。已被旧插件记为 unmatched 的历史条目需在修复连接后手动「补全识别」。第三期仅更新源码及索引，未重新导出 1.2.1 的 tar.gz；部署前需按本目录打包或更新本地插件仓库，并在真实 MP v2/v3 环境验收。

## 配置顺序

1. VT「基础设置 → 通知工具」新增 MoviePilot 通知，填写 **MP 后端根地址**和 **MP 系统 API 令牌**，开启「Vertex 桥接」。通知默认走 MP 的插件消息，请在 MP 通知设置中允许该消息类型。
2. 要使用指令，开启 VT 的「接收 MP 指令」，填写一段 **32–128 位随机桥接密钥**和「允许用户」。桥接密钥使用字母、数字、下划线或短横线，与 MP 系统 API 令牌分开。
3. 允许用户按 `渠道名:用户ID` 填写，一行一个，如 `Telegram:123456`、`Wechat:zhangsan`。这里的渠道名是 MP 枚举名，微信为 `Wechat`。默认只允许查询；要暂停／恢复自动删种，另开「允许控制」。
4. 保存 VT 通知工具，再编辑它，复制页面上的「通知工具 ID」。将需要通知的 RSS、下载器等关联到此通知工具，并勾选需要的推送类型。
5. MP 插件填写 **VT 根地址、VT 通知工具 ID、相同的桥接密钥**，开启插件及「转发 /vt 指令」。双方地址需从各自容器内可达，`localhost` 通常指各自容器，不能代指另一台主机。
6. MP 插件里的「通知渠道」留空时使用 MP 的通知设置。需要限定通知到某个渠道、通知服务或用户时再填写后面三项；服务 ID 来自 MP 通知服务配置。命令回复始终使用命令来源渠道、服务及发送者，不使用通知广播设置。
7. 同一个 Telegram 机器人只让 MP 接收消息，VT 对应机器人的「接收命令」关闭。HTTP 跨不可信网络时使用 HTTPS；插件默认校验证书。

不知道自己的身份值时，可以先在 VT 填一个占位允许用户（如 `Telegram:0`），完成连接后发送 `/vt 状态`。拒绝回复会给出当前身份值，再回 VT 替换，不必开放给所有群成员。

## 指令

| 指令 | 作用 |
| --- | --- |
| `/vt 帮助` | 查看支持的命令 |
| `/vt 状态` | 查询下载器连接、速度、空间和自动删种开关 |
| `/vt 候选` | 查询待核实及停止自动重试的候选 |
| `/vt 硬链接` | 最近硬链接记录 |
| `/vt 删种预览 qb` | 只读预览指定下载器的删种结果；别名可省略 |
| `/vt 暂停删种 qb` | 暂停指定下载器的自动删种，需控制权限 |
| `/vt 恢复删种 qb` | 恢复指定下载器的自动删种，需控制权限 |

英文命令同样可用，例如 `/vt status`。下载器别名可含空格。
当前不提供候选下载／拒绝、RSS 开关、直接删除文件或任意 API／Shell 执行。

## 交付与失败语义

- VT → MP：`POST /api/v1/plugin/VertexBridge/notify`，`X-API-KEY` 携带 MP 系统令牌，正文只有 `title`、`text`。MP 端返回 `success:true` 表示已交给通知队列，不保证用户最终送达。VT 保留原通知队列的限速及重试；MP 在运行期间将 60 秒内相同标题和正文合并。
- MP → VT：`POST /api/openapi/moviepilot/command`，`X-Vertex-Key` 携带独立桥接密钥。正文包含 `channelId`、`requestId`、`issuedAt`（毫秒）、`user:{channel,userId}`、`command`、`args`。VT 从已保存配置核对身份与控制权限，不信任调用方提交的管理员标志。
- 指令逐条执行，最多 10 个运行／等待请求。相同请求编号和内容在 VT 当前进程中 10 分钟内复用结果，不同内容复用编号会被拒绝；只接受两分钟以内的请求，需两机时间同步。去重状态不跨重启保留。
- MP 不自动重试指令。超时、502、非 JSON 或结果格式错误均返回「未确认」，可能已经执行的控制操作应先查询状态；不把网络失败当成「一定没执行」。暂停／恢复都是设置明确状态，不是切换开关。
- 插件关闭、VT 桥接关闭、用户移出名单后，新指令被拒绝；尚未执行的 VT 排队指令也会重新校验权限。已经执行中的操作不会被强行中断。
- 命令回复采用 MP 现有的“渠道＋服务＋用户”路由。是否在群聊或私聊显示取决于该渠道实现，本版不转发 VT 的 Telegram 交互按钮。
- 单独的通知故障不阻塞 VT 下载、RSS 或删种；启用 MP 独占识别后，MP 不可用的新候选会等待识别。VT 原通知队列并非无限重试或持久化消息总线。

## 手动验收

1. VT 通知工具点「测试」，确认 MP 渠道收到带 `[VT]` 前缀的通知。
2. 在同一聊天渠道发送 `/vt 帮助`、`/vt 状态`，确认回复来自 MP。
3. 发送 `/vt 删种预览 qb`，确认只有预览，没有删种动作。
4. 关闭 VT「允许控制」后发送暂停指令，应明确拒绝。
5. 如需验证控制，再开启权限，选测试下载器暂停后查询状态，最后恢复。

上述实际消息与控制动作由你手动验收，本次开发测试使用模拟渠道和下载器。

## 开发验证

在 MoviePilot 仓库根目录运行：

```sh
python -m pytest tests/test_vertexbridge.py tests/test_vertexbridge_recognition.py -q -p no:cacheprovider
```

使用 MP 的测试环境。宿主模块通过 pytest monkeypatch 隔离，不读取真实配置、访问外网或操作下载器。VT 侧的接口、通知与页面测试仍位于 VT 仓库。
