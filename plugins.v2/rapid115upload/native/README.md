# 原版媒体整理界面

`src/` 来自本地 MP 前端源码 `artifacts/rapid115-frontend/src`。`source-manifest.json` 记录保持原样的历史页与关键组件 SHA256。`adapted-source-manifest.json` 单独记录增强组件的上游原始 SHA256 和改动说明，不将插件修改冒充原版。`ReorganizeDialog.vue` 保留原版完整交互，并仅在插件历史重整中提供逐文件目标路径编辑、恢复默认及校验；有编辑时提交插件专用接口，未编辑沿用 MP 接口。表单变更使旧预览和编辑失效；最终库根、文件安全和目标检查由服务端执行。适配在 runtime.ts、router.ts、pwa.ts、entry.ts、Root.vue 及 stores/index.ts（禁用独立应用持久化插件）中。115 状态组件沿用已有实现。

依赖使用原前端 package-lock.json，未引入新依赖。独立构建：

```sh
cd native
npm ci --ignore-scripts --no-audit --no-fund
npm run build
cd ../frontend
npm ci --no-audit --no-fund
npm run build
```

先构建 native，再构建 frontend；外层入口从 native.js 计算版本指纹，为入口和样式增加缓存版本。原版图标 bundle 已包含在源码中，不依赖安装后的图标生成脚本。开发环境可以复用已有前端 node_modules，但安装包不包含 node_modules。

生产构建显式替换 process.env.NODE_ENV，避免 Vue/Vuetify 依赖在浏览器访问 Node 全局变量。验证通过本地接口替身完成，不对真实媒体执行整理、删除或恢复。
