import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PLUGIN_ID } from './shared-yLuSZolc.js';

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementVNode:_createElementVNode,createElementBlock:_createElementBlock} = await importShared('vue');

const {getCurrentInstance,onMounted,onUnmounted,ref} = await importShared('vue');

const {useTheme} = await importShared('vuetify');
const _sfc_main = {
  __name: "History",
  props: { api: { type: [Object, Function], required: true }, pluginId: { type: String, default: PLUGIN_ID } },
  setup(__props) {
    const props = __props;
    const container = ref(null), loading = ref(true), error = ref("");
    const theme = useTheme();
    const host = getCurrentInstance()?.appContext.config.globalProperties;
    let dispose, stylesheet, removed = false;
    onMounted(async () => {
      try {
        const uri = props.api.getUri({ url: `plugin/file/${props.pluginId}/native-dist/native.js` });
        const moduleUrl = new URL(uri, document.baseURI);
        moduleUrl.searchParams.set("v", "0923b08774ba875d");
        window.__rapid115NativeBase = props.api.getUri({ url: "" }).replace(/\/?$/, "/");
        stylesheet = document.createElement("link");
        stylesheet.rel = "stylesheet";
        stylesheet.href = new URL(`style.css?v=${"0923b08774ba875d"}`, moduleUrl).href;
        const styled = new Promise((resolve, reject) => {
          stylesheet.onload = resolve;
          stylesheet.onerror = () => reject(new Error("原版整理页面样式加载失败"));
        });
        document.head.appendChild(stylesheet);
        const [native] = await Promise.all([import(
          /* @vite-ignore */
          moduleUrl.href
        ), styled]);
        if (removed) return;
        const state = host?.$pinia?.state?.value || {};
        dispose = await native.mount(container.value, { api: props.api, pluginId: props.pluginId, theme: theme.global.name.value, user: state.user ? JSON.parse(JSON.stringify(state.user)) : void 0, auth: state.auth ? JSON.parse(JSON.stringify(state.auth)) : void 0 });
        if (removed) dispose();
      } catch (failure) {
        if (!removed) error.value = failure?.message || "原版整理页面加载失败";
      } finally {
        loading.value = false;
      }
    });
    onUnmounted(() => {
      removed = true;
      dispose?.();
      stylesheet?.remove();
    });
    return (_ctx, _cache) => {
      const _component_v_alert = _resolveComponent("v-alert");
      const _component_v_progress_linear = _resolveComponent("v-progress-linear");
      return _openBlock(), _createElementBlock("div", null, [
        error.value ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: "error",
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        })) : loading.value ? (_openBlock(), _createBlock(_component_v_progress_linear, {
          key: 1,
          indeterminate: "",
          color: "primary"
        })) : _createCommentVNode("", true),
        _createElementVNode("div", {
          ref_key: "container",
          ref: container
        }, null, 512)
      ]);
    };
  }
};

export { _sfc_main as default };
