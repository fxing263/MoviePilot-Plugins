# 1.3.1 发布验证

- 在提供 app.sdk 的 MoviePilot 后端和独立锁定 Python 环境中，插件后端/前端专项 pytest：122 passed。
- 本插件 Python 变更 pylint：10/10；插件版本门禁通过。
- 前端 dist 为已验证的本地构建制品；本次发布未重新解析依赖，未声称可复现锁定前端构建。
- 所有文件测试使用临时目录，未调用真实上传器、下载器、Emby 或操作真实媒体。
- 插件仓原始测试引导引用已改名的 app.testing.network_guard；临时改为当前 app.testing.network 后，专项测试通过。
- 仓库全量测试仍被既有缺失插件测试阻塞：agenttokens、brushflow、libraryscraper、maoyanrank、bangumicoll 等；未删测试或修改基线。临时引导修正不纳入发布。
- 当前源码依赖 MoviePilot app.sdk，旧版 SDK 缺失环境不在验证范围。

维护者发布决定：用户已了解仓库既有全量测试阻塞，并明确回复“发布”，授权按本插件专项验证发布 1.3.1；全量问题留待独立修复。
